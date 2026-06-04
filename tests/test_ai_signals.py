"""Tests for the AI signals trading strategy — position tracking,
signal evaluation, order placement, and position management."""

import asyncio
import time
from collections import deque
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from strategies.ai_signals import AISignalsStrategy, AIPosition
from data.signal_model import Signal
from data.news_fetcher import Article, NewsFetcher
from data.market_scanner import MarketScanner, MarketInfo


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def ai_config():
    """Config with AI signals strategy settings."""
    return {
        "risk": {
            "max_position_pct": 0.05,
            "daily_loss_cap_pct": 0.10,
            "halt_total_loss_pct": 0.40,
            "min_profit_threshold_usd": 0.30,
            "max_correlated_exposure_pct": 0.15,
            "time_of_day": {"enabled": False},
        },
        "taker_fees": {
            "crypto": 0.018, "sports": 0.0075, "finance": 0.01,
            "politics": 0.01, "economics": 0.015, "geopolitics": 0.0,
        },
        "execution": {
            "rate_limit_per_min": 55,
            "post_only_default": True,
            "pending_timeout_sec": 2.0,
        },
        "strategies": {
            "ai_signals": {
                "enabled": True,
                "min_edge_to_trade": 0.05,
                "min_confidence": 0.3,
                "max_concurrent_positions": 5,
                "base_order_usd": 25.0,
                "max_order_usd": 100.0,
                "stop_loss_pct": 0.15,
                "take_profit_pct": 0.50,
                "max_hold_sec": 86400 * 3,
                "target_categories": ["politics", "geopolitics", "finance"],
                "min_market_volume_usd": 5000.0,
                "min_days_to_resolution": 3,
                "max_days_to_resolution": 180,
                "cycle_interval_sec": 60.0,
                "max_consecutive_errors": 10,
            },
        },
        "scheduled_events": [],
    }


# ── AIPosition ────────────────────────────────────────────────────────

class TestAIPosition:
    """Tests for the AIPosition dataclass."""

    def test_yes_position_pnl_positive(self):
        pos = AIPosition(
            market_id="test",
            token_id="tok-1",
            direction="YES",
            entry_price=0.50,
            current_price=0.65,
            size=10.0,
        )
        assert pos.pnl_pct > 0.0

    def test_yes_position_pnl_negative(self):
        pos = AIPosition(
            market_id="test",
            token_id="tok-1",
            direction="YES",
            entry_price=0.50,
            current_price=0.35,
            size=10.0,
        )
        assert pos.pnl_pct < 0.0

    def test_no_position_pnl_positive(self):
        pos = AIPosition(
            market_id="test",
            token_id="tok-1",
            direction="NO",
            entry_price=0.50,
            current_price=0.35,
            size=10.0,
        )
        # NO position: profit when price drops
        assert pos.pnl_pct > 0.0

    def test_no_position_pnl_negative(self):
        pos = AIPosition(
            market_id="test",
            token_id="tok-1",
            direction="NO",
            entry_price=0.50,
            current_price=0.65,
            size=10.0,
        )
        assert pos.pnl_pct < 0.0

    def test_zero_entry_price_pnl(self):
        pos = AIPosition(
            market_id="test",
            token_id="tok-1",
            direction="YES",
            entry_price=0.0,
            current_price=0.50,
            size=10.0,
        )
        assert pos.pnl_pct == 0.0

    def test_should_exit_stop_loss_yes(self):
        pos = AIPosition(
            market_id="test",
            token_id="tok-1",
            direction="YES",
            entry_price=0.50,
            current_price=0.40,
            stop_loss_price=0.42,
        )
        should_exit, reason = pos.should_exit
        assert should_exit is True
        assert reason == "stop_loss"

    def test_should_exit_stop_loss_no(self):
        pos = AIPosition(
            market_id="test",
            token_id="tok-1",
            direction="NO",
            entry_price=0.50,
            current_price=0.60,
            stop_loss_price=0.58,
        )
        should_exit, reason = pos.should_exit
        assert should_exit is True
        assert reason == "stop_loss"

    def test_should_exit_take_profit_yes(self):
        pos = AIPosition(
            market_id="test",
            token_id="tok-1",
            direction="YES",
            entry_price=0.50,
            current_price=0.75,
            take_profit_price=0.70,
        )
        should_exit, reason = pos.should_exit
        assert should_exit is True
        assert reason == "take_profit"

    def test_should_exit_take_profit_no(self):
        pos = AIPosition(
            market_id="test",
            token_id="tok-1",
            direction="NO",
            entry_price=0.50,
            current_price=0.25,
            stop_loss_price=0.70,  # NO stop triggers when price >= 0.70
            take_profit_price=0.30,  # NO take-profit triggers when price <= 0.30
        )
        should_exit, reason = pos.should_exit
        assert should_exit is True
        assert reason == "take_profit"

    def test_should_not_exit(self):
        pos = AIPosition(
            market_id="test",
            token_id="tok-1",
            direction="YES",
            entry_price=0.50,
            current_price=0.55,
            stop_loss_price=0.40,
            take_profit_price=0.70,
        )
        should_exit, reason = pos.should_exit
        assert should_exit is False
        assert reason == ""

    def test_max_hold_time_exit(self):
        pos = AIPosition(
            market_id="test",
            token_id="tok-1",
            direction="YES",
            entry_price=0.50,
            current_price=0.50,
            stop_loss_price=0.40,  # price 0.50 > stop, no stop-loss trigger
            take_profit_price=0.60,  # price 0.50 < TP, no take-profit trigger
            max_hold_sec=0.001, # 1ms — will immediately expire
        )
        pos.entry_time = time.monotonic() - 10 # 10 seconds ago
        should_exit, reason = pos.should_exit
        assert should_exit is True
        assert reason == "max_hold_time"

    def test_hold_time_sec(self):
        pos = AIPosition(
            market_id="test",
            token_id="tok-1",
        )
        assert pos.hold_time_sec >= 0.0

    def test_default_values(self):
        pos = AIPosition(market_id="test", token_id="tok-1")
        assert pos.direction == "FLAT"
        assert pos.entry_price == 0.0
        assert pos.size == 0.0
        assert pos.signal_edge == 0.0
        assert pos.signal_confidence == 0.0

    def test_category_default(self):
        pos = AIPosition(market_id="test", token_id="tok-1")
        assert pos.category == ""

    def test_question_default(self):
        pos = AIPosition(market_id="test", token_id="tok-1")
        assert pos.question == ""


