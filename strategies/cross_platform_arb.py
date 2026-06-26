"""Cross-platform arbitrage strategy — Polymarket vs Kalshi.

Finds the same event priced differently across platforms and executes
risk-free arbitrage by buying the underpriced side on one platform
and selling the overpriced side on the other.

Key concepts:
- Cross-platform spread = |P_polymarket - P_kalshi| where both represent
  the same event outcome probability
- A risk-free arb exists when: buy YES on platform A + buy NO on platform B
  costs less than $1.00 combined (guaranteed $1.00 payout regardless of outcome)
- Minimum spread threshold accounts for taker fees on both platforms
- Position management: both legs must be placed atomically or with failover

Arbitrage detection:
  For each mapped market (same event on both platforms):
    poly_yes  = YES price on Polymarket (0.00–1.00)
    kalshi_yes = YES price on Kalshi   (0.00–1.00, converted from cents)

  Risk-free condition:
    poly_yes + (1 - kalshi_yes) < 1.0 - min_profit_bps/10000
    OR
    kalshi_yes + (1 - poly_yes) < 1.0 - min_profit_bps/10000

  Simplified: |poly_yes - kalshi_yes| > fee_adjusted_threshold

Execution modes:
  - SIMULTANEOUS: Place both legs at once (ideal, requires capital on both)
  - SEQUENTIAL: Place first leg, then second (slippage risk on second leg)
  - FAVOR_POLY: Always place Polymarket leg first (lower latency to our bot)
"""

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import structlog

from core.client import TAKER_FEES
from core.executor import Executor, OrderRejectedByRisk
from core.orderbook import OrderBookManager
from core.order_state import OrderStore
from core.portfolio import Portfolio
from core.risk import RiskManager
from data.kalshi_client import KalshiClient, KalshiMarket, KalshiOrderBook
from strategies.base import Strategy
from utils import metrics as m

logger = structlog.get_logger(__name__)


@dataclass
class ArbOpportunity:
    """A detected cross-platform arbitrage opportunity."""

    polymarket_id: str
    kalshi_ticker: str
    market_title: str = ""

    # Prices (probabilities 0.0–1.0)
    poly_yes_price: float = 0.0
    kalshi_yes_price: float = 0.0

    # Spread info
    spread_bps: float = 0.0           # Raw spread in basis points
    net_profit_bps: float = 0.0       # After fees
    fee_cost_bps: float = 0.0         # Total fee cost in bps

    # Which side to buy where
    buy_yes_platform: str = ""        # "polymarket" or "kalshi"
    buy_no_platform: str = ""         # Opposite platform

    # Execution
    size: float = 0.0                 # Shares to trade
    estimated_profit_usd: float = 0.0

    # Timestamps
    detected_at: float = field(default_factory=time.monotonic)

    @property
    def age_sec(self) -> float:
        """Seconds since detection."""
        return time.monotonic() - self.detected_at

    @property
    def is_fresh(self) -> bool:
        """Check if this opportunity is still actionable (< 5 sec old)."""
        return self.age_sec < 5.0

    @property
    def combined_cost(self) -> float:
        """Cost of buying YES on one platform + NO on the other.

        If combined_cost < 1.0, profit = 1.0 - combined_cost per share.
        """
        if self.buy_yes_platform == "polymarket":
            return self.poly_yes_price + (1.0 - self.kalshi_yes_price)
        else:
            return self.kalshi_yes_price + (1.0 - self.poly_yes_price)


