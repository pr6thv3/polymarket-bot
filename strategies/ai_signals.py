"""AI/News-based signal trading strategy — Phase 4.

Uses an ensemble probability model combining news sentiment, market
microstructure features, and momentum signals to identify mispriced
Polymarket contracts. When the model detects a sufficient edge between
its estimated probability and the market-implied probability, it places
directional limit orders on the underpriced side.

Strategy lifecycle:
 initialize() → Load news sources, warm up signal model
 run_cycle()  → 1. Fetch fresh news articles
                2. Scan markets for opportunities
                3. Evaluate each market with SignalModel
                4. Place/cancel orders based on signals
                5. Manage existing positions (trailing stops, take-profit)
 shutdown()   → Cancel all orders, save model state

Risk controls:
 - Maximum concurrent positions
 - Position sizing based on signal confidence and edge
 - Time-based exit (avoid holding near resolution)
 - Stop-loss on individual positions
 - Daily loss cap enforced by RiskManager

This is the highest-ceiling strategy but also the most complex.
It requires quality news data to be effective.
"""

import asyncio
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import structlog

from core.client import ClobClient, TAKER_FEES
from core.executor import Executor, OrderRejectedByRisk
from core.orderbook import OrderBookManager
from core.order_state import OrderStore, OrderState
from core.portfolio import Portfolio
from core.risk import RiskManager
from data.news_fetcher import NewsFetcher, Article, MockSource
from data.signal_model import SignalModel, Signal
from data.market_scanner import MarketScanner, MarketInfo
from strategies.base import Strategy
from utils import metrics as m

logger = structlog.get_logger(__name__)


# ── Position tracking ─────────────────────────────────────────────────

@dataclass
class AIPosition:
    """Tracks an AI signal-driven position."""

    market_id: str
    token_id: str
    category: str = ""
    direction: str = "FLAT"  # "YES" or "NO"
    entry_price: float = 0.0
    current_price: float = 0.0
    size: float = 0.0
    order_id: Optional[str] = None
    entry_time: float = field(default_factory=time.monotonic)
    signal_edge: float = 0.0
    signal_confidence: float = 0.0
    stop_loss_price: float = 0.0
    take_profit_price: float = 0.0
    max_hold_sec: float = 86400 * 3  # 3 days default
    question: str = ""

    @property
    def pnl_pct(self) -> float:
        """Current P&L as percentage of entry."""
        if self.entry_price <= 0:
            return 0.0
        if self.direction == "YES":
            return (self.current_price - self.entry_price) / self.entry_price
        else:
            return (self.entry_price - self.current_price) / self.entry_price

    @property
    def hold_time_sec(self) -> float:
        """Seconds since position was opened."""
        return time.monotonic() - self.entry_time

    @property
    def should_exit(self) -> Tuple[bool, str]:
        """Check if position should be exited.

        Returns:
            Tuple of (should_exit, reason).
        """
        # Stop loss hit
        if self.direction == "YES" and self.current_price <= self.stop_loss_price:
            return True, "stop_loss"
        if self.direction == "NO" and self.current_price >= self.stop_loss_price:
            return True, "stop_loss"

        # Take profit hit
        if self.direction == "YES" and self.current_price >= self.take_profit_price:
            return True, "take_profit"
        if self.direction == "NO" and self.current_price <= self.take_profit_price:
            return True, "take_profit"

        # Max hold time exceeded
        if self.hold_time_sec > self.max_hold_sec:
            return True, "max_hold_time"

        return False, ""


# ── AI Signals Strategy ───────────────────────────────────────────────