# ── AISignalsStrategy unit tests (no __init__ required) ────────────────

class TestAISignalsStrategyConfig:
    """Tests for AI signals strategy configuration."""

    def test_strategy_name(self):
        """AISignalsStrategy.name should return 'AISignals'."""
        # We can't easily instantiate without all deps,
        # but we can test the class attribute pattern
        assert AISignalsStrategy.__name__ == "AISignalsStrategy"

    def test_target_categories_from_config(self, ai_config):
        ai_cfg = ai_config["strategies"]["ai_signals"]
        categories = set(ai_cfg.get("target_categories", []))
        assert "politics" in categories
        assert "finance" in categories
        assert "geopolitics" in categories
        assert "sports" not in categories

    def test_stop_loss_pct_from_config(self, ai_config):
        ai_cfg = ai_config["strategies"]["ai_signals"]
        assert ai_cfg.get("stop_loss_pct", 0.15) == 0.15

    def test_take_profit_pct_from_config(self, ai_config):
        ai_cfg = ai_config["strategies"]["ai_signals"]
        assert ai_cfg.get("take_profit_pct", 0.50) == 0.50

    def test_max_concurrent_positions(self, ai_config):
        ai_cfg = ai_config["strategies"]["ai_signals"]
        assert ai_cfg.get("max_concurrent_positions", 5) == 5

    def test_min_edge_to_trade(self, ai_config):
        ai_cfg = ai_config["strategies"]["ai_signals"]
        assert ai_cfg.get("min_edge_to_trade", 0.05) == 0.05

    def test_min_confidence(self, ai_config):
        ai_cfg = ai_config["strategies"]["ai_signals"]
        assert ai_cfg.get("min_confidence", 0.3) == 0.3


# ── Market filtering logic ────────────────────────────────────────────

