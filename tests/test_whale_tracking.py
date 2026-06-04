"""Tests for the whale tracking strategy (strategies/whale_tracking.py).

Covers:
- WhalePosition: direction-aware is_stopped_out, is_take_profit, age_sec
- AggregatedSignal + _aggregate_signals(): conflicting enter+exit → skip,
  weighted conviction, multi-whale bonus (3+ and 5+)
- _compute_signal_strength(): conviction × win_rate × √(profit_factor) × recency
- _get_streak_multiplier(): clamped to [0.2, 3.0], win cap at 5, loss cap at 3
- WhaleTrackingStrategy: constructor with whale_tracker arg
"""

import math
import time
from collections import defaultdict
from unittest.mock import MagicMock

import pytest

from strategies.whale_tracking import (
    AggregatedSignal,
    WhalePosition,
    WhaleTrackingStrategy,
)
from data.whale_tracker import WhaleSignal


# ── WhalePosition ───────────────────────────────────────────────────────


class TestWhalePosition:
    """Test WhalePosition direction-aware risk properties."""

    def test_age_sec(self):
        """age_sec is time.monotonic() - opened_at."""
        pos = WhalePosition(
            market_id="m1",
            token_id="t1",
            side="BUY",
            entry_price=0.50,
            size=10.0,
        )
        assert pos.age_sec >= 0.0

    # ── is_stopped_out ──

    def test_is_stopped_out_buy_side_hit(self):
        """BUY position: stopped out when current_price <= stop_loss_price."""
        pos = WhalePosition(
            market_id="m1",
            token_id="t1",
            side="BUY",
            entry_price=0.60,
            size=10.0,
            stop_loss_price=0.50,
            current_price=0.45,
        )
        assert pos.is_stopped_out is True

    def test_is_stopped_out_buy_side_safe(self):
        """BUY position: NOT stopped out when current_price > stop_loss_price."""
        pos = WhalePosition(
            market_id="m1",
            token_id="t1",
            side="BUY",
            entry_price=0.60,
            size=10.0,
            stop_loss_price=0.50,
            current_price=0.55,
        )
        assert pos.is_stopped_out is False

    def test_is_stopped_out_sell_side_hit(self):
        """SELL position: stopped out when current_price >= stop_loss_price."""
        pos = WhalePosition(
            market_id="m1",
            token_id="t1",
            side="SELL",
            entry_price=0.40,
            size=10.0,
            stop_loss_price=0.50,
            current_price=0.55,
        )
        assert pos.is_stopped_out is True

    def test_is_stopped_out_sell_side_safe(self):
        """SELL position: NOT stopped out when current_price < stop_loss_price."""
        pos = WhalePosition(
            market_id="m1",
            token_id="t1",
            side="SELL",
            entry_price=0.40,
            size=10.0,
            stop_loss_price=0.50,
            current_price=0.45,
        )
        assert pos.is_stopped_out is False

    def test_is_stopped_out_zero_stop_loss(self):
        """If stop_loss_price is 0 (unset), is_stopped_out is always False."""
        pos_buy = WhalePosition(
            market_id="m1", token_id="t1", side="BUY",
            entry_price=0.50, size=10.0, stop_loss_price=0.0, current_price=0.01,
        )
        assert pos_buy.is_stopped_out is False

        pos_sell = WhalePosition(
            market_id="m1", token_id="t1", side="SELL",
            entry_price=0.50, size=10.0, stop_loss_price=0.0, current_price=0.99,
        )
        assert pos_sell.is_stopped_out is False

    # ── is_take_profit ──

    def test_is_take_profit_buy_side_hit(self):
        """BUY position: take profit when current_price >= take_profit_price."""
        pos = WhalePosition(
            market_id="m1",
            token_id="t1",
            side="BUY",
            entry_price=0.50,
            size=10.0,
            take_profit_price=0.80,
            current_price=0.85,
        )
        assert pos.is_take_profit is True

    def test_is_take_profit_buy_side_not_hit(self):
        """BUY position: NOT take profit when current_price < take_profit_price."""
        pos = WhalePosition(
            market_id="m1",
            token_id="t1",
            side="BUY",
            entry_price=0.50,
            size=10.0,
            take_profit_price=0.80,
            current_price=0.75,
        )
        assert pos.is_take_profit is False

    def test_is_take_profit_sell_side_hit(self):
        """SELL position: take profit when current_price <= take_profit_price."""
        pos = WhalePosition(
            market_id="m1",
            token_id="t1",
            side="SELL",
            entry_price=0.70,
            size=10.0,
            take_profit_price=0.30,
            current_price=0.25,
        )
        assert pos.is_take_profit is True

    def test_is_take_profit_sell_side_not_hit(self):
        """SELL position: NOT take profit when current_price > take_profit_price."""
        pos = WhalePosition(
            market_id="m1",
            token_id="t1",
            side="SELL",
            entry_price=0.70,
            size=10.0,
            take_profit_price=0.30,
            current_price=0.35,
        )
        assert pos.is_take_profit is False

    def test_is_take_profit_zero_tp(self):
        """If take_profit_price is 0 (unset), is_take_profit is always False."""
        pos_buy = WhalePosition(
            market_id="m1", token_id="t1", side="BUY",
            entry_price=0.50, size=10.0, take_profit_price=0.0, current_price=0.99,
        )
        assert pos_buy.is_take_profit is False

        pos_sell = WhalePosition(
            market_id="m1", token_id="t1", side="SELL",
            entry_price=0.50, size=10.0, take_profit_price=0.0, current_price=0.01,
        )
        assert pos_sell.is_take_profit is False


