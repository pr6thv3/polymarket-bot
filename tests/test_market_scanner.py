"""Tests for the market scanner — scoring, eligibility, and scanning logic."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from data.market_scanner import MarketScanner, MarketInfo, ScanResult, DEFAULT_WEIGHTS


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def mock_client():
    """Create a mock ClobClient."""
    client = MagicMock()
    client.get_markets = AsyncMock(return_value={"data": [], "next_cursor": 0})
    return client


@pytest.fixture
def mock_orderbook():
    """Create a mock OrderBookManager."""
    ob = MagicMock()
    ob.refresh_from_rest = AsyncMock()
    snapshot = MagicMock()
    snapshot.spread_bps = 200.0
    snapshot.mid_price = 0.50
    ob.get_snapshot = MagicMock(return_value=snapshot)
    return ob


@pytest.fixture
def scanner_config():
    """Config with scanner-specific settings."""
    return {
        "risk": {
            "max_position_pct": 0.05,
            "daily_loss_cap_pct": 0.10,
            "halt_total_loss_pct": 0.40,
            "min_profit_threshold_usd": 0.30,
            "max_correlated_exposure_pct": 0.15,
            "time_of_day": {"enabled": False},
        },
        "strategies": {
            "market_making": {
                "enabled": True,
                "min_spread_bps": 100,
                "max_spread_bps": 400,
                "scanner_min_daily_volume_usd": 5000,
                "scanner_min_days_to_resolution": 3,
                "scanner_top_n": 5,
                "scanner_interval_sec": 60,
                "scanner_weights": DEFAULT_WEIGHTS,
                "target_categories": ["geopolitics", "finance", "politics"],
            }
        },
        "taker_fees": {
            "crypto": 0.018,
            "sports": 0.0075,
            "finance": 0.01,
            "politics": 0.01,
            "economics": 0.015,
            "geopolitics": 0.0,
        },
    }


@pytest.fixture
def scanner(mock_client, mock_orderbook, scanner_config):
    """Create a MarketScanner instance."""
    return MarketScanner(mock_client, mock_orderbook, scanner_config)


# Map category to representative tags for the tag-based inference
_CATEGORY_TAGS = {
    "finance": ["Finance", "economy", "All"],
    "politics": ["Politics", "election", "All"],
    "geopolitics": ["geopolitics", "war", "conflict", "All"],
    "crypto": ["Crypto", "bitcoin", "blockchain", "All"],
    "sports": ["Sports", "NBA", "NFL", "All"],
    "economics": ["economics", "employment", "trade", "All"],
}


def make_market_raw(
    condition_id="market-1",
    token_id="token-1",
    daily_volume=50000,
    category="finance",
    days_to_resolution=30,
    active=True,
    closed=False,
    accepting_orders=True,
    enable_order_book=True,
    end_date_iso="",
) -> dict:
    """Helper to create a raw market dict matching real CLOB API shape."""
    from datetime import datetime, timezone, timedelta
    if not end_date_iso and days_to_resolution:
        future = datetime.now(timezone.utc) + timedelta(days=days_to_resolution)
        end_date_iso = future.isoformat()

    return {
        "condition_id": condition_id,
        "id": condition_id,
        "tokens": [
            {"outcome": "YES", "token_id": token_id},
            {"outcome": "NO", "token_id": f"{token_id}-no"},
        ],
        "volume": daily_volume * 10,
        "volume_24hr": daily_volume,
        "tags": _CATEGORY_TAGS.get(category, ["All"]),
        "market_slug": f"{category}-event-{condition_id}",
        "question": f"Will event {condition_id} happen?",
        "active": active,
        "closed": closed,
        "accepting_orders": accepting_orders,
        "enable_order_book": enable_order_book,
        "end_date_iso": end_date_iso,
    }


# ── Market parsing tests ──────────────────────────────────────────────

class TestMarketParsing:
    """Tests for parsing raw API market data into MarketInfo."""

    def test_parse_valid_market(self, scanner):
        raw = make_market_raw(condition_id="m1", token_id="t1", category="finance")
        info = scanner._parse_market(raw)

        assert info is not None
        assert info.market_id == "m1"
        assert info.token_id == "t1"
        assert info.category == "finance"
        assert info.daily_volume_usd == 50000
        assert info.active is True
        assert info.closed is False

    def test_parse_market_no_id_returns_none(self, scanner):
        raw = {"tokens": []}
        info = scanner._parse_market(raw)
        assert info is None

    def test_parse_market_closed(self, scanner):
        raw = make_market_raw(closed=True)
        info = scanner._parse_market(raw)
        assert info is not None
        assert info.closed is True

    def test_parse_market_fallback_token(self, scanner):
        """When no YES token found, uses first token."""
        raw = {
            "condition_id": "m1",
            "tokens": [{"outcome": "NO", "token_id": "t-no"}],
            "category": "politics",
        }
        info = scanner._parse_market(raw)
        assert info is not None
        assert info.token_id == "t-no"

    def test_parse_days_to_resolution(self, scanner):
        """Days to resolution should be computed from end_date_iso."""
        from datetime import datetime, timezone, timedelta
        future = datetime.now(timezone.utc) + timedelta(days=14)
        raw = make_market_raw(end_date_iso=future.isoformat())
        info = scanner._parse_market(raw)
        assert info is not None
        # Should be roughly 14 days (allow 1-day tolerance)
        assert 12 <= info.days_to_resolution <= 15

    def test_parse_empty_end_date_defaults_around_30(self, scanner):
        raw = make_market_raw(end_date_iso="")
        info = scanner._parse_market(raw)
        assert info is not None
        # Empty end_date falls back to ~30 days from now; allow ±2 tolerance
        assert 28 <= info.days_to_resolution <= 32


# ── Scoring tests ─────────────────────────────────────────────────────

class TestScoring:
    """Tests for the composite scoring formula."""

    def test_high_volume_gets_high_volume_score(self, scanner):
        info = MarketInfo(
            market_id="m1", token_id="t1",
            category="finance", daily_volume_usd=1_000_000,
            spread_bps=200, days_to_resolution=30,
        )
        scanner._compute_score(info)
        # A market with $1M daily volume should score decently
        assert info.score > 0

    def test_zero_volume_market_scores_low(self, scanner):
        info = MarketInfo(
            market_id="m1", token_id="t1",
            category="finance", daily_volume_usd=0,
            spread_bps=200, days_to_resolution=30,
        )
        scanner._compute_score(info)
        # Zero volume should still have some score from other factors
        assert info.score >= 0

    def test_geopolitics_category_zero_taker_fee(self, scanner):
        """Geopolitics has 0% taker fee, so rebate yield is 0."""
        info = MarketInfo(
            market_id="m1", token_id="t1",
            category="geopolitics", daily_volume_usd=50000,
            spread_bps=200, days_to_resolution=30,
        )
        scanner._compute_score(info)
        assert info.rebate_yield == 0.0
        # But holding yield and other factors should still contribute
        assert info.score > 0

    def test_finance_category_has_high_rebate_yield(self, scanner):
        """Finance has 50% rebate rate on 1% taker fee = 0.005 yield."""
        info = MarketInfo(
            market_id="m1", token_id="t1",
            category="finance", daily_volume_usd=50000,
            spread_bps=200, days_to_resolution=30,
        )
        scanner._compute_score(info)
        assert info.rebate_yield == pytest.approx(0.01 * 0.50, abs=1e-6)

    def test_near_resolution_market_gets_risk_penalty(self, scanner):
        info_soon = MarketInfo(
            market_id="m1", token_id="t1",
            category="finance", daily_volume_usd=50000,
            spread_bps=200, days_to_resolution=2,
        )
        info_late = MarketInfo(
            market_id="m2", token_id="t2",
            category="finance", daily_volume_usd=50000,
            spread_bps=200, days_to_resolution=60,
        )
        scanner._compute_score(info_soon)
        scanner._compute_score(info_late)
        # Long-dated market should score higher (less resolution risk)
        assert info_late.score > info_soon.score

    def test_holding_yield_requires_14_days(self, scanner):
        info_short = MarketInfo(
            market_id="m1", token_id="t1",
            category="finance", daily_volume_usd=50000,
            days_to_resolution=5,
        )
        info_long = MarketInfo(
            market_id="m2", token_id="t2",
            category="finance", daily_volume_usd=50000,
            days_to_resolution=30,
        )
        scanner._compute_score(info_short)
        scanner._compute_score(info_long)
        # Long-dated should have higher holding yield
        assert info_long.holding_yield >= info_short.holding_yield

    def test_score_is_bounded_0_to_100(self, scanner):
        """Score should always be between 0 and 100."""
        for vol in [0, 100, 50000, 10_000_000]:
            for days in [1, 7, 14, 30, 365]:
                info = MarketInfo(
                    market_id="m", token_id="t",
                    category="finance", daily_volume_usd=vol,
                    spread_bps=200, days_to_resolution=days,
                )
                scanner._compute_score(info)
                assert 0 <= info.score <= 100, f"Score {info.score} out of range for vol={vol}, days={days}"


# ── Eligibility tests ─────────────────────────────────────────────────

class TestEligibility:
    """Tests for market eligibility filtering."""

    def test_eligible_market_passes(self, scanner):
        info = MarketInfo(
            market_id="m1", token_id="t1",
            category="finance", daily_volume_usd=50000,
            spread_bps=200, days_to_resolution=30,
            active=True, closed=False, accepting_orders=True,
        )
        scanner._compute_score(info)
        assert scanner._is_eligible(info) is True

    def test_closed_market_rejected(self, scanner):
        """Market with closed=True and accepting_orders=False is rejected."""
        info = MarketInfo(
            market_id="m1", token_id="t1",
            category="finance", daily_volume_usd=50000,
            spread_bps=200, days_to_resolution=30,
            active=True, closed=True, accepting_orders=False,
        )
        scanner._compute_score(info)
        assert scanner._is_eligible(info) is False

    def test_inactive_market_rejected(self, scanner):
        """Market with accepting_orders=False is rejected."""
        info = MarketInfo(
            market_id="m1", token_id="t1",
            category="finance", daily_volume_usd=50000,
            spread_bps=200, days_to_resolution=30,
            active=False, closed=False, accepting_orders=False,
        )
        scanner._compute_score(info)
        assert scanner._is_eligible(info) is False

    def test_wrong_category_rejected(self, scanner):
        info = MarketInfo(
            market_id="m1", token_id="t1",
            category="sports", daily_volume_usd=50000,
            spread_bps=200, days_to_resolution=30,
            active=True, closed=False, accepting_orders=True,
        )
        scanner._compute_score(info)
        assert scanner._is_eligible(info) is False

    def test_low_volume_rejected(self, scanner):
        info = MarketInfo(
            market_id="m1", token_id="t1",
            category="finance", daily_volume_usd=100,
            spread_bps=200, days_to_resolution=30,
            active=True, closed=False, accepting_orders=True,
        )
        scanner._compute_score(info)
        assert scanner._is_eligible(info) is False

    def test_near_resolution_rejected(self, scanner):
        info = MarketInfo(
            market_id="m1", token_id="t1",
            category="finance", daily_volume_usd=50000,
            spread_bps=200, days_to_resolution=1,
            active=True, closed=False, accepting_orders=True,
        )
        scanner._compute_score(info)
        assert scanner._is_eligible(info) is False

    def test_narrow_spread_rejected(self, scanner):
        """Spreads below min_spread_bps should be rejected."""
        info = MarketInfo(
            market_id="m1", token_id="t1",
            category="finance", daily_volume_usd=50000,
            spread_bps=50, days_to_resolution=30,
            active=True, closed=False, accepting_orders=True,
        )
        scanner._compute_score(info)
        assert scanner._is_eligible(info) is False

    def test_wide_spread_rejected(self, scanner):
        """Spreads above max_spread_bps should be rejected."""
        info = MarketInfo(
            market_id="m1", token_id="t1",
            category="finance", daily_volume_usd=50000,
            spread_bps=600, days_to_resolution=30,
            active=True, closed=False, accepting_orders=True,
        )
        scanner._compute_score(info)
        assert scanner._is_eligible(info) is False

    def test_zero_spread_market_passes(self, scanner):
        """Markets with 0 spread_bps (not yet fetched) should pass
        the spread check since we can't evaluate them yet."""
        info = MarketInfo(
            market_id="m1", token_id="t1",
            category="finance", daily_volume_usd=50000,
            spread_bps=0, days_to_resolution=30,
            active=True, closed=False, accepting_orders=True,
        )
        scanner._compute_score(info)
        # Zero spread = book not fetched yet, don't reject
        assert scanner._is_eligible(info) is True


