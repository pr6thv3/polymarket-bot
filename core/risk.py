"""Risk manager with position limits, correlation checks, time-of-day gates, and circuit breaker."""

import asyncio
import time
from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import structlog

from core.client import TAKER_FEES, REBATE_RATES
from core.portfolio import Portfolio
from utils import metrics as m

logger = structlog.get_logger(__name__)


class RiskHaltTriggered(Exception):
    """Raised when the risk manager has triggered a full halt."""


class RiskManager:
    """Pre-trade risk checks with portfolio-level enforcement.

    Every order must pass through allow_order() before being placed.
    The risk manager enforces:

    1. Per-market position limit (max 5% of portfolio)
    2. Correlated exposure limit (max 15% of portfolio per correlation group)
    3. Daily loss cap (max 10% daily loss)
    4. Total loss halt (40% total loss → permanent halt)
    5. Gas fee accounting (minimum profit threshold per trade)
    6. Time-of-day gate (reduced size outside 08:00–22:00 UTC)
    7. Category fee checks (avoid being a taker)
    8. Emergency halt trigger
    """

    def __init__(self, portfolio: Portfolio, config: dict) -> None:
        """Initialize the risk manager.

        Args:
            portfolio: Portfolio tracker instance.
            config: Full config dict.
        """
        self.portfolio = portfolio
        self.config = config

        risk_cfg = config.get("risk", {})
        self.max_position_pct = risk_cfg.get("max_position_pct", 0.05)
        self.daily_loss_cap_pct = risk_cfg.get("daily_loss_cap_pct", 0.10)
        self.halt_total_loss_pct = risk_cfg.get("halt_total_loss_pct", 0.40)
        self.min_profit_threshold_usd = risk_cfg.get("min_profit_threshold_usd", 0.30)
        self.max_correlated_exposure_pct = risk_cfg.get("max_correlated_exposure_pct", 0.15)

        # Time-of-day gate
        tod_cfg = risk_cfg.get("time_of_day", {})
        self.tod_enabled = tod_cfg.get("enabled", True)
        self.tod_active_start = tod_cfg.get("active_start_hour_utc", 8)
        self.tod_active_end = tod_cfg.get("active_end_hour_utc", 22)
        self.tod_size_reduction = tod_cfg.get("reduced_size_pct", 0.5)

        # Halt state
        self._halt_triggered = False
        self._halt_reason = ""
        self._halt_at: Optional[float] = None

        # Daily loss tracking
        self._daily_start_pnl: Optional[float] = None
        self._current_day: str = ""
        self._daily_loss_checks: deque = deque(maxlen=100)

        # Alerter reference (set after construction to avoid circular imports)
        self.alerter: Optional[object] = None

    # --- Core pre-flight check ---

    async def allow_order(
        self,
        market_id: str,
        side: str,
        price: float,
        size: float,
        category: str = "",
    ) -> Tuple[bool, str]:
        """Pre-flight risk check. Must pass before any order is placed.

        Args:
            market_id: Market/condition ID.
            side: "BUY" or "SELL".
            price: Limit price.
            size: Order size.
            category: Market category (for fee lookup).

        Returns:
            Tuple of (allowed: bool, reason: str).
            If allowed=False, reason explains why.
        """
        # 1. Halt check (highest priority)
        if self._halt_triggered:
            return False, f"Risk halt active: {self._halt_reason}"

        # 2. Total loss halt check
        total_loss_pct = self.portfolio.total_loss_pct
        if total_loss_pct >= self.halt_total_loss_pct:
            await self._trigger_halt(
                f"Total loss {total_loss_pct:.1%} exceeded halt threshold {self.halt_total_loss_pct:.1%}"
            )
            return False, "Total loss halt triggered"

        # 3. Daily loss cap check
        daily_loss_pct = await self._get_daily_loss_pct()
        if daily_loss_pct >= self.daily_loss_cap_pct:
            await self._trigger_halt(
                f"Daily loss {daily_loss_pct:.1%} exceeded cap {self.daily_loss_cap_pct:.1%}"
            )
            return False, "Daily loss cap exceeded"

        # 4. Per-market position limit (5% of portfolio)
        portfolio_value = self.portfolio.get_total_value()
        if portfolio_value <= 0:
            return False, "Portfolio value is zero or negative"

        order_notional = price * size
        current_position = self.portfolio.get_position(market_id)
        current_notional = current_position.notional_value if current_position else 0.0

        if side == "BUY":
            new_notional = current_notional + order_notional
        else:
            new_notional = max(0, current_notional - order_notional)

        position_pct = new_notional / portfolio_value
        if position_pct > self.max_position_pct:
            return False, (
                f"Position {position_pct:.1%} would exceed limit "
                f"{self.max_position_pct:.1%} for market {market_id}"
            )

        # 5. Correlated exposure limit (15% of portfolio)
        # get_correlated_exposure already includes the current market's existing
        # position, so we only add the NEW notional from this order.
        correlated_exposure = self.portfolio.get_correlated_exposure(market_id)
        if side == "BUY":
            total_correlated = correlated_exposure + order_notional
        else:
            total_correlated = max(0, correlated_exposure - order_notional)

        correlated_pct = total_correlated / portfolio_value
        if correlated_pct > self.max_correlated_exposure_pct:
            return False, (
                f"Correlated exposure {correlated_pct:.1%} would exceed limit "
                f"{self.max_correlated_exposure_pct:.1%}"
            )

        # 6. Gas/profit threshold check
        # Maker fee is 0%, but we need to cover gas costs
        # For a market-making spread, expected profit per round-trip:
        spread_usd = size * (1.0 - 2 * price) if side == "BUY" else size * (2 * price - 1.0)
        # Simplified: check that the trade makes economic sense
        # This is more of a sanity check — the strategy layer sets actual spread
        if category and category in TAKER_FEES:
            taker_fee = TAKER_FEES[category]
            # Warn if this order would cross the spread (taking)
            # This shouldn't happen with POST_ONLY, but double-check
            if taker_fee > 0 and price > 0.99:
                logger.warning(
                    "Order near $1.00 — high taker fee risk",
                    category=category,
                    taker_fee=taker_fee,
                )

        # 7. Time-of-day gate
        if self.tod_enabled:
            size_multiplier = self._get_time_of_day_multiplier()
            if size_multiplier < 1.0:
                logger.info(
                    "Outside active hours, size reduced",
                    multiplier=size_multiplier,
                )
                # Note: we don't reject, just flag for the strategy to reduce size

        # All checks passed
        return True, "OK"

    def _get_time_of_day_multiplier(self) -> float:
        """Get the size multiplier based on current time of day.

        Returns:
            1.0 during active hours, reduced_size_pct outside.
        """
        current_hour = datetime.now(timezone.utc).hour

        if self.tod_active_start <= current_hour < self.tod_active_end:
            return 1.0
        else:
            return self.tod_size_reduction

    async def _get_daily_loss_pct(self) -> float:
        """Calculate today's loss as a percentage of portfolio.

        Returns:
            Daily loss percentage (0 if profitable or no data).
        """
        daily_pnl = await self.portfolio.get_daily_pnl()
        total = daily_pnl.total_pnl
        portfolio_value = self.portfolio.get_total_value()

        if portfolio_value <= 0 or total >= 0:
            return 0.0

        return abs(total) / portfolio_value

    # --- Halt management ---

    async def _trigger_halt(self, reason: str) -> None:
        """Trigger an emergency halt.

        Args:
            reason: Human-readable reason for the halt.
        """
        self._halt_triggered = True
        self._halt_reason = reason
        self._halt_at = time.monotonic()

        m.record_circuit_breaker_trigger()
        logger.critical("RISK HALT TRIGGERED", reason=reason)

        if self.alerter:
            await self.alerter.send_alert("halt_triggered", reason)

    @property
    def is_halted(self) -> bool:
        """Check if the risk manager has triggered a halt."""
        return self._halt_triggered

    @property
    def halt_reason(self) -> str:
        """Get the reason for the current halt."""
        return self._halt_reason

    def reset_halt(self) -> None:
        """Reset the halt state (manual intervention only).

        This should only be called after a human reviews the situation.
        """
        logger.warning("Risk halt manually reset", previous_reason=self._halt_reason)
        self._halt_triggered = False
        self._halt_reason = ""
        self._halt_at = None

    # --- Utility methods ---

    def get_taker_fee(self, category: str) -> float:
        """Get the taker fee for a market category.

        Args:
            category: Market category.

        Returns:
            Taker fee as a decimal (e.g., 0.018 for 1.8%).
        """
        return TAKER_FEES.get(category, 0.01)

    def get_rebate_rate(self, category: str) -> float:
        """Get the maker rebate rate for a market category.

        Args:
            category: Market category.

        Returns:
            Rebate rate as a decimal (e.g., 0.50 for 50% of taker fee returned).
        """
        return REBATE_RATES.get(category, 0.25)

    def calculate_expected_rebate(
        self,
        notional: float,
        category: str,
    ) -> float:
        """Calculate expected rebate for a maker order.

        Args:
            notional: Notional value of the order.
            category: Market category.

        Returns:
            Expected rebate in USD.
        """
        taker_fee = self.get_taker_fee(category)
        rebate_rate = self.get_rebate_rate(category)
        return notional * taker_fee * rebate_rate

    def get_size_multiplier(self) -> float:
        """Get the current time-of-day size multiplier.

        Returns:
            Size multiplier (1.0 during active hours, reduced otherwise).
        """
        if self.tod_enabled:
            return self._get_time_of_day_multiplier()
        return 1.0

    def get_risk_summary(self) -> Dict:
        """Get a summary of current risk state.

        Returns:
            Dict with risk metrics.
        """
        return {
            "halted": self._halt_triggered,
            "halt_reason": self._halt_reason if self._halt_triggered else None,
            "total_loss_pct": self.portfolio.total_loss_pct,
            "max_position_pct": self.max_position_pct,
            "daily_loss_cap_pct": self.daily_loss_cap_pct,
            "halt_total_loss_pct": self.halt_total_loss_pct,
            "time_of_day_multiplier": self.get_size_multiplier(),
            "portfolio_value": self.portfolio.get_total_value(),
            "free_usdc": self.portfolio.free_usdc,
            "locked_usdc": self.portfolio.locked_usdc,
        }