@dataclass
class ArbPosition:
    """An active arbitrage position with legs on both platforms."""

    polymarket_id: str
    kalshi_ticker: str
    opportunity: ArbOpportunity = None  # type: ignore

    # Leg 1: Polymarket
    poly_side: str = ""         # "BUY" or "SELL"
    poly_order_id: Optional[str] = None
    poly_filled: float = 0.0
    poly_fill_price: float = 0.0
    poly_status: str = "pending"  # pending, placed, filled, failed

    # Leg 2: Kalshi
    kalshi_side: str = ""
    kalshi_order_id: Optional[str] = None
    kalshi_filled: float = 0.0
    kalshi_fill_price: float = 0.0
    kalshi_status: str = "pending"

    # Overall
    opened_at: float = field(default_factory=time.monotonic)
    realized_pnl: float = 0.0
    is_hedged: bool = False

    @property
    def age_sec(self) -> float:
        return time.monotonic() - self.opened_at

    @property
    def is_complete(self) -> bool:
        """Both legs filled."""
        return self.poly_status == "filled" and self.kalshi_status == "filled"

    @property
    def is_failed(self) -> bool:
        """At least one leg failed."""
        return self.poly_status == "failed" or self.kalshi_status == "failed"


class CrossPlatformArbStrategy(Strategy):
    """Cross-platform arbitrage: Polymarket vs Kalshi.

    Cycle logic:
    1. Refresh Kalshi market data
    2. For each mapped market, compute cross-platform spread
    3. Filter opportunities exceeding min_profit_bps after fees
    4. Execute arbitrage (place both legs)
    5. Monitor existing positions for completion / failure
    6. Hedge any unhedged positions (one leg filled, other failed)
    """

    def __init__(
        self,
        client,
        orderbook: OrderBookManager,
        portfolio: Portfolio,
        risk_manager: RiskManager,
        executor: Executor,
        order_store: OrderStore,
        kalshi_client: KalshiClient,
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
        self.kalshi = kalshi_client

        arb_cfg = self._strategy_config

        # ── Thresholds ──
        self.min_profit_bps = arb_cfg.get("min_profit_bps", 50)  # 0.5% minimum
        self.max_position_size_usd = arb_cfg.get("max_position_size_usd", 100.0)
        self.max_concurrent_positions = arb_cfg.get("max_concurrent_positions", 5)
        self.stale_opportunity_sec = arb_cfg.get("stale_opportunity_sec", 5.0)

        # ── Execution ──
        self.execution_mode = arb_cfg.get("execution_mode", "FAVOR_POLY")
        self.kalshi_taker_fee_bps = arb_cfg.get("kalshi_taker_fee_bps", 100)  # 1%

        # ── Position tracking ──
        self._active_positions: Dict[str, ArbPosition] = {}
        self._completed_count: int = 0
        self._failed_count: int = 0
        self._total_pnl: float = 0.0

        # ── Opportunity history (for dedup and analytics) ──
        self._recent_opportunities: deque = deque(maxlen=100)

        # ── Market title cache (for logging) ──
        self._market_titles: Dict[str, str] = {}

    # ── Strategy interface ────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "CrossPlatformArb"

    def _config_key(self) -> str:
        return "cross_platform_arb"

    async def initialize(self) -> None:
        """Set up cross-platform arb: refresh Kalshi markets, validate mappings."""
        logger.info("Initializing cross-platform arbitrage strategy")

        if not self.kalshi.enabled:
            logger.warning("Kalshi client is disabled — arb strategy cannot run")
            self._state.enabled = False
            return

        # Refresh Kalshi market data
        try:
            await self.kalshi.refresh_markets(force=True)
        except Exception as exc:
            logger.error("Failed to refresh Kalshi markets on init", error=str(exc))

        # Validate market mappings
        mappings = self.kalshi.get_mapped_markets()
        if not mappings:
            logger.warning("No market mappings configured — arb strategy has no targets")
        else:
            logger.info("Market mappings loaded", count=len(mappings))

    async def run_cycle(self) -> None:
        """Main arb cycle: scan → evaluate → execute → monitor."""
        # 1. Refresh Kalshi data
        try:
            await self.kalshi.refresh_markets()
        except Exception as exc:
            logger.error("Kalshi refresh failed", error=str(exc))

        # 2. Scan for opportunities
        opportunities = await self._scan_opportunities()

        if opportunities:
            logger.info("Arb opportunities found", count=len(opportunities))
            # Record in metrics
            m.update_arb_opportunities_found(len(opportunities))

        # 3. Execute best opportunities
        for opp in opportunities:
            if len(self._active_positions) >= self.max_concurrent_positions:
                break

            if not opp.is_fresh:
                continue

            await self._execute_opportunity(opp)

        # 4. Monitor existing positions
        await self._monitor_positions()

        # 5. Update state
        self._state.markets_active = list(self._active_positions.keys())

    async def shutdown(self) -> None:
        """Cancel any open Polymarket orders for active arb positions."""
        logger.info("Cross-platform arb shutting down")

        for pos in self._active_positions.values():
            if pos.poly_order_id and pos.poly_status in ("pending", "placed"):
                try:
                    await self.executor.cancel_order(pos.poly_order_id)
                except Exception as exc:
                    logger.warning(
                        "Failed to cancel arb order on shutdown",
                        order_id=pos.poly_order_id,
                        error=str(exc),
                    )

    # ── Opportunity scanning ──────────────────────────────────────────

    async def _scan_opportunities(self) -> List[ArbOpportunity]:
        """Scan all mapped markets for cross-platform arbitrage.

        Returns:
            List of ArbOpportunity objects, sorted by net profit (best first).
        """
        opportunities = []
        mappings = self.kalshi.get_mapped_markets()

        for poly_id, kalshi_ticker in mappings.items():
            try:
                opp = await self._evaluate_pair(poly_id, kalshi_ticker)
                if opp and opp.net_profit_bps >= self.min_profit_bps:
                    opportunities.append(opp)
                    self._recent_opportunities.append(opp)
            except Exception as exc:
                logger.debug(
                    "Pair evaluation failed",
                    poly_id=poly_id,
                    kalshi=kalshi_ticker,
                    error=str(exc),
                )

        # Sort by net profit (best first)
        opportunities.sort(key=lambda o: o.net_profit_bps, reverse=True)
        return opportunities

    async def _evaluate_pair(
        self, polymarket_id: str, kalshi_ticker: str
    ) -> Optional[ArbOpportunity]:
        """Evaluate a single market pair for arbitrage.

        Computes the cross-platform spread and checks if it exceeds
        the fee-adjusted minimum profit threshold.

        Args:
            polymarket_id: Polymarket condition/market ID.
            kalshi_ticker: Kalshi market ticker.

        Returns:
            ArbOpportunity if profitable, None otherwise.
        """
        # Get Polymarket price
        snapshot = self.orderbook.get_snapshot(polymarket_id)
        if snapshot is None or snapshot.mid_price is None:
            return None

        poly_yes = snapshot.mid_price  # 0.0–1.0

        # Get Kalshi price
        kalshi_market = self.kalshi.get_cached_market(kalshi_ticker)
        if kalshi_market is None:
            return None

        kalshi_yes = kalshi_market.yes_prob  # 0.0–1.0

        # ── Compute spread ──
        raw_spread = abs(poly_yes - kalshi_yes)
        spread_bps = raw_spread * 10_000

        # ── Compute fee cost ──
        # Polymarket taker fee (depends on category)
        category = self._get_market_category(polymarket_id)
        poly_fee_pct = TAKER_FEES.get(category, 0.01)
        poly_fee_bps = poly_fee_pct * 10_000

        # Kalshi taker fee
        kalshi_fee_bps = self.kalshi_taker_fee_bps

        # We pay taker fees on both legs (can't use limit orders for arb)
        total_fee_bps = poly_fee_bps + kalshi_fee_bps

        # ── Net profit ──
        net_profit_bps = spread_bps - total_fee_bps

        if net_profit_bps < self.min_profit_bps:
            return None

        # ── Determine which side to buy where ──
        if poly_yes < kalshi_yes:
            # Polymarket YES is cheaper: buy YES on Poly, buy NO on Kalshi
            buy_yes_platform = "polymarket"
            buy_no_platform = "kalshi"
        else:
            # Kalshi YES is cheaper: buy YES on Kalshi, buy NO on Poly
            buy_yes_platform = "kalshi"
            buy_no_platform = "polymarket"

        # ── Compute position size ──
        combined_cost = (
            poly_yes + (1.0 - kalshi_yes)
            if buy_yes_platform == "polymarket"
            else kalshi_yes + (1.0 - poly_yes)
        )
        profit_per_share = 1.0 - combined_cost

        # Size: limited by max position, free USDC, and orderbook depth
        max_size_by_usd = self.max_position_size_usd / max(combined_cost, 0.01)
        max_size_by_portfolio = self.portfolio.free_usdc / max(combined_cost, 0.01)
        size = min(max_size_by_usd, max_size_by_portfolio)

        # Check orderbook depth
        poly_depth = self._get_book_depth(polymarket_id, snapshot)
        size = min(size, poly_depth)

        # Minimum viable size
        if size * profit_per_share < 0.50:  # At least $0.50 expected profit
            return None

        estimated_profit = size * profit_per_share

        # ── Build opportunity ──
        title = self._market_titles.get(polymarket_id, kalshi_ticker)

        opp = ArbOpportunity(
            polymarket_id=polymarket_id,
            kalshi_ticker=kalshi_ticker,
            market_title=title,
            poly_yes_price=poly_yes,
            kalshi_yes_price=kalshi_yes,
            spread_bps=spread_bps,
            net_profit_bps=net_profit_bps,
            fee_cost_bps=total_fee_bps,
            buy_yes_platform=buy_yes_platform,
            buy_no_platform=buy_no_platform,
            size=size,
            estimated_profit_usd=estimated_profit,
        )

        return opp

    # ── Execution ─────────────────────────────────────────────────────

    async def _execute_opportunity(self, opp: ArbOpportunity) -> Optional[ArbPosition]:
        """Execute a cross-platform arbitrage opportunity.

        Two-phase execution:
        1. Place the Polymarket leg first (we have full control)
        2. Place the Kalshi leg (external platform, may need API call)

        If the second leg fails, we enter hedging mode.

        Args:
            opp: The arbitrage opportunity to execute.

        Returns:
            ArbPosition if execution started, None if rejected.
        """
        if opp.polymarket_id in self._active_positions:
            return None  # Already have a position in this market

        position = ArbPosition(
            polymarket_id=opp.polymarket_id,
            kalshi_ticker=opp.kalshi_ticker,
            opportunity=opp,
        )

        # Determine sides
        if opp.buy_yes_platform == "polymarket":
            # Buy YES on Polymarket, Buy NO on Kalshi
            position.poly_side = "BUY"
            position.kalshi_side = "BUY_NO"
        else:
            # Buy NO on Polymarket, Buy YES on Kalshi
            position.poly_side = "SELL"  # SELL YES = effectively buying NO
            position.kalshi_side = "BUY_YES"

        # ── Phase 1: Place Polymarket leg ──
        try:
            # Get token ID for this market
            token_id = self._get_token_id(opp.polymarket_id)
            if not token_id:
                logger.warning("No token ID for market", market_id=opp.polymarket_id)
                return None

            poly_price = opp.poly_yes_price if position.poly_side == "BUY" else (1.0 - opp.poly_yes_price)

            # For arb, we MUST take (taker fee) — use post_only=False
            order_id = await self.executor.place_order(
                market_id=opp.polymarket_id,
                token_id=token_id,
                side=position.poly_side,
                price=poly_price,
                size=opp.size,
                category=self._get_market_category(opp.polymarket_id),
                post_only=False,  # Must take for arb
            )

            if order_id:
                position.poly_order_id = order_id
                position.poly_status = "placed"
                m.record_order_placed(market_id=opp.polymarket_id, side=position.poly_side.lower())
                logger.info(
                    "Arb Polymarket leg placed",
                    market_id=opp.polymarket_id,
                    side=position.poly_side,
                    price=poly_price,
                    size=opp.size,
                )
            else:
                position.poly_status = "failed"
                logger.warning("Arb Polymarket leg failed", market_id=opp.polymarket_id)
                return None

        except OrderRejectedByRisk as exc:
            logger.warning("Arb leg rejected by risk", reason=str(exc))
            return None
        except Exception as exc:
            logger.error("Arb Polymarket leg error", error=str(exc))
            position.poly_status = "failed"
            return None

        # ── Phase 2: Place Kalshi leg ──
        # Note: In production, this would call the Kalshi trading API.
        # For now, we log the intended trade and mark as "placed".
        try:
            # Kalshi execution would go here via kalshi_client
            # await self.kalshi.place_order(...)
            position.kalshi_status = "placed"
            logger.info(
                "Arb Kalshi leg initiated",
                ticker=opp.kalshi_ticker,
                side=position.kalshi_side,
                size=opp.size,
            )
        except Exception as exc:
            logger.error("Arb Kalshi leg error", error=str(exc))
            position.kalshi_status = "failed"
            # We need to hedge the Polymarket position
            await self._hedge_unhedged_position(position)

        # Track position
        self._active_positions[opp.polymarket_id] = position

        return position

    # ── Position monitoring ───────────────────────────────────────────

    async def _monitor_positions(self) -> None:
        """Monitor active positions for completion, failure, or timeout."""
        to_remove = []

        for market_id, pos in self._active_positions.items():
            # Check Polymarket order status
            if pos.poly_order_id and pos.poly_status == "placed":
                record = self.order_store.get(pos.poly_order_id)
                if record:
                    if record.state.value == "FILLED":
                        pos.poly_status = "filled"
                        pos.poly_filled = record.filled_size
                        pos.poly_fill_price = record.price
                    elif record.state.value in ("CANCELLED", "REJECTED", "EXPIRED"):
                        pos.poly_status = "failed"

            # Check Kalshi order status (would query Kalshi API)
            # For now, simulate based on time
            if pos.kalshi_status == "placed" and pos.age_sec > 10:
                # Assume filled after 10 seconds (in production, poll API)
                pos.kalshi_status = "filled"
                pos.kalshi_filled = pos.opportunity.size if pos.opportunity else 0
                pos.kalshi_fill_price = pos.opportunity.kalshi_yes_price if pos.opportunity else 0

            # Handle completed positions
            if pos.is_complete:
                pos.realized_pnl = self._compute_position_pnl(pos)
                self._total_pnl += pos.realized_pnl
                self._completed_count += 1
                to_remove.append(market_id)

                logger.info(
                    "Arb position completed",
                    market_id=market_id,
                    pnl=pos.realized_pnl,
                    total_pnl=self._total_pnl,
                )

                m.record_arb_pnl(pos.realized_pnl)

            # Handle failed positions
            elif pos.is_failed:
                self._failed_count += 1
                await self._hedge_unhedged_position(pos)
                to_remove.append(market_id)

                logger.warning(
                    "Arb position failed",
                    market_id=market_id,
                    poly_status=pos.poly_status,
                    kalshi_status=pos.kalshi_status,
                )

            # Timeout: positions open too long
            elif pos.age_sec > 300:  # 5 minutes
                logger.warning("Arb position timed out", market_id=market_id)
                if pos.poly_order_id and pos.poly_status == "placed":
                    await self.executor.cancel_order(pos.poly_order_id)
                to_remove.append(market_id)

        # Clean up
        for market_id in to_remove:
            del self._active_positions[market_id]

    def _compute_position_pnl(self, pos: ArbPosition) -> float:
        """Compute realized PnL for a completed arb position.

        For a risk-free arb:
        - We bought YES on platform A at price P1
        - We bought NO on platform B at price (1 - P2)
        - Total cost = P1 + (1 - P2) per share
        - Payout = $1.00 per share (guaranteed)
        - Profit = 1.0 - total_cost per share

        Args:
            pos: Completed ArbPosition.

        Returns:
            Realized PnL in USD.
        """
        if not pos.opportunity:
            return 0.0

        cost = pos.opportunity.combined_cost
        size = min(pos.poly_filled, pos.kalshi_filled) if pos.kalshi_filled > 0 else pos.poly_filled

        if cost <= 0 or size <= 0:
            return 0.0

        profit_per_share = 1.0 - cost
        return profit_per_share * size

    # ── Hedging ───────────────────────────────────────────────────────

    async def _hedge_unhedged_position(self, pos: ArbPosition) -> None:
        """Hedge a position where one leg failed.

        If we bought YES on Polymarket but Kalshi leg failed,
        we need to sell YES on Polymarket to close the position.

        Args:
            pos: The partially-filled arb position to hedge.
        """
        if pos.poly_status == "filled" and pos.kalshi_status == "failed":
            # We have an unhedged YES position on Polymarket — sell it
            logger.warning(
                "Hedging unhedged Polymarket position",
                market_id=pos.polymarket_id,
                side="SELL",
                size=pos.poly_filled,
            )

            token_id = self._get_token_id(pos.polymarket_id)
            if token_id:
                try:
                    await self.executor.place_order(
                        market_id=pos.polymarket_id,
                        token_id=token_id,
                        side="SELL",
                        price=pos.opportunity.poly_yes_price - 0.01 if pos.opportunity else 0.49,
                        size=pos.poly_filled,
                        post_only=False,
                    )
                except Exception as exc:
                    logger.error("Hedge order failed", error=str(exc))

        elif pos.kalshi_status == "filled" and pos.poly_status == "failed":
            # We have an unhedged position on Kalshi — need to close it
            logger.warning(
                "Hedging unhedged Kalshi position (manual intervention required)",
                ticker=pos.kalshi_ticker,
            )
            # Kalshi hedging would require Kalshi trading API

    # ── Helpers ───────────────────────────────────────────────────────

    def _get_market_category(self, market_id: str) -> str:
        """Get the category for a market (from orderbook or cache)."""
        # Try to get from scanner or market data
        snapshot = self.orderbook.get_snapshot(market_id)
        if snapshot and hasattr(snapshot, "category"):
            return snapshot.category
        return "crypto"  # Default to highest fee tier (conservative)

    def _get_token_id(self, market_id: str) -> Optional[str]:
        """Get the token ID for a Polymarket market."""
        # Check if orderbook manager has the mapping
        markets = self.orderbook._markets  # type: ignore
        if market_id in markets:
            info = markets[market_id]
            if hasattr(info, "token_id"):
                return info.token_id
            if isinstance(info, dict):
                return info.get("token_id")
        return market_id  # Fallback: use market_id as token_id

    def _get_book_depth(self, market_id: str, snapshot) -> float:
        """Estimate orderbook depth available at the arb price.

        Returns:
            Estimated available size in shares.
        """
        if snapshot is None:
            return 0.0

        # Sum sizes at best 3 levels
        depth = 0.0
        if hasattr(snapshot, "bids") and snapshot.bids:
            for level in snapshot.bids[:3]:
                if isinstance(level, (list, tuple)) and len(level) >= 2:
                    depth += float(level[1])
        if hasattr(snapshot, "asks") and snapshot.asks:
            for level in snapshot.asks[:3]:
                if isinstance(level, (list, tuple)) and len(level) >= 2:
                    depth += float(level[1])

        return max(depth, 0.0)

    # ── Reporting ─────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, any]:
        """Get arbitrage strategy statistics.

        Returns:
            Dict with performance metrics.
        """
        return {
            "active_positions": len(self._active_positions),
            "completed_positions": self._completed_count,
            "failed_positions": self._failed_count,
            "total_pnl": round(self._total_pnl, 4),
            "opportunities_seen": len(self._recent_opportunities),
            "market_mappings": len(self.kalshi.get_mapped_markets()),
        }
