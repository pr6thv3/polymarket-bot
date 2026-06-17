"""Market-making strategy — Avellaneda-Stoikov dynamic spread with inventory skew.

Core algorithm:
  reservation_price = mid - inventory * δ
  bid = reservation_price - spread/2 - κ·σ·√T
  ask = reservation_price + spread/2 + κ·σ·√T

Where:
  - inventory = our net position in the market (positive = long)
  - δ (delta) = inventory skew factor (shifts quotes away from inventory)
  - κ (kappa) = risk aversion parameter (higher = wider spread)
  - σ (sigma) = rolling volatility from orderbook.VolatilityTracker
  - T = time scaling factor (remaining epoch fraction)

Additional features:
  - Adverse selection guard: pause quoting when volatility spikes
  - Event-driven re-quoting: cancel + replace when midpoint moves
  - Fill rate monitoring: reduce size if getting picked off
  - Rebate qualification: only quote within max qualifying spread
  - News blackout: widen spreads before scheduled events
  - POST_ONLY enforcement: never pay taker fees
"""

import asyncio
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import structlog

from core.client import TAKER_FEES, REBATE_RATES
from core.executor import Executor, OrderRejectedByRisk
from core.orderbook import OrderBookManager
from core.order_state import OrderStore
from core.portfolio import Portfolio
from core.risk import RiskManager
from data.market_scanner import MarketInfo, MarketScanner
from strategies.base import Strategy
from utils import metrics as m

logger = structlog.get_logger(__name__)


@dataclass
class MMPosition:
    """Per-market market-making state."""

    market_id: str
    token_id: str
    category: str = ""
    days_to_resolution: int = 30
    score: float = 0.0

    # Current quotes
    bid_order_id: Optional[str] = None
    ask_order_id: Optional[str] = None
    bid_price: float = 0.0
    ask_price: float = 0.0
    quote_size: float = 0.0

    # Inventory
    net_inventory: float = 0.0  # positive = long

    # Tracking
    last_quote_time: float = 0.0
    last_fill_time: float = 0.0
    consecutive_fills_same_side: int = 0
    last_fill_side: str = ""
    paused: bool = False
    pause_until: float = 0.0
    pause_reason: str = ""

    # Fill rate tracking
    fills_in_window: deque = field(default_factory=lambda: deque(maxlen=50))
    cycles_completed: int = 0
    errors_consecutive: int = 0
    reference_mid: float = 0.0

    @property
    def is_paused(self) -> bool:
        """Check if this market is currently paused."""
        if self.paused and time.monotonic() < self.pause_until:
            return True
        if self.paused and time.monotonic() >= self.pause_until:
            self.paused = False
            self.pause_reason = ""
        return False