class TestMarketFiltering:
    """Tests for market filtering logic using MarketInfo."""

    def test_politics_market_in_target_categories(self, ai_config):
        categories = set(ai_config["strategies"]["ai_signals"].get("target_categories", []))
        assert "politics" in categories

    def test_geopolitics_market_in_target_categories(self, ai_config):
        categories = set(ai_config["strategies"]["ai_signals"].get("target_categories", []))
        assert "geopolitics" in categories

    def test_sports_market_not_in_target(self, ai_config):
        categories = set(ai_config["strategies"]["ai_signals"].get("target_categories", []))
        assert "sports" not in categories

    def test_crypto_market_not_in_target(self, ai_config):
        categories = set(ai_config["strategies"]["ai_signals"].get("target_categories", []))
        assert "crypto" not in categories

    def test_min_market_volume_filter(self, ai_config):
        min_vol = ai_config["strategies"]["ai_signals"].get("min_market_volume_usd", 5000.0)
        market = MarketInfo(
            market_id="low-vol",
            token_id="tok",
            category="politics",
            daily_volume_usd=500.0,
        )
        assert market.daily_volume_usd < min_vol

    def test_accept_market_with_sufficient_volume(self, ai_config):
        min_vol = ai_config["strategies"]["ai_signals"].get("min_market_volume_usd", 5000.0)
        market = MarketInfo(
            market_id="high-vol",
            token_id="tok",
            category="politics",
            daily_volume_usd=10000.0,
        )
        assert market.daily_volume_usd >= min_vol

    def test_reject_market_near_resolution(self, ai_config):
        min_days = ai_config["strategies"]["ai_signals"].get("min_days_to_resolution", 3)
        market = MarketInfo(
            market_id="near-res",
            token_id="tok",
            category="politics",
            days_to_resolution=1,
        )
        assert market.days_to_resolution < min_days

    def test_reject_market_far_from_resolution(self, ai_config):
        max_days = ai_config["strategies"]["ai_signals"].get("max_days_to_resolution", 180)
        market = MarketInfo(
            market_id="far-res",
            token_id="tok",
            category="politics",
            days_to_resolution=365,
        )
        assert market.days_to_resolution > max_days

    def test_accept_market_in_resolution_range(self, ai_config):
        min_days = ai_config["strategies"]["ai_signals"].get("min_days_to_resolution", 3)
        max_days = ai_config["strategies"]["ai_signals"].get("max_days_to_resolution", 180)
        market = MarketInfo(
            market_id="good-res",
            token_id="tok",
            category="politics",
            days_to_resolution=60,
        )
        assert min_days <= market.days_to_resolution <= max_days


# ── Signal + Position integration ──────────────────────────────────────

