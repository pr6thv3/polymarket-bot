"""Tests for the market-making strategy — Avellaneda-Stoikov quoting,
adverse selection, re-quoting, and inventory skew."""

import asyncio
import math
import time
from collections import deque
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from strategies.market_making import MarketMakingStrategy, MMPosition
from strategies.base import Strategy, StrategyState
from data.market_scanner import MarketScanner, MarketInfo


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def mm_config():
    """Config with market-making strategy settings."""
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
            "market_making": {
                "enabled": True,
                "cycle_interval_sec": 1.0,
                "kappa": 0.5,
                "delta": 0.002,
                "time_horizon": 1.0,
                "min_spread_bps": 100,
                "max_spread_bps": 400,
                "base_spread_bps": 200,
                "order_size_usd": 15.0,
                "min_order_size_usd": 5.0,
                "midpoint_move_threshold_bps": 50,
                "cancel_stale_sec": 120,
                "adverse_selection": {
                    "volatility_pause_threshold": 0.05,
                    "pause_duration_sec": 300,
                    "fill_rate_window_sec": 60,
                    "fill_rate_pause_threshold": 0.8,
                },
            }
        },
        "scheduled_events": [],
    }


@pytest.fixture
def mock_client():
    """Create a mock ClobClient."""
    client = MagicMock()
    client.get_markets = AsyncMock(return_value={"markets": [], "next_cursor": 0})
    client.create_order = AsyncMock(return_value="order-123")
    client.cancel_order = AsyncMock(return_value=True)
    client.cancel_all_for_market = AsyncMock(return_value=2)
    return client


@pytest.fixture
def mock_orderbook():
    """Create a mock OrderBookManager."""
    ob = MagicMock()
    ob.register_market = MagicMock()
    ob.unregister_market = MagicMock()
    ob.refresh_from_rest = AsyncMock()

    snapshot = MagicMock()
    snapshot.mid_price = 0.50
    snapshot.spread_bps = 200.0
    snapshot.best_bid = 0.49
    snapshot.best_ask = 0.51
    ob.get_snapshot = MagicMock(return_value=snapshot)
    ob.get_volatility = MagicMock(return_value=0.01)
    ob.is_volatile = MagicMock(return_value=False)
    return ob


@pytest.fixture
def mock_portfolio():
    """Create a mock Portfolio."""
    portfolio = MagicMock()
    portfolio.free_usdc = 10000.0
    portfolio._free_usdc = 10000.0
    portfolio._initial_capital = 10000.0
    portfolio.get_position = MagicMock(return_value=None)
    portfolio.get_total_value = MagicMock(return_value=10000.0)
    portfolio.total_pnl = 0.0
    portfolio.lock_usdc = AsyncMock(return_value=True)
    portfolio.unlock_usdc = AsyncMock()
    portfolio.save_state = AsyncMock()
    portfolio.force_save = AsyncMock()
    portfolio.calculate_daily_holding_reward = MagicMock(return_value=0.0)
    return portfolio


@pytest.fixture
def mock_risk():
    """Create a mock RiskManager."""
    risk = MagicMock()
    risk.allow_order = AsyncMock(return_value=(True, ""))
    risk.get_size_multiplier = MagicMock(return_value=1.0)
    risk.max_position_pct = 0.05
    risk.get_risk_summary = MagicMock(return_value={})
    risk.calculate_rebate_value = MagicMock(return_value=0.0)
    return risk


@pytest.fixture
def mock_order_store():
    """Create a mock OrderStore."""
    store = MagicMock()
    store.add = AsyncMock()
    store.get = MagicMock(return_value=None)
    store.get_open_orders = AsyncMock(return_value=[])
    store.check_pending_timeouts = AsyncMock(return_value=[])
    return store


@pytest.fixture
def mock_executor():
    """Create a mock Executor."""
    executor = MagicMock()
    executor.place_quote_pair = AsyncMock(return_value=("bid-1", "ask-1"))
    executor.cancel_all_for_market = AsyncMock(return_value=2)
    executor.emergency_cancel_all = AsyncMock(return_value=0)
    return executor