class AISignalsStrategy(Strategy):
    """AI/News-based signal trading strategy.

    Uses an ensemble probability model to find mispriced contracts
    and place directional trades. Combines news sentiment analysis,
    market microstructure features, and momentum signals.

    The strategy:
    1. Fetches fresh news articles from configured sources
    2. Scans markets for potential mispricing
    3. Evaluates each candidate market with the SignalModel
    4. For actionable signals, places limit orders on the underpriced side
    5. Monitors existing positions for stop-loss / take-profit exits
    6. Cancels stale or expired signals
    """

    def __init__(
        self,
        client: ClobClient,
        orderbook: OrderBookManager,
        portfolio: Portfolio,
        risk_manager: RiskManager,
        executor: Executor,
        order_store: OrderStore,
        news_fetcher: NewsFetcher,
        scanner: MarketScanner,
        config: dict,
    ) -> None:
        super().__init__(
            client=client,
            orderbook=orderbook,
            portfolio=portfolio,
            risk_manager=risk_manager,
            executor=executor,
            order_store=order_store,
            config=config,
        )
        self.news_fetcher = news_fetcher
        self.scanner = scanner
        self.signal_model = SignalModel(config.get("strategies", {}).get("ai_signals", {}))

        ai_cfg = self._strategy_config

        # ── Signal thresholds ──
        self.min_edge = ai_cfg.get("min_edge_to_trade", 0.05)
        self.min_confidence = ai_cfg.get("min_confidence", 0.3)
        self.max_concurrent_positions = ai_cfg.get("max_concurrent_positions", 5)

        # ── Position sizing ──
        self.base_order_usd = ai_cfg.get("base_order_usd", 25.0)
        self.max_order_usd = ai_cfg.get("max_order_usd", 100.0)
        self.confidence_size_scale = ai_cfg.get("confidence_size_scale", 1.5)

        # ── Exit parameters ──
        self.stop_loss_pct = ai_cfg.get("stop_loss_pct", 0.15)
        self.take_profit_pct = ai_cfg.get("take_profit_pct", 0.50)
        self.default_max_hold_sec = ai_cfg.get("max_hold_sec", 86400 * 3)

        # ── Market filter ──
        self.target_categories = set(
            ai_cfg.get("target_categories", ["politics", "geopolitics", "finance", "economics"])
        )
        self.min_market_volume_usd = ai_cfg.get("min_market_volume_usd", 5000.0)
        self.min_days_to_resolution = ai_cfg.get("min_days_to_resolution", 3)
        self.max_days_to_resolution = ai_cfg.get("max_days_to_resolution", 180)

        # ── State ──
        self._positions: Dict[str, AIPosition] = {}
        self._recent_signals: deque = deque(maxlen=100)
        self._total_signals: int = 0
        self._actionable_signals: int = 0
        self._trades_placed: int = 0

    # ── Strategy interface ────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "AISignals"

    def _config_key(self) -> str:
        return "ai_signals"

    async def initialize(self) -> None:
        """Initialize the AI signals strategy.

        - Perform initial news fetch
        - Run initial market scan
        - Warm up the signal model
        """
        logger.info("Initializing AI signals strategy")

        # Initial news fetch
        try:
            fetch_result = await self.news_fetcher.fetch_all()
            logger.info(
                "Initial news fetch complete",
                articles=fetch_result.articles_new,
                sources=fetch_result.sources_queried,
            )
        except Exception as exc:
            logger.warning("Initial news fetch failed", error=str(exc))

        # Initial market scan
        try:
            scan_result = await self.scanner.scan(force=True)
            logger.info(
                "Initial market scan complete",
                eligible=scan_result.eligible_markets,
            )
        except Exception as exc:
            logger.warning("Initial market scan failed", error=str(exc))

        logger.info(
            "AI signals strategy initialized",
            sources=len(self.news_fetcher._sources),
            model_stats=self.signal_model.get_stats(),
        )

    async def run_cycle(self) -> None:
        """Main AI signals strategy tick.

        1. Fetch fresh news (if interval elapsed)
        2. Get candidate markets from scanner
        3. Evaluate each market with the signal model
        4. Place new trades for actionable signals
        5. Manage existing positions (exits, adjustments)
        6. Record metrics
        """
        # 1. Fetch news (non-blocking check)
        if self.news_fetcher.should_fetch:
            try:
                fetch_result = await self.news_fetcher.fetch_all()
                logger.debug(
                    "News fetch cycle",
                    new_articles=fetch_result.articles_new,
                )
            except Exception as exc:
                logger.warning("News fetch cycle failed", error=str(exc))

        # 2. Get candidate markets
        try:
            eligible = await self.scanner.get_eligible_markets()
        except Exception as exc:
            logger.error("Market scan failed", error=str(exc))
            return

        # 3. Evaluate markets and generate signals
        signals: List[Signal] = []
        for info in eligible:
            try:
                signal = await self._evaluate_market(info)
                if signal and signal.is_actionable:
                    signals.append(signal)
            except Exception as exc:
                logger.debug(
                    "Market evaluation failed",
                    market_id=info.market_id,
                    error=str(exc),
                )

        # 4. Sort signals by expected value and take top opportunities
        signals.sort(key=lambda s: s.expected_value, reverse=True)

        # 5. Place trades for top signals (respecting position limits)
        available_slots = self.max_concurrent_positions - len(self._positions)
        for signal in signals[:available_slots]:
            try:
                await self._place_signal_trade(signal)
            except Exception as exc:
                logger.error(
                    "Failed to place signal trade",
                    market_id=signal.market_id,
                    error=str(exc),
                )

        # 6. Manage existing positions
        await self._manage_positions()

        # 7. Update state
        self._state.markets_active = list(self._positions.keys())
        self._recent_signals.extend(signals)
        self._total_signals += len(eligible)
        self._actionable_signals += len(signals)

        logger.info(
            "AI signals cycle complete",
            markets_evaluated=len(eligible),
            signals_generated=len(signals),
            trades_placed=min(len(signals), available_slots),
            open_positions=len(self._positions),
        )

    async def shutdown(self) -> None:
        """Cancel all AI signal orders and close positions."""
        logger.info("AI signals strategy shutting down")

        # Cancel all open orders
        for market_id, pos in list(self._positions.items()):
            try:
                if pos.order_id:
                    await self.executor.cancel_order(pos.order_id)
            except Exception as exc:
                logger.warning(
                    "Failed to cancel order on shutdown",
                    market_id=market_id,
                    error=str(exc),
                )

        self._positions.clear()

    # ── Market evaluation ─────────────────────────────────────────────

    async def _evaluate_market(self, info: MarketInfo) -> Optional[Signal]:
        """Evaluate a single market with the ensemble model.

        Args:
            info: MarketInfo from scanner.

        Returns:
            Signal or None if market doesn't pass filters.
        """
        # Skip markets we're already in
        if info.market_id in self._positions:
            return None

        # Category filter
        if info.category not in self.target_categories:
            return None

        # Resolution window filter
        if info.days_to_resolution < self.min_days_to_resolution:
            return None
        if info.days_to_resolution > self.max_days_to_resolution:
            return None

        # Volume filter
        if info.daily_volume_usd < self.min_market_volume_usd:
            return None

        # Get market-implied probability (mid price)
        mid_price = info.mid_price
        if mid_price <= 0.01 or mid_price >= 0.99:
            return None  # Skip extreme-probability markets

        # Get relevant articles
        articles = self.news_fetcher.get_articles_for_market(
            market_id=info.market_id,
            market_question=info.question,
            category=info.category,
            max_articles=20,
        )

        # Get orderbook snapshot
        orderbook_snapshot = None
        snapshot = self.orderbook.get_snapshot(info.market_id)
        if snapshot:
            orderbook_snapshot = {
                "bids": [
                    {"price": b.price, "size": b.size}
                    for b in (snapshot.bids or [])[:10]
                ] if hasattr(snapshot, "bids") else [],
                "asks": [
                    {"price": a.price, "size": a.size}
                    for a in (snapshot.asks or [])[:10]
                ] if hasattr(snapshot, "asks") else [],
                "mid_price": snapshot.mid_price,
            }

        # Get price history (if available)
        price_history = self._get_price_history(info.market_id)

        # Run ensemble model
        signal = self.signal_model.evaluate(
            market_id=info.market_id,
            market_prob=mid_price,
            articles=articles,
            orderbook_snapshot=orderbook_snapshot,
            price_history=price_history,
            category=info.category,
        )

        return signal

    def _get_price_history(self, market_id: str) -> list:
        """Get recent price history for a market.

        Args:
            market_id: Market ID.

        Returns:
            List of (timestamp, price) tuples.
        """
        # Try to get from orderbook's volatility tracker
        history = []
        snapshot = self.orderbook.get_snapshot(market_id)
        if snapshot and hasattr(snapshot, "price_history"):
            history = list(snapshot.price_history)

        # Fallback: use mid price as single data point
        if not history and snapshot and snapshot.mid_price:
            history = [(time.time(), snapshot.mid_price)]

        return history

    # ── Trade execution ───────────────────────────────────────────────

    async def _place_signal_trade(self, signal: Signal) -> None:
        """Place a trade based on an actionable signal.

        Args:
            signal: Actionable Signal from the ensemble model.
        """
        # Additional confidence check
        if signal.confidence < self.min_confidence:
            logger.debug(
                "Signal below confidence threshold",
                market_id=signal.market_id,
                confidence=signal.confidence,
                threshold=self.min_confidence,
            )
            return

        # Determine side and price
        if signal.direction == "YES":
            side = "BUY"
            # Place limit order slightly below market to get maker fill
            target_price = signal.market_prob - 0.01
        elif signal.direction == "NO":
            side = "BUY"  # Buying NO shares = selling YES
            target_price = 1.0 - signal.market_prob - 0.01
        else:
            return

        # Compute position size based on confidence and edge
        size_usd = self._compute_position_size(signal)
        if size_usd < 1.0:
            return

        # Get token_id from scanner
        info = self.scanner.get_market_info(signal.market_id)
        if not info:
            return
        token_id = info.token_id

        # Size in shares
        size_shares = size_usd / max(0.01, target_price)

        # Risk check
        allowed, reason = await self.risk_manager.allow_order(
            market_id=signal.market_id,
            side=side,
            price=target_price,
            size=size_shares,
            category=info.category,
        )

        if not allowed:
            logger.debug(
                "Signal trade rejected by risk",
                market_id=signal.market_id,
                reason=reason,
            )
            return

        # Place the order (POST_ONLY to avoid taker fees)
        try:
            order_id = await self.executor.place_order(
                market_id=signal.market_id,
                token_id=token_id,
                side=side,
                price=target_price,
                size=size_shares,
                post_only=True,
                category=info.category,
            )
        except OrderRejectedByRisk as exc:
            logger.info("Signal order rejected by risk", reason=str(exc))
            return
        except Exception as exc:
            logger.error(
                "Failed to place signal order",
                market_id=signal.market_id,
                error=str(exc),
            )
            return

        if not order_id:
            return

        # Track position
        stop_loss = self._compute_stop_loss(target_price, signal.direction)
        take_profit = self._compute_take_profit(target_price, signal.direction)

        self._positions[signal.market_id] = AIPosition(
            market_id=signal.market_id,
            token_id=token_id,
            category=info.category,
            direction=signal.direction,
            entry_price=target_price,
            current_price=target_price,
            size=size_shares,
            order_id=order_id,
            signal_edge=signal.edge,
            signal_confidence=signal.confidence,
            stop_loss_price=stop_loss,
            take_profit_price=take_profit,
            max_hold_sec=min(
                self.default_max_hold_sec,
                info.days_to_resolution * 86400 * 0.7,  # Exit before resolution
            ),
            question=info.question,
        )

        self._trades_placed += 1
        self._state.orders_placed += 1

        logger.info(
            "Signal trade placed",
            market_id=signal.market_id,
            direction=signal.direction,
            edge=signal.edge,
            confidence=signal.confidence,
            price=target_price,
            size_usd=size_usd,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )

        # Record metrics
        m.record_signal_generated(
            edge=signal.edge,
            confidence=signal.confidence,
        )

    def _compute_position_size(self, signal: Signal) -> float:
        """Compute position size based on signal quality.

        Position sizing uses the Kelly-inspired formula:
        size = base_size * (edge / max_edge) * (confidence / confidence_scale)

        Args:
            signal: The trading signal.

        Returns:
            Position size in USD.
        """
        # Base size scaled by edge magnitude
        edge_factor = min(2.0, signal.edge / self.min_edge)

        # Confidence scaling
        confidence_factor = min(
            self.confidence_size_scale,
            signal.confidence * self.confidence_size_scale,
        )

        size_usd = self.base_order_usd * edge_factor * confidence_factor

        # Clamp to configured limits
        size_usd = max(1.0, min(self.max_order_usd, size_usd))

        # Scale by time-of-day multiplier
        tod_multiplier = self.risk_manager.get_size_multiplier()
        size_usd *= tod_multiplier

        # Ensure we don't exceed available capital
        free_usdc = self.portfolio.free_usdc
        max_allocation = free_usdc * self.risk_manager.max_position_pct
        size_usd = min(size_usd, max_allocation)

        return size_usd

    def _compute_stop_loss(self, entry_price: float, direction: str) -> float:
        """Compute stop-loss price for a position.

        Args:
            entry_price: Entry price.
            direction: "YES" or "NO".

        Returns:
            Stop-loss price.
        """
        if direction == "YES":
            return entry_price * (1.0 - self.stop_loss_pct)
        else:
            return entry_price * (1.0 + self.stop_loss_pct)

    def _compute_take_profit(self, entry_price: float, direction: str) -> float:
        """Compute take-profit price for a position.

        Args:
            entry_price: Entry price.
            direction: "YES" or "NO".

        Returns:
            Take-profit price.
        """
        if direction == "YES":
            return min(0.99, entry_price * (1.0 + self.take_profit_pct))
        else:
            return max(0.01, entry_price * (1.0 - self.take_profit_pct))

    # ── Position management ───────────────────────────────────────────

    async def _manage_positions(self) -> None:
        """Check and manage existing positions.

        For each open position:
        - Update current price from orderbook
        - Check stop-loss / take-profit triggers
        - Check max hold time
        - Exit if needed
        """
        for market_id, pos in list(self._positions.items()):
            # Update current price
            snapshot = self.orderbook.get_snapshot(market_id)
            if snapshot and snapshot.mid_price:
                pos.current_price = snapshot.mid_price

            # Check exit conditions
            should_exit, reason = pos.should_exit
            if should_exit:
                await self._exit_position(market_id, pos, reason)
                continue

            # Check if order is still live
            if pos.order_id:
                order_record = self.order_store.get(pos.order_id)
                if order_record and order_record.is_terminal:
                    # Order completed, update position
                    pos.order_id = None
                    if order_record.state == OrderState.FILLED:
                        self._state.orders_filled += 1

    async def _exit_position(
        self,
        market_id: str,
        pos: AIPosition,
        reason: str,
    ) -> None:
        """Exit a position by cancelling orders and cleaning up.

        Args:
            market_id: Market to exit.
            pos: Position to exit.
            reason: Exit reason for logging.
        """
        try:
            # Cancel any remaining open orders
            await self.executor.cancel_all_for_market(market_id)

            pnl = pos.pnl_pct
            logger.info(
                "Position exited",
                market_id=market_id,
                direction=pos.direction,
                reason=reason,
                pnl_pct=pnl,
                hold_time_sec=pos.hold_time_sec,
            )

            # Record outcome for model retraining
            if reason in ("stop_loss", "take_profit", "max_hold_time"):
                # Map position outcome to a probability estimate for Brier tracking
                # If we were long YES and hit take-profit, actual outcome → toward 1.0
                if pos.direction == "YES":
                    if reason == "take_profit":
                        actual = 1.0
                    elif reason == "stop_loss":
                        actual = 0.0
                    else:
                        actual = pos.current_price
                else:  # NO
                    if reason == "take_profit":
                        actual = 0.0
                    elif reason == "stop_loss":
                        actual = 1.0
                    else:
                        actual = 1.0 - pos.current_price

                self.signal_model.record_outcome(
                    market_id=market_id,
                    actual_outcome=actual,
                    predicted_prob=pos.signal_confidence,
                )

        except Exception as exc:
            logger.error(
                "Failed to exit position",
                market_id=market_id,
                error=str(exc),
            )
        finally:
            self._positions.pop(market_id, None)

    # ── Status and reporting ──────────────────────────────────────────

    def get_strategy_summary(self) -> Dict[str, any]:
        """Get strategy summary for logging.

        Returns:
            Dict with strategy stats.
        """
        return {
            "total_signals": self._total_signals,
            "actionable_signals": self._actionable_signals,
            "trades_placed": self._trades_placed,
            "open_positions": len(self._positions),
            "model_stats": self.signal_model.get_stats(),
            "news_stats": self.news_fetcher.get_stats(),
            "positions": {
                mid: {
                    "direction": pos.direction,
                    "pnl_pct": pos.pnl_pct,
                    "edge": pos.signal_edge,
                    "confidence": pos.signal_confidence,
                    "hold_time_sec": pos.hold_time_sec,
                }
                for mid, pos in self._positions.items()
            },
        }
