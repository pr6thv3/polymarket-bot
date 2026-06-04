"""In-memory order book with volatility and spread tracking."""

import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class BookLevel:
    """A single price level in the order book."""

    price: float
    size: float


@dataclass
class OrderBookSnapshot:
    """Snapshot of an L2 order book for a single market."""

    market_id: str
    token_id: str
    bids: List[BookLevel] = field(default_factory=list)  # sorted descending
    asks: List[BookLevel] = field(default_factory=list)  # sorted ascending
    last_update: float = 0.0

    @property
    def best_bid(self) -> Optional[float]:
        """Best (highest) bid price."""
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        """Best (lowest) ask price."""
        return self.asks[0].price if self.asks else None

    @property
    def mid_price(self) -> Optional[float]:
        """Midpoint between best bid and best ask."""
        if self.best_bid is not None and self.best_ask is not None:
            return (self.best_bid + self.best_ask) / 2.0
        return None

    @property
    def spread_bps(self) -> Optional[float]:
        """Spread in basis points between best bid and best ask."""
        if self.best_bid is not None and self.best_ask is not None:
            return (self.best_ask - self.best_bid) * 10_000
        return None

    @property
    def spread_usd(self) -> Optional[float]:
        """Spread in dollars between best bid and best ask."""
        if self.best_bid is not None and self.best_ask is not None:
            return self.best_ask - self.best_bid
        return None


class VolatilityTracker:
    """Track rolling 60-second midpoint volatility for a market."""

    def __init__(self, window_sec: float = 60.0) -> None:
        self.window_sec = window_sec
        self._midpoints: deque = deque()  # (timestamp, mid_price)

    def record(self, mid_price: float) -> None:
        """Record a midpoint observation."""
        now = time.monotonic()
        self._midpoints.append((now, mid_price))
        self._prune()

    def _prune(self) -> None:
        """Remove observations older than the window."""
        cutoff = time.monotonic() - self.window_sec
        while self._midpoints and self._midpoints[0][0] < cutoff:
            self._midpoints.popleft()

    def get_volatility(self) -> float:
        """Get the rolling standard deviation of midpoint changes.

        Returns:
            Standard deviation of midpoint changes (in price units).
            Returns 0.0 if fewer than 2 observations.
        """
        self._prune()
        if len(self._midpoints) < 2:
            return 0.0

        prices = [p for _, p in self._midpoints]
        changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        if not changes:
            return 0.0

        mean = sum(changes) / len(changes)
        variance = sum((c - mean) ** 2 for c in changes) / len(changes)
        return variance ** 0.5

    def is_volatile(self, threshold: float = 0.05) -> bool:
        """Check if current volatility exceeds the threshold.

        Args:
            threshold: Price movement threshold (e.g., 0.05 = 5¢).

        Returns:
            True if the market is currently volatile.
        """
        return self.get_volatility() > threshold


class SpreadTracker:
    """Track current spread width vs rebate-qualifying thresholds."""

    def __init__(self, max_qualifying_spread_bps: float = 500.0) -> None:
        self.max_qualifying_spread_bps = max_qualifying_spread_bps

    def is_rebate_qualifying(self, current_spread_bps: float) -> bool:
        """Check if the current spread qualifies for maker rebates.

        Args:
            current_spread_bps: Current spread in basis points.

        Returns:
            True if within the qualifying threshold.
        """
        return current_spread_bps <= self.max_qualifying_spread_bps