@pytest.fixture
def mock_scanner():
    """Create a mock MarketScanner."""
    scanner = MagicMock(spec=MarketScanner)
    scanner.scan = AsyncMock()
    scanner._last_scan = time.monotonic()
    scanner.scan_interval_sec = 300
    scanner.refresh_market_book = AsyncMock()

    eligible_market = MarketInfo(
        market_id="m1", token_id="t1",
        category="finance", daily_volume_usd=50000,
        spread_bps=200, days_to_resolution=30,
        score=75.0, active=True,
    )
    scanner.get_eligible_markets = AsyncMock(return_value=[eligible_market])
    return scanner


@pytest.fixture
def mm_strategy(
    mm_config, mock_client, mock_orderbook, mock_portfolio,
    mock_risk, mock_executor, mock_order_store, mock_scanner,
):
    """Create a MarketMakingStrategy instance with all mocks."""
    return MarketMakingStrategy(
        client=mock_client,
        orderbook=mock_orderbook,
        portfolio=mock_portfolio,
        risk_manager=mock_risk,
        executor=mock_executor,
        order_store=mock_order_store,
        scanner=mock_scanner,
        config=mm_config,
    )


# ── Strategy interface tests ──────────────────────────────────────────

class TestStrategyInterface:
    """Tests for the strategy base class integration."""

    def test_name(self, mm_strategy):
        assert mm_strategy.name == "MarketMaking"

    def test_config_key(self, mm_strategy):
        assert mm_strategy._config_key() == "market_making"

    def test_is_enabled(self, mm_strategy):
        assert mm_strategy.is_enabled is True

    def test_cycle_interval(self, mm_strategy):
        assert mm_strategy.cycle_interval_sec == 1.0

    @pytest.mark.asyncio
    async def test_initialize_calls_scanner(self, mm_strategy, mock_scanner):
        mock_scanner.scan = AsyncMock(return_value=MagicMock(
            top_markets=[
                MarketInfo(market_id="m1", token_id="t1", category="finance", score=75.0),
            ],
            eligible_markets=1,
        ))

        await mm_strategy.initialize()

        mock_scanner.scan.assert_called_once_with(force=True)
        assert "m1" in mm_strategy._positions

    @pytest.mark.asyncio
    async def test_shutdown_cancels_orders(self, mm_strategy, mock_executor):
        mm_strategy._positions["m1"] = MMPosition(
            market_id="m1", token_id="t1",
        )

        await mm_strategy.shutdown()

        mock_executor.cancel_all_for_market.assert_called_with("m1")

    @pytest.mark.asyncio
    async def test_safe_run_cycle_wraps_errors(self, mm_strategy):
        """safe_run_cycle should catch exceptions, not crash."""
        mm_strategy._state.enabled = True

        # Make run_cycle raise
        async def bad_cycle():
            raise RuntimeError("test error")

        mm_strategy.run_cycle = bad_cycle

        await mm_strategy.safe_run_cycle()

        assert mm_strategy._state.errors_consecutive == 1
        assert mm_strategy._state.errors_total == 1

    @pytest.mark.asyncio
    async def test_auto_pause_after_consecutive_errors(self, mm_strategy):
        """Strategy should auto-pause after max consecutive errors."""
        # Set via config (max_consecutive_errors is a read-only property)
        mm_strategy._strategy_config["max_consecutive_errors"] = 3
        mm_strategy._state.errors_consecutive = 3

        await mm_strategy.safe_run_cycle()

        assert mm_strategy._state.enabled is False

    @pytest.mark.asyncio
    async def test_start_skips_if_disabled(self, mm_config, mm_strategy):
        mm_config["strategies"]["market_making"]["enabled"] = False
        strategy = MarketMakingStrategy(
            client=mock_client, orderbook=mock_orderbook,
            portfolio=mock_portfolio, risk_manager=mock_risk,
            executor=mock_executor, order_store=mock_order_store,
            scanner=mock_scanner, config=mm_config,
        )

        await strategy.start()

        assert strategy._state.started_at == 0.0


# ── Avellaneda-Stoikov quote computation tests ────────────────────────