# ── AggregatedSignal ────────────────────────────────────────────────────


class TestAggregatedSignal:
    """Test AggregatedSignal data structure."""

    def test_basic_creation(self):
        sig = AggregatedSignal(
            market_id="m1",
            direction="long",
            whale_count=3,
            weighted_conviction=0.8,
            avg_whale_win_rate=0.65,
            avg_whale_profit_factor=2.0,
        )
        assert sig.market_id == "m1"
        assert sig.direction == "long"
        assert sig.whale_count == 3
        assert sig.weighted_conviction == 0.8

    def test_default_values(self):
        sig = AggregatedSignal(market_id="m1", direction="short")
        assert sig.whale_count == 0
        assert sig.weighted_conviction == 0.0
        assert sig.avg_whale_win_rate == 0.0
        assert sig.avg_whale_profit_factor == 0.0
        assert sig.signals == []


# ── _aggregate_signals ─────────────────────────────────────────────────


class TestAggregateSignals:
    """Test the _aggregate_signals method on WhaleTrackingStrategy.

    The method returns Dict[str, AggregatedSignal], not a list.
    Conflicting enter+exit on the same market → market skipped.
    """

    @pytest.fixture
    def strategy(self):
        """Build a minimal WhaleTrackingStrategy with mocked deps."""
        client = MagicMock()
        orderbook = MagicMock()
        portfolio = MagicMock()
        portfolio.free_usdc = 10000.0
        risk_manager = MagicMock()
        executor = MagicMock()
        order_store = MagicMock()
        whale_tracker = MagicMock()

        config = {
            "strategies": {
                "whale_tracking": {
                    "enabled": True,
                    "base_size_usd": 50.0,
                    "max_portfolio_pct": 0.05,
                    "stop_loss_pct": 0.15,
                    "take_profit_pct": 0.30,
                }
            }
        }

        return WhaleTrackingStrategy(
            client=client,
            orderbook=orderbook,
            portfolio=portfolio,
            risk_manager=risk_manager,
            executor=executor,
            order_store=order_store,
            whale_tracker=whale_tracker,
            config=config,
        )

    def _make_signal(self, market_id, action, side="BUY", win_rate=0.7,
                      profit_factor=2.0, size=100.0):
        """Helper to create a WhaleSignal."""
        return WhaleSignal(
            whale_address=f"0x{market_id}_{action}_{win_rate}",
            market_id=market_id,
            action=action,
            side=side,
            size=size,
            price=0.50,
            whale_win_rate=win_rate,
            whale_profit_factor=profit_factor,
        )

    def test_conflicting_enter_and_exit_skips_market(self, strategy):
        """When whales have both enter and exit signals for the same market,
        the market should be skipped (not in returned dict).
        """
        signals = [
            self._make_signal("m1", "enter", side="BUY"),
            self._make_signal("m1", "exit", side="SELL"),
        ]
        result = strategy._aggregate_signals(signals)
        # Conflicting signals → skip this market
        assert "m1" not in result

    def test_single_enter_signal(self, strategy):
        """A single enter signal should produce an aggregated long signal."""
        signals = [self._make_signal("m1", "enter", side="BUY")]
        result = strategy._aggregate_signals(signals)
        assert "m1" in result
        assert result["m1"].direction == "long"
        assert result["m1"].whale_count == 1

    def test_single_exit_signal(self, strategy):
        """A single exit signal should produce an aggregated short signal."""
        signals = [self._make_signal("m1", "exit", side="SELL")]
        result = strategy._aggregate_signals(signals)
        assert "m1" in result
        assert result["m1"].direction == "short"
        assert result["m1"].whale_count == 1

    def test_multi_whale_bonus_3_plus(self, strategy):
        """3+ whales on same side → signal strength boosted by 1.2×.
        _aggregate_signals itself computes weighted_conviction.
        """
        signals = [
            self._make_signal("m1", "enter", side="BUY", win_rate=0.7, profit_factor=2.0),
            self._make_signal("m1", "enter", side="BUY", win_rate=0.7, profit_factor=2.0),
            self._make_signal("m1", "enter", side="BUY", win_rate=0.7, profit_factor=2.0),
        ]
        result = strategy._aggregate_signals(signals)
        assert "m1" in result
        assert result["m1"].whale_count == 3
        # Weighted conviction: weight = 0.7 * min(2.0, 5.0) = 1.4 per whale
        # total_weight = 3 * 1.4 = 4.2
        # conviction = min(1.0, 4.2 / 3) = min(1.0, 1.4) = 1.0
        assert result["m1"].weighted_conviction == pytest.approx(1.0)

    def test_multi_whale_bonus_5_plus(self, strategy):
        """5+ whales → signal strength gets additional 1.1× bonus
        (applied in _compute_signal_strength, not in _aggregate_signals).
        But _aggregate_signals should correctly set whale_count = 5.
        """
        signals = [
            self._make_signal("m5", "enter", side="BUY", win_rate=0.7, profit_factor=2.0)
            for _ in range(5)
        ]
        result = strategy._aggregate_signals(signals)
        assert "m5" in result
        assert result["m5"].whale_count == 5

    def test_weighted_conviction_by_win_rate(self, strategy):
        """Whales with higher win rates should contribute more to weighted conviction."""
        # Strong whale: win_rate=0.9, pf=2.0 → weight = 0.9 * 2.0 = 1.8
        sig_strong = self._make_signal("m1", "enter", side="BUY", win_rate=0.9, profit_factor=2.0)
        result_strong = strategy._aggregate_signals([sig_strong])
        # Weak whale: win_rate=0.5, pf=2.0 → weight = 0.5 * 2.0 = 1.0
        sig_weak = self._make_signal("m2", "enter", side="BUY", win_rate=0.5, profit_factor=2.0)
        result_weak = strategy._aggregate_signals([sig_weak])

        # Strong conviction: min(1.0, 1.8/1) = 1.0
        # Weak conviction: min(1.0, 1.0/1) = 1.0
        # But avg_whale_win_rate differs
        assert result_strong["m1"].avg_whale_win_rate > result_weak["m2"].avg_whale_win_rate

    def test_separate_markets_not_conflicting(self, strategy):
        """Enter on m1 + exit on m2 should NOT be treated as conflicting."""
        signals = [
            self._make_signal("m1", "enter", side="BUY"),
            self._make_signal("m2", "exit", side="SELL"),
        ]
        result = strategy._aggregate_signals(signals)
        assert "m1" in result
        assert "m2" in result
        assert result["m1"].direction == "long"
        assert result["m2"].direction == "short"

    def test_empty_signals_returns_empty_dict(self, strategy):
        """No signals should return empty dict."""
        result = strategy._aggregate_signals([])
        assert result == {}


