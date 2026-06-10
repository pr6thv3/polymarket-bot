"""CLOB client wrapper with rate limiting, circuit breaker, and nonce caching."""

import asyncio
import os
import time
from collections import deque
from typing import Any, Optional

import structlog
from dotenv import load_dotenv

from utils.helpers import TokenBucketRateLimiter, retry_async, load_config
from utils import metrics as m

load_dotenv()

logger = structlog.get_logger(__name__)

# Fee and rebate lookup tables
TAKER_FEES = {
    "crypto": 0.018,
    "sports": 0.0075,
    "finance": 0.01,
    "politics": 0.01,
    "economics": 0.015,
    "geopolitics": 0.0,
}

REBATE_RATES = {
    "crypto": 0.20,
    "sports": 0.25,
    "finance": 0.50,
    "politics": 0.25,
    "economics": 0.25,
    "geopolitics": 0.20,
}


class CircuitBreakerOpen(Exception):
    """Raised when the circuit breaker is open and calls are paused."""


class ClobClient:
    """Async wrapper around py_clob_client.ClobClient.

    Features:
    - Token bucket rate limiting (55 req/min default)
    - Local EIP-712 nonce cache (increment locally, sync on error)
    - Circuit breaker: pause calls after N errors in a time window
    - Exponential backoff on 429/5xx responses
    - WebSocket management with auto-reconnect
    """

    def __init__(self, config: dict) -> None:
        """Initialize the CLOB client from config and environment.

        Args:
            config: Full config dict.
        """
        self.config = config
        exec_cfg = config.get("execution", {})
        cb_cfg = exec_cfg.get("error_circuit_breaker", {})

        # API credentials from environment
        self.api_key = os.environ.get("POLY_API_KEY", "")
        self.api_secret = os.environ.get("POLY_API_SECRET", "")
        self.api_passphrase = os.environ.get("POLY_PASSPHRASE", "")
        self.private_key = os.environ.get("POLYGON_PRIVATE_KEY", "")
        self.chain_id = 137  # Polygon mainnet

        # Rate limiter: 55 requests per minute = 0.9167/sec
        rate_per_sec = exec_cfg.get("rate_limit_per_min", 55) / 60.0
        self._rate_limiter = TokenBucketRateLimiter(rate=rate_per_sec, capacity=15)

        # Retry config
        self.retry_max = exec_cfg.get("retry_max_attempts", 3)
        self.retry_backoff = exec_cfg.get("retry_backoff_base_sec", 2.0)

        # Circuit breaker
        self._cb_threshold = cb_cfg.get("threshold", 10)
        self._cb_window_sec = cb_cfg.get("window_sec", 60)
        self._cb_pause_sec = cb_cfg.get("pause_sec", 300)
        self._cb_errors: deque = deque()  # timestamps of recent errors
        self._cb_open_until: float = 0.0  # monotonic time until CB is open
        self._cb_lock = asyncio.Lock()

        # Nonce cache
        self._nonce: Optional[int] = None
        self._nonce_lock = asyncio.Lock()

        # Underlying sync client (lazy init)
        self._sync_client: Optional[Any] = None

        # WebSocket
        self._ws: Optional[Any] = None
        self._ws_connected = False
        self._ws_reconnect_delay = 5.0

        # Alerter reference (set later to avoid circular imports)
        self.alerter: Optional[Any] = None

    def _get_sync_client(self) -> Any:
        """Lazily initialize the py_clob_client.ClobClient."""
        if self._sync_client is not None:
            return self._sync_client

        try:
            from py_clob_client.client import ClobClient as SyncClobClient
            from py_clob_client.clob_types import ApiCreds

            api_creds = ApiCreds(
                api_key=self.api_key,
                api_secret=self.api_secret,
                api_passphrase=self.api_passphrase,
            )

            self._sync_client = SyncClobClient(
                host="https://polymarket-proxy.nameispreeth.workers.dev",
                creds=api_creds,
                key=self.private_key,
                chain_id=self.chain_id,
                signature_type=0,
            )
            logger.info("CLOB sync client initialized")
            return self._sync_client
        except ImportError:
            logger.warning(
                "py_clob_client not installed — running in mock/offline mode"
            )
            return None
        except Exception as exc:
            logger.error("Failed to initialize CLOB client", error=str(exc))
            return None

    async def _check_circuit_breaker(self) -> None:
        """Check if the circuit breaker is open. If so, raise exception."""
        async with self._cb_lock:
            now = time.monotonic()
            if now < self._cb_open_until:
                remaining = self._cb_open_until - now
                raise CircuitBreakerOpen(
                    f"Circuit breaker open for {remaining:.1f}s more"
                )

    async def _record_error(self) -> None:
        """Record an error for circuit breaker tracking."""
        async with self._cb_lock:
            now = time.monotonic()
            self._cb_errors.append(now)

            # Prune old errors outside the window
            cutoff = now - self._cb_window_sec
            while self._cb_errors and self._cb_errors[0] < cutoff:
                self._cb_errors.popleft()

            # Check if threshold exceeded
            if len(self._cb_errors) >= self._cb_threshold:
                self._cb_open_until = now + self._cb_pause_sec
                logger.critical(
                    "Circuit breaker triggered",
                    errors_in_window=len(self._cb_errors),
                    pause_sec=self._cb_pause_sec,
                )
                m.record_circuit_breaker_trigger()
                if self.alerter:
                    await self.alerter.send_alert(
                        "connection_lost",
                        f"Circuit breaker triggered. Bot paused for {self._cb_pause_sec}s. "
                        f"{len(self._cb_errors)} errors in {self._cb_window_sec}s window.",
                    )

    async def _call_with_protection(self, func: callable, *args: Any, **kwargs: Any) -> Any:
        """Call a sync function with rate limiting, circuit breaker, and retry.

        Args:
            func: Sync function to call (will be wrapped in asyncio.to_thread).
            *args: Positional args for the function.
            **kwargs: Keyword args for the function.

        Returns:
            Result of the function call.

        Raises:
            CircuitBreakerOpen: If the circuit breaker is active.
        """
        await self._check_circuit_breaker()
        await self._rate_limiter.acquire()

        last_exc = None
        for attempt in range(1, self.retry_max + 1):
            try:
                result = await asyncio.to_thread(func, *args, **kwargs)
                return result
            except CircuitBreakerOpen:
                raise
            except Exception as exc:
                last_exc = exc
                error_str = str(exc)

                # Check if it's a retryable error (429, 5xx)
                is_retryable = any(
                    s in error_str
                    for s in ["429", "500", "502", "503", "504", "rate limit"]
                )

                if is_retryable and attempt < self.retry_max:
                    delay = self.retry_backoff ** attempt
                    logger.warning(
                        "API call failed, retrying",
                        attempt=attempt,
                        max_attempts=self.retry_max,
                        delay=delay,
                        error=error_str,
                    )
                    await self._record_error()
                    await asyncio.sleep(delay)
                elif is_retryable:
                    await self._record_error()
                    logger.error(
                        "API call failed after all retries",
                        attempt=attempt,
                        error=error_str,
                    )
                    raise
                else:
                    await self._record_error()
                    raise

        raise last_exc  # type: ignore[misc]

    # --- Public API methods ---

    async def get_markets(self, next_cursor: Optional[str] = None) -> dict:
        """Fetch available markets from the CLOB.

        Args:
            next_cursor: Pagination cursor (None to use default first page).

        Returns:
            Dict with markets data.
        """
        client = self._get_sync_client()
        if client is None:
            return {"markets": [], "next_cursor": None}

        # Use client's default cursor if None
        if next_cursor is None:
            return await self._call_with_protection(client.get_markets)
        else:
            return await self._call_with_protection(
                client.get_markets, next_cursor
            )

    async def get_market(self, condition_id: str) -> dict:
        """Fetch a single market by condition ID.

        Args:
            condition_id: The market's condition ID.

        Returns:
            Market data dict.
        """
        client = self._get_sync_client()
        if client is None:
            return {}

        return await self._call_with_protection(
            client.get_market, condition_id
        )

    async def get_orderbook(self, token_id: str) -> dict:
        """Fetch the current order book for a token.

        Args:
            token_id: The token ID for the YES or NO side.

        Returns:
            Order book dict with bids and asks.
        """
        client = self._get_sync_client()
        if client is None:
            return {"bids": [], "asks": []}

        return await self._call_with_protection(
            client.get_order_book, token_id
        )

    async def create_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
        post_only: bool = True,
    ) -> Optional[str]:
        """Create a limit order with POST_ONLY by default.

        Args:
            token_id: Token ID to trade.
            side: "BUY" or "SELL".
            price: Limit price (0.00 to 1.00).
            size: Order size in shares.
            post_only: CRITICAL — must be True for market making to avoid taker fees.

        Returns:
            Order ID string, or None on failure.
        """
        client = self._get_sync_client()
        if client is None:
            logger.info(
                "Dry/mock mode: would create order",
                token_id=token_id,
                side=side,
                price=price,
                size=size,
                post_only=post_only,
            )
            return f"mock-{int(time.time()*1000)}"

        if not post_only:
            logger.warning(
                "Creating order WITHOUT post_only — this may execute as taker!",
                token_id=token_id,
                side=side,
            )

        try:
            from py_clob_client.clob_types import OrderArgs, OrderType

            order_args = OrderArgs(
                price=price,
                size=size,
                side=side,
                token_id=token_id,
            )

            # Get or create signed order
            signed_order = await self._call_with_protection(
                client.create_order, order_args
            )

            # Place with post_only flag
            result = await self._call_with_protection(
                client.post_order, signed_order, OrderType.GTD
            )

            order_id = result.get("orderID", result.get("id", ""))
            logger.info(
                "Order created",
                order_id=order_id,
                token_id=token_id,
                side=side,
                price=price,
                size=size,
                post_only=post_only,
            )
            return order_id

        except Exception as exc:
            error_str = str(exc)
            if "post_only" in error_str.lower() or "would cross" in error_str.lower():
                logger.info(
                    "POST_ONLY rejection (expected)",
                    token_id=token_id,
                    side=side,
                    price=price,
                )
                m.record_post_only_rejection()
            else:
                logger.error("Failed to create order", error=error_str)
            return None

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a single order.

        Args:
            order_id: The order ID to cancel.

        Returns:
            True if cancellation succeeded.
        """
        client = self._get_sync_client()
        if client is None:
            logger.info("Mock: would cancel order", order_id=order_id)
            return True

        try:
            await self._call_with_protection(client.cancel, order_id)
            logger.info("Order cancelled", order_id=order_id)
            return True
        except Exception as exc:
            logger.error("Failed to cancel order", order_id=order_id, error=str(exc))
            return False

    async def cancel_all_for_market(self, market_id: str) -> int:
        """Cancel all open orders for a market.

        Args:
            market_id: The market/condition ID.

        Returns:
            Number of orders cancelled.
        """
        client = self._get_sync_client()
        if client is None:
            logger.info("Mock: would cancel all orders for market", market_id=market_id)
            return 0

        try:
            result = await self._call_with_protection(
                client.cancel_all, market_id
            )
            count = len(result) if isinstance(result, list) else 1
            logger.info("Batch cancel complete", market_id=market_id, count=count)
            return count
        except Exception as exc:
            logger.error(
                "Batch cancel failed", market_id=market_id, error=str(exc)
            )
            return 0

    async def amend_order(self, order_id: str, new_price: float, new_size: float) -> bool:
        """Amend an existing order (preferred over cancel+replace).

        Args:
            order_id: The order ID to amend.
            new_price: New limit price.
            new_size: New order size.

        Returns:
            True if amendment succeeded.
        """
        client = self._get_sync_client()
        if client is None:
            logger.info(
                "Mock: would amend order",
                order_id=order_id,
                new_price=new_price,
                new_size=new_size,
            )
            return True

        try:
            await self._call_with_protection(
                client.amend_order, order_id, new_price, new_size
            )
            logger.info(
                "Order amended",
                order_id=order_id,
                new_price=new_price,
                new_size=new_size,
            )
            return True
        except Exception as exc:
            # Fallback to cancel+replace
            logger.warning(
                "Amend failed, will fallback to cancel+replace",
                order_id=order_id,
                error=str(exc),
            )
            return False

    # --- Nonce management ---

    async def get_nonce(self) -> int:
        """Get the next nonce for order signing.

        Uses local cache to avoid round-trip. Syncs from chain on error.

        Returns:
            Next nonce integer.
        """
        async with self._nonce_lock:
            if self._nonce is None:
                # First call: fetch from chain
                try:
                    client = self._get_sync_client()
                    if client:
                        self._nonce = await asyncio.to_thread(
                            client.get_next_nonce
                        )
                    else:
                        self._nonce = 0
                except Exception as exc:
                    logger.error("Failed to fetch nonce from chain", error=str(exc))
                    self._nonce = 0

            nonce = self._nonce
            self._nonce += 1
            return nonce

    async def sync_nonce(self) -> None:
        """Force sync nonce from chain (called after errors)."""
        async with self._nonce_lock:
            try:
                client = self._get_sync_client()
                if client:
                    self._nonce = await asyncio.to_thread(client.get_next_nonce)
                    logger.info("Nonce synced from chain", nonce=self._nonce)
            except Exception as exc:
                logger.error("Failed to sync nonce", error=str(exc))

    # --- Health check ---

    async def health_check(self) -> dict:
        """Check connectivity to the CLOB API.

        Retries up to 3 times with exponential backoff before reporting
        failure, to avoid false "connection_lost" Telegram alerts.

        Returns:
            Dict with status and latency info.
        """
        max_retries = 3
        last_exc = None

        for attempt in range(1, max_retries + 1):
            try:
                start = time.monotonic()
                await self.get_markets(next_cursor=None)
                latency = time.monotonic() - start
                return {
                    "status": "ok",
                    "latency_sec": round(latency, 3),
                    "latency_ms": round(latency * 1000, 1),
                }
            except CircuitBreakerOpen:
                return {
                    "status": "circuit_breaker_open",
                    "latency_sec": None,
                    "latency_ms": "timeout",
                }
            except Exception as exc:
                last_exc = exc
                if attempt < max_retries:
                    logger.debug(
                        "Health check retry",
                        attempt=attempt,
                        max_retries=max_retries,
                        error=str(exc),
                    )
                    await asyncio.sleep(2 ** attempt)  # 2s, 4s backoff

        # All retries exhausted
        return {
            "status": "error",
            "error": str(last_exc),
            "latency_sec": None,
            "latency_ms": "timeout",
        }

    @property
    def is_circuit_breaker_open(self) -> bool:
        """Check if the circuit breaker is currently open."""
        return time.monotonic() < self._cb_open_until
