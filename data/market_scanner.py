"""Market scanner — scores and ranks markets for market-making eligibility.

Scoring formula (0–100 scale):
  score = w1·volume   + w2·spread_width   + w3·rebate_yield
        + w4·holding_yield + w5·resolution_risk

Where each factor is normalized to 0–1 before weighting:
  - volume:         log(daily_volume_usd) / log(max_expected)   →  [0,1]
  - spread_width:   (observed_bps - min_bps) / (max_bps - min_bps), clamped
  - rebate_yield:   taker_fee * rebate_rate / max_possible_yield
  - holding_yield:  (apy * min(1, days/14)) / max_apy
  - resolution_rsk: negative factor — 1 - (days < 7 ? 1 : days < 14 ? 0.5 : 0)

Default weights: volume=25, spread=20, rebate=25, holding=15, risk=15
"""

import asyncio
import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import structlog

from core.client import ClobClient, TAKER_FEES, REBATE_RATES
from core.orderbook import OrderBookManager

logger = structlog.get_logger(__name__)

# ── Default scoring weights ──────────────────────────────────────────
DEFAULT_WEIGHTS = {
    "volume": 0.25,
    "spread_width": 0.20,
    "rebate_yield": 0.25,
    "holding_yield": 0.15,
    "resolution_risk": 0.15,
}

# Normalization constants
MAX_EXPECTED_VOLUME_USD = 10_000_000  # log-scale normalization ceiling
MIN_SPREAD_BPS = 50
MAX_SPREAD_BPS = 500
MAX_REBATE_YIELD = 0.018 * 0.50  # max possible = crypto taker * finance rebate
MAX_HOLDING_APY = 0.04


@dataclass
class MarketInfo:
    """Snapshot of a single market's key attributes for scoring."""

    market_id: str
    token_id: str
    question: str = ""
    category: str = "politics"
    volume_usd: float = 0.0
    daily_volume_usd: float = 0.0
    spread_bps: float = 0.0
    mid_price: float = 0.5
    days_to_resolution: int = 30
    active: bool = True
    closed: bool = False
    accepting_orders: bool = False
    enable_order_book: bool = True

    # Computed
    score: float = 0.0
    rebate_yield: float = 0.0
    holding_yield: float = 0.0
    last_scanned: float = 0.0


@dataclass
class ScanResult:
    """Result of a market scan pass."""

    timestamp: float = 0.0
    total_markets: int = 0
    eligible_markets: int = 0
    top_markets: List[MarketInfo] = field(default_factory=list)
    errors: int = 0


