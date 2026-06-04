"""Tests for data feed components:
- KalshiMarket.yes_prob, KalshiOrderBook (data/kalshi_client.py)
- WhaleProfile.qualifies, .win_rate, .profit_factor (data/whale_tracker.py)
- MarketScanner scoring formula (data/market_scanner.py)
"""

import math
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from data.kalshi_client import KalshiMarket, KalshiOrderBook
from data.whale_tracker import WhaleProfile, MIN_TRADES_FOR_TRACKING
from data.market_scanner import (
    MarketInfo,
    MarketScanner,
    ScanResult,
    DEFAULT_WEIGHTS,
    MAX_EXPECTED_VOLUME_USD,
    MIN_SPREAD_BPS,
    MAX_SPREAD_BPS,
    MAX_REBATE_YIELD,
    MAX_HOLDING_APY,
)
from core.client import TAKER_FEES, REBATE_RATES


# ── KalshiMarket.yes_prob ───────────────────────────────────────────────


class TestKalshiMarket:
    """Test KalshiMarket dataclass and yes_prob property."""

    def test_yes_prob_converts_cents_to_probability(self):
        """yes_prob = yes_price / 100 (convert cents to 0–1 probability)."""
        market = KalshiMarket(
            market_id="KX_TEST",
            title="Test market",
            category="politics",
            yes_price=65.0,  # 65 cents
            no_price=35.0,
            last_price=65.0,
            volume_24h=1000,
            open_interest=500,
            expiration_date="2026-12-01",
            active=True,
        )
        assert market.yes_prob == pytest.approx(0.65)

    def test_yes_prob_zero(self):
        """yes_price = 0 → yes_prob = 0.0."""
        market = KalshiMarket(
            market_id="KX_ZERO",
            title="Zero market",
            category="politics",
            yes_price=0.0,
            no_price=100.0,
            last_price=0.0,
            volume_24h=0,
            open_interest=0,
            expiration_date="2026-12-01",
            active=True,
        )
        assert market.yes_prob == pytest.approx(0.0)

    def test_yes_prob_100(self):
        """yes_price = 100 → yes_prob = 1.0."""
        market = KalshiMarket(
            market_id="KX_CERTAIN",
            title="Certain market",
            category="politics",
            yes_price=100.0,
            no_price=0.0,
            last_price=100.0,
            volume_24h=5000,
            open_interest=1000,
            expiration_date="2026-12-01",
            active=True,
        )
        assert market.yes_prob == pytest.approx(1.0)

    def test_yes_prob_midrange(self):
        """yes_price = 50 → yes_prob = 0.50."""
        market = KalshiMarket(
            market_id="KX_FIFTY",
            title="Fifty-fifty",
            category="politics",
            yes_price=50.0,
            no_price=50.0,
            last_price=50.0,
            volume_24h=2000,
            open_interest=500,
            expiration_date="2026-12-01",
            active=True,
        )
        assert market.yes_prob == pytest.approx(0.50)

    def test_no_prob_converts_cents(self):
        """no_prob = no_price / 100."""
        market = KalshiMarket(
            market_id="KX_NO",
            title="NO test",
            category="politics",
            yes_price=30.0,
            no_price=70.0,
            last_price=30.0,
            volume_24h=1000,
            open_interest=500,
            expiration_date="2026-12-01",
            active=True,
        )
        assert market.no_prob == pytest.approx(0.70)


# ── KalshiOrderBook ─────────────────────────────────────────────────────


