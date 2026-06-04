"""Portfolio tracker with position management, P&L, and reward tracking."""

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional

import structlog

logger = structlog.get_logger(__name__)

STATE_DIR = os.path.join(os.path.dirname(__file__), "..", "state")
STATE_FILE = os.path.join(STATE_DIR, "portfolio.json")


@dataclass
class Position:
    """A position in a single market."""

    market_id: str
    size: float = 0.0  # Positive = long, negative = short
    avg_entry_price: float = 0.0
    unrealized_pnl: float = 0.0
    category: str = ""
    days_to_resolution: int = 0
    first_opened_at: float = field(default_factory=time.time)

    @property
    def notional_value(self) -> float:
        """Current notional value of the position."""
        return abs(self.size * self.avg_entry_price)

    @property
    def is_long(self) -> bool:
        """Check if position is long."""
        return self.size > 0

    @property
    def qualifies_for_holding_reward(self) -> bool:
        """Check if this position qualifies for 4% APY holding rewards.

        Requirements: long-dated market (>=14 days to resolution).
        """
        return self.days_to_resolution >= 14 and abs(self.size) > 0


@dataclass
class DailyPnL:
    """Daily P&L tracking."""

    date: str = ""  # YYYY-MM-DD
    realized_pnl: float = 0.0
    unrealized_pnl_start: float = 0.0
    unrealized_pnl_end: float = 0.0
    spread_captured: float = 0.0
    rebates_earned: float = 0.0
    holding_rewards_earned: float = 0.0

    @property
    def total_pnl(self) -> float:
        """Total daily P&L including all components."""
        return (
            self.realized_pnl
            + (self.unrealized_pnl_end - self.unrealized_pnl_start)
            + self.rebates_earned
            + self.holding_rewards_earned
        )