class MarketScanner:
    """Scan, score, and rank Polymarket markets for market-making.

    Fetches market data via the CLOB REST API, computes a composite
    eligibility score for each market, and returns the top-N markets
    that the market-making strategy should quote.

    Features:
    - Weighted composite scoring (volume, spread, rebate, holding, risk)
    - Category filtering (only target configured categories)
    - Minimum quality gates (min volume, min spread, min days to resolution)
    - Deduplication: won't re-score markets that haven't changed
    - Batch fetching with pagination
    - Caching: recent scan results available without re-fetch
    """

    def __init__(self, client: ClobClient, orderbook: OrderBookManager, config: dict) -> None:
        """Initialize the market scanner.

        Args:
            client: CLOB client for API calls.
            orderbook: Order book manager for spread/mid data.
            config: Full config dict.
        """
        self.client = client
        self.orderbook = orderbook
        self.config = config

        mm_cfg = config.get("strategies", {}).get("market_making", {})

        # Target categories for market making
        self.target_categories = set(mm_cfg.get("target_categories", ["geopolitics", "finance", "politics"]))

        # Quality gates
        self.min_daily_volume_usd = mm_cfg.get("scanner_min_daily_volume_usd", 5000.0)
        self.min_spread_bps = mm_cfg.get("min_spread_bps", 100)
        self.max_spread_bps = mm_cfg.get("max_spread_bps", 400)
        self.min_days_to_resolution = mm_cfg.get("scanner_min_days_to_resolution", 3)

        # Scoring weights
        self.weights = mm_cfg.get("scanner_weights", DEFAULT_WEIGHTS)

        # Top-N markets to return
        self.top_n = mm_cfg.get("scanner_top_n", mm_cfg.get("max_active_markets", 10))

        # Scan interval
        self.scan_interval_sec = mm_cfg.get("scanner_interval_sec", 300)

        # Cache
        self._markets: Dict[str, MarketInfo] = {}
        self._last_scan: float = 0.0
        self._scan_lock = asyncio.Lock()

        # State
        self._running = False
        self._total_scans = 0
        self._total_errors = 0

    # ── Public API ───────────────────────────────────────────────────

    async def scan(self, force: bool = False) -> ScanResult:
        """Run a full market scan and return top-N eligible markets.

        Args:
            force: If True, re-scan even if cache is fresh.

        Returns:
            ScanResult with ranked markets.
        """
        async with self._scan_lock:
            now = time.monotonic()
            if not force and (now - self._last_scan) < self.scan_interval_sec:
                # Return cached result
                return self._cached_result()

            result = await self._fetch_and_score()
            self._last_scan = now
            self._total_scans += 1
            return result

    async def get_eligible_markets(self) -> List[MarketInfo]:
        """Get the current list of eligible markets (may use cache).

        Returns:
            List of MarketInfo for eligible markets, sorted by score desc.
        """
        result = await self.scan()
        return result.top_markets

    async def refresh_market_book(self, market_id: str) -> None:
        """Refresh the order book for a single market via REST fallback.

        Args:
            market_id: Market to refresh.
        """
        info = self._markets.get(market_id)
        if info is None:
            return

        try:
            await self.orderbook.refresh_from_rest(self.client, market_id)
            snapshot = self.orderbook.get_snapshot(market_id)
            if snapshot:
                info.spread_bps = snapshot.spread_bps or 0.0
                info.mid_price = snapshot.mid_price or 0.5
                info.last_scanned = time.monotonic()
        except Exception as exc:
            logger.warning("Failed to refresh book for market", market_id=market_id, error=str(exc))

    def get_market_info(self, market_id: str) -> Optional[MarketInfo]:
        """Get cached info for a single market.

        Args:
            market_id: Market ID.

        Returns:
            MarketInfo or None.
        """
        return self._markets.get(market_id)

    @property
    def total_scans(self) -> int:
        """Total number of scans performed."""
        return self._total_scans

    # ── Internal: fetch and score ─────────────────────────────────────

    async def _fetch_and_score(self) -> ScanResult:
        """Fetch all markets, score them, and return top-N.

        Returns:
            ScanResult.
        """
        result = ScanResult(timestamp=time.monotonic())
        all_markets: List[MarketInfo] = []

        # Paginate through all markets
        cursor = None
        pages = 0
        max_pages = 50  # Safety limit

        while pages < max_pages:
            try:
                data = await self.client.get_markets(next_cursor=cursor)
            except Exception as exc:
                logger.error("Failed to fetch markets page", page=pages, error=str(exc))
                result.errors += 1
                self._total_errors += 1
                break

            markets_list = data.get("data", data.get("markets", [])) if isinstance(data, dict) else []
            if not markets_list:
                break

            for mkt in markets_list:
                if not isinstance(mkt, dict):
                    continue
                info = self._parse_market(mkt)
                if info is not None:
                    all_markets.append(info)

            # Check next cursor
            next_cursor = data.get("next_cursor") if isinstance(data, dict) else None
            if not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
            pages += 1
            await asyncio.sleep(0.25)

        result.total_markets = len(all_markets)

        # Score and filter
        for info in all_markets:
            self._compute_score(info)
            self._markets[info.market_id] = info

        # Filter eligible
        eligible = [
            m for m in all_markets
            if self._is_eligible(m)
        ]
        result.eligible_markets = len(eligible)

        # Sort by score descending
        eligible.sort(key=lambda m: m.score, reverse=True)

        # Top-N
        result.top_markets = eligible[: self.top_n]

        logger.info(
            "Market scan complete",
            total=result.total_markets,
            eligible=result.eligible_markets,
            top=len(result.top_markets),
            errors=result.errors,
        )

        return result

    def _parse_market(self, raw: dict) -> Optional[MarketInfo]:
        """Parse a raw market dict from the API into a MarketInfo.

        Args:
            raw: Raw market dict from CLOB API.

        Returns:
            MarketInfo or None if invalid.
        """
        try:
            market_id = raw.get("condition_id", raw.get("id", ""))
            if not market_id:
                return None

            # Extract token ID for YES side
            tokens = raw.get("tokens") or []
            if isinstance(tokens, str):
                # Some API responses serialize tokens as a string
                try:
                    import ast
                    tokens = ast.literal_eval(tokens)
                except (ValueError, SyntaxError):
                    tokens = []
            token_id = ""
            for tok in tokens:
                if isinstance(tok, dict) and tok.get("outcome", "").upper() == "YES":
                    token_id = tok.get("token_id", "")
                    break
            if not token_id and tokens:
                # Fallback: first token
                first = tokens[0]
                token_id = first.get("token_id", "") if isinstance(first, dict) else ""

            # Volume — API may not include volume fields; use fallback chain
            volume = float(
                raw.get("volume")
                or raw.get("volume_num")
                or raw.get("volumeNum")
                or raw.get("usdcVolume")
                or 0
            )
            daily_volume = float(
                raw.get("volume_24hr")
                or raw.get("volume24hr")
                or raw.get("daily_volume")
                or raw.get("volume_num")
                or volume  # Fall back to total volume
                or 0
            )

            # Category — API doesn't have a "category" field;
            # infer from tags list and market_slug instead.
            category = self._infer_category(raw)

            # Days to resolution
            end_date = raw.get("end_date_iso", raw.get("endDate", ""))
            days_to_resolution = self._parse_days_to_resolution(end_date)

            # Active/closed/accepting
            active = raw.get("active", True)
            closed = raw.get("closed", False)
            accepting_orders = raw.get("accepting_orders", False)
            enable_order_book = raw.get("enable_order_book", False)

            # Question
            question = raw.get("question", raw.get("title", "")) or ""

            return MarketInfo(
                market_id=market_id,
                token_id=token_id,
                question=question,
                category=category,
                volume_usd=volume,
                daily_volume_usd=daily_volume,
                days_to_resolution=days_to_resolution,
                active=bool(active),
                closed=bool(closed),
                accepting_orders=bool(accepting_orders),
                enable_order_book=bool(enable_order_book),
                last_scanned=time.monotonic(),
            )

        except Exception as exc:
            logger.debug("Failed to parse market", error=str(exc))
            return None

    @staticmethod
    def _infer_category(raw: dict) -> str:
        """Infer market category from tags and market_slug.

        The CLOB API does not return a 'category' field directly.
        Instead, we match against the tags list and slug text.

        Args:
            raw: Raw market dict.

        Returns:
            Inferred category string (lowercase).
        """
        # Build a searchable string from tags
        tags = raw.get("tags") or []
        tag_names = [
            t.get("label", t) if isinstance(t, dict) else str(t)
            for t in tags
        ]
        tag_str = " ".join(tag_names).lower()
        slug = (raw.get("market_slug", "") or "").lower()
        question = (raw.get("question", "") or "").lower()
        search = f"{tag_str} {slug} {question}"

        # Match against category keywords (most specific first)
        if any(kw in search for kw in [
            "geopolit", "war", "conflict", "nato", "ukraine", "russia",
            "middle east", "iran", "china", "taiwan", "sanction",
            "missile", "military", "ceasefire", "invasion",
        ]):
            return "geopolitics"

        if any(kw in search for kw in [
            "finance", "fed ", "federal reserve", "interest rate",
            "inflation", "gdp", "recession", "s&p", "stock",
            "treasury", "bond", "fomc", "cpi", "economy",
            "monetary policy", "rate cut", "rate hike", "dow",
        ]):
            return "finance"

        if any(kw in search for kw in [
            "crypto", "bitcoin", "ethereum", "btc", "eth ",
            "token", "blockchain", "defi", "nft", "solana",
            "web3", "mining", "halving", "opensea",
        ]):
            return "crypto"

        if any(kw in search for kw in [
            "nba", "nfl", "mlb", "nhl", "ncaa", "soccer",
            "football", "tennis", "ufc", "boxing", "f1",
            "formula", "premier league", "champions league",
            "world cup", "olympics", "sport", "game",
            "match", "playoff", "super bowl", "espn",
        ]):
            return "sports"

        if any(kw in search for kw in [
            "politic", "election", "president", "congress",
            "senate", "governor", "democrat", "republican",
            "vote", "ballot", "primary", "nominee",
            "cabinet", "secretary", "impeach", "legislation",
            "u.s. politic", "white house", "trump", "biden",
        ]):
            return "politics"

        if any(kw in search for kw in [
            "economic", "employment", "jobs", "labor",
            "trade", "tariff", "gdp", "growth",
        ]):
            return "economics"

        # Default fallback
        return "politics"

    def _parse_days_to_resolution(self, end_date_str: str) -> int:
        """Parse an end date string into days remaining.

        Args:
            end_date_str: ISO date string or empty.

        Returns:
            Days to resolution (default 30 if unparseable).
        """
        if not end_date_str:
            return 30

        try:
            from datetime import datetime, timezone
            # Try ISO format
            end_date_str = end_date_str.replace("Z", "+00:00")
            end_dt = datetime.fromisoformat(end_date_str)
            now = datetime.now(timezone.utc)
            delta = (end_dt - now).total_seconds() / 86400.0
            return max(0, int(delta))
        except Exception:
            return 30

    # ── Scoring engine ────────────────────────────────────────────────

    def _compute_score(self, info: MarketInfo) -> None:
        """Compute the composite score for a market.

        Score = w1·volume_norm + w2·spread_norm + w3·rebate_norm
              + w4·holding_norm + w5·risk_factor

        Each component is normalized to [0, 1].

        Args:
            info: MarketInfo to score (mutated in-place).
        """
        w = self.weights

        # 1. Volume factor (log scale)
        volume_norm = 0.0
        if info.daily_volume_usd > 0:
            volume_norm = math.log10(max(1, info.daily_volume_usd)) / math.log10(max(2, MAX_EXPECTED_VOLUME_USD))
            volume_norm = min(1.0, max(0.0, volume_norm))

        # 2. Spread width factor (wider spread = more profit opportunity)
        spread_norm = 0.0
        if info.spread_bps > 0:
            spread_norm = (info.spread_bps - MIN_SPREAD_BPS) / (MAX_SPREAD_BPS - MIN_SPREAD_BPS)
            spread_norm = min(1.0, max(0.0, spread_norm))

        # 3. Rebate yield factor
        taker_fee = TAKER_FEES.get(info.category, 0.01)
        rebate_rate = REBATE_RATES.get(info.category, 0.25)
        info.rebate_yield = taker_fee * rebate_rate
        rebate_norm = info.rebate_yield / MAX_REBATE_YIELD if MAX_REBATE_YIELD > 0 else 0.0
        rebate_norm = min(1.0, max(0.0, rebate_norm))

        # 4. Holding reward yield factor
        holding_apy = MAX_HOLDING_APY if info.days_to_resolution >= 14 else 0.0
        # Scale by proximity to 14-day threshold
        days_factor = min(1.0, info.days_to_resolution / 14.0)
        info.holding_yield = holding_apy * days_factor
        holding_norm = info.holding_yield / MAX_HOLDING_APY if MAX_HOLDING_APY > 0 else 0.0
        holding_norm = min(1.0, max(0.0, holding_norm))

        # 5. Resolution risk factor (penalize near-resolution markets)
        #    0 = high risk (resolves soon), 1 = low risk (long-dated)
        if info.days_to_resolution < 3:
            risk_factor = 0.0  # Too close to resolution
        elif info.days_to_resolution < 7:
            risk_factor = 0.3
        elif info.days_to_resolution < 14:
            risk_factor = 0.6
        else:
            risk_factor = 1.0

        # Composite score (0–100)
        info.score = (
            w.get("volume", 0.25) * volume_norm
            + w.get("spread_width", 0.20) * spread_norm
            + w.get("rebate_yield", 0.25) * rebate_norm
            + w.get("holding_yield", 0.15) * holding_norm
            + w.get("resolution_risk", 0.15) * risk_factor
        ) * 100.0

    def _is_eligible(self, info: MarketInfo) -> bool:
        """Check if a market passes all quality gates.

        Args:
            info: MarketInfo to check.

        Returns:
            True if the market is eligible for market making.
        """
        # Must be accepting orders (the real tradability indicator).
        # The CLOB API returns active=True + closed=True for many tradeable
        # markets, so we use accepting_orders instead of active+!closed.
        if not info.accepting_orders:
            return False

        # Must have CLOB order book enabled
        if not info.enable_order_book:
            return False

        # Category filter
        if info.category not in self.target_categories:
            return False

        # Minimum daily volume (skip gate if API didn't provide volume)
        if info.daily_volume_usd > 0 and info.daily_volume_usd < self.min_daily_volume_usd:
            return False

        # Minimum days to resolution
        if info.days_to_resolution < self.min_days_to_resolution:
            return False

        # Spread must be within our target range
        if info.spread_bps > 0:
            if info.spread_bps < self.min_spread_bps:
                return False
            if info.spread_bps > self.max_spread_bps:
                return False

        # Minimum score threshold
        if info.score < 10.0:
            return False

        return True

    # ── Cache ─────────────────────────────────────────────────────────

    def _cached_result(self) -> ScanResult:
        """Build a ScanResult from the current cache.

        Returns:
            ScanResult with cached top markets.
        """
        eligible = [m for m in self._markets.values() if self._is_eligible(m)]
        eligible.sort(key=lambda m: m.score, reverse=True)

        return ScanResult(
            timestamp=self._last_scan,
            total_markets=len(self._markets),
            eligible_markets=len(eligible),
            top_markets=eligible[: self.top_n],
            errors=0,
        )
