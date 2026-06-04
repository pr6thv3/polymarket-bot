"""Kalshi API client — REST + WebSocket for cross-platform arbitrage.

Provides market data access to Kalshi (https://kalshi.com) prediction markets.
Kalshi is a CFTC-regulated exchange — the primary cross-platform arb target
for Polymarket since both cover US politics, economics, and geopolitics.

Rate limits: 200 req/min for REST, 10 msg/sec for WebSocket.
Authentication requires Kalshi API key (generate at kalshi.com/auth).
"""

import asyncio
import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
import structlog

logger = structlog.get_logger(__name__)

# Kalshi API base URLs
KALSHI_REST_URL = "https://api.elections.kalshi.com/trade-api/v2"
KALSHI_WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"

# Rate limiting
KALSHI_RATE_LIMIT_PER_MIN = 200
KALSHI_WS_MSG_PER_SEC = 10


@dataclass
class KalshiMarket:
    """A Kalshi market (event contract)."""

    market_id: str  # Kalshi ticker (e.g., "KXPRES2024")
    title: str = ""
    category: str = ""
    yes_price: float = 0.0  # Price in cents (0-100)
    no_price: float = 0.0
    last_price: float = 0.0
    volume_24h: int = 0
    open_interest: int = 0
    expiration_date: str = ""
    active: bool = True
    subtitle: str = ""

    @property
    def yes_prob(self) -> float:
        """Convert Kalshi cents price to probability (0.0–1.0)."""
        return self.yes_price / 100.0

    @property
    def no_prob(self) -> float:
        """NO probability."""
        return self.no_price / 100.0


@dataclass
class KalshiOrderBook:
    """L2 order book snapshot for a Kalshi market."""

    market_id: str
    bids: List[Tuple[int, int]] = field(default_factory=list)  # (price_cents, size)
    asks: List[Tuple[int, int]] = field(default_factory=list)
    last_update: float = 0.0

    @property
    def best_bid_cents(self) -> Optional[int]:
        """Best bid in cents."""
        return self.bids[0][0] if self.bids else None

    @property
    def best_ask_cents(self) -> Optional[int]:
        """Best ask in cents."""
        return self.asks[0][0] if self.asks else None

    @property
    def mid_cents(self) -> Optional[float]:
        """Midpoint in cents."""
        if self.best_bid_cents is not None and self.best_ask_cents is not None:
            return (self.best_bid_cents + self.best_ask_cents) / 2.0
        return None

    @property
    def spread_cents(self) -> Optional[int]:
        """Spread in cents."""
        if self.best_bid_cents is not None and self.best_ask_cents is not None:
            return self.best_ask_cents - self.best_bid_cents
        return None