# ── _compute_signal_strength ────────────────────────────────────────────


class TestComputeSignalStrength:
    """Test the _compute_signal_strength formula:
    strength = conviction × avg_win_rate × sqrt(avg_profit_factor) × recency

    Then multi-whale bonuses are applied:
    - 3+ whales: strength *= 1.2
    - 5+ whales: strength *= 1.1 (additional)
    """

    @pytest.fixture
    def strategy(self):
        """Build a minimal WhaleTrackingStrategy."""
        client = MagicMock()
        orderbook = MagicMock()
        portfolio = MagicMock()
        portfolio.free_usdc = 10000.0
        risk_manager = MagicMock()
        executor = MagicMock()
        order_store = MagicMock()
        whale_tracker = MagicMock()

        config = {
            "strategies": {
                "whale_tracking": {
                    "enabled": True,
                    "base_size_usd": 50.0,
                }
            }
        }
        return WhaleTrackingStrategy(
            client=client,
            orderbook=orderbook,
            portfolio=portfolio,
            risk_manager=risk_manager,
            executor=executor,
            order_store=order_store,
            whale_tracker=whale_tracker,
            config=config,
        )

    def test_basic_formula_single_whale(self, strategy):
        """Verify: strength = conviction × win_rate × √(pf) × recency
        for a single whale signal (no multi-whale bonus).
        """
        conviction = 0.8
        win_rate = 0.7
        profit_factor = 4.0  # √4 = 2.0

        # Create a signal with known timestamp so age_sec ≈ 0 → recency ≈ 1.0
        fresh_signal = WhaleSignal(
            whale_address="0xTEST",
            market_id="m1",
            action="enter",
            side="BUY",
            size=100.0,
            price=0.50,
            whale_win_rate=win_rate,
            whale_profit_factor=profit_factor,
            timestamp=time.monotonic(),  # Fresh
        )
        agg = AggregatedSignal(
            market_id="m1",
            direction="long",
            whale_count=1,  # Below 3 — no bonus
            weighted_conviction=conviction,
            avg_whale_win_rate=win_rate,
            avg_whale_profit_factor=profit_factor,
            signals=[fresh_signal],
        )
        strength = strategy._compute_signal_strength(agg)

        # Recency for age_sec ≈ 0: exp(-0.012 * 0) = 1.0, max(0.5, 1.0) = 1.0
        recency = 1.0
        pf_factor = math.sqrt(max(0.01, profit_factor))  # √4 = 2.0
        expected = conviction * win_rate * pf_factor * recency
        assert strength == pytest.approx(expected, rel=0.01)

    def test_zero_win_rate_gives_zero(self, strategy):
        """Zero avg win rate should produce near-zero signal strength."""
        fresh_signal = WhaleSignal(
            whale_address="0xZERO", market_id="m1", action="enter",
            side="BUY", size=100.0, price=0.50,
            whale_win_rate=0.0, whale_profit_factor=2.0,
        )
        agg = AggregatedSignal(
            market_id="m1", direction="long", whale_count=1,
            weighted_conviction=0.8, avg_whale_win_rate=0.0,
            avg_whale_profit_factor=2.0, signals=[fresh_signal],
        )
        strength = strategy._compute_signal_strength(agg)
        assert strength == pytest.approx(0.0)

    def test_zero_conviction_gives_zero(self, strategy):
        """Zero conviction should produce zero signal strength."""
        fresh_signal = WhaleSignal(
            whale_address="0xZERO_C", market_id="m1", action="enter",
            side="BUY", size=100.0, price=0.50,
            whale_win_rate=0.7, whale_profit_factor=2.0,
        )
        agg = AggregatedSignal(
            market_id="m1", direction="long", whale_count=1,
            weighted_conviction=0.0, avg_whale_win_rate=0.7,
            avg_whale_profit_factor=2.0, signals=[fresh_signal],
        )
        strength = strategy._compute_signal_strength(agg)
        assert strength == pytest.approx(0.0)

    def test_profit_factor_sqrt_not_linear(self, strategy):
        """Verify profit_factor enters as √(pf), not linearly."""
        fresh_signal_low = WhaleSignal(
            whale_address="0xLOW_PF", market_id="m1", action="enter",
            side="BUY", size=100.0, price=0.50,
            whale_win_rate=1.0, whale_profit_factor=1.0,
        )
        fresh_signal_high = WhaleSignal(
            whale_address="0xHIGH_PF", market_id="m1", action="enter",
            side="BUY", size=100.0, price=0.50,
            whale_win_rate=1.0, whale_profit_factor=9.0,
        )
        agg_low = AggregatedSignal(
            market_id="m1", direction="long", whale_count=1,
            weighted_conviction=1.0, avg_whale_win_rate=1.0,
            avg_whale_profit_factor=1.0, signals=[fresh_signal_low],
        )
        agg_high = AggregatedSignal(
            market_id="m1", direction="long", whale_count=1,
            weighted_conviction=1.0, avg_whale_win_rate=1.0,
            avg_whale_profit_factor=9.0, signals=[fresh_signal_high],
        )
        s_low = strategy._compute_signal_strength(agg_low)
        s_high = strategy._compute_signal_strength(agg_high)
        # √9 = 3, so s_high ≈ 3× s_low (no whale bonus since count=1)
        assert s_high == pytest.approx(s_low * 3.0, rel=0.01)

    def test_multi_whale_3_bonus(self, strategy):
        """3+ whales should apply a 1.2× bonus to signal strength."""
        signals = [
            WhaleSignal(
                whale_address=f"0xW{i}", market_id="m1", action="enter",
                side="BUY", size=100.0, price=0.50,
                whale_win_rate=0.7, whale_profit_factor=2.0,
            )
            for i in range(3)
        ]
        agg = AggregatedSignal(
            market_id="m1", direction="long", whale_count=3,
            weighted_conviction=1.0, avg_whale_win_rate=0.7,
            avg_whale_profit_factor=2.0, signals=signals,
        )
        strength = strategy._compute_signal_strength(agg)

        # Base without bonus: 1.0 * 0.7 * √2 * ~1.0
        base = 1.0 * 0.7 * math.sqrt(2.0) * 1.0
        expected = base * 1.2  # 3+ whale bonus
        assert strength == pytest.approx(expected, rel=0.05)

    def test_multi_whale_5_bonus(self, strategy):
        """5+ whales should apply 1.2× * 1.1× = 1.32× bonus."""
        signals = [
            WhaleSignal(
                whale_address=f"0xW{i}", market_id="m1", action="enter",
                side="BUY", size=100.0, price=0.50,
                whale_win_rate=0.7, whale_profit_factor=2.0,
            )
            for i in range(5)
        ]
        agg = AggregatedSignal(
            market_id="m1", direction="long", whale_count=5,
            weighted_conviction=1.0, avg_whale_win_rate=0.7,
            avg_whale_profit_factor=2.0, signals=signals,
        )
        strength = strategy._compute_signal_strength(agg)

        # Base without bonus * 1.2 * 1.1
        base = 1.0 * 0.7 * math.sqrt(2.0) * 1.0
        expected = base * 1.2 * 1.1  # 3+ then 5+ whale bonus
        assert strength == pytest.approx(expected, rel=0.05)

    def test_recency_decays_for_old_signals(self, strategy):
        """Lower recency (older signal) should produce lower strength.
        Recency = max(0.5, exp(-0.012 * age_sec)).
        """
        # Fresh signal (age ≈ 0 → recency ≈ 1.0)
        fresh_signal = WhaleSignal(
            whale_address="0xFRESH", market_id="m1", action="enter",
            side="BUY", size=100.0, price=0.50,
            whale_win_rate=0.7, whale_profit_factor=2.0,
        )
        agg_fresh = AggregatedSignal(
            market_id="m1", direction="long", whale_count=1,
            weighted_conviction=0.8, avg_whale_win_rate=0.7,
            avg_whale_profit_factor=2.0, signals=[fresh_signal],
        )

        # Stale signal (timestamp 60s ago → recency = max(0.5, exp(-0.72)) ≈ max(0.5, 0.487) = 0.5)
        stale_signal = WhaleSignal(
            whale_address="0xSTALE", market_id="m1", action="enter",
            side="BUY", size=100.0, price=0.50,
            whale_win_rate=0.7, whale_profit_factor=2.0,
            timestamp=time.monotonic() - 60.0,
        )
        agg_stale = AggregatedSignal(
            market_id="m1", direction="long", whale_count=1,
            weighted_conviction=0.8, avg_whale_win_rate=0.7,
            avg_whale_profit_factor=2.0, signals=[stale_signal],
        )

        s_fresh = strategy._compute_signal_strength(agg_fresh)
        s_stale = strategy._compute_signal_strength(agg_stale)
        assert s_fresh > s_stale


