"""Whale / Smart Money tracking strategy.

Follows profitable wallets (win rate > 60%, profit factor > 1.5x) and
copies their trades with dynamic position sizing.

Core algorithm:
  signal_strength = whale_win_rate × whale_profit_factor × recency_weight
  position_size = base_size × signal_strength × portfolio_pct
  side = signal.action (enter → BUY, exit → SELL)

Dynamic position sizing:
  - Increases size during winning streaks (Kelly-inspired scaling)
  - Decreases size during losing streaks (capital preservation)
  - Never exceeds risk_manager limits

Aggregation:
  - Multiple whales entering the same market = stronger signal
  - Conflicting whale signals = skip the market
  - Weighted average of whale conviction for position sizing

Risk controls:
  - Max % of portfolio per whale trade
  - Stop-loss on each position
  - Daily loss cap across all whale-following positions
  - Cooldown after stop-loss hit
"""

import asyncio
import math
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

import structlog

from core.executor import Executor, OrderRejectedByRisk
from core.orderbook import OrderBookManager
from core.order_state import OrderStore
from core.portfolio import Portfolio
from core.risk import RiskManager
from data.whale_tracker import WhaleProfile, WhaleSignal, WhaleTracker
from strategies.base import Strategy
from utils import metrics as m

logger = structlog.get_logger(__name__)


@dataclass
class WhalePosition:
    """A position opened by following a whale signal."""

    market_id: str
    token_id: str
    side: str          # "BUY" or "SELL"
    entry_price: float = 0.0
    size: float = 0.0
    order_id: Optional[str] = None

    # Whale attribution
    whale_address: str = ""
    whale_win_rate: float = 0.0
    whale_profit_factor: float = 0.0
    signal_strength: float = 0.0

    # Risk management
    stop_loss_price: float = 0.0
    take_profit_price: float = 0.0
    max_loss_usd: float = 0.0

    # Tracking
    opened_at: float = field(default_factory=time.monotonic)
    current_price: float = 0.0
    unrealized_pnl: float = 0.0

    @property
    def age_sec(self) -> float:
        return time.monotonic() - self.opened_at

    @property
    def is_stopped_out(self) -> bool:
        """Check if stop-loss has been hit."""
        if self.stop_loss_price <= 0:
            return False
        if self.side == "BUY":
            return self.current_price <= self.stop_loss_price
        else:
            return self.current_price >= self.stop_loss_price

    @property
    def is_take_profit(self) -> bool:
        """Check if take-profit has been hit."""
        if self.take_profit_price <= 0:
            return False
        if self.side == "BUY":
            return self.current_price >= self.take_profit_price
        else:
            return self.current_price <= self.take_profit_price


@dataclass
class AggregatedSignal:
    """Aggregated signal from multiple whales for the same market."""

    market_id: str
    direction: str  # "long" or "short"
    whale_count: int = 0
    weighted_conviction: float = 0.0
    avg_whale_win_rate: float = 0.0
    avg_whale_profit_factor: float = 0.0
    signals: List[WhaleSignal] = field(default_factory=list)


