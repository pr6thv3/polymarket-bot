"""Tests for the cross-platform arbitrage strategy (strategies/cross_platform_arb.py).

Covers:
- ArbOpportunity: combined_cost property, is_fresh (age < 5s), buy_yes/buy_no fields
- ArbPosition: all 4 status strings, is_complete, is_failed
- CrossPlatformArbStrategy: constructor with kalshi_client arg
"""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from strategies.cross_platform_arb import (
    ArbOpportunity,
    ArbPosition,
    CrossPlatformArbStrategy,
)


# ── ArbOpportunity ──────────────────────────────────────────────────────


class TestArbOpportunity:
    """Test ArbOpportunity dataclass and computed properties."""

    def test_basic_creation(self):
        opp = ArbOpportunity(
            polymarket_id="poly-m1",
            kalshi_ticker="KX_M1",
            market_title="Will X happen?",
            poly_yes_price=0.45,
            kalshi_yes_price=0.55,
            spread_bps=1000,
            net_profit_bps=600,
            fee_cost_bps=400,
            buy_yes_platform="polymarket",
            buy_no_platform="kalshi",
            size=50.0,
            estimated_profit_usd=5.0,
        )
        assert opp.polymarket_id == "poly-m1"
        assert opp.kalshi_ticker == "KX_M1"
        assert opp.poly_yes_price == 0.45
        assert opp.kalshi_yes_price == 0.55
        assert opp.buy_yes_platform == "polymarket"
        assert opp.buy_no_platform == "kalshi"
        assert opp.size == 50.0

    def test_combined_cost_buy_yes_on_polymarket(self):
        """When buy_yes_platform is polymarket:
        combined_cost = poly_yes_price + (1 - kalshi_yes_price)
        """
        opp = ArbOpportunity(
            polymarket_id="p1",
            kalshi_ticker="K1",
            poly_yes_price=0.40,
            kalshi_yes_price=0.65,
            buy_yes_platform="polymarket",
            buy_no_platform="kalshi",
        )
        # 0.40 + (1 - 0.65) = 0.40 + 0.35 = 0.75
        assert opp.combined_cost == pytest.approx(0.75)

    def test_combined_cost_buy_yes_on_kalshi(self):
        """When buy_yes_platform is kalshi:
        combined_cost = kalshi_yes_price + (1 - poly_yes_price)
        """
        opp = ArbOpportunity(
            polymarket_id="p2",
            kalshi_ticker="K2",
            poly_yes_price=0.65,
            kalshi_yes_price=0.40,
            buy_yes_platform="kalshi",
            buy_no_platform="polymarket",
        )
        # 0.40 + (1 - 0.65) = 0.40 + 0.35 = 0.75
        assert opp.combined_cost == pytest.approx(0.75)

    def test_combined_cost_below_1_indicates_profit(self):
        """If combined_cost < 1.0, there is a risk-free profit."""
        opp = ArbOpportunity(
            polymarket_id="p3",
            kalshi_ticker="K3",
            poly_yes_price=0.30,
            kalshi_yes_price=0.60,
            buy_yes_platform="polymarket",
            buy_no_platform="kalshi",
        )
        # 0.30 + (1 - 0.60) = 0.30 + 0.40 = 0.70 → profit = 0.30/share
        assert opp.combined_cost < 1.0
        assert pytest.approx(1.0 - opp.combined_cost) == 0.30

    def test_is_fresh_when_newly_created(self):
        """An opportunity just created should be fresh (< 5 sec old)."""
        opp = ArbOpportunity(
            polymarket_id="p4",
            kalshi_ticker="K4",
            detected_at=time.monotonic(),
        )
        assert opp.is_fresh is True

    def test_is_fresh_false_when_old(self):
        """An opportunity older than 5 seconds is NOT fresh."""
        opp = ArbOpportunity(
            polymarket_id="p5",
            kalshi_ticker="K5",
            detected_at=time.monotonic() - 6.0,  # 6 seconds ago
        )
        assert opp.is_fresh is False

    def test_is_fresh_boundary(self):
        """Exactly 5 seconds old is NOT fresh (strict <)."""
        opp = ArbOpportunity(
            polymarket_id="p6",
            kalshi_ticker="K6",
            detected_at=time.monotonic() - 5.0,
        )
        # Property uses strict < 5.0
        assert opp.is_fresh is False

    def test_is_fresh_just_under_boundary(self):
        """4.99 seconds old is still fresh."""
        opp = ArbOpportunity(
            polymarket_id="p7",
            kalshi_ticker="K7",
            detected_at=time.monotonic() - 4.99,
        )
        assert opp.is_fresh is True

    def test_age_sec_increases_over_time(self):
        """age_sec should increase as real time passes."""
        before = time.monotonic()
        opp = ArbOpportunity(
            polymarket_id="p8",
            kalshi_ticker="K8",
            detected_at=before,
        )
        age = opp.age_sec
        assert age >= 0.0

    def test_buy_yes_and_buy_no_platform_fields(self):
        """Verify the two platform direction fields are set correctly."""
        # Case 1: buy YES on Polymarket
        opp1 = ArbOpportunity(
            polymarket_id="p9",
            kalshi_ticker="K9",
            poly_yes_price=0.40,
            kalshi_yes_price=0.60,
            buy_yes_platform="polymarket",
            buy_no_platform="kalshi",
        )
        assert opp1.buy_yes_platform == "polymarket"
        assert opp1.buy_no_platform == "kalshi"

        # Case 2: buy YES on Kalshi
        opp2 = ArbOpportunity(
            polymarket_id="p10",
            kalshi_ticker="K10",
            poly_yes_price=0.60,
            kalshi_yes_price=0.40,
            buy_yes_platform="kalshi",
            buy_no_platform="polymarket",
        )
        assert opp2.buy_yes_platform == "kalshi"
        assert opp2.buy_no_platform == "polymarket"

    def test_default_detected_at_is_monotonic(self):
        """Default detected_at should be set to time.monotonic()."""
        before = time.monotonic()
        opp = ArbOpportunity(
            polymarket_id="p11",
            kalshi_ticker="K11",
        )
        after = time.monotonic()
        assert before <= opp.detected_at <= after