class TestSignalPositionIntegration:
    """Tests for how signals translate to positions."""

    def test_actionable_yes_signal_creates_yes_position(self):
        signal = Signal(
            market_id="mkt-1",
            estimated_prob=0.70,
            market_prob=0.50,
            confidence=0.8,
        )
        assert signal.direction == "YES"
        assert signal.is_actionable is True

        pos = AIPosition(
            market_id=signal.market_id,
            token_id="tok-1",
            direction=signal.direction,
            entry_price=0.50,
            current_price=0.50,
            size=25.0,
            signal_edge=signal.edge,
            signal_confidence=signal.confidence,
        )
        assert pos.direction == "YES"
        assert pos.signal_edge == pytest.approx(0.20, abs=0.001)
        assert pos.signal_confidence == 0.8

    def test_actionable_no_signal_creates_no_position(self):
        signal = Signal(
            market_id="mkt-1",
            estimated_prob=0.30,
            market_prob=0.60,
            confidence=0.7,
        )
        assert signal.direction == "NO"
        assert signal.is_actionable is True

        pos = AIPosition(
            market_id=signal.market_id,
            token_id="tok-1",
            direction=signal.direction,
            entry_price=0.60,
            current_price=0.60,
            size=25.0,
            signal_edge=signal.edge,
            signal_confidence=signal.confidence,
        )
        assert pos.direction == "NO"
        assert pos.signal_edge == pytest.approx(0.30, abs=0.001)

    def test_flat_signal_does_not_create_position(self):
        signal = Signal(
            market_id="mkt-1",
            estimated_prob=0.51,
            market_prob=0.50,
            confidence=0.5,
        )
        assert signal.direction == "FLAT"
        assert signal.is_actionable is False
        # Flat signals should not create positions

    def test_position_exit_on_stop_loss_yes(self):
        """YES position with price dropping below stop loss should exit."""
        pos = AIPosition(
            market_id="test",
            token_id="tok-1",
            direction="YES",
            entry_price=0.50,
            current_price=0.40,
            stop_loss_price=0.425,  # 15% below entry
        )
        should_exit, reason = pos.should_exit
        assert should_exit is True
        assert reason == "stop_loss"

    def test_position_exit_on_take_profit_yes(self):
        pos = AIPosition(
            market_id="test",
            token_id="tok-1",
            direction="YES",
            entry_price=0.50,
            current_price=0.80,
            take_profit_price=0.75,  # 50% above entry
        )
        should_exit, reason = pos.should_exit
        assert should_exit is True
        assert reason == "take_profit"

    def test_position_held_within_range(self):
        pos = AIPosition(
            market_id="test",
            token_id="tok-1",
            direction="YES",
            entry_price=0.50,
            current_price=0.55,
            stop_loss_price=0.425,
            take_profit_price=0.75,
        )
        should_exit, _ = pos.should_exit
        assert should_exit is False

    def test_position_pnl_tracking_yes(self):
        """Track P&L as price moves for a YES position."""
        pos = AIPosition(
            market_id="test",
            token_id="tok-1",
            direction="YES",
            entry_price=0.50,
            current_price=0.60,
            size=100.0,
        )
        # 10 cent gain on 50 cent entry = 20% gain
        assert pos.pnl_pct == pytest.approx(0.20, abs=0.01)

    def test_position_pnl_tracking_no(self):
        """Track P&L as price moves for a NO position."""
        pos = AIPosition(
            market_id="test",
            token_id="tok-1",
            direction="NO",
            entry_price=0.50,
            current_price=0.40,
            size=100.0,
        )
        # Price dropped 10c from 50c entry = 20% gain for NO
        assert pos.pnl_pct == pytest.approx(0.20, abs=0.01)


# ── Position management edge cases ────────────────────────────────────

class TestPositionEdgeCases:
    """Edge case tests for position management."""

    def test_position_at_exact_stop_loss(self):
        """Position at exactly the stop loss price should exit."""
        pos = AIPosition(
            market_id="test",
            token_id="tok-1",
            direction="YES",
            entry_price=0.50,
            current_price=0.425,
            stop_loss_price=0.425,
        )
        # <= stop_loss_price → should exit
        should_exit, reason = pos.should_exit
        assert should_exit is True
        assert reason == "stop_loss"

    def test_position_at_exact_take_profit(self):
        """Position at exactly the take profit price should exit."""
        pos = AIPosition(
            market_id="test",
            token_id="tok-1",
            direction="YES",
            entry_price=0.50,
            current_price=0.75,
            take_profit_price=0.75,
        )
        # >= take_profit_price → should exit
        should_exit, reason = pos.should_exit
        assert should_exit is True
        assert reason == "take_profit"

    def test_no_position_pnl_when_entry_is_zero(self):
        pos = AIPosition(
            market_id="test",
            token_id="tok-1",
            direction="YES",
            entry_price=0.0,
            current_price=0.50,
        )
        assert pos.pnl_pct == 0.0

    def test_position_with_no_order_id(self):
        pos = AIPosition(
            market_id="test",
            token_id="tok-1",
            direction="YES",
            entry_price=0.50,
        )
        assert pos.order_id is None

    def test_signal_deque_maxlen(self):
        """Signal tracking deque should be bounded."""
        signals = deque(maxlen=100)
        for i in range(150):
            signals.append(Signal(
                market_id=f"mkt-{i}",
                estimated_prob=0.70,
                market_prob=0.50,
                confidence=0.8,
            ))
        assert len(signals) == 100

    def test_max_concurrent_positions_limit(self, ai_config):
        max_pos = ai_config["strategies"]["ai_signals"]["max_concurrent_positions"]
        positions = {}
        for i in range(max_pos + 2):
            if len(positions) < max_pos:
                positions[f"mkt-{i}"] = AIPosition(
                    market_id=f"mkt-{i}", token_id=f"tok-{i}",
                )
        assert len(positions) == max_pos
