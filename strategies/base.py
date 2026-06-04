"""Strategy base class — defines the interface all strategies must implement.

Every strategy receives the same core dependencies (client, orderbook,
portfolio, risk manager, executor) and must implement:
  - initialize():   one-time setup (register markets, load models, etc.)
  - run_cycle():    called each tick — the strategy's main logic
  - shutdown():     clean up on bot stop (cancel orders, save state)
"""

import abc
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import structlog

from core.client import ClobClient
from core.executor import Executor
from core.orderbook import OrderBookManager
from core.order_state import OrderStore
from core.portfolio import Portfolio
from core.risk import RiskManager

logger = structlog.get_logger(__name__)


@dataclass
class StrategyState:
    """Runtime state for a strategy instance."""

    name: str = ""
    enabled: bool = True
    started_at: float = 0.0
    last_cycle_at: float = 0.0
    cycles_completed: int = 0
    errors_consecutive: int = 0
    errors_total: int = 0
    markets_active: List[str] = field(default_factory=list)
    orders_placed: int = 0
    orders_filled: int = 0


class Strategy(abc.ABC):
    """Abstract base class for all trading strategies.

    Subclasses must implement:
      - initialize()
      - run_cycle()
      - shutdown()

    The base class provides:
      - Common dependency references
      - State tracking (cycles, errors, timing)
      - Error resilience wrapper for run_cycle
      - Helper methods for accessing market data
    """

    def __init__(
        self,
        client: ClobClient,
        orderbook: OrderBookManager,
        portfolio: Portfolio,
        risk_manager: RiskManager,
        executor: Executor,
        order_store: OrderStore,
        config: dict,
    ) -> None:
        """Initialize the strategy with core dependencies.

        Args:
            client: CLOB client for API calls.
            orderbook: Order book manager for market data.
            portfolio: Portfolio tracker.
            risk_manager: Risk manager for pre-flight checks.
            executor: Order execution engine.
            order_store: Order state machine.
            config: Full config dict.
        """
        self.client = client
        self.orderbook = orderbook
        self.portfolio = portfolio
        self.risk_manager = risk_manager
        self.executor = executor
        self.order_store = order_store
        self.config = config

        # Strategy state
        self._state = StrategyState(name=self.name)

        # Config convenience
        self._strategy_config = config.get("strategies", {}).get(self._config_key(), {})

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Human-readable strategy name."""
        ...

    @abc.abstractmethod
    def _config_key(self) -> str:
        """Config key under strategies.* for this strategy."""
        ...

    @abc.abstractmethod
    async def initialize(self) -> None:
        """One-time setup: register markets, load models, etc.

        Called once before the main loop starts.
        """
        ...

    @abc.abstractmethod
    async def run_cycle(self) -> None:
        """Execute one strategy tick.

        Called repeatedly by the main loop. Must be idempotent and
        safe to call at any time.
        """
        ...

    @abc.abstractmethod
    async def shutdown(self) -> None:
        """Clean up: cancel strategy orders, save state.

        Called on bot shutdown.
        """
        ...

    # ── State management ──────────────────────────────────────────────

    @property
    def state(self) -> StrategyState:
        """Current strategy state."""
        return self._state

    @property
    def is_enabled(self) -> bool:
        """Check if the strategy is enabled in config."""
        return self._strategy_config.get("enabled", False)

    @property
    def cycle_interval_sec(self) -> float:
        """Time between run_cycle calls (from config or default)."""
        return self._strategy_config.get("cycle_interval_sec", 5.0)

    @property
    def max_consecutive_errors(self) -> int:
        """Max consecutive errors before the strategy pauses itself."""
        return self._strategy_config.get("max_consecutive_errors", 10)

    # ── Safe cycle wrapper ────────────────────────────────────────────

    async def safe_run_cycle(self) -> None:
        """Run one cycle with error tracking and auto-pause.

        Wraps run_cycle() with:
        - Consecutive error counting
        - Auto-pause after max_consecutive_errors
        - Cycle timing
        """
        if not self._state.enabled:
            return

        if self._state.errors_consecutive >= self.max_consecutive_errors:
            logger.error(
                "Strategy auto-paused due to consecutive errors",
                strategy=self.name,
                errors=self._state.errors_consecutive,
            )
            self._state.enabled = False
            return

        start = time.monotonic()
        try:
            await self.run_cycle()
            self._state.errors_consecutive = 0
            self._state.cycles_completed += 1
        except Exception as exc:
            self._state.errors_consecutive += 1
            self._state.errors_total += 1
            logger.error(
                "Strategy cycle error",
                strategy=self.name,
                error=str(exc),
                consecutive_errors=self._state.errors_consecutive,
            )
        finally:
            self._state.last_cycle_at = time.monotonic()

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the strategy: initialize and mark as running."""
        if not self.is_enabled:
            logger.info("Strategy disabled in config, skipping", strategy=self.name)
            return

        logger.info("Starting strategy", strategy=self.name)
        await self.initialize()
        self._state.started_at = time.monotonic()
        self._state.enabled = True

    async def stop(self) -> None:
        """Stop the strategy: shutdown and mark as stopped."""
        logger.info("Stopping strategy", strategy=self.name)
        self._state.enabled = False
        await self.shutdown()

    # ── Helpers ───────────────────────────────────────────────────────

    def get_strategy_config(self, key: str, default=None):
        """Get a value from this strategy's config section.

        Args:
            key: Config key under strategies.<config_key>.
            default: Default value if key not found.

        Returns:
            Config value or default.
        """
        return self._strategy_config.get(key, default)

    def get_time_since_last_cycle(self) -> float:
        """Get seconds since the last run_cycle completed.

        Returns:
            Seconds since last cycle, or infinity if never run.
        """
        if self._state.last_cycle_at == 0.0:
            return float("inf")
        return time.monotonic() - self._state.last_cycle_at

    def should_run_cycle(self) -> bool:
        """Check if enough time has passed for another cycle.

        Returns:
            True if the cycle interval has elapsed.
        """
        return self.get_time_since_last_cycle() >= self.cycle_interval_sec