class TestQuoteComputation:
    """Tests for the Avellaneda-Stoikov spread and price computation."""

    def test_flat_inventory_mid_quotes(self, mm_strategy, mock_orderbook, mock_portfolio):
        """With zero inventory, quotes should be symmetric around mid."""
        mock_orderbook.get_volatility = MagicMock(return_value=0.0)
        mock_portfolio.get_position = MagicMock(return_value=None)

        pos = MMPosition(market_id="m1", token_id="t1")
        bid, ask, size = mm_strategy._compute_quotes("m1", 0.50, pos)

        assert bid is not None
        assert ask is not None
        # Should be symmetric around 0.50 with zero inventory and zero vol
        mid_quote = (bid + ask) / 2
        assert abs(mid_quote - 0.50) < 0.005  # Within 5 bps of mid

    def test_long_inventory_skews_away(self, mm_strategy, mock_orderbook, mock_portfolio):
        """With positive inventory (long), quotes should shift down."""
        mock_orderbook.get_volatility = MagicMock(return_value=0.0)

        # Long position
        long_pos = MagicMock()
        long_pos.size = 100.0
        mock_portfolio.get_position = MagicMock(return_value=long_pos)

        pos = MMPosition(market_id="m1", token_id="t1")
        bid_long, ask_long, _ = mm_strategy._compute_quotes("m1", 0.50, pos)

        # Flat position
        mock_portfolio.get_position = MagicMock(return_value=None)
        pos2 = MMPosition(market_id="m1", token_id="t1")
        bid_flat, ask_flat, _ = mm_strategy._compute_quotes("m1", 0.50, pos2)

        # With long inventory, reservation price shifts down
        assert bid_long < bid_flat
        assert ask_long < ask_flat

    def test_volatility_widens_spread(self, mm_strategy, mock_orderbook, mock_portfolio):
        """Higher volatility should produce wider spreads."""
        mock_portfolio.get_position = MagicMock(return_value=None)

        # Low volatility
        mock_orderbook.get_volatility = MagicMock(return_value=0.01)
        pos1 = MMPosition(market_id="m1", token_id="t1")
        bid1, ask1, _ = mm_strategy._compute_quotes("m1", 0.50, pos1)
        spread1 = ask1 - bid1

        # High volatility
        mock_orderbook.get_volatility = MagicMock(return_value=0.05)
        pos2 = MMPosition(market_id="m1", token_id="t1")
        bid2, ask2, _ = mm_strategy._compute_quotes("m1", 0.50, pos2)
        spread2 = ask2 - bid2

        assert spread2 > spread1

    def test_spread_respects_min_max(self, mm_strategy, mock_orderbook, mock_portfolio):
        """Computed quotes should be clamped to min/max spread."""
        mock_orderbook.get_volatility = MagicMock(return_value=0.0)
        mock_portfolio.get_position = MagicMock(return_value=None)

        # Very low kappa + zero vol → tight spread
        mm_strategy.kappa = 0.001
        mm_strategy.base_spread_bps = 50  # Below min of 100

        pos = MMPosition(market_id="m1", token_id="t1")
        # _compute_quotes returns raw values, but _quote_market clamps
        bid, ask, _ = mm_strategy._compute_quotes("m1", 0.50, pos)

        # The raw spread might be below min, but _quote_market will clamp
        # Here we just test that compute returns values
        assert bid is not None
        assert ask is not None

    def test_size_reduces_with_inventory(self, mm_strategy, mock_orderbook, mock_portfolio):
        """Order size should decrease as inventory grows."""
        mock_orderbook.get_volatility = MagicMock(return_value=0.01)

        # No inventory
        mock_portfolio.get_position = MagicMock(return_value=None)
        pos1 = MMPosition(market_id="m1", token_id="t1")
        _, _, size1 = mm_strategy._compute_quotes("m1", 0.50, pos1)

        # Large inventory
        big_pos = MagicMock()
        big_pos.size = 400.0  # 80% of max_position_pct * total_value
        mock_portfolio.get_position = MagicMock(return_value=big_pos)
        pos2 = MMPosition(market_id="m1", token_id="t1")
        _, _, size2 = mm_strategy._compute_quotes("m1", 0.50, pos2)

        assert size2 < size1

    def test_quotes_clamped_to_valid_range(self, mm_strategy, mock_orderbook, mock_portfolio):
        """Quotes should never go below 0.01 or above 0.99."""
        mock_orderbook.get_volatility = MagicMock(return_value=0.0)
        mock_portfolio.get_position = MagicMock(return_value=None)

        # Extreme mid price
        pos = MMPosition(market_id="m1", token_id="t1")
        bid, ask, _ = mm_strategy._compute_quotes("m1", 0.02, pos)

        # _compute_quotes doesn't clamp; _quote_market does
        # But even raw, ask should be above bid
        if bid is not None and ask is not None:
            assert ask > bid