# ── _get_streak_multiplier ──────────────────────────────────────────────


class TestGetStreakMultiplier:
    """Test _get_streak_multiplier: clamped to [0.2, 3.0],
    win streak capped at 5, loss streak capped at 3.

    Formula:
    - win_streak > 0: multiplier = win_streak_multiplier ** min(win_streak, 5)
    - loss_streak > 0: multiplier = loss_streak_multiplier ** min(loss_streak, 3)
    - else: 1.0
    - clamped to [min_size_multiplier, max_size_multiplier] = [0.2, 3.0]
    """

    @pytest.fixture
    def strategy(self):
        client = MagicMock()
        orderbook = MagicMock()
        portfolio = MagicMock()
        portfolio.free_usdc = 10000.0
        risk_manager = MagicMock()
        executor = MagicMock()
        order_store = MagicMock()
        whale_tracker = MagicMock()

        config = {
            "strategies": {
                "whale_tracking": {"enabled": True}
            }
        }
        return WhaleTrackingStrategy(
            client=client,
            orderbook=orderbook,
            portfolio=portfolio,
            risk_manager=risk_manager,
            executor=executor,
            order_store=order_store,
            whale_tracker=whale_tracker,
            config=config,
        )

    def test_no_streak_returns_base(self, strategy):
        """Zero streak (no wins or losses) should return 1.0."""
        strategy._win_streak = 0
        strategy._loss_streak = 0
        mult = strategy._get_streak_multiplier()
        assert mult == pytest.approx(1.0)

    def test_win_streak_increases_multiplier(self, strategy):
        """Win streak should increase the multiplier above 1.0."""
        strategy._win_streak = 3
        strategy._loss_streak = 0
        mult = strategy._get_streak_multiplier()
        # 1.1 ** 3 = 1.331
        expected = 1.1 ** 3
        assert mult == pytest.approx(expected)

    def test_loss_streak_decreases_multiplier(self, strategy):
        """Loss streak should decrease the multiplier below 1.0."""
        strategy._win_streak = 0
        strategy._loss_streak = 2
        mult = strategy._get_streak_multiplier()
        # 0.7 ** 2 = 0.49
        expected = 0.7 ** 2
        assert mult == pytest.approx(expected)

    def test_clamp_lower_bound(self, strategy):
        """Multiplier should never go below min_size_multiplier (0.2)."""
        strategy._win_streak = 0
        strategy._loss_streak = 10  # 0.7 ** 3 = 0.343, but capped at min(10,3) = 3 → 0.7**3 = 0.343
        # 0.343 is still above 0.2, so need longer streak
        # Actually with cap at 3: 0.7^3 = 0.343 > 0.2
        # So max loss streak effect = 0.7^3 = 0.343
        # To get below 0.2, the multiplier itself would need to be configured differently
        # But the clamp ensures we never go below 0.2 regardless
        mult = strategy._get_streak_multiplier()
        assert mult >= 0.2

    def test_clamp_upper_bound(self, strategy):
        """Multiplier should never go above max_size_multiplier (3.0)."""
        strategy._win_streak = 20
        strategy._loss_streak = 0
        mult = strategy._get_streak_multiplier()
        assert mult <= 3.0

    def test_win_streak_cap_at_5(self, strategy):
        """Win streak is capped at 5 for multiplier calculation.
        A streak of 5 and a streak of 10 should give the same multiplier.
        """
        strategy._win_streak = 5
        strategy._loss_streak = 0
        mult_5 = strategy._get_streak_multiplier()

        strategy._win_streak = 10
        mult_10 = strategy._get_streak_multiplier()

        assert mult_5 == pytest.approx(mult_10)

    def test_loss_streak_cap_at_3(self, strategy):
        """Loss streak is capped at 3 for multiplier calculation.
        A streak of 3 and a streak of 7 should give the same multiplier.
        """
        strategy._win_streak = 0
        strategy._loss_streak = 3
        mult_3 = strategy._get_streak_multiplier()

        strategy._loss_streak = 7
        mult_7 = strategy._get_streak_multiplier()

        assert mult_3 == pytest.approx(mult_7)

    def test_streak_1_win(self, strategy):
        """Single win should give win_streak_multiplier^1 = 1.1."""
        strategy._win_streak = 1
        strategy._loss_streak = 0
        mult = strategy._get_streak_multiplier()
        assert mult == pytest.approx(1.1)

    def test_streak_1_loss(self, strategy):
        """Single loss should give loss_streak_multiplier^1 = 0.7."""
        strategy._win_streak = 0
        strategy._loss_streak = 1
        mult = strategy._get_streak_multiplier()
        assert mult == pytest.approx(0.7)

    def test_win_streak_takes_priority_over_loss(self, strategy):
        """When both streaks are >0, win_streak is checked first."""
        strategy._win_streak = 2
        strategy._loss_streak = 2
        mult = strategy._get_streak_multiplier()
        # Win path: 1.1^2 = 1.21
        expected = 1.1 ** 2
        assert mult == pytest.approx(expected)