class KalshiClient:
    """Async REST + WebSocket client for Kalshi markets.

    Features:
    - Authenticated REST access with HMAC signing
    - Market search + order book retrieval
    - WebSocket streaming for real-time price updates
    - Rate limiting with token bucket
    - Automatic session management with retry
    - Market mapping for cross-platform comparison
    """

    def __init__(self, config: dict) -> None:
        """Initialize the Kalshi client.

        Args:
            config: Full config dict (reads from data_feeds.kalshi section).
        """
        self.config = config
        kalshi_cfg = config.get("data_feeds", {}).get("kalshi", {})

        self.api_key = kalshi_cfg.get("api_key", "")
        self.api_secret = kalshi_cfg.get("api_secret", "")
        self.rest_url = kalshi_cfg.get("rest_url", KALSHI_REST_URL)
        self.ws_url = kalshi_cfg.get("ws_url", KALSHI_WS_URL)
        self.enabled = kalshi_cfg.get("enabled", False)

        # Session management
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws_session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None

        # Rate limiting
        self._request_interval = 60.0 / min(kalshi_cfg.get("rate_limit_per_min", 180), KALSHI_RATE_LIMIT_PER_MIN)
        self._last_request_time: float = 0.0
        self._lock = asyncio.Lock()

        # Market data cache
        self._markets: Dict[str, KalshiMarket] = {}
        self._orderbooks: Dict[str, KalshiOrderBook] = {}
        self._last_cache_refresh: float = 0.0
        self._cache_ttl = kalshi_cfg.get("cache_ttl_sec", 30.0)

        # Market mapping: Polymarket slug -> Kalshi ticker (loaded from config)
        self._market_map: Dict[str, str] = kalshi_cfg.get("market_map", {})

        # Callbacks for WebSocket events
        self._on_price_update = None

    # ── Session management ─────────────────────────────────────────────

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Ensure an HTTP session exists, creating one if needed."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=10.0)
            self._session = aiohttp.ClientSession(
                base_url=self.rest_url,
                timeout=timeout,
                headers=self._auth_headers(),
            )
        return self._session

    def _auth_headers(self) -> Dict[str, str]:
        """Build authentication headers for Kalshi API.

        Returns:
            Headers dict with API key.
        """
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["KALSHI-ACCESS-KEY"] = self.api_key
        return headers

    def _sign_request(self, method: str, path: str, body: str = "") -> str:
        """Sign a request with HMAC-SHA256 for Kalshi authentication.

        Args:
            method: HTTP method (GET, POST, etc.).
            path: API path (e.g., /markets).
            body: Request body (empty for GET).

        Returns:
            Hex-encoded signature string.
        """
        if not self.api_secret:
            return ""

        timestamp = int(time.time())
        message = f"{timestamp}/{path}/{body}"
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"{timestamp}:{signature}"

    async def _rate_limit(self) -> None:
        """Enforce rate limiting between requests."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < self._request_interval:
                await asyncio.sleep(self._request_interval - elapsed)
            self._last_request_time = time.monotonic()

    # ── REST API methods ───────────────────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict] = None,
        json_body: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """Make an authenticated REST request to Kalshi.

        Args:
            method: HTTP method.
            path: API path.
            params: Query parameters.
            json_body: JSON request body.

        Returns:
            Response JSON as dict.

        Raises:
            aiohttp.ClientError: On network errors.
            ValueError: On API errors.
        """
        if not self.enabled:
            raise RuntimeError("Kalshi client is disabled in config")

        await self._rate_limit()
        session = await self._ensure_session()

        body_str = json.dumps(json_body) if json_body else ""
        signature = self._sign_request(method, path, body_str)

        headers = {}
        if signature:
            headers["KALSHI-ACCESS-SIGNATURE"] = signature

        try:
            async with session.request(
                method,
                path,
                params=params,
                json=json_body,
                headers=headers,
            ) as resp:
                if resp.status == 429:
                    retry_after = int(resp.headers.get("Retry-After", "60"))
                    logger.warning("Kalshi rate limited", retry_after_sec=retry_after)
                    await asyncio.sleep(retry_after)
                    # Retry once
                    async with session.request(
                        method, path, params=params, json=json_body, headers=headers,
                    ) as resp2:
                        resp2.raise_for_status()
                        return await resp2.json()

                resp.raise_for_status()
                return await resp.json()

        except aiohttp.ClientError as exc:
            logger.error("Kalshi API request failed", path=path, error=str(exc))
            raise

    async def get_markets(
        self,
        category: Optional[str] = None,
        active_only: bool = True,
        limit: int = 100,
        cursor: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetch markets from Kalshi.

        Args:
            category: Filter by category (e.g., "politics", "economics").
            active_only: Only return active markets.
            limit: Number of results per page.
            cursor: Pagination cursor.

        Returns:
            Dict with "markets" list and "cursor" for pagination.
        """
        params: Dict[str, Any] = {"limit": limit}
        if category:
            params["category"] = category
        if active_only:
            params["status"] = "open"
        if cursor:
            params["cursor"] = cursor

        return await self._request("GET", "/markets", params=params)

    async def get_market(self, ticker: str) -> Optional[KalshiMarket]:
        """Fetch a single market by ticker.

        Args:
            ticker: Kalshi market ticker (e.g., "KXPRES2024").

        Returns:
            KalshiMarket or None if not found.
        """
        try:
            data = await self._request("GET", f"/markets/{ticker}")
            market_data = data.get("market", data)
            return self._parse_market(market_data)
        except Exception as exc:
            logger.warning("Failed to fetch Kalshi market", ticker=ticker, error=str(exc))
            return None

    async def get_orderbook(self, ticker: str, depth: int = 10) -> Optional[KalshiOrderBook]:
        """Fetch the order book for a Kalshi market.

        Args:
            ticker: Kalshi market ticker.
            depth: Number of price levels.

        Returns:
            KalshiOrderBook or None if not found.
        """
        try:
            data = await self._request(
                "GET", f"/markets/{ticker}/orderbook",
                params={"depth": depth},
            )

            bids = [(int(b.get("price", 0)), int(b.get("size", 0)))
                     for b in data.get("bids", [])]
            asks = [(int(a.get("price", 0)), int(a.get("size", 0)))
                     for a in data.get("asks", [])]

            # Sort bids descending, asks ascending
            bids.sort(key=lambda x: x[0], reverse=True)
            asks.sort(key=lambda x: x[0])

            ob = KalshiOrderBook(
                market_id=ticker,
                bids=bids,
                asks=asks,
                last_update=time.monotonic(),
            )
            self._orderbooks[ticker] = ob
            return ob

        except Exception as exc:
            logger.warning("Failed to fetch Kalshi orderbook", ticker=ticker, error=str(exc))
            return None

    async def refresh_markets(self, force: bool = False) -> List[KalshiMarket]:
        """Refresh the market cache from Kalshi API.

        Args:
            force: Force refresh even if cache is still valid.

        Returns:
            List of KalshiMarket objects.
        """
        now = time.monotonic()
        if not force and (now - self._last_cache_refresh) < self._cache_ttl:
            return list(self._markets.values())

        try:
            all_markets = []
            cursor = None

            while True:
                result = await self.get_markets(
                    active_only=True,
                    limit=100,
                    cursor=cursor,
                )
                markets_data = result.get("markets", [])

                for m_data in markets_data:
                    market = self._parse_market(m_data)
                    if market:
                        self._markets[market.market_id] = market
                        all_markets.append(market)

                cursor = result.get("cursor")
                if not cursor:
                    break

                # Safety: don't fetch more than 5 pages at once
                if len(all_markets) >= 500:
                    break

            self._last_cache_refresh = time.monotonic()
            logger.info("Kalshi markets refreshed", count=len(all_markets))
            return all_markets

        except Exception as exc:
            logger.error("Failed to refresh Kalshi markets", error=str(exc))
            return list(self._markets.values())

    # ── Market mapping ─────────────────────────────────────────────────

    def add_market_mapping(self, polymarket_id: str, kalshi_ticker: str) -> None:
        """Add a mapping between a Polymarket market and a Kalshi market.

        Args:
            polymarket_id: Polymarket condition/market ID.
            kalshi_ticker: Kalshi market ticker.
        """
        self._market_map[polymarket_id] = kalshi_ticker
        logger.info("Market mapping added", poly=polymarket_id, kalshi=kalshi_ticker)

    def get_kalshi_ticker(self, polymarket_id: str) -> Optional[str]:
        """Get the Kalshi ticker for a Polymarket market.

        Args:
            polymarket_id: Polymarket condition/market ID.

        Returns:
            Kalshi ticker string or None.
        """
        return self._market_map.get(polymarket_id)

    def get_mapped_markets(self) -> Dict[str, str]:
        """Get all mapped markets (Polymarket ID -> Kalshi ticker).

        Returns:
            Dict of polymarket_id -> kalshi_ticker.
        """
        return dict(self._market_map)

    def get_cached_market(self, ticker: str) -> Optional[KalshiMarket]:
        """Get a cached market by ticker.

        Args:
            ticker: Kalshi market ticker.

        Returns:
            KalshiMarket or None.
        """
        return self._markets.get(ticker)

    def get_cached_orderbook(self, ticker: str) -> Optional[KalshiOrderBook]:
        """Get a cached orderbook by ticker.

        Args:
            ticker: Kalshi market ticker.

        Returns:
            KalshiOrderBook or None.
        """
        return self._orderbooks.get(ticker)

    # ── WebSocket ──────────────────────────────────────────────────────

    async def connect_ws(self) -> None:
        """Connect to the Kalshi WebSocket for real-time price updates.

        Subscribes to all mapped markets for price change notifications.
        """
        if not self.enabled:
            return

        try:
            if self._ws_session is None or self._ws_session.closed:
                self._ws_session = aiohttp.ClientSession()

            self._ws = await self._ws_session.ws_connect(
                self.ws_url,
                heartbeat=30,
            )

            # Authenticate on WS
            if self.api_key:
                auth_msg = {
                    "type": "auth",
                    "api_key": self.api_key,
                    "timestamp": int(time.time()),
                }
                await self._ws.send_json(auth_msg)

            # Subscribe to mapped markets
            for _, kalshi_ticker in self._market_map.items():
                sub_msg = {
                    "type": "subscribe",
                    "channel": "market_price",
                    "markets": [kalshi_ticker],
                }
                await self._ws.send_json(sub_msg)

            logger.info("Kalshi WebSocket connected")

        except Exception as exc:
            logger.error("Kalshi WebSocket connection failed", error=str(exc))
            self._ws = None

    async def listen_ws(self) -> None:
        """Listen for WebSocket messages and process them.

        Runs in an infinite loop until disconnected. Calls the
        registered price update callback on each message.
        """
        if self._ws is None:
            return

        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    if data.get("type") == "market_price":
                        ticker = data.get("market", "")
                        yes_price = float(data.get("yes_price", 0))
                        no_price = float(data.get("no_price", 0))

                        # Update cache
                        if ticker in self._markets:
                            self._markets[ticker].yes_price = yes_price
                            self._markets[ticker].no_price = no_price

                        # Call registered callback
                        if self._on_price_update:
                            await self._on_price_update(ticker, yes_price, no_price)

                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    logger.warning("Kalshi WebSocket closed/error, reconnecting")
                    await asyncio.sleep(5)
                    await self.connect_ws()
                    return  # Exit this loop; caller should re-spawn

        except Exception as exc:
            logger.error("Kalshi WS listen error", error=str(exc))

    def on_price_update(self, callback) -> None:
        """Register a callback for WebSocket price updates.

        Args:
            callback: Async callable(ticker, yes_price, no_price).
        """
        self._on_price_update = callback

    # ── Cleanup ────────────────────────────────────────────────────────

    async def close(self) -> None:
        """Close all connections."""
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._ws_session and not self._ws_session.closed:
            await self._ws_session.close()
        if self._session and not self._session.closed:
            await self._session.close()
        logger.info("Kalshi client closed")

    async def health_check(self) -> Dict[str, Any]:
        """Check connectivity to Kalshi API.

        Returns:
            Dict with status, latency, and market count.
        """
        if not self.enabled:
            return {"status": "disabled", "latency_sec": None, "markets_cached": 0}

        try:
            start = time.monotonic()
            await self._request("GET", "/markets", params={"limit": 1})
            latency = time.monotonic() - start

            return {
                "status": "ok",
                "latency_sec": round(latency, 3),
                "markets_cached": len(self._markets),
                "ws_connected": self._ws is not None and not self._ws.closed,
            }
        except Exception as exc:
            return {
                "status": "error",
                "error": str(exc),
                "latency_sec": None,
                "markets_cached": len(self._markets),
            }

    # ── Internal helpers ───────────────────────────────────────────────

    def _parse_market(self, data: Dict[str, Any]) -> Optional[KalshiMarket]:
        """Parse a Kalshi market API response into a KalshiMarket object.

        Args:
            data: Raw market dict from API.

        Returns:
            KalshiMarket or None on parse failure.
        """
        try:
            return KalshiMarket(
                market_id=data.get("ticker", data.get("market_id", "")),
                title=data.get("title", ""),
                category=data.get("category", ""),
                yes_price=float(data.get("yes_price", data.get("last_price", 0))),
                no_price=float(data.get("no_price", 0)),
                last_price=float(data.get("last_price", 0)),
                volume_24h=int(data.get("volume_24h", data.get("volume", 0))),
                open_interest=int(data.get("open_interest", 0)),
                expiration_date=data.get("expiration_date", data.get("close_time", "")),
                active=data.get("status", "open") == "open",
                subtitle=data.get("subtitle", ""),
            )
        except (ValueError, TypeError) as exc:
            logger.warning("Failed to parse Kalshi market", error=str(exc))
            return None