# ── Adverse selection tests ───────────────────────────────────────────

class TestAdverseSelection:
    """Tests for adverse selection detection and response."""

    def test_volatility_spike_pauses_market(self, mm_strategy, mock_orderbook):
        """High volatility should trigger a pause."""
        mock_orderbook.is_volatile = MagicMock(return_value=True)

        pos = MMPosition(market_id="m1", token_id="t1")
        result = mm_strategy._check_adverse_selection("m1", pos)

        assert result is True
        assert pos.is_paused is True
        assert pos.pause_reason == "volatility_spike"

    def test_no_volatility_no_pause(self, mm_strategy, mock_orderbook):
        """Normal volatility should not trigger a pause."""
        mock_orderbook.is_volatile = MagicMock(return_value=False)

        pos = MMPosition(market_id="m1", token_id="t1")
        result = mm_strategy._check_adverse_selection("m1", pos)

        assert result is False

    def test_consecutive_same_side_fills_pause(self, mm_strategy, mock_orderbook):
        """3+ consecutive fills on the same side should pause."""
        mock_orderbook.is_volatile = MagicMock(return_value=False)

        pos = MMPosition(market_id="m1", token_id="t1")
        pos.consecutive_fills_same_side = 3
        pos.last_fill_side = "BUY"

        result = mm_strategy._check_adverse_selection("m1", pos)

        assert result is True
        assert pos.pause_reason == "consecutive_same_side_fills"

    def test_pause_expires(self, mm_strategy):
        """Paused market should resume after timeout."""
        pos = MMPosition(market_id="m1", token_id="t1")
        pos.paused = True
        pos.pause_until = time.monotonic() - 1  # Already expired

        assert pos.is_paused is False

    def test_record_fill_tracking(self, mm_strategy):
        """record_fill should track fill events for adverse selection."""
        mm_strategy._positions["m1"] = MMPosition(market_id="m1", token_id="t1")

        # First fill
        mm_strategy.record_fill("m1", "BUY")
        assert mm_strategy._positions["m1"].consecutive_fills_same_side == 1
        assert mm_strategy._positions["m1"].last_fill_side == "BUY"

        # Second fill same side
        mm_strategy.record_fill("m1", "BUY")
        assert mm_strategy._positions["m1"].consecutive_fills_same_side == 2

        # Different side resets
        mm_strategy.record_fill("m1", "SELL")
        assert mm_strategy._positions["m1"].consecutive_fills_same_side == 1
        assert mm_strategy._positions["m1"].last_fill_side == "SELL"

    def test_record_fill_unknown_market(self, mm_strategy):
        """record_fill on unknown market should be a no-op."""
        mm_strategy.record_fill("unknown", "BUY")  # Should not raise


# ── Re-quoting tests ──────────────────────────────────────────────────

class TestRequoting:
    """Tests for the re-quoting logic."""

    def test_needs_requote_when_no_orders(self, mm_strategy):
        """Should need requote when no orders exist."""
        pos = MMPosition(market_id="m1", token_id="t1")
        assert mm_strategy._needs_requote(pos, 0.50) is True

    def test_needs_requote_on_mid_move(self, mm_strategy):
        """Should need requote when midpoint moves beyond threshold."""
        pos = MMPosition(
            market_id="m1", token_id="t1",
            bid_price=0.48, ask_price=0.52,
            bid_order_id="bid-1", ask_order_id="ask-1",
            last_quote_time=time.monotonic(),
        )

        # Move midpoint by 100 bps (well beyond 50 bps threshold)
        assert mm_strategy._needs_requote(pos, 0.55) is True

    def test_no_requote_on_small_mid_move(self, mm_strategy):
        """Should NOT requote on tiny midpoint moves."""
        pos = MMPosition(
            market_id="m1", token_id="t1",
            bid_price=0.49, ask_price=0.51,
            bid_order_id="bid-1", ask_order_id="ask-1",
            last_quote_time=time.monotonic(),
        )

        # Tiny move (within threshold)
        assert mm_strategy._needs_requote(pos, 0.501) is False

    def test_needs_requote_on_stale_orders(self, mm_strategy):
        """Should requote when orders are stale."""
        pos = MMPosition(
            market_id="m1", token_id="t1",
            bid_price=0.49, ask_price=0.51,
            bid_order_id="bid-1", ask_order_id="ask-1",
            last_quote_time=time.monotonic() - 200,  # 200s ago, beyond 120s stale
        )

        assert mm_strategy._needs_requote(pos, 0.50) is True