class Portfolio:
    """Portfolio tracker with position management, P&L, and reward tracking.

    Features:
    - Track positions per market with size, avg entry, unrealized P&L
    - Track balances: free USDC, locked in orders
    - Daily P&L rolling calculation
    - Holding rewards tracker (4% APY on long-dated positions)
    - Rebate tracker (expected vs received)
    - Persist state to JSON file every 60 seconds
    """

    def __init__(self, config: dict) -> None:
        """Initialize the portfolio from config.

        Args:
            config: Full config dict.
        """
        self.config = config
        mm_cfg = config.get("strategies", {}).get("market_making", {})
        hr_cfg = mm_cfg.get("holding_rewards", {})

        self._positions: Dict[str, Position] = {}
        self._free_usdc: float = 0.0
        self._locked_usdc: float = 0.0
        self._initial_capital: float = 0.0

        # Holding rewards config
        self._holding_rewards_enabled = hr_cfg.get("enabled", True)
        self._holding_reward_apy = hr_cfg.get("target_apy", 0.04)
        self._min_days_for_reward = hr_cfg.get("min_days_to_resolution", 14)

        # Daily P&L
        self._daily_pnl: Dict[str, DailyPnL] = {}
        self._current_day: str = ""

        # Rebate tracking: expected vs received per day
        self._expected_rebates: Dict[str, float] = {}  # date -> expected USD
        self._received_rebates: Dict[str, float] = {}  # date -> received USD

        # State persistence
        self._state_file = STATE_FILE
        self._last_save_time: float = 0.0
        self._save_interval = 60.0  # Save every 60 seconds
        self._lock = asyncio.Lock()

        # Correlation groups: map group_name -> set of market_ids
        # This is populated externally or from config
        self._correlation_groups: Dict[str, set] = {}

    async def initialize(self, starting_capital: float = 0.0) -> None:
        """Initialize the portfolio, loading from state file if available.

        Args:
            starting_capital: Starting USDC balance (used if no state file).
        """
        loaded = self._load_state()
        if not loaded:
            self._free_usdc = starting_capital
            self._initial_capital = starting_capital
            self._current_day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            logger.info(
                "Portfolio initialized from scratch",
                starting_capital=starting_capital,
            )
        else:
            logger.info(
                "Portfolio loaded from state",
                free_usdc=self._free_usdc,
                positions=len(self._positions),
            )

    def set_correlation_groups(self, groups: Dict[str, set]) -> None:
        """Set market correlation groups for risk management.

        Args:
            groups: Dict mapping group_name -> set of market_ids.
        """
        self._correlation_groups = groups

    # --- Position management ---

    async def update_position(
        self,
        market_id: str,
        fill_size: float,
        fill_price: float,
        category: str = "",
        days_to_resolution: int = 0,
    ) -> None:
        """Update a position after a fill.

        Args:
            market_id: The market ID.
            fill_size: Size of the fill (positive for buy, negative for sell).
            fill_price: Price of the fill.
            category: Market category for fee lookup.
            days_to_resolution: Days until market resolution.
        """
        async with self._lock:
            pos = self._positions.get(market_id)
            if pos is None:
                pos = Position(
                    market_id=market_id,
                    category=category,
                    days_to_resolution=days_to_resolution,
                )
                self._positions[market_id] = pos

            # Update average entry price
            old_size = pos.size
            new_size = old_size + fill_size

            if old_size == 0 or (old_size > 0 and fill_size > 0) or (old_size < 0 and fill_size < 0):
                # Adding to position
                if new_size != 0:
                    total_cost = (abs(old_size) * pos.avg_entry_price) + (abs(fill_size) * fill_price)
                    pos.avg_entry_price = total_cost / abs(new_size)
            else:
                # Reducing position — realize P&L
                close_size = min(abs(fill_size), abs(old_size))
                realized = close_size * (fill_price - pos.avg_entry_price)
                if old_size < 0:
                    realized = -realized  # Flip for short positions

                # Track realized P&L
                day = self._get_current_day()
                if day not in self._daily_pnl:
                    self._daily_pnl[day] = DailyPnL(date=day)
                self._daily_pnl[day].realized_pnl += realized

                # If flipping direction, reset avg entry
                if (old_size > 0 and new_size < 0) or (old_size < 0 and new_size > 0):
                    pos.avg_entry_price = fill_price

            pos.size = new_size
            pos.category = category or pos.category
            pos.days_to_resolution = days_to_resolution or pos.days_to_resolution

            # Remove zero-size positions
            if abs(pos.size) < 1e-8:
                del self._positions[market_id]

            logger.debug(
                "Position updated",
                market_id=market_id,
                fill_size=fill_size,
                fill_price=fill_price,
                new_size=pos.size if market_id in self._positions else 0,
            )

    async def lock_usdc(self, amount: float) -> bool:
        """Lock USDC for an open order.

        Args:
            amount: USDC to lock.

        Returns:
            True if enough free USDC available.
        """
        async with self._lock:
            if amount > self._free_usdc:
                return False
            self._free_usdc -= amount
            self._locked_usdc += amount
            return True

    async def unlock_usdc(self, amount: float) -> None:
        """Unlock USDC when an order is cancelled.

        Args:
            amount: USDC to unlock.
        """
        async with self._lock:
            self._locked_usdc = max(0, self._locked_usdc - amount)
            self._free_usdc += amount

    # --- Queries ---

    def get_position(self, market_id: str) -> Optional[Position]:
        """Get position for a market.

        Args:
            market_id: The market ID.

        Returns:
            Position or None if no position.
        """
        return self._positions.get(market_id)

    def get_total_value(self) -> float:
        """Get total portfolio value (free + locked + positions)."""
        positions_value = sum(p.notional_value for p in self._positions.values())
        return self._free_usdc + self._locked_usdc + positions_value

    @property
    def free_usdc(self) -> float:
        """Free USDC balance."""
        return self._free_usdc

    @property
    def locked_usdc(self) -> float:
        """USDC locked in open orders."""
        return self._locked_usdc

    @property
    def total_pnl(self) -> float:
        """Total P&L since inception."""
        return self.get_total_value() - self._initial_capital

    @property
    def total_loss_pct(self) -> float:
        """Total loss as a percentage of initial capital (0 if profitable)."""
        pnl = self.total_pnl
        if pnl >= 0:
            return 0.0
        return abs(pnl) / self._initial_capital if self._initial_capital > 0 else 0.0

    def get_correlated_exposure(self, market_id: str) -> float:
        """Get combined exposure across correlated markets.

        Args:
            market_id: Market ID to check correlation for.

        Returns:
            Total notional exposure across correlated markets.
        """
        total = 0.0
        pos = self._positions.get(market_id)
        if pos:
            total += pos.notional_value

        # Check correlation groups
        for group_name, market_ids in self._correlation_groups.items():
            if market_id in market_ids:
                for mid in market_ids:
                    other_pos = self._positions.get(mid)
                    if other_pos and mid != market_id:
                        total += other_pos.notional_value

        return total

    # --- Daily P&L ---

    def _get_current_day(self) -> str:
        """Get current UTC day string."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    async def get_daily_pnl(self) -> DailyPnL:
        """Get or create today's P&L record."""
        day = self._get_current_day()
        async with self._lock:
            if day != self._current_day:
                # New day — roll over
                self._current_day = day
                if day not in self._daily_pnl:
                    self._daily_pnl[day] = DailyPnL(
                        date=day,
                        unrealized_pnl_start=sum(
                            p.unrealized_pnl for p in self._positions.values()
                        ),
                    )
            return self._daily_pnl[day]

    async def record_spread_captured(self, amount: float) -> None:
        """Record spread captured from a round-trip fill."""
        pnl = await self.get_daily_pnl()
        async with self._lock:
            pnl.spread_captured += amount

    async def record_rebate_expected(self, amount: float) -> None:
        """Record expected rebate earnings."""
        day = self._get_current_day()
        async with self._lock:
            self._expected_rebates[day] = self._expected_rebates.get(day, 0.0) + amount

    async def record_rebate_received(self, amount: float) -> None:
        """Record received rebate from Polymarket."""
        day = self._get_current_day()
        async with self._lock:
            self._received_rebates[day] = self._received_rebates.get(day, 0.0) + amount
            pnl = await self.get_daily_pnl()
            pnl.rebates_earned += amount

    # --- Holding rewards ---

    def calculate_daily_holding_reward(self) -> float:
        """Calculate total daily holding reward across all qualifying positions.

        Returns:
            Estimated daily holding reward in USD.
        """
        if not self._holding_rewards_enabled:
            return 0.0

        total = 0.0
        for pos in self._positions.values():
            if pos.qualifies_for_holding_reward:
                # Daily reward = APY / 365 * notional value
                daily_rate = self._holding_reward_apy / 365.0
                total += daily_rate * pos.notional_value

        return total

    # --- State persistence ---

    def _load_state(self) -> bool:
        """Load portfolio state from JSON file.

        Returns:
            True if state was loaded successfully.
        """
        if not os.path.exists(self._state_file):
            return False

        try:
            with open(self._state_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            self._free_usdc = data.get("free_usdc", 0.0)
            self._locked_usdc = data.get("locked_usdc", 0.0)
            self._initial_capital = data.get("initial_capital", 0.0)
            self._current_day = data.get("current_day", "")

            # Restore positions
            for mid, pdata in data.get("positions", {}).items():
                self._positions[mid] = Position(
                    market_id=mid,
                    size=pdata.get("size", 0.0),
                    avg_entry_price=pdata.get("avg_entry_price", 0.0),
                    unrealized_pnl=pdata.get("unrealized_pnl", 0.0),
                    category=pdata.get("category", ""),
                    days_to_resolution=pdata.get("days_to_resolution", 0),
                    first_opened_at=pdata.get("first_opened_at", time.time()),
                )

            return True
        except Exception as exc:
            logger.error("Failed to load portfolio state", error=str(exc))
            return False

    async def save_state(self) -> None:
        """Save portfolio state to JSON file."""
        async with self._lock:
            now = time.monotonic()
            if now - self._last_save_time < self._save_interval:
                return

            try:
                os.makedirs(os.path.dirname(self._state_file), exist_ok=True)

                data = {
                    "free_usdc": self._free_usdc,
                    "locked_usdc": self._locked_usdc,
                    "initial_capital": self._initial_capital,
                    "current_day": self._current_day,
                    "positions": {
                        mid: {
                            "size": pos.size,
                            "avg_entry_price": pos.avg_entry_price,
                            "unrealized_pnl": pos.unrealized_pnl,
                            "category": pos.category,
                            "days_to_resolution": pos.days_to_resolution,
                            "first_opened_at": pos.first_opened_at,
                        }
                        for mid, pos in self._positions.items()
                    },
                    "daily_pnl": {
                        day: {
                            "realized_pnl": pnl.realized_pnl,
                            "spread_captured": pnl.spread_captured,
                            "rebates_earned": pnl.rebates_earned,
                            "holding_rewards_earned": pnl.holding_rewards_earned,
                        }
                        for day, pnl in self._daily_pnl.items()
                    },
                    "saved_at": datetime.now(timezone.utc).isoformat(),
                }

                with open(self._state_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)

                self._last_save_time = now
                logger.debug("Portfolio state saved")
            except Exception as exc:
                logger.error("Failed to save portfolio state", error=str(exc))

    async def force_save(self) -> None:
        """Force save portfolio state regardless of interval."""
        self._last_save_time = 0.0
        await self.save_state()
