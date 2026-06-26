"""Order lifecycle state machine for tracking order states."""

import asyncio
import enum
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)


class OrderState(enum.Enum):
    """Possible states for an order."""

    PENDING = "pending"
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


# Valid state transitions: current_state -> set of allowed next states
VALID_TRANSITIONS: Dict[OrderState, set] = {
    OrderState.PENDING: {
        OrderState.OPEN,
        OrderState.REJECTED,
        OrderState.CANCELLED,
    },
    OrderState.OPEN: {
        OrderState.PARTIALLY_FILLED,
        OrderState.FILLED,
        OrderState.CANCELLED,
    },
    OrderState.PARTIALLY_FILLED: {
        OrderState.PARTIALLY_FILLED,
        OrderState.FILLED,
        OrderState.CANCELLED,
    },
    OrderState.FILLED: set(),   # Terminal
    OrderState.CANCELLED: set(),  # Terminal
    OrderState.REJECTED: set(),   # Terminal
}


@dataclass
class OrderRecord:
    """Record of a single order and its lifecycle."""

    order_id: str
    market_id: str
    side: str  # "BUY" or "SELL"
    price: float
    size: float
    filled_size: float = 0.0
    state: OrderState = OrderState.PENDING
    created_at: float = field(default_factory=time.monotonic)
    updated_at: float = field(default_factory=time.monotonic)

    @property
    def is_terminal(self) -> bool:
        """Check if the order is in a terminal state."""
        return self.state in {
            OrderState.FILLED,
            OrderState.CANCELLED,
            OrderState.REJECTED,
        }

    @property
    def is_active(self) -> bool:
        """Check if the order is still active (could receive fills)."""
        return self.state in {
            OrderState.PENDING,
            OrderState.OPEN,
            OrderState.PARTIALLY_FILLED,
        }

    @property
    def unfilled_size(self) -> float:
        """Remaining unfilled size."""
        return self.size - self.filled_size


class InvalidTransition(Exception):
    """Raised when an invalid state transition is attempted."""