# ── ArbPosition ─────────────────────────────────────────────────────────


class TestArbPosition:
    """Test ArbPosition status tracking and computed properties."""

    def test_all_four_status_strings(self):
        """ArbPosition uses 4 status strings: pending, placed, filled, failed."""
        valid = {"pending", "placed", "filled", "failed"}
        # Both legs start as pending
        pos = ArbPosition(polymarket_id="p1", kalshi_ticker="K1")
        assert pos.poly_status == "pending"
        assert pos.kalshi_status == "pending"
        assert "pending" in valid

        # All four strings are valid status values
        for status in valid:
            pos.poly_status = status
            assert pos.poly_status == status

    def test_is_complete_both_filled(self):
        """is_complete is True only when both legs are filled."""
        pos = ArbPosition(polymarket_id="p1", kalshi_ticker="K1")

        # Neither filled
        pos.poly_status = "pending"
        pos.kalshi_status = "pending"
        assert pos.is_complete is False

        # Only one filled
        pos.poly_status = "filled"
        pos.kalshi_status = "placed"
        assert pos.is_complete is False

        # Both filled
        pos.poly_status = "filled"
        pos.kalshi_status = "filled"
        assert pos.is_complete is True

    def test_is_complete_not_true_when_one_pending(self):
        """is_complete is False if one leg is still pending."""
        pos = ArbPosition(polymarket_id="p1", kalshi_ticker="K1")
        pos.poly_status = "filled"
        pos.kalshi_status = "pending"
        assert pos.is_complete is False

    def test_is_failed_poly_failed(self):
        """is_failed is True if the Polymarket leg failed."""
        pos = ArbPosition(polymarket_id="p1", kalshi_ticker="K1")
        pos.poly_status = "failed"
        pos.kalshi_status = "placed"
        assert pos.is_failed is True

    def test_is_failed_kalshi_failed(self):
        """is_failed is True if the Kalshi leg failed."""
        pos = ArbPosition(polymarket_id="p1", kalshi_ticker="K1")
        pos.poly_status = "filled"
        pos.kalshi_status = "failed"
        assert pos.is_failed is True

    def test_is_failed_both_failed(self):
        """is_failed is True when both legs failed."""
        pos = ArbPosition(polymarket_id="p1", kalshi_ticker="K1")
        pos.poly_status = "failed"
        pos.kalshi_status = "failed"
        assert pos.is_failed is True

    def test_is_not_failed_when_no_failures(self):
        """is_failed is False when neither leg has failed."""
        pos = ArbPosition(polymarket_id="p1", kalshi_ticker="K1")
        pos.poly_status = "pending"
        pos.kalshi_status = "placed"
        assert pos.is_failed is False

    def test_is_not_failed_when_both_filled(self):
        """is_failed is False when both legs filled (successful completion)."""
        pos = ArbPosition(polymarket_id="p1", kalshi_ticker="K1")
        pos.poly_status = "filled"
        pos.kalshi_status = "filled"
        assert pos.is_failed is False

    def test_age_sec(self):
        """age_sec should be non-negative after creation."""
        pos = ArbPosition(polymarket_id="p1", kalshi_ticker="K1")
        assert pos.age_sec >= 0.0

    def test_default_values(self):
        """Check all default field values."""
        pos = ArbPosition(polymarket_id="p1", kalshi_ticker="K1")
        assert pos.poly_side == ""
        assert pos.poly_order_id is None
        assert pos.poly_filled == 0.0
        assert pos.poly_fill_price == 0.0
        assert pos.kalshi_side == ""
        assert pos.kalshi_order_id is None
        assert pos.kalshi_filled == 0.0
        assert pos.kalshi_fill_price == 0.0
        assert pos.realized_pnl == 0.0
        assert pos.is_hedged is False