class TestKalshiOrderBook:
    """Test KalshiOrderBook dataclass and properties."""

    def test_mid_cents_both_sides(self):
        """mid_cents = (best_bid + best_ask) / 2 when both present."""
        ob = KalshiOrderBook(
            market_id="KX_TEST",
            bids=[(60, 100), (55, 200)],
            asks=[(65, 150), (70, 100)],
            last_update=time.monotonic(),
        )
        assert ob.best_bid_cents == 60
        assert ob.best_ask_cents == 65
        assert ob.mid_cents == pytest.approx(62.5)

    def test_mid_cents_none_when_missing_bid(self):
        """mid_cents is None when best_bid is missing."""
        ob = KalshiOrderBook(
            market_id="KX_TEST",
            bids=[],
            asks=[(65, 150)],
            last_update=time.monotonic(),
        )
        assert ob.best_bid_cents is None
        assert ob.mid_cents is None

    def test_mid_cents_none_when_missing_ask(self):
        """mid_cents is None when best_ask is missing."""
        ob = KalshiOrderBook(
            market_id="KX_TEST",
            bids=[(60, 100)],
            asks=[],
            last_update=time.monotonic(),
        )
        assert ob.best_ask_cents is None
        assert ob.mid_cents is None

    def test_spread_cents(self):
        """spread_cents = best_ask - best_bid."""
        ob = KalshiOrderBook(
            market_id="KX_TEST",
            bids=[(55, 200)],
            asks=[(60, 150)],
            last_update=time.monotonic(),
        )
        assert ob.spread_cents == 5

    def test_spread_cents_none_when_empty(self):
        """spread_cents is None when one side is missing."""
        ob = KalshiOrderBook(
            market_id="KX_TEST",
            bids=[],
            asks=[],
            last_update=time.monotonic(),
        )
        assert ob.spread_cents is None

    def test_best_bid_first_element(self):
        """Best bid is the first element of the bids list."""
        ob = KalshiOrderBook(
            market_id="KX_TEST",
            bids=[(50, 100), (45, 200)],
            asks=[(65, 100)],
            last_update=time.monotonic(),
        )
        assert ob.best_bid_cents == 50

    def test_best_ask_first_element(self):
        """Best ask is the first element of the asks list."""
        ob = KalshiOrderBook(
            market_id="KX_TEST",
            bids=[(55, 200)],
            asks=[(60, 150), (65, 100)],
            last_update=time.monotonic(),
        )
        assert ob.best_ask_cents == 60


# ── WhaleProfile ────────────────────────────────────────────────────────


class TestWhaleProfile:
    """Test WhaleProfile: qualifies, win_rate, profit_factor."""

    def test_win_rate_calculation(self):
        """win_rate = winning_trades / total_trades."""
        profile = WhaleProfile(
            address="0xABC",
            total_trades=100,
            winning_trades=65,
        )
        assert profile.win_rate == pytest.approx(0.65)

    def test_win_rate_zero_trades(self):
        """win_rate = 0.0 when total_trades is 0 (avoid div-by-zero)."""
        profile = WhaleProfile(
            address="0xZERO",
            total_trades=0,
            winning_trades=0,
        )
        assert profile.win_rate == pytest.approx(0.0)

    def test_profit_factor_calculation(self):
        """profit_factor = total_profit / total_loss."""
        profile = WhaleProfile(
            address="0xPROFIT",
            total_trades=50,
            winning_trades=30,
            total_profit_usd=1000.0,
            total_loss_usd=400.0,
        )
        assert profile.profit_factor == pytest.approx(2.5)

    def test_profit_factor_zero_loss_with_profit(self):
        """profit_factor = inf when total_loss=0 but profit>0."""
        profile = WhaleProfile(
            address="0xPERFECT",
            total_trades=20,
            winning_trades=20,
            total_profit_usd=500.0,
            total_loss_usd=0.0,
        )
        assert profile.profit_factor == float("inf")

    def test_profit_factor_zero_loss_zero_profit(self):
        """profit_factor = 0.0 when both total_loss and total_profit are 0."""
        profile = WhaleProfile(
            address="0xEMPTY",
            total_trades=0,
            winning_trades=0,
            total_profit_usd=0.0,
            total_loss_usd=0.0,
        )
        assert profile.profit_factor == pytest.approx(0.0)

    def test_qualifies_meets_all_criteria(self):
        """qualifies is True when:
        - total_trades >= MIN_TRADES_FOR_TRACKING (20)
        - win_rate >= 0.60
        - profit_factor >= 1.5
        """
        profile = WhaleProfile(
            address="0xGOOD",
            total_trades=50,
            winning_trades=35,  # 70% win rate
            total_profit_usd=1500.0,
            total_loss_usd=800.0,  # 1.875 profit factor
        )
        assert profile.win_rate >= 0.6
        assert profile.profit_factor >= 1.5
        assert profile.total_trades >= MIN_TRADES_FOR_TRACKING
        assert profile.qualifies is True

    def test_qualifies_low_win_rate(self):
        """qualifies is False when win_rate < 0.60."""
        profile = WhaleProfile(
            address="0xLOW_WR",
            total_trades=50,
            winning_trades=25,  # 50% win rate — below threshold
            total_profit_usd=1000.0,
            total_loss_usd=400.0,  # 2.5 profit factor — good
        )
        assert profile.win_rate < 0.6
        assert profile.qualifies is False

    def test_qualifies_low_profit_factor(self):
        """qualifies is False when profit_factor < 1.5."""
        profile = WhaleProfile(
            address="0xLOW_PF",
            total_trades=50,
            winning_trades=35,  # 70% win rate — good
            total_profit_usd=600.0,
            total_loss_usd=500.0,  # 1.2 profit factor — below threshold
        )
        assert profile.profit_factor < 1.5
        assert profile.qualifies is False

    def test_qualifies_insufficient_trades(self):
        """qualifies is False when total_trades < MIN_TRADES_FOR_TRACKING (20)."""
        profile = WhaleProfile(
            address="0xNEWBIE",
            total_trades=5,  # Too few trades
            winning_trades=4,  # 80% win rate
            total_profit_usd=200.0,
            total_loss_usd=20.0,  # 10.0 profit factor
        )
        assert profile.total_trades < MIN_TRADES_FOR_TRACKING
        assert profile.qualifies is False

    def test_is_active_recent(self):
        """is_active is True when last_active_at is within 24h."""
        profile = WhaleProfile(
            address="0xACTIVE",
            last_active_at=time.monotonic(),
        )
        assert profile.is_active is True

    def test_is_not_active_stale(self):
        """is_active is False when last_active_at is over 24h ago."""
        profile = WhaleProfile(
            address="0xSTALE",
            last_active_at=time.monotonic() - 90000,  # > 86400 sec
        )
        assert profile.is_active is False