class OrderBookManager:
    """Manage in-memory order books for multiple markets.

    Features:
    - Real-time L2 book updates via WebSocket or REST
    - Volatility tracking per market (60s rolling window)
    - Spread tracking for rebate qualification
    - Event emission via asyncio.Queue on book changes
    """

    def __init__(self, config: dict) -> None:
        """Initialize the order book manager.

        Args:
            config: Full config dict.
        """
        self.config = config
        mm_cfg = config.get("strategies", {}).get("market_making", {})
        adverse_cfg = mm_cfg.get("adverse_selection", {})

        self._books: Dict[str, OrderBookSnapshot] = {}
        self._volatility_trackers: Dict[str, VolatilityTracker] = {}
        self._spread_trackers: Dict[str, SpreadTracker] = {}
        self._volatility_threshold = adverse_cfg.get(
            "volatility_pause_threshold", 0.05
        )
        self._max_qualifying_spread_bps = 500.0

        # Event queue for book change notifications
        self.event_queue: asyncio.Queue = asyncio.Queue()

        # WebSocket state
        self._ws_connected = False
        self._polling_active = False

    def register_market(self, market_id: str, token_id: str) -> None:
        """Register a market for tracking.

        Args:
            market_id: The market/condition ID.
            token_id: The token ID for the YES side.
        """
        self._books[market_id] = OrderBookSnapshot(
            market_id=market_id, token_id=token_id
        )
        self._volatility_trackers[market_id] = VolatilityTracker()
        self._spread_trackers[market_id] = SpreadTracker(
            max_qualifying_spread_bps=self._max_qualifying_spread_bps
        )
        logger.info("Market registered for order book tracking", market_id=market_id)

    def unregister_market(self, market_id: str) -> None:
        """Stop tracking a market.

        Args:
            market_id: The market/condition ID.
        """
        self._books.pop(market_id, None)
        self._volatility_trackers.pop(market_id, None)
        self._spread_trackers.pop(market_id, None)
        logger.info("Market unregistered from order book tracking", market_id=market_id)

    def update_book(
        self,
        market_id: str,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
    ) -> None:
        """Update the order book for a market.

        Args:
            market_id: The market/condition ID.
            bids: List of (price, size) tuples for bids (will be sorted descending).
            asks: List of (price, size) tuples for asks (will be sorted ascending).
        """
        if market_id not in self._books:
            logger.warning("Update for unregistered market", market_id=market_id)
            return

        book = self._books[market_id]
        old_mid = book.mid_price

        book.bids = sorted(
            [BookLevel(price=p, size=s) for p, s in bids],
            key=lambda x: x.price,
            reverse=True,
        )
        book.asks = sorted(
            [BookLevel(price=p, size=s) for p, s in asks],
            key=lambda x: x.price,
        )
        book.last_update = time.monotonic()

        # Track volatility
        new_mid = book.mid_price
        if new_mid is not None:
            tracker = self._volatility_trackers.get(market_id)
            if tracker:
                tracker.record(new_mid)

        # Emit event if midpoint changed
        if old_mid is not None and new_mid is not None:
            move_bps = abs(new_mid - old_mid) * 10_000
            if move_bps > 0:
                try:
                    self.event_queue.put_nowait(
                        {
                            "type": "book_change",
                            "market_id": market_id,
                            "old_mid": old_mid,
                            "new_mid": new_mid,
                            "move_bps": move_bps,
                        }
                    )
                except asyncio.QueueFull:
                    pass  # Drop event if queue is full

    def get_snapshot(self, market_id: str) -> Optional[OrderBookSnapshot]:
        """Get the current order book snapshot for a market.

        Args:
            market_id: The market/condition ID.

        Returns:
            OrderBookSnapshot or None if market not tracked.
        """
        return self._books.get(market_id)

    def best_bid(self, market_id: str) -> Optional[float]:
        """Get the best bid for a market."""
        book = self._books.get(market_id)
        return book.best_bid if book else None

    def best_ask(self, market_id: str) -> Optional[float]:
        """Get the best ask for a market."""
        book = self._books.get(market_id)
        return book.best_ask if book else None

    def mid_price(self, market_id: str) -> Optional[float]:
        """Get the midpoint for a market."""
        book = self._books.get(market_id)
        return book.mid_price if book else None

    def spread_bps(self, market_id: str) -> Optional[float]:
        """Get the spread in basis points for a market."""
        book = self._books.get(market_id)
        return book.spread_bps if book else None

    def is_volatile(self, market_id: str, threshold: Optional[float] = None) -> bool:
        """Check if a market is currently volatile.

        Args:
            market_id: The market/condition ID.
            threshold: Override volatility threshold. Uses config default if None.

        Returns:
            True if volatility exceeds the threshold.
        """
        tracker = self._volatility_trackers.get(market_id)
        if tracker is None:
            return False
        return tracker.is_volatile(threshold or self._volatility_threshold)

    def get_volatility(self, market_id: str) -> float:
        """Get the current volatility for a market.

        Args:
            market_id: The market/condition ID.

        Returns:
            Rolling standard deviation of midpoint changes.
        """
        tracker = self._volatility_trackers.get(market_id)
        return tracker.get_volatility() if tracker else 0.0

    def is_rebate_qualifying(self, market_id: str) -> bool:
        """Check if the current spread qualifies for rebates.

        Args:
            market_id: The market/condition ID.

        Returns:
            True if within the qualifying threshold.
        """
        book = self._books.get(market_id)
        if book is None or book.spread_bps is None:
            return False
        tracker = self._spread_trackers.get(market_id)
        return tracker.is_rebate_qualifying(book.spread_bps) if tracker else False

    async def refresh_from_rest(self, client: Any, market_id: str) -> None:
        """Fallback: refresh order book from REST API.

        Args:
            client: ClobClient instance for API calls.
            market_id: The market/condition ID.
        """
        book = self._books.get(market_id)
        if book is None:
            return

        try:
            ob_data = await client.get_orderbook(book.token_id)
            bids = [(float(b.get("price", 0)), float(b.get("size", 0))) for b in ob_data.get("bids", [])]
            asks = [(float(a.get("price", 0)), float(a.get("size", 0))) for a in ob_data.get("asks", [])]
            self.update_book(market_id, bids, asks)
            logger.debug("Order book refreshed from REST", market_id=market_id)
        except Exception as exc:
            logger.error(
                "Failed to refresh order book from REST",
                market_id=market_id,
                error=str(exc),
            )