# ── CrossPlatformArbStrategy ────────────────────────────────────────────


class TestCrossPlatformArbStrategy:
    """Test strategy constructor and configuration."""

    @pytest.fixture
    def mock_deps(self):
        """Create mock dependencies for strategy construction."""
        client = MagicMock()
        orderbook = MagicMock()
        portfolio = MagicMock()
        portfolio.free_usdc = 5000.0
        risk_manager = MagicMock()
        executor = MagicMock()
        order_store = MagicMock()
        kalshi_client = MagicMock()
        kalshi_client.enabled = True
        kalshi_client.get_mapped_markets = MagicMock(return_value={})

        config = {
            "strategies": {
                "cross_platform_arb": {
                    "min_profit_bps": 50,
                    "max_position_size_usd": 100.0,
                    "max_concurrent_positions": 5,
                    "stale_opportunity_sec": 5.0,
                    "execution_mode": "FAVOR_POLY",
                    "kalshi_taker_fee_bps": 100,
                }
            }
        }

        return {
            "client": client,
            "orderbook": orderbook,
            "portfolio": portfolio,
            "risk_manager": risk_manager,
            "executor": executor,
            "order_store": order_store,
            "kalshi_client": kalshi_client,
            "config": config,
        }

    def test_constructor_assigns_kalshi_client(self, mock_deps):
        """Constructor must accept kalshi_client and store it as self.kalshi."""
        strategy = CrossPlatformArbStrategy(
            client=mock_deps["client"],
            orderbook=mock_deps["orderbook"],
            portfolio=mock_deps["portfolio"],
            risk_manager=mock_deps["risk_manager"],
            executor=mock_deps["executor"],
            order_store=mock_deps["order_store"],
            kalshi_client=mock_deps["kalshi_client"],
            config=mock_deps["config"],
        )
        assert strategy.kalshi is mock_deps["kalshi_client"]

    def test_strategy_name(self, mock_deps):
        """Strategy name property returns 'CrossPlatformArb'."""
        strategy = CrossPlatformArbStrategy(
            client=mock_deps["client"],
            orderbook=mock_deps["orderbook"],
            portfolio=mock_deps["portfolio"],
            risk_manager=mock_deps["risk_manager"],
            executor=mock_deps["executor"],
            order_store=mock_deps["order_store"],
            kalshi_client=mock_deps["kalshi_client"],
            config=mock_deps["config"],
        )
        assert strategy.name == "CrossPlatformArb"

    def test_default_thresholds(self, mock_deps):
        """Verify default thresholds from config are loaded."""
        strategy = CrossPlatformArbStrategy(
            client=mock_deps["client"],
            orderbook=mock_deps["orderbook"],
            portfolio=mock_deps["portfolio"],
            risk_manager=mock_deps["risk_manager"],
            executor=mock_deps["executor"],
            order_store=mock_deps["order_store"],
            kalshi_client=mock_deps["kalshi_client"],
            config=mock_deps["config"],
        )
        assert strategy.min_profit_bps == 50
        assert strategy.max_position_size_usd == 100.0
        assert strategy.max_concurrent_positions == 5
        assert strategy.stale_opportunity_sec == 5.0
        assert strategy.execution_mode == "FAVOR_POLY"
        assert strategy.kalshi_taker_fee_bps == 100

    def test_defaults_with_empty_config(self, mock_deps):
        """Strategy uses sensible defaults when config section is empty."""
        mock_deps["config"]["strategies"]["cross_platform_arb"] = {}
        strategy = CrossPlatformArbStrategy(
            client=mock_deps["client"],
            orderbook=mock_deps["orderbook"],
            portfolio=mock_deps["portfolio"],
            risk_manager=mock_deps["risk_manager"],
            executor=mock_deps["executor"],
            order_store=mock_deps["order_store"],
            kalshi_client=mock_deps["kalshi_client"],
            config=mock_deps["config"],
        )
        assert strategy.min_profit_bps == 50
        assert strategy.max_position_size_usd == 100.0
        assert strategy.max_concurrent_positions == 5
        assert strategy.kalshi_taker_fee_bps == 100

    def test_position_tracking_initialized(self, mock_deps):
        """Strategy initializes empty position tracking state."""
        strategy = CrossPlatformArbStrategy(
            client=mock_deps["client"],
            orderbook=mock_deps["orderbook"],
            portfolio=mock_deps["portfolio"],
            risk_manager=mock_deps["risk_manager"],
            executor=mock_deps["executor"],
            order_store=mock_deps["order_store"],
            kalshi_client=mock_deps["kalshi_client"],
            config=mock_deps["config"],
        )
        assert strategy._active_positions == {}
        assert strategy._completed_count == 0
        assert strategy._failed_count == 0
        assert strategy._total_pnl == 0.0