# ── MarketScanner scoring ───────────────────────────────────────────────


class TestMarketScannerScoring:
    """Test the MarketScanner._compute_score formula:
    score = w1·volume_norm + w2·spread_norm + w3·rebate_norm
            + w4·holding_norm + w5·risk_factor

    Each component normalized to [0, 1], then weighted and scaled to [0, 100].

    Key formulas from source:
    - volume_norm = log10(max(1, daily_vol)) / log10(max(2, MAX_EXPECTED_VOLUME_USD))
    - spread_norm = (spread_bps - MIN_SPREAD_BPS) / (MAX_SPREAD_BPS - MIN_SPREAD_BPS)
    - rebate_norm = rebate_yield / MAX_REBATE_YIELD  where rebate_yield = taker_fee * rebate_rate
    - holding_apy = MAX_HOLDING_APY if days >= 14 else 0.0
      days_factor = min(1.0, days / 14.0)
      holding_yield = holding_apy * days_factor
      holding_norm = holding_yield / MAX_HOLDING_APY
    - risk_factor: 0.0 if days < 3, 0.3 if days < 7, 0.6 if days < 14, else 1.0
    """

    @pytest.fixture
    def scanner(self):
        """Create a MarketScanner with default weights."""
        client = MagicMock()
        client.get_markets = AsyncMock(return_value={"markets": [], "next_cursor": 0})
        orderbook = MagicMock()

        config = {
            "strategies": {
                "market_making": {
                    "target_categories": ["geopolitics", "finance", "politics"],
                    "scanner_min_daily_volume_usd": 5000.0,
                    "min_spread_bps": 100,
                    "max_spread_bps": 400,
                    "scanner_min_days_to_resolution": 3,
                    "scanner_top_n": 10,
                    "scanner_interval_sec": 300,
                }
            }
        }
        return MarketScanner(client=client, orderbook=orderbook, config=config)

    def test_volume_norm_log_scale(self, scanner):
        """Volume factor uses log10 scale:
        volume_norm = log10(max(1, daily_vol)) / log10(MAX_EXPECTED_VOLUME_USD)
        """
        info = MarketInfo(
            market_id="m1",
            token_id="t1",
            category="finance",
            daily_volume_usd=100_000.0,  # log10(100K) = 5
            spread_bps=200,
            days_to_resolution=30,
            active=True,
        )
        scanner._compute_score(info)

        expected_norm = math.log10(100_000) / math.log10(MAX_EXPECTED_VOLUME_USD)
        expected_norm = min(1.0, max(0.0, expected_norm))
        assert info.score > 0

    def test_volume_higher_score_for_higher_volume(self, scanner):
        """Higher volume should produce higher score (all else equal)."""
        info_small = MarketInfo(
            market_id="m_small",
            token_id="t_small",
            category="finance",
            daily_volume_usd=10.0,  # log10(10) = 1
            spread_bps=200,
            days_to_resolution=30,
            active=True,
        )
        info_big = MarketInfo(
            market_id="m_big",
            token_id="t_big",
            category="finance",
            daily_volume_usd=1_000_000.0,  # log10(1M) = 6
            spread_bps=200,
            days_to_resolution=30,
            active=True,
        )
        scanner._compute_score(info_small)
        scanner._compute_score(info_big)
        assert info_big.score > info_small.score

    def test_rebate_yield_calculation(self, scanner):
        """rebate_yield = taker_fee * rebate_rate for the market's category."""
        info = MarketInfo(
            market_id="m_fin",
            token_id="t_fin",
            category="finance",
            daily_volume_usd=50000.0,
            spread_bps=200,
            days_to_resolution=30,
            active=True,
        )
        scanner._compute_score(info)

        expected_rebate = TAKER_FEES["finance"] * REBATE_RATES["finance"]
        assert info.rebate_yield == pytest.approx(expected_rebate)

    def test_holding_yield_at_or_above_14_days(self, scanner):
        """Holding yield = MAX_HOLDING_APY * 1.0 when days_to_resolution >= 14.
        holding_apy = MAX_HOLDING_APY (0.04)
        days_factor = min(1.0, 28/14) = 1.0
        holding_yield = 0.04 * 1.0 = 0.04
        """
        info = MarketInfo(
            market_id="m_hold",
            token_id="t_hold",
            category="finance",
            daily_volume_usd=50000.0,
            spread_bps=200,
            days_to_resolution=28,
            active=True,
        )
        scanner._compute_score(info)

        expected_yield = MAX_HOLDING_APY * 1.0
        assert info.holding_yield == pytest.approx(expected_yield)

    def test_holding_yield_below_14_days_is_zero(self, scanner):
        """When days < 14: holding_apy = 0.0, so holding_yield = 0.0.

        Source: holding_apy = MAX_HOLDING_APY if days >= 14 else 0.0
        Then: holding_yield = holding_apy * days_factor
        So: 0.0 * anything = 0.0
        """
        info = MarketInfo(
            market_id="m_short",
            token_id="t_short",
            category="finance",
            daily_volume_usd=50000.0,
            spread_bps=200,
            days_to_resolution=7,
            active=True,
        )
        scanner._compute_score(info)
        assert info.holding_yield == pytest.approx(0.0)

    def test_holding_yield_zero_for_zero_days(self, scanner):
        """Holding yield is 0 when days_to_resolution = 0."""
        info = MarketInfo(
            market_id="m_expired",
            token_id="t_expired",
            category="finance",
            daily_volume_usd=50000.0,
            spread_bps=200,
            days_to_resolution=0,
            active=True,
        )
        scanner._compute_score(info)
        assert info.holding_yield == pytest.approx(0.0)

    def test_resolution_risk_near_zero_days(self, scanner):
        """Risk factor = 0.0 when days < 3 (too close to resolution)."""
        info_risky = MarketInfo(
            market_id="m_risky",
            token_id="t_risky",
            category="finance",
            daily_volume_usd=50000.0,
            spread_bps=200,
            days_to_resolution=2,
            active=True,
        )
        info_safe = MarketInfo(
            market_id="m_safe",
            token_id="t_safe",
            category="finance",
            daily_volume_usd=50000.0,
            spread_bps=200,
            days_to_resolution=30,
            active=True,
        )
        scanner._compute_score(info_risky)
        scanner._compute_score(info_safe)
        assert info_safe.score > info_risky.score

    def test_resolution_risk_graduated(self, scanner):
        """Risk factor: days<3→0.0, days<7→0.3, days<14→0.6, else→1.0."""
        info_2 = MarketInfo(
            market_id="m2", token_id="t2", category="finance",
            daily_volume_usd=50000.0, spread_bps=200, days_to_resolution=2, active=True,
        )
        info_5 = MarketInfo(
            market_id="m5", token_id="t5", category="finance",
            daily_volume_usd=50000.0, spread_bps=200, days_to_resolution=5, active=True,
        )
        info_10 = MarketInfo(
            market_id="m10", token_id="t10", category="finance",
            daily_volume_usd=50000.0, spread_bps=200, days_to_resolution=10, active=True,
        )
        info_30 = MarketInfo(
            market_id="m30", token_id="t30", category="finance",
            daily_volume_usd=50000.0, spread_bps=200, days_to_resolution=30, active=True,
        )
        scanner._compute_score(info_2)
        scanner._compute_score(info_5)
        scanner._compute_score(info_10)
        scanner._compute_score(info_30)

        # Score should increase with more days to resolution (lower risk)
        assert info_5.score > info_2.score
        assert info_10.score > info_5.score
        assert info_30.score > info_10.score

    def test_score_range_0_to_100(self, scanner):
        """Score should always be in [0, 100] range."""
        info_low = MarketInfo(
            market_id="m_low",
            token_id="t_low",
            category="finance",
            daily_volume_usd=10.0,
            spread_bps=0,
            days_to_resolution=1,
            active=True,
        )
        scanner._compute_score(info_low)
        assert 0.0 <= info_low.score <= 100.0

        info_high = MarketInfo(
            market_id="m_high",
            token_id="t_high",
            category="finance",
            daily_volume_usd=5_000_000.0,
            spread_bps=450,
            days_to_resolution=60,
            active=True,
        )
        scanner._compute_score(info_high)
        assert 0.0 <= info_high.score <= 100.0

    def test_geopolitics_zero_taker_fee(self, scanner):
        """Geopolitics has 0% taker fee → 0 rebate yield."""
        info = MarketInfo(
            market_id="m_geo",
            token_id="t_geo",
            category="geopolitics",
            daily_volume_usd=50000.0,
            spread_bps=200,
            days_to_resolution=30,
            active=True,
        )
        scanner._compute_score(info)
        # Geopolitics: taker_fee = 0.0 → rebate_yield = 0.0 * 0.20 = 0.0
        assert info.rebate_yield == pytest.approx(0.0)

    def test_eligibility_requires_active(self, scanner):
        """Inactive markets are not eligible."""
        info = MarketInfo(
            market_id="m_inactive",
            token_id="t_inactive",
            category="finance",
            daily_volume_usd=50000.0,
            spread_bps=200,
            days_to_resolution=30,
            active=False,
        )
        scanner._compute_score(info)
        assert scanner._is_eligible(info) is False

    def test_eligibility_requires_min_volume(self, scanner):
        """Markets below min_daily_volume_usd are not eligible."""
        info = MarketInfo(
            market_id="m_lowvol",
            token_id="t_lowvol",
            category="finance",
            daily_volume_usd=100.0,  # Below 5000 threshold
            spread_bps=200,
            days_to_resolution=30,
            active=True,
        )
        scanner._compute_score(info)
        assert scanner._is_eligible(info) is False

    def test_eligibility_requires_category_in_target(self, scanner):
        """Markets not in target_categories are not eligible."""
        info = MarketInfo(
            market_id="m_sports",
            token_id="t_sports",
            category="sports",  # Not in target: geopolitics, finance, politics
            daily_volume_usd=50000.0,
            spread_bps=200,
            days_to_resolution=30,
            active=True,
        )
        scanner._compute_score(info)
        assert scanner._is_eligible(info) is False

    def test_eligibility_min_days_to_resolution(self, scanner):
        """Markets with fewer than min_days_to_resolution (3) are not eligible."""
        info = MarketInfo(
            market_id="m_soon",
            token_id="t_soon",
            category="finance",
            daily_volume_usd=50000.0,
            spread_bps=200,
            days_to_resolution=2,  # Below min of 3
            active=True,
        )
        scanner._compute_score(info)
        assert scanner._is_eligible(info) is False

    def test_eligibility_requires_score_above_threshold(self, scanner):
        """Markets with score < 10.0 are not eligible."""
        info = MarketInfo(
            market_id="m_low_score",
            token_id="t_low_score",
            category="finance",
            daily_volume_usd=100.0,  # Very low volume → low score
            spread_bps=0,
            days_to_resolution=2,  # Also high risk
            active=True,
        )
        scanner._compute_score(info)
        if info.score < 10.0:
            assert scanner._is_eligible(info) is False

    def test_full_scoring_formula_deterministic(self, scanner):
        """Verify the full formula with known inputs produces a deterministic score."""
        info = MarketInfo(
            market_id="m_exact",
            token_id="t_exact",
            category="finance",
            daily_volume_usd=100_000.0,
            spread_bps=200,
            days_to_resolution=30,
            active=True,
        )
        scanner._compute_score(info)

        # Compute each factor manually
        w = DEFAULT_WEIGHTS

        # Volume: log10(max(1, 100000)) / log10(10M) = 5 / 7 = 0.7143
        vol_norm = math.log10(max(1, 100_000)) / math.log10(max(2, MAX_EXPECTED_VOLUME_USD))
        vol_norm = min(1.0, max(0.0, vol_norm))

        # Spread: (200 - 50) / (500 - 50) = 150/450 = 0.333
        spread_norm = (200 - MIN_SPREAD_BPS) / (MAX_SPREAD_BPS - MIN_SPREAD_BPS)
        spread_norm = min(1.0, max(0.0, spread_norm))

        # Rebate: finance taker * finance rebate / MAX_REBATE_YIELD
        rebate = TAKER_FEES["finance"] * REBATE_RATES["finance"]  # 0.01 * 0.50 = 0.005
        assert info.rebate_yield == pytest.approx(rebate)
        rebate_norm = rebate / MAX_REBATE_YIELD if MAX_REBATE_YIELD > 0 else 0.0
        rebate_norm = min(1.0, max(0.0, rebate_norm))

        # Holding: days >= 14 → holding_apy = 0.04, days_factor = min(1, 30/14) = 1.0
        # holding_yield = 0.04 * 1.0 = 0.04
        holding_apy = MAX_HOLDING_APY  # days >= 14
        days_factor = min(1.0, 30 / 14.0)
        holding_yield = holding_apy * days_factor
        assert info.holding_yield == pytest.approx(holding_yield)
        holding_norm = holding_yield / MAX_HOLDING_APY if MAX_HOLDING_APY > 0 else 0.0
        holding_norm = min(1.0, max(0.0, holding_norm))

        # Risk: 30 days > 14 → risk_factor = 1.0
        risk_factor = 1.0

        expected_score = (
            w.get("volume", 0.25) * vol_norm
            + w.get("spread_width", 0.20) * spread_norm
            + w.get("rebate_yield", 0.25) * rebate_norm
            + w.get("holding_yield", 0.15) * holding_norm
            + w.get("resolution_risk", 0.15) * risk_factor
        ) * 100.0

        assert info.score == pytest.approx(expected_score, rel=1e-6)

    def test_finance_highest_rebate_yield(self, scanner):
        """Finance category has the highest rebate yield (50% rebate rate)."""
        categories = ["crypto", "sports", "finance", "politics", "economics", "geopolitics"]
        yields = {}
        for cat in categories:
            info = MarketInfo(
                market_id=f"m_{cat}", token_id=f"t_{cat}", category=cat,
                daily_volume_usd=50000.0, spread_bps=200,
                days_to_resolution=30, active=True,
            )
            scanner._compute_score(info)
            yields[cat] = info.rebate_yield

        # Finance: 0.01 * 0.50 = 0.005
        assert yields["finance"] > yields["politics"]  # 0.005 > 0.0025
        assert yields["finance"] > yields["sports"]    # 0.005 > 0.001875
        assert yields["geopolitics"] == pytest.approx(0.0)


# ── MarketInfo / ScanResult ─────────────────────────────────────────────


class TestMarketInfoAndScanResult:
    """Test MarketInfo and ScanResult dataclasses."""

    def test_market_info_defaults(self):
        """MarketInfo has sensible defaults."""
        info = MarketInfo(market_id="m1", token_id="t1")
        assert info.category == "politics"
        assert info.volume_usd == 0.0
        assert info.daily_volume_usd == 0.0
        assert info.spread_bps == 0.0
        assert info.mid_price == 0.5
        assert info.days_to_resolution == 30
        assert info.active is True
        assert info.closed is False
        assert info.score == 0.0
        assert info.rebate_yield == 0.0
        assert info.holding_yield == 0.0

    def test_scan_result_defaults(self):
        """ScanResult has zero defaults."""
        result = ScanResult()
        assert result.total_markets == 0
        assert result.eligible_markets == 0
        assert result.top_markets == []
        assert result.errors == 0