class OrderStore:
    """Thread-safe store for order records with state machine enforcement.

    Tracks the full lifecycle of every order: PENDING → OPEN → FILLED/CANCELLED.
    Handles REJECTED as a non-error state (POST_ONLY rejections are expected).
    Detects stale PENDING orders via timeout.
    """

    def __init__(self, pending_timeout_sec: float = 5.0) -> None:
        """Initialize the order store.

        Args:
            pending_timeout_sec: Seconds after which PENDING orders are assumed OPEN.
        """
        self._orders: Dict[str, OrderRecord] = {}
        self._pending_timeout = pending_timeout_sec
        self._lock = asyncio.Lock()
        self._last_filled_scan_at: float = 0.0

    async def add(self, record: OrderRecord) -> None:
        """Add a new order to the store.

        Args:
            record: The OrderRecord to add.
        """
        async with self._lock:
            self._orders[record.order_id] = record
            logger.debug(
                "Order added to store",
                order_id=record.order_id,
                market_id=record.market_id,
                state=record.state.value,
            )

    async def transition(self, order_id: str, new_state: OrderState, filled_size: Optional[float] = None) -> None:
        """Transition an order to a new state.

        Validates the transition is allowed. Logs REJECTED at INFO level
        (not error — POST_ONLY rejections are expected behavior).

        Args:
            order_id: The order ID to transition.
            new_state: The target state.
            filled_size: If provided, update the filled size.

        Raises:
            InvalidTransition: If the transition is not valid.
            KeyError: If the order_id is not found.
        """
        async with self._lock:
            record = self._orders.get(order_id)
            if record is None:
                raise KeyError(f"Order {order_id} not found in store")

            current = record.state

            # Check valid transition
            if new_state not in VALID_TRANSITIONS.get(current, set()):
                raise InvalidTransition(
                    f"Cannot transition order {order_id} from {current.value} "
                    f"to {new_state.value}. Valid transitions: "
                    f"{[s.value for s in VALID_TRANSITIONS.get(current, set())]}"
                )

            # Update record
            record.state = new_state
            record.updated_at = time.monotonic()

            if filled_size is not None:
                record.filled_size = filled_size

            # Log with appropriate level
            if new_state == OrderState.REJECTED:
                logger.info(
                    "Order REJECTED (POST_ONLY guard working correctly)",
                    order_id=order_id,
                    market_id=record.market_id,
                    previous_state=current.value,
                )
            elif new_state == OrderState.PARTIALLY_FILLED:
                logger.info(
                    "Order partially filled",
                    order_id=order_id,
                    market_id=record.market_id,
                    filled_size=record.filled_size,
                    total_size=record.size,
                )
            else:
                logger.debug(
                    "Order state transition",
                    order_id=order_id,
                    from_state=current.value,
                    to_state=new_state.value,
                )

    async def check_pending_timeouts(self) -> List[str]:
        """Check for PENDING orders that have exceeded the timeout.

        Moves timed-out PENDING orders to OPEN state.

        Returns:
            List of order IDs that were timed out.
        """
        timed_out = []
        now = time.monotonic()

        async with self._lock:
            for order_id, record in list(self._orders.items()):
                if record.state == OrderState.PENDING:
                    if now - record.created_at > self._pending_timeout:
                        record.state = OrderState.OPEN
                        record.updated_at = now
                        timed_out.append(order_id)
                        logger.info(
                            "PENDING order timed out, assuming OPEN",
                            order_id=order_id,
                            age_sec=now - record.created_at,
                        )

        return timed_out

    def get(self, order_id: str) -> Optional[OrderRecord]:
        """Get an order record by ID (non-async, for read-only access).

        Args:
            order_id: The order ID.

        Returns:
            OrderRecord or None.
        """
        return self._orders.get(order_id)

    async def get_open_orders(self, market_id: Optional[str] = None) -> List[OrderRecord]:
        """Get all open (active) orders, optionally filtered by market.

        Args:
            market_id: If provided, filter to this market only.

        Returns:
            List of active OrderRecords.
        """
        async with self._lock:
            results = []
            for record in self._orders.values():
                if record.is_active:
                    if market_id is None or record.market_id == market_id:
                        results.append(record)
            return results

    async def get_all_orders(self, market_id: Optional[str] = None) -> List[OrderRecord]:
        """Get all orders, optionally filtered by market.

        Args:
            market_id: If provided, filter to this market only.

        Returns:
            List of all OrderRecords for the market.
        """
        async with self._lock:
            results = []
            for record in self._orders.values():
                if market_id is None or record.market_id == market_id:
                    results.append(record)
            return results

    def get_recently_filled(self, since: Optional[float] = None) -> List[OrderRecord]:
        """Get orders filled after a monotonic timestamp.

        The live bot's fill-processing loop calls this synchronously to notify
        strategies about newly filled orders. When ``since`` is omitted, the
        store advances an internal cursor so each filled order is returned at
        most once to that polling loop.

        Args:
            since: Optional ``time.monotonic()`` timestamp. If provided, return
                matching filled orders without advancing the internal cursor.

        Returns:
            Filled OrderRecords sorted by update time.
        """
        cursor = self._last_filled_scan_at if since is None else since
        results = [
            record
            for record in self._orders.values()
            if record.state == OrderState.FILLED and record.updated_at > cursor
        ]
        results.sort(key=lambda record: record.updated_at)

        if since is None:
            if results:
                self._last_filled_scan_at = max(record.updated_at for record in results)
            else:
                self._last_filled_scan_at = max(self._last_filled_scan_at, time.monotonic())

        return results

    async def remove_terminal(self, max_age_sec: float = 3600.0) -> int:
        """Remove old terminal orders from the store to prevent memory growth.

        Args:
            max_age_sec: Remove terminal orders older than this.

        Returns:
            Number of orders removed.
        """
        now = time.monotonic()
        to_remove = []

        async with self._lock:
            for order_id, record in self._orders.items():
                if record.is_terminal and (now - record.updated_at) > max_age_sec:
                    to_remove.append(order_id)

            for order_id in to_remove:
                del self._orders[order_id]

        if to_remove:
            logger.debug("Cleaned up terminal orders", count=len(to_remove))

        return len(to_remove)

    @property
    def size(self) -> int:
        """Total number of orders in the store."""
        return len(self._orders)

    @property
    def active_count(self) -> int:
        """Number of active (non-terminal) orders."""
        return sum(1 for r in self._orders.values() if r.is_active)