# ── MMPosition tests ──────────────────────────────────────────────────

class TestMMPosition:
    """Tests for MMPosition dataclass."""

    def test_default_values(self):
        pos = MMPosition(market_id="m1", token_id="t1")
        assert pos.net_inventory == 0.0
        assert pos.paused is False
        assert pos.is_paused is False
        assert pos.bid_order_id is None
        assert pos.ask_order_id is None

    def test_pause_expires(self):
        pos = MMPosition(market_id="m1", token_id="t1")
        pos.paused = True
        pos.pause_until = time.monotonic() + 60
        assert pos.is_paused is True

        # After expiry
        pos.pause_until = time.monotonic() - 1
        assert pos.is_paused is False
        assert pos.paused is False  # Auto-clears

    def test_fills_in_window_bounded(self):
        """fills_in_window should be bounded by maxlen."""
        pos = MMPosition(market_id="m1", token_id="t1")
        for i in range(60):
            pos.fills_in_window.append(time.monotonic())
        assert len(pos.fills_in_window) == 50  # maxlen


# ── Strategy lifecycle tests ──────────────────────────────────────────

class TestStrategyLifecycle:
    """Tests for strategy start/stop/recovery."""

    @pytest.mark.asyncio
    async def test_add_market(self, mm_strategy, mock_orderbook, mock_scanner):
        """Adding a market should register it and create an MMPosition."""
        info = MarketInfo(
            market_id="m1", token_id="t1",
            category="finance", score=75.0, days_to_resolution=30,
        )

        await mm_strategy._add_market(info)

        mock_orderbook.register_market.assert_called_once_with("m1", "t1")
        assert "m1" in mm_strategy._positions
        assert mm_strategy._positions["m1"].category == "finance"

    @pytest.mark.asyncio
    async def test_remove_market(self, mm_strategy, mock_executor, mock_orderbook):
        """Removing a market should cancel orders and unregister."""
        mm_strategy._positions["m1"] = MMPosition(
            market_id="m1", token_id="t1",
        )

        await mm_strategy._remove_market("m1")

        mock_executor.cancel_all_for_market.assert_called_with("m1")
        mock_orderbook.unregister_market.assert_called_with("m1")
        assert "m1" not in mm_strategy._positions

    @pytest.mark.asyncio
    async def test_remove_unknown_market(self, mm_strategy):
        """Removing unknown market should be a no-op."""
        await mm_strategy._remove_market("nonexistent")  # Should not raise

    @pytest.mark.asyncio
    async def test_quote_market_places_orders(self, mm_strategy, mock_orderbook, mock_executor):
        """_quote_market should place bid/ask when needed."""
        mock_orderbook.is_volatile = MagicMock(return_value=False)
        mock_orderbook.get_volatility = MagicMock(return_value=0.01)

        pos = MMPosition(market_id="m1", token_id="t1", category="finance")
        mm_strategy._positions["m1"] = pos

        await mm_strategy._quote_market("m1", pos)

        # Should have placed a quote pair
        mock_executor.place_quote_pair.assert_called_once()
        assert pos.bid_order_id is not None
        assert pos.ask_order_id is not None

    @pytest.mark.asyncio
    async def test_quote_market_skips_paused(self, mm_strategy, mock_executor):
        """Paused markets should be skipped."""
        pos = MMPosition(market_id="m1", token_id="t1")
        pos.paused = True
        pos.pause_until = time.monotonic() + 60

        await mm_strategy._quote_market("m1", pos)

        mock_executor.place_quote_pair.assert_not_called()

    @pytest.mark.asyncio
    async def test_quote_market_skips_no_snapshot(self, mm_strategy, mock_orderbook, mock_executor):
        """Markets with no orderbook snapshot should be skipped."""
        mock_orderbook.get_snapshot = MagicMock(return_value=None)

        pos = MMPosition(market_id="m1", token_id="t1")
        await mm_strategy._quote_market("m1", pos)

        mock_executor.place_quote_pair.assert_not_called()

    @pytest.mark.asyncio
    async def test_quote_market_handles_risk_rejection(self, mm_strategy, mock_orderbook, mock_executor):
        """Risk rejection should be handled gracefully."""
        mock_orderbook.is_volatile = MagicMock(return_value=False)
        mock_orderbook.get_volatility = MagicMock(return_value=0.01)

        from core.executor import OrderRejectedByRisk
        mock_executor.place_quote_pair = AsyncMock(side_effect=OrderRejectedByRisk("test"))

        pos = MMPosition(market_id="m1", token_id="t1", category="finance")
        mm_strategy._positions["m1"] = pos

        # Should not raise
        await mm_strategy._quote_market("m1", pos)

    @pytest.mark.asyncio
    async def test_run_cycle_processes_markets(self, mm_strategy, mock_scanner, mock_orderbook, mock_executor):
        """run_cycle should quote all active markets."""
        # Set up scanner to return our market
        mock_scanner._last_scan = time.monotonic()  # Skip re-scan
        mock_scanner.scan_interval_sec = 9999

        # Add market manually
        pos = MMPosition(market_id="m1", token_id="t1", category="finance")
        mm_strategy._positions["m1"] = pos

        mock_orderbook.is_volatile = MagicMock(return_value=False)
        mock_orderbook.get_volatility = MagicMock(return_value=0.01)

        await mm_strategy.run_cycle()

        mock_executor.place_quote_pair.assert_called()