# ── WhaleTrackingStrategy ───────────────────────────────────────────────


class TestWhaleTrackingStrategy:
    """Test strategy constructor with whale_tracker argument."""

    @pytest.fixture
    def mock_deps(self):
        client = MagicMock()
        orderbook = MagicMock()
        portfolio = MagicMock()
        portfolio.free_usdc = 10000.0
        risk_manager = MagicMock()
        executor = MagicMock()
        order_store = MagicMock()
        whale_tracker = MagicMock()

        config = {
            "strategies": {
                "whale_tracking": {
                    "enabled": True,
                    "base_size_usd": 50.0,
                    "max_portfolio_pct": 0.05,
                    "stop_loss_pct": 0.15,
                    "take_profit_pct": 0.30,
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
            "whale_tracker": whale_tracker,
            "config": config,
        }

    def test_constructor_assigns_whale_tracker(self, mock_deps):
        """Constructor must accept whale_tracker and store it as self.whale_tracker."""
        strategy = WhaleTrackingStrategy(
            client=mock_deps["client"],
            orderbook=mock_deps["orderbook"],
            portfolio=mock_deps["portfolio"],
            risk_manager=mock_deps["risk_manager"],
            executor=mock_deps["executor"],
            order_store=mock_deps["order_store"],
            whale_tracker=mock_deps["whale_tracker"],
            config=mock_deps["config"],
        )
        assert strategy.whale_tracker is mock_deps["whale_tracker"]

    def test_strategy_name(self, mock_deps):
        """Strategy name property returns 'WhaleTracking'."""
        strategy = WhaleTrackingStrategy(
            client=mock_deps["client"],
            orderbook=mock_deps["orderbook"],
            portfolio=mock_deps["portfolio"],
            risk_manager=mock_deps["risk_manager"],
            executor=mock_deps["executor"],
            order_store=mock_deps["order_store"],
            whale_tracker=mock_deps["whale_tracker"],
            config=mock_deps["config"],
        )
        assert strategy.name == "WhaleTracking"