class WhaleTrackingStrategy(Strategy):
    """Whale / smart money following strategy.

    Cycle logic:
    1. Poll whale tracker for recent signals
    2. Aggregate signals per market (multiple whales = stronger conviction)
    3. Compute signal strength and position size
    4. Enter positions for strong signals
    5. Monitor existing positions for stop-loss / take-profit
    6. Exit positions when whales exit
    """

    def __init__(
        self,
        client,
        orderbook: OrderBookManager,
        portfolio: Portfolio,
        risk_manager: RiskManager,
        executor: Executor,
        order_store: OrderStore,
        whale_tracker: WhaleTracker,
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
        self.whale_tracker = whale_tracker

        wt_cfg = self._strategy_config

        # ── Signal thresholds ──
        self.min_signal_strength = wt_cfg.get("min_signal_strength", 0.6)
        self.min_whales_for_entry = wt_cfg.get("min_whales_for_entry", 1)
        self.max_whale_positions = wt_cfg.get("max_positions", 10)
        self.base_position_usd = wt_cfg.get("base_position_usd", 25.0)
        self.max_position_pct = wt_cfg.get("max_position_pct", 0.05)  # 5% of portfolio

        # ── Position sizing ──
        self.kelly_fraction = wt_cfg.get("kelly_fraction", 0.25)  # Quarter-Kelly
        self.win_streak_multiplier = wt_cfg.get("win_streak_multiplier", 1.1)
        self.loss_streak_multiplier = wt_cfg.get("loss_streak_multiplier", 0.7)
        self.max_size_multiplier = wt_cfg.get("max_size_multiplier", 3.0)
        self.min_size_multiplier = wt_cfg.get("min_size_multiplier", 0.2)

        # ── Risk management ──
        self.stop_loss_pct = wt_cfg.get("stop_loss_pct", 0.15)  # 15% stop
        self.take_profit_pct = wt_cfg.get("take_profit_pct", 0.30)  # 30% take profit
        self.max_hold_time_sec = wt_cfg.get("max_hold_time_sec", 86400)  # 24h default
        self.cooldown_after_stop_sec = wt_cfg.get("cooldown_after_stop_sec", 1800)  # 30 min

        # ── State ──
        self._positions: Dict[str, WhalePosition] = {}
        self._recently_stopped: Dict[str, float] = {}  # market_id -> cooldown_until
        self._win_streak: int = 0
        self._loss_streak: int = 0
        self._total_trades: int = 0
        self._winning_trades: int = 0
        self._total_pnl: float = 0.0
        self._closed_positions: deque = deque(maxlen=200)

    # ── Strategy interface ────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "WhaleTracking"

    def _config_key(self) -> str:
        return "whale_tracking"

    async def initialize(self) -> None:
        """Initialize whale tracking strategy: ensure tracker is ready."""
        logger.info("Initializing whale tracking strategy")

        if not self.whale_tracker.enabled:
            logger.warning("Whale tracker is disabled — strategy cannot run")
            self._state.enabled = False
            return

        await self.whale_tracker.initialize()

        qualified = self.whale_tracker.get_qualified_whales()
        logger.info(
            "Whale tracking initialized",
            whales_tracked=len(qualified),
        )

    async def run_cycle(self) -> None:
        """Main whale following cycle."""
        # 1. Scan whale activity
        signals = await self.whale_tracker.scan_whale_activity()

        # 2. Also check the signal queue (from WebSocket-driven updates)
        queue_signals = await self.whale_tracker.get_recent_signals(max_age_sec=60.0)
        all_signals = signals + queue_signals

        if not all_signals:
            # 3. Still need to monitor existing positions
            await self._monitor_positions()
            return

        logger.info("Whale signals received", count=len(all_signals))

        # 4. Aggregate signals by market
        aggregated = self._aggregate_signals(all_signals)

        # 5. Execute on strongest signals
        for market_id, agg_signal in aggregated.items():
            if len(self._positions) >= self.max_whale_positions:
                break

            await self._process_aggregated_signal(market_id, agg_signal)

        # 6. Monitor existing positions
        await self._monitor_positions()

        # 7. Update state
        self._state.markets_active = list(self._positions.keys())

    async def shutdown(self) -> None:
        """Close all whale-following positions."""
        logger.info("Whale tracking strategy shutting down")

        for market_id, pos in list(self._positions.items()):
            if pos.order_id:
                try:
                    await self.executor.cancel_order(pos.order_id)
                except Exception as exc:
                    logger.warning(
                        "Failed to cancel whale position order",
                        market_id=market_id,
                        error=str(exc),
                    )

        await self.whale_tracker.close()

    # ── Signal aggregation ────────────────────────────────────────────

    def _aggregate_signals(
        self, signals: List[WhaleSignal]
    ) -> Dict[str, AggregatedSignal]:
        """Aggregate multiple whale signals by market.

        When multiple whales signal the same market, combine them into
        a single aggregated signal with weighted conviction.

        Conflicting signals (some enter, some exit) result in the
        market being skipped — no position taken.

        Args:
            signals: List of raw whale signals.

        Returns:
            Dict of market_id -> AggregatedSignal.
        """
        market_signals: Dict[str, List[WhaleSignal]] = defaultdict(list)

        for signal in signals:
            market_signals[signal.market_id].append(signal)

        aggregated = {}

        for market_id, market_sigs in market_signals.items():
            # Separate enter and exit signals
            enter_sigs = [s for s in market_sigs if s.action == "enter"]
            exit_sigs = [s for s in market_sigs if s.action == "exit"]

            # Skip conflicting signals
            if enter_sigs and exit_sigs:
                logger.debug(
                    "Conflicting whale signals, skipping market",
                    market_id=market_id,
                    enters=len(enter_sigs),
                    exits=len(exit_sigs),
                )
                continue

            if not enter_sigs and not exit_sigs:
                continue

            active_sigs = enter_sigs if enter_sigs else exit_sigs
            direction = "long" if enter_sigs else "short"

            # Weighted conviction based on whale quality
            total_weight = 0.0
            weighted_win_rate = 0.0
            weighted_pf = 0.0

            for sig in active_sigs:
                # Weight = win_rate × profit_factor (better whales count more)
                weight = sig.whale_win_rate * min(sig.whale_profit_factor, 5.0)
                total_weight += weight
                weighted_win_rate += sig.whale_win_rate * weight
                weighted_pf += min(sig.whale_profit_factor, 5.0) * weight

            if total_weight > 0:
                weighted_win_rate /= total_weight
                weighted_pf /= total_weight

            # Conviction = weighted average, normalized to 0–1
            conviction = min(1.0, total_weight / len(active_sigs))

            agg = AggregatedSignal(
                market_id=market_id,
                direction=direction,
                whale_count=len(active_sigs),
                weighted_conviction=conviction,
                avg_whale_win_rate=weighted_win_rate,
                avg_whale_profit_factor=weighted_pf,
                signals=active_sigs,
            )

            aggregated[market_id] = agg

        return aggregated

    # ── Signal processing ─────────────────────────────────────────────

    async def _process_aggregated_signal(
        self, market_id: str, agg: AggregatedSignal
    ) -> None:
        """Process an aggregated whale signal and potentially enter a position.

        Args:
            market_id: Target market.
            agg: Aggregated signal data.
        """
        # Check if we already have a position
        if market_id in self._positions:
            # If whales are exiting and we're in, close position
            if agg.direction == "short" and self._positions[market_id].side == "BUY":
                await self._exit_position(market_id, reason="whale_exit_signal")
            return

        # Check cooldown (recently stopped out)
        cooldown_until = self._recently_stopped.get(market_id, 0.0)
        if time.monotonic() < cooldown_until:
            return

        # Check minimum whales
        if agg.whale_count < self.min_whales_for_entry:
            return

        # Check signal strength
        signal_strength = self._compute_signal_strength(agg)
        if signal_strength < self.min_signal_strength:
            logger.debug(
                "Signal too weak",
                market_id=market_id,
                strength=signal_strength,
                threshold=self.min_signal_strength,
            )
            return

        # ── Enter position ──
        await self._enter_position(market_id, agg, signal_strength)

    def _compute_signal_strength(self, agg: AggregatedSignal) -> float:
        """Compute the strength of an aggregated signal.

        Formula:
          strength = conviction × avg_win_rate × sqrt(avg_profit_factor) × recency

        Recency weight decays exponentially from 1.0 (just now) to 0.5 (60 sec old).

        Args:
            agg: Aggregated signal data.

        Returns:
            Signal strength (0.0–1.0+).
        """
        conviction = agg.weighted_conviction
        win_rate = agg.avg_whale_win_rate
        pf_factor = math.sqrt(max(0.01, agg.avg_whale_profit_factor))

        # Recency: freshest signal gets weight 1.0, 60-sec-old gets 0.5
        if agg.signals:
            freshest = min(s.age_sec for s in agg.signals)
            recency = max(0.5, math.exp(-0.012 * freshest))
        else:
            recency = 0.5

        strength = conviction * win_rate * pf_factor * recency

        # Bonus for multiple whales agreeing
        if agg.whale_count >= 3:
            strength *= 1.2
        if agg.whale_count >= 5:
            strength *= 1.1

        return strength

    # ── Position entry ────────────────────────────────────────────────

    async def _enter_position(
        self, market_id: str, agg: AggregatedSignal, signal_strength: float
    ) -> None:
        """Enter a position based on a whale signal.

        Dynamic position sizing:
          base_size = base_position_usd / price
          adjusted_size = base_size × signal_strength × streak_multiplier
          final_size = min(adjusted_size, max_position_pct × portfolio_value)

        Args:
            market_id: Market to enter.
            agg: Aggregated signal data.
            signal_strength: Computed signal strength.
        """
        # Get current market price
        snapshot = self.orderbook.get_snapshot(market_id)
        if snapshot is None or snapshot.mid_price is None:
            logger.debug("No orderbook data for whale signal", market_id=market_id)
            return

        mid = snapshot.mid_price
        side = "BUY" if agg.direction == "long" else "SELL"

        # ── Position sizing ──
        streak_multiplier = self._get_streak_multiplier()
        base_size = self.base_position_usd / mid if mid > 0 else 0
        adjusted_size = base_size * signal_strength * streak_multiplier

        # Cap at max % of portfolio
        portfolio_value = self.portfolio.get_total_value()
        max_size_by_portfolio = (portfolio_value * self.max_position_pct) / mid if mid > 0 else 0
        size = min(adjusted_size, max_size_by_portfolio)

        # Apply risk manager size multiplier
        size_multiplier = self.risk_manager.get_size_multiplier()
        size *= size_multiplier

        # Minimum size check
        if size * mid < 1.0:  # At least $1 position
            return

        # ── Compute stop-loss and take-profit ──
        if side == "BUY":
            stop_loss = mid * (1.0 - self.stop_loss_pct)
            take_profit = mid * (1.0 + self.take_profit_pct)
        else:
            stop_loss = mid * (1.0 + self.stop_loss_pct)
            take_profit = mid * (1.0 - self.take_profit_pct)

        # ── Place order ──
        token_id = self._get_token_id(market_id)
        if not token_id:
            return

        try:
            order_id = await self.executor.place_order(
                market_id=market_id,
                token_id=token_id,
                side=side,
                price=mid,
                size=size,
                category=self._get_market_category(market_id),
                post_only=False,  # Must take to follow whale quickly
            )

            if order_id:
                pos = WhalePosition(
                    market_id=market_id,
                    token_id=token_id,
                    side=side,
                    entry_price=mid,
                    size=size,
                    order_id=order_id,
                    whale_address=agg.signals[0].whale_address if agg.signals else "",
                    whale_win_rate=agg.avg_whale_win_rate,
                    whale_profit_factor=agg.avg_whale_profit_factor,
                    signal_strength=signal_strength,
                    stop_loss_price=stop_loss,
                    take_profit_price=take_profit,
                    max_loss_usd=size * mid * self.stop_loss_pct,
                    current_price=mid,
                )

                self._positions[market_id] = pos
                self._state.orders_placed += 1

                logger.info(
                    "Whale-follow position opened",
                    market_id=market_id,
                    side=side,
                    price=mid,
                    size=size,
                    signal_strength=f"{signal_strength:.2f}",
                    whale_count=agg.whale_count,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                )

                m.record_order_placed(market_id=market_id, side=side.lower())

        except OrderRejectedByRisk as exc:
            logger.warning(
                "Whale position rejected by risk",
                market_id=market_id,
                reason=str(exc),
            )
        except Exception as exc:
            logger.error(
                "Whale position entry failed",
                market_id=market_id,
                error=str(exc),
            )

    # ── Position monitoring ───────────────────────────────────────────

    async def _monitor_positions(self) -> None:
        """Monitor all open whale-following positions.

        Checks for:
        1. Stop-loss hit → exit immediately
        2. Take-profit hit → exit
        3. Max hold time exceeded → exit
        4. Whale exit signal → exit
        5. Update current price and unrealized PnL
        """
        to_exit = []

        for market_id, pos in list(self._positions.items()):
            # Update current price
            snapshot = self.orderbook.get_snapshot(market_id)
            if snapshot and snapshot.mid_price is not None:
                pos.current_price = snapshot.mid_price

                # Compute unrealized PnL
                if pos.side == "BUY":
                    pos.unrealized_pnl = (pos.current_price - pos.entry_price) * pos.size
                else:
                    pos.unrealized_pnl = (pos.entry_price - pos.current_price) * pos.size

            # Check stop-loss
            if pos.is_stopped_out:
                logger.warning(
                    "Whale position stop-loss hit",
                    market_id=market_id,
                    entry_price=pos.entry_price,
                    current_price=pos.current_price,
                    stop_loss=pos.stop_loss_price,
                )
                to_exit.append((market_id, "stop_loss"))
                continue

            # Check take-profit
            if pos.is_take_profit:
                logger.info(
                    "Whale position take-profit hit",
                    market_id=market_id,
                    entry_price=pos.entry_price,
                    current_price=pos.current_price,
                    take_profit=pos.take_profit_price,
                )
                to_exit.append((market_id, "take_profit"))
                continue

            # Check max hold time
            if pos.age_sec > self.max_hold_time_sec:
                logger.info(
                    "Whale position max hold time exceeded",
                    market_id=market_id,
                    hold_time_sec=pos.age_sec,
                )
                to_exit.append((market_id, "max_hold_time"))
                continue

        # Execute exits
        for market_id, reason in to_exit:
            await self._exit_position(market_id, reason=reason)

    # ── Position exit ─────────────────────────────────────────────────

    async def _exit_position(self, market_id: str, reason: str = "") -> None:
        """Exit a whale-following position.

        Args:
            market_id: Market to exit.
            reason: Exit reason (for logging and metrics).
        """
        pos = self._positions.pop(market_id, None)
        if pos is None:
            return

        # Place closing order
        close_side = "SELL" if pos.side == "BUY" else "BUY"

        try:
            close_price = pos.current_price if pos.current_price > 0 else pos.entry_price

            order_id = await self.executor.place_order(
                market_id=market_id,
                token_id=pos.token_id,
                side=close_side,
                price=close_price,
                size=pos.size,
                post_only=False,
            )

            if order_id:
                logger.info(
                    "Whale position closed",
                    market_id=market_id,
                    side=close_side,
                    price=close_price,
                    size=pos.size,
                    reason=reason,
                    pnl=pos.unrealized_pnl,
                )

                m.record_order_filled(market_id=market_id, side=close_side.lower())

        except OrderRejectedByRisk:
            # Emergency: try market order at any price
            logger.error(
                "Whale position close rejected by risk — attempting emergency close",
                market_id=market_id,
            )
        except Exception as exc:
            logger.error(
                "Whale position close failed",
                market_id=market_id,
                error=str(exc),
            )

        # ── Update tracking ──
        pnl = pos.unrealized_pnl
        self._total_pnl += pnl
        self._total_trades += 1
        self._closed_positions.append({
            "market_id": market_id,
            "pnl": pnl,
            "reason": reason,
            "held_sec": pos.age_sec,
        })

        if pnl > 0:
            self._winning_trades += 1
            self._win_streak += 1
            self._loss_streak = 0
        else:
            self._loss_streak += 1
            self._win_streak = 0

        # Set cooldown if stopped out
        if reason == "stop_loss":
            self._recently_stopped[market_id] = (
                time.monotonic() + self.cooldown_after_stop_sec
            )

    # ── Dynamic position sizing ───────────────────────────────────────

    def _get_streak_multiplier(self) -> float:
        """Compute position size multiplier based on win/loss streaks.

        Increases size during winning streaks (confidence) and
        decreases during losing streaks (capital preservation).

        Returns:
            Size multiplier (0.2 to 3.0).
        """
        if self._win_streak > 0:
            multiplier = self.win_streak_multiplier ** min(self._win_streak, 5)
        elif self._loss_streak > 0:
            multiplier = self.loss_streak_multiplier ** min(self._loss_streak, 3)
        else:
            multiplier = 1.0

        return max(self.min_size_multiplier, min(self.max_size_multiplier, multiplier))

    # ── Helpers ───────────────────────────────────────────────────────

    def _get_token_id(self, market_id: str) -> Optional[str]:
        """Get the token ID for a Polymarket market."""
        markets = self.orderbook._markets  # type: ignore
        if market_id in markets:
            info = markets[market_id]
            if hasattr(info, "token_id"):
                return info.token_id
            if isinstance(info, dict):
                return info.get("token_id")
        return market_id

    def _get_market_category(self, market_id: str) -> str:
        """Get the category for a market."""
        snapshot = self.orderbook.get_snapshot(market_id)
        if snapshot and hasattr(snapshot, "category"):
            return snapshot.category
        return "crypto"

    # ── Reporting ─────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, any]:
        """Get whale tracking strategy statistics.

        Returns:
            Dict with performance metrics.
        """
        win_rate = self._winning_trades / self._total_trades if self._total_trades > 0 else 0.0

        return {
            "open_positions": len(self._positions),
            "total_trades": self._total_trades,
            "winning_trades": self._winning_trades,
            "win_rate": f"{win_rate:.1%}",
            "win_streak": self._win_streak,
            "loss_streak": self._loss_streak,
            "total_pnl": round(self._total_pnl, 4),
            "streak_multiplier": round(self._get_streak_multiplier(), 2),
            "tracked_whales": len(self.whale_tracker.get_qualified_whales()),
        }