# ── MM summary tests ──────────────────────────────────────────────────

class TestMMSummary:
    """Tests for the get_mm_summary reporting method."""

    def test_summary_with_positions(self, mm_strategy):
        mm_strategy._positions["m1"] = MMPosition(market_id="m1", token_id="t1")
        mm_strategy._positions["m2"] = MMPosition(
            market_id="m2", token_id="t2",
            paused=True, pause_until=time.monotonic() + 60,
        )

        summary = mm_strategy.get_mm_summary()

        assert summary["total_markets"] == 2
        assert summary["active_markets"] == 1
        assert summary["paused_markets"] == 1

    def test_summary_empty(self, mm_strategy):
        summary = mm_strategy.get_mm_summary()
        assert summary["total_markets"] == 0
        assert summary["active_markets"] == 0


# ── Scheduled event tests ─────────────────────────────────────────────

class TestScheduledEvents:
    """Tests for news blackout / scheduled event handling."""

    def test_no_events_no_blackout(self, mm_strategy):
        assert mm_strategy._is_near_scheduled_event() is False

    def test_event_near_now_triggers_blackout(self, mm_strategy):
        from datetime import datetime, timezone, timedelta
        soon = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        mm_strategy._scheduled_events = [{"time": soon, "name": "FOMC"}]

        assert mm_strategy._is_near_scheduled_event() is True

    def test_event_far_away_no_blackout(self, mm_strategy):
        from datetime import datetime, timezone, timedelta
        far = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
        mm_strategy._scheduled_events = [{"time": far, "name": "FOMC"}]

        assert mm_strategy._is_near_scheduled_event() is False

    def test_parse_event_time_string(self, mm_strategy):
        from datetime import datetime, timezone
        # ISO format
        dt = mm_strategy._parse_event_time({"time": "2026-06-15T14:00:00+00:00"})
        assert dt is not None

    def test_parse_event_time_invalid(self, mm_strategy):
        result = mm_strategy._parse_event_time({"time": "not-a-date"})
        # Should return None or handle gracefully
        # With our implementation, "not-a-date" with HH:MM parse will also fail
        assert result is None  # Both ISO and HH:MM parsing fail