class MarketMakingStrategy(Strategy):
    """Avellaneda-Stoikov market-making strategy.

    Quotes both sides of eligible markets with dynamic spreads that
    widen with volatility and skew based on inventory.

    The strategy:
    1. Gets eligible markets from MarketScanner
    2. For each market, computes reservation price and optimal quotes
    3. Places POST_ONLY limit orders on both sides
    4. Re-quotes when midpoint moves beyond threshold
    5. Pauses individual markets on adverse selection signals
    6. Cancels all orders on shutdown
    """

    def __init__(
        self,
        client,
        orderbook: OrderBookManager,
        portfolio: Portfolio,
        risk_manager: RiskManager,
        executor: Executor,
        order_store: OrderStore,
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
        self.scanner = scanner

        mm_cfg = self._strategy_config

        # ── Avellaneda-Stoikov parameters ──
        self.kappa = mm_cfg.get("kappa", 0.5)            # Risk aversion
        self.delta = mm_cfg.get("delta", 0.002)           # Inventory skew per unit
        self.time_horizon = mm_cfg.get("time_horizon", 1.0)  # T scaling

        # ── Spread constraints ──
        self.min_spread_bps = mm_cfg.get("min_spread_bps", 100)
        self.max_spread_bps = mm_cfg.get("max_spread_bps", 400)
        self.base_spread_bps = mm_cfg.get("base_spread_bps", 200)
        self.order_size_usd = mm_cfg.get("order_size_usd", 15.0)
        self.min_order_size_usd = mm_cfg.get("min_order_size_usd", 5.0)

        # ── Re-quoting ──
        self.requote_threshold_bps = mm_cfg.get("midpoint_move_threshold_bps", 50)
        self.cancel_stale_sec = mm_cfg.get("cancel_stale_sec", 120)
        self.requote_cooldown_sec = mm_cfg.get("requote_cooldown_sec", 10)
        self.emergency_requote_bps = mm_cfg.get("emergency_requote_bps", 200)

        # ── Adverse selection ──
        adverse_cfg = mm_cfg.get("adverse_selection", {})
        self.volatility_pause_threshold = adverse_cfg.get("volatility_pause_threshold", 0.05)
        self.volatility_pause_duration = adverse_cfg.get("pause_duration_sec", 300)
        self.fill_rate_window_sec = adverse_cfg.get("fill_rate_window_sec", 60)
        self.fill_rate_pause_threshold = adverse_cfg.get("fill_rate_pause_threshold", 0.8)
        self.news_blackout_min = adverse_cfg.get("news_blackout_min", 30)

        # ── Per-market state ──
        self._positions: Dict[str, MMPosition] = {}

        # ── Scheduled events (from config) ──
        self._scheduled_events = config.get("scheduled_events", [])

    # ── Strategy interface ────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "MarketMaking"

    def _config_key(self) -> str:
        return "market_making"

    async def initialize(self) -> None:
        """Set up market-making: scan for eligible markets and register them."""
        logger.info("Initializing market-making strategy")

        # Run initial scan
        result = await self.scanner.scan(force=True)

        # Register top markets
        for info in result.top_markets:
            await self._add_market(info)

        logger.info(
            "Market-making initialized",
            markets=len(self._positions),
            eligible=result.eligible_markets,
        )

    async def run_cycle(self) -> None:
        """Main market-making tick.

        1. Refresh eligible markets
        2. For each market: compute quotes, re-quote if needed
        3. Cancel stale orders
        4. Record metrics
        """
        # 1. Periodically refresh scanner
        if self.scanner._last_scan == 0 or (
            time.monotonic() - self.scanner._last_scan
        ) > self.scanner.scan_interval_sec:
            try:
                result = await self.scanner.scan()
                if result.errors > 0:
                    logger.warning(
                        "Scanner encountered errors during scan; skipping active market list update to preserve active quotes",
                        errors=result.errors,
                    )
                else:
                    # Add new eligible markets
                    for info in result.top_markets:
                        if info.market_id not in self._positions:
                            await self._add_market(info)
                            logger.info("New market added to MM", market_id=info.market_id, score=info.score)

                    # Remove markets that dropped out of top-N
                    active_ids = {m.market_id for m in result.top_markets}
                    for mid in list(self._positions.keys()):
                        if mid not in active_ids:
                            await self._remove_market(mid)
            except Exception as exc:
                logger.error("Scanner refresh failed", error=str(exc))

        # 2. Quote each active market
        for mid, pos in list(self._positions.items()):
            try:
                await self._quote_market(mid, pos)
            except Exception as exc:
                logger.error("Quote failed for market", market_id=mid, error=str(exc))

        # 3. Cancel stale orders
        await self._cancel_stale_orders()

        # 4. Update state
        self._state.markets_active = list(self._positions.keys())

    async def shutdown(self) -> None:
        """Cancel all market-making orders."""
        logger.info("Market-making shutting down, cancelling all orders")

        for mid, pos in self._positions.items():
            try:
                await self.executor.cancel_all_for_market(mid)
            except Exception as exc:
                logger.error("Failed to cancel orders on shutdown", market_id=mid, error=str(exc))

        self._positions.clear()

    # ── Market management ─────────────────────────────────────────────

    async def _add_market(self, info: MarketInfo) -> None:
        """Add a market to the market-making universe.

        Args:
            info: MarketInfo from the scanner.
        """
        # Register with orderbook manager
        self.orderbook.register_market(info.market_id, info.token_id)

        # Refresh order book
        await self.scanner.refresh_market_book(info.market_id)

        # Create MM position tracker
        self._positions[info.market_id] = MMPosition(
            market_id=info.market_id,
            token_id=info.token_id,
            category=info.category,
            days_to_resolution=info.days_to_resolution,
            score=info.score,
        )

        logger.info(
            "Market added to MM",
            market_id=info.market_id,
            category=info.category,
            score=info.score,
        )

    async def _remove_market(self, market_id: str) -> None:
        """Remove a market and cancel its orders.

        Args:
            market_id: Market to remove.
        """
        pos = self._positions.pop(market_id, None)
        if pos is None:
            return

        try:
            await self.executor.cancel_all_for_market(market_id)
        except Exception as exc:
            logger.error("Failed to cancel orders on removal", market_id=market_id, error=str(exc))

        self.orderbook.unregister_market(market_id)

        logger.info("Market removed from MM", market_id=market_id)

    # ── Core quoting logic ────────────────────────────────────────────

    async def _quote_market(self, market_id: str, pos: MMPosition) -> None:
        """Compute and place/update quotes for a single market.

        Args:
            market_id: Market ID.
            pos: Per-market MM state.
        """
        # Check pause
        if pos.is_paused:
            return

        # Get orderbook data
        snapshot = self.orderbook.get_snapshot(market_id)
        if snapshot is None:
            return

        mid = snapshot.mid_price
        if mid is None:
            return

        # ── Adverse selection guard ──
        if self._check_adverse_selection(market_id, pos):
            return

        # ── Compute optimal quotes ──
        bid_price, ask_price, size = self._compute_quotes(market_id, mid, pos)

        if bid_price is None or ask_price is None:
            return

        # Clamp to prevent spread-crossing (POST_ONLY rejections)
        if snapshot.best_ask is not None:
            bid_price = min(bid_price, snapshot.best_ask - 0.01)
        if snapshot.best_bid is not None:
            ask_price = max(ask_price, snapshot.best_bid + 0.01)

        # Validate spread bounds
        spread_bps = (ask_price - bid_price) * 10_000
        if spread_bps < self.min_spread_bps:
            # Widen to minimum
            half_min = self.min_spread_bps / 20_000  # bps/2 to price
            bid_price = mid - half_min
            ask_price = mid + half_min
        if spread_bps > self.max_spread_bps:
            half_max = self.max_spread_bps / 20_000
            bid_price = mid - half_max
            ask_price = mid + half_max

        # Clamp to valid range [0.01, 0.99]
        bid_price = max(0.01, min(0.99, bid_price))
        ask_price = max(0.01, min(0.99, ask_price))

        # Ensure bid < ask
        if bid_price >= ask_price:
            return

        # ── Check if re-quote needed ──
        needs_requote = self._needs_requote(pos, mid)

        now = time.monotonic()
        time_since_last_requote = now - pos.last_quote_time if pos.last_quote_time > 0 else float("inf")
        has_no_quotes = pos.bid_order_id is None and pos.ask_order_id is None
        cooldown_elapsed = time_since_last_requote >= self.requote_cooldown_sec

        should_place = needs_requote or (has_no_quotes and (pos.last_quote_time == 0 or cooldown_elapsed))

        if should_place:
            # Cancel existing quotes
            if pos.bid_order_id or pos.ask_order_id:
                await self.executor.cancel_all_for_market(market_id)
                pos.bid_order_id = None
                pos.ask_order_id = None

            # Apply time-of-day size reduction
            size_multiplier = self.risk_manager.get_size_multiplier()
            adjusted_size = size * size_multiplier

            # Ensure minimum size
            if adjusted_size * mid < self.min_order_size_usd:
                adjusted_size = self.min_order_size_usd / mid if mid > 0 else 0

            # Place new quote pair
            try:
                # Update quote time and reference mid to enforce cooldown on attempt
                pos.last_quote_time = time.monotonic()
                pos.reference_mid = mid

                bid_id, ask_id = await self.executor.place_quote_pair(
                    market_id=market_id,
                    token_id=pos.token_id,
                    bid_price=bid_price,
                    ask_price=ask_price,
                    size=adjusted_size,
                    category=pos.category,
                )

                pos.bid_order_id = bid_id
                pos.ask_order_id = ask_id
                pos.bid_price = bid_price
                pos.ask_price = ask_price
                pos.quote_size = adjusted_size
                self._state.orders_placed += 2

            except OrderRejectedByRisk as exc:
                logger.warning(
                    "Quote rejected by risk",
                    market_id=market_id,
                    reason=str(exc),
                )
            except Exception as exc:
                logger.error("Failed to place quotes", market_id=market_id, error=str(exc), exc_info=True)
                pos.errors_consecutive += 1

    def _compute_quotes(
        self,
        market_id: str,
        mid: float,
        pos: MMPosition,
    ) -> Tuple[Optional[float], Optional[float], float]:
        """Compute Avellaneda-Stoikov optimal bid/ask prices.

        reservation_price = mid - inventory * delta
        half_spread = (base_spread/2) + kappa * sigma * sqrt(T)
        bid = reservation_price - half_spread
        ask = reservation_price + half_spread

        Inventory skew shifts both quotes away from the side we're
        already long on, to reduce inventory risk.

        Args:
            market_id: Market ID.
            mid: Current midpoint price.
            pos: Per-market MM state.

        Returns:
            Tuple of (bid_price, ask_price, size).
        """
        # Get volatility
        sigma = self.orderbook.get_volatility(market_id)

        # Get current inventory from portfolio
        portfolio_pos = self.portfolio.get_position(market_id)
        inventory = portfolio_pos.size if portfolio_pos else 0.0
        pos.net_inventory = inventory

        # ── Reservation price ──
        reservation = mid - inventory * self.delta

        # ── Dynamic half-spread ──
        base_half_spread = self.base_spread_bps / 20_000  # bps/2 → price

        # Volatility component: κ * σ * √T
        vol_component = self.kappa * sigma * math.sqrt(max(0.001, self.time_horizon))

        half_spread = base_half_spread + vol_component

        # ── News blackout widening ──
        if self._is_near_scheduled_event():
            # Widen spread by 50% during blackout window
            half_spread *= 1.5
            logger.debug("Widening spread for scheduled event", market_id=market_id)

        # ── Compute bid/ask ──
        bid = reservation - half_spread
        ask = reservation + half_spread

        # ── Size computation ──
        # Reduce size when inventory is large
        max_inventory = self.portfolio.get_total_value() * self.risk_manager.max_position_pct
        if max_inventory > 0:
            inventory_ratio = abs(inventory) / max_inventory
            # Scale size down as inventory grows: 1.0 at 0%, 0.2 at 100%
            size_factor = max(0.2, 1.0 - 0.8 * inventory_ratio)
        else:
            size_factor = 1.0

        size = self.order_size_usd / mid if mid > 0 else 0
        size *= size_factor

        return bid, ask, size

    # ── Adverse selection detection ───────────────────────────────────

    def _check_adverse_selection(self, market_id: str, pos: MMPosition) -> bool:
        """Check for adverse selection signals and pause if detected.

        Signals:
        1. Volatility spike (rolling stddev exceeds threshold)
        2. Fill rate too high (getting picked off)
        3. Consecutive fills on same side (someone knows something)

        Args:
            market_id: Market to check.
            pos: Per-market MM state.

        Returns:
            True if market should be paused (adverse selection detected).
        """
        # 1. Volatility spike
        if self.orderbook.is_volatile(market_id):
            pos.paused = True
            pos.pause_until = time.monotonic() + self.volatility_pause_duration
            pos.pause_reason = "volatility_spike"
            logger.warning(
                "Adverse selection: volatility spike",
                market_id=market_id,
                volatility=self.orderbook.get_volatility(market_id),
                pause_sec=self.volatility_pause_duration,
            )
            m.record_adverse_selection_loss(0)  # Count, not dollar amount
            return True

        # 2. Fill rate check
        if self._is_fill_rate_too_high(pos):
            pos.paused = True
            pos.pause_until = time.monotonic() + self.volatility_pause_duration / 2
            pos.pause_reason = "high_fill_rate"
            logger.warning(
                "Adverse selection: fill rate too high",
                market_id=market_id,
                pause_sec=self.volatility_pause_duration / 2,
            )
            return True

        # 3. Consecutive same-side fills (≥ 3)
        if pos.consecutive_fills_same_side >= 3:
            pos.paused = True
            pos.pause_until = time.monotonic() + 60  # 1-minute pause
            pos.pause_reason = "consecutive_same_side_fills"
            logger.warning(
                "Adverse selection: consecutive same-side fills",
                market_id=market_id,
                side=pos.last_fill_side,
                count=pos.consecutive_fills_same_side,
            )
            return True

        return False

    def _is_fill_rate_too_high(self, pos: MMPosition) -> bool:
        """Check if recent fill rate suggests adverse selection.

        Args:
            pos: Per-market MM state.

        Returns:
            True if fill rate exceeds the threshold.
        """
        now = time.monotonic()
        cutoff = now - self.fill_rate_window_sec
        recent_fills = sum(1 for t in pos.fills_in_window if t > cutoff)
        # If we've been placing quotes for the full window and
        # more than threshold% of them filled, we're getting picked off
        if pos.cycles_completed > 0 and recent_fills > 0:
            # Simplified: if we have > 4 fills in 60s, that's a lot
            return recent_fills >= 5
        return False

    def record_fill(self, market_id: str, side: str) -> None:
        """Record a fill event for adverse selection tracking.

        Args:
            market_id: Market that was filled.
            side: "BUY" or "SELL".
        """
        pos = self._positions.get(market_id)
        if pos is None:
            return

        pos.fills_in_window.append(time.monotonic())
        pos.last_fill_time = time.monotonic()
        self._state.orders_filled += 1

        # Track consecutive same-side fills
        if side == pos.last_fill_side:
            pos.consecutive_fills_same_side += 1
        else:
            pos.consecutive_fills_same_side = 1
            pos.last_fill_side = side

    # ── Re-quoting logic ──────────────────────────────────────────────

    def _needs_requote(self, pos: MMPosition, current_mid: float) -> bool:
        """Check if current quotes need to be replaced.

        Triggers re-quote when:
        - Midpoint moved beyond threshold (enforcing cooldown unless emergency)
        - Quotes are stale (exceeded cancel_stale_sec)
        - No quotes exist yet

        Args:
            pos: Per-market MM state.
            current_mid: Current midpoint price.

        Returns:
            True if quotes should be replaced.
        """
        # No existing quotes
        if pos.bid_order_id is None and pos.ask_order_id is None:
            return True

        now = time.monotonic()
        time_since_last_requote = now - pos.last_quote_time if pos.last_quote_time > 0 else float("inf")

        # Stale quotes
        if time_since_last_requote > self.cancel_stale_sec:
            logger.info(
                "Re-quote triggered: stale quotes",
                market_id=pos.market_id,
                seconds_since_last_requote=round(time_since_last_requote, 2),
                cancel_stale_sec=self.cancel_stale_sec,
            )
            return True

        # Midpoint moved beyond threshold
        if pos.bid_price > 0 and pos.ask_price > 0:
            ref_mid = pos.reference_mid if pos.reference_mid > 0 else (pos.bid_price + pos.ask_price) / 2
            if current_mid > 0:
                move_bps = abs(current_mid - ref_mid) * 10_000
                if move_bps >= self.requote_threshold_bps:
                    # Cooldown checks
                    if time_since_last_requote >= self.requote_cooldown_sec:
                        logger.info(
                            "Re-quote triggered: cooldown_expired",
                            market_id=pos.market_id,
                            reason="cooldown_expired",
                            bps_moved=round(move_bps, 2),
                            seconds_since_last_requote=round(time_since_last_requote, 2),
                        )
                        return True
                    elif move_bps >= self.emergency_requote_bps:
                        logger.info(
                            "Re-quote triggered: emergency",
                            market_id=pos.market_id,
                            reason="emergency",
                            bps_moved=round(move_bps, 2),
                            seconds_since_last_requote=round(time_since_last_requote, 2),
                        )
                        return True
                    else:
                        logger.debug(
                            "Re-quote blocked by cooldown",
                            market_id=pos.market_id,
                            bps_moved=round(move_bps, 2),
                            seconds_since_last_requote=round(time_since_last_requote, 2),
                            cooldown_sec=self.requote_cooldown_sec,
                        )

        return False

    # ── Scheduled event check ─────────────────────────────────────────

    def _is_near_scheduled_event(self) -> bool:
        """Check if we're within the blackout window of a scheduled event.

        Returns:
            True if within news_blackout_min minutes of any scheduled event.
        """
        if not self._scheduled_events:
            return False

        from datetime import datetime, timezone, timedelta

        now = datetime.now(timezone.utc)
        blackout = timedelta(minutes=self.news_blackout_min)

        for event in self._scheduled_events:
            event_time = self._parse_event_time(event)
            if event_time and abs((event_time - now).total_seconds()) < blackout.total_seconds():
                return True

        return False

    def _parse_event_time(self, event) -> Optional[object]:
        """Parse a scheduled event config into a datetime.

        Args:
            event: Event config dict or string.

        Returns:
            datetime or None.
        """
        from datetime import datetime, timezone

        if isinstance(event, dict):
            time_str = event.get("time", "")
        elif isinstance(event, str):
            time_str = event
        else:
            return None

        if not time_str:
            return None

        try:
            # Try full ISO datetime
            return datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            pass

        try:
            # Try HH:MM format (today or tomorrow in UTC)
            from datetime import date
            hour, minute = int(time_str[:2]), int(time_str[3:5])
            target = datetime(now := datetime.now(timezone.utc).date(), hour, minute, tzinfo=timezone.utc)
            if target < datetime.now(timezone.utc):
                from datetime import timedelta
                target += timedelta(days=1)
            return target
        except (ValueError, IndexError):
            return None

    # ── Stale order cleanup ───────────────────────────────────────────

    async def _cancel_stale_orders(self) -> None:
        """Cancel orders that have been open too long without fills."""
        now = time.monotonic()

        for mid, pos in list(self._positions.items()):
            if pos.last_quote_time > 0:
                age = now - pos.last_quote_time
                if age > self.cancel_stale_sec:
                    try:
                        await self.executor.cancel_all_for_market(mid)
                        pos.bid_order_id = None
                        pos.ask_order_id = None
                        logger.debug("Cancelled stale quotes", market_id=mid, age_sec=age)
                    except Exception as exc:
                        logger.error("Failed to cancel stale orders", market_id=mid, error=str(exc))

    # ── Metrics and reporting ─────────────────────────────────────────

    def get_mm_summary(self) -> Dict:
        """Get a summary of market-making state.

        Returns:
            Dict with MM metrics.
        """
        active = sum(1 for p in self._positions.values() if not p.is_paused)
        paused = sum(1 for p in self._positions.values() if p.is_paused)

        return {
            "total_markets": len(self._positions),
            "active_markets": active,
            "paused_markets": paused,
            "cycles_completed": self._state.cycles_completed,
            "total_errors": self._state.errors_total,
            "orders_placed": self._state.orders_placed,
            "orders_filled": self._state.orders_filled,
            "strategy_enabled": self._state.enabled,
        }