# ── Scan integration tests ────────────────────────────────────────────

class TestScanning:
    """Tests for the full scan flow."""

    @pytest.mark.asyncio
    async def test_scan_returns_top_markets(self, scanner, mock_client):
        """Scan should return top-N eligible markets."""
        markets = [
            make_market_raw(condition_id=f"m{i}", token_id=f"t{i}", category="finance", daily_volume=50000 * (i + 1))
            for i in range(10)
        ]
        mock_client.get_markets = AsyncMock(return_value={
            "data": markets,
            "next_cursor": 0,
        })

        result = await scanner.scan(force=True)

        assert result.total_markets == 10
        assert result.eligible_markets > 0
        assert len(result.top_markets) <= scanner.top_n

    @pytest.mark.asyncio
    async def test_scan_caches_result(self, scanner, mock_client):
        """Second scan without force should use cache."""
        mock_client.get_markets = AsyncMock(return_value={
            "data": [make_market_raw()],
            "next_cursor": 0,
        })

        result1 = await scanner.scan(force=True)
        result2 = await scanner.scan(force=False)

        # Should have called API only once (for force=True)
        assert mock_client.get_markets.call_count == 1
        assert result2.total_markets == result1.total_markets

    @pytest.mark.asyncio
    async def test_scan_handles_api_error(self, scanner, mock_client):
        """Scan should gracefully handle API errors."""
        mock_client.get_markets = AsyncMock(side_effect=Exception("API down"))

        result = await scanner.scan(force=True)

        assert result.errors == 1
        assert result.total_markets == 0

    @pytest.mark.asyncio
    async def test_scan_pagination(self, scanner, mock_client):
        """Scan should paginate through multiple pages."""
        page1 = [make_market_raw(condition_id=f"m{i}") for i in range(5)]
        page2 = [make_market_raw(condition_id=f"m{i+5}") for i in range(3)]

        call_count = 0
        async def get_markets_paginated(next_cursor=0):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"data": page1, "next_cursor": 1}
            else:
                return {"data": page2, "next_cursor": 0}

        mock_client.get_markets = get_markets_paginated

        result = await scanner.scan(force=True)

        assert result.total_markets == 8
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_get_eligible_markets(self, scanner, mock_client):
        """get_eligible_markets should return sorted list."""
        mock_client.get_markets = AsyncMock(return_value={
            "data": [
                make_market_raw(condition_id="m1", category="finance", daily_volume=100000),
                make_market_raw(condition_id="m2", category="geopolitics", daily_volume=50000),
                make_market_raw(condition_id="m3", category="sports", daily_volume=200000),
            ],
            "next_cursor": 0,
        })

        eligible = await scanner.get_eligible_markets()

        # sports category should be filtered out
        assert all(m.category != "sports" for m in eligible)
        # Should be sorted by score descending
        scores = [m.score for m in eligible]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_refresh_market_book(self, scanner, mock_orderbook):
        """refresh_market_book should update market info from book snapshot."""
        scanner._markets["m1"] = MarketInfo(
            market_id="m1", token_id="t1", category="finance",
        )

        await scanner.refresh_market_book("m1")

        mock_orderbook.refresh_from_rest.assert_called_once()

    @pytest.mark.asyncio
    async def test_refresh_market_book_unknown_market(self, scanner):
        """refresh_market_book on unknown market should be a no-op."""
        await scanner.refresh_market_book("unknown")  # Should not raise


# ── ScanResult tests ──────────────────────────────────────────────────

class TestScanResult:
    """Tests for ScanResult dataclass."""

    def test_default_values(self):
        result = ScanResult()
        assert result.timestamp == 0.0
        assert result.total_markets == 0
        assert result.eligible_markets == 0
        assert result.top_markets == []
        assert result.errors == 0

    def test_with_values(self):
        markets = [MarketInfo(market_id="m1", token_id="t1")]
        result = ScanResult(
            timestamp=1.0,
            total_markets=10,
            eligible_markets=3,
            top_markets=markets,
            errors=0,
        )
        assert result.total_markets == 10
        assert len(result.top_markets) == 1


# ── MarketInfo tests ──────────────────────────────────────────────────

class TestMarketInfo:
    """Tests for MarketInfo dataclass."""

    def test_default_values(self):
        info = MarketInfo(market_id="m1", token_id="t1")
        assert info.category == "politics"
        assert info.active is True
        assert info.closed is False
        assert info.score == 0.0

    def test_score_mutable(self):
        info = MarketInfo(market_id="m1", token_id="t1")
        info.score = 75.0
        assert info.score == 75.0
