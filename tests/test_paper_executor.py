"""Tests for the paper-trading executor (core/paper_executor.py)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.paper_executor import (
    PaperOrder,
    PaperPortfolio,
    PaperTrade,
    PaperExecutor,
    PAPER_TAG,
)
from core.executor import OrderRejectedByRisk


class TestPaperOrder:
    """Test PaperOrder data structure."""

    def test_defaults(self):
        order = PaperOrder(
            order_id="p-1",
            market_id="m1",
            token_id="t1",
            side="BUY",
            price=0.55,
            size=10.0,
        )
        assert order.post_only is True
        assert order.status == "open"
        assert order.filled_size == 0.0
        assert order.filled_price == 0.0

    def test_is_open(self):
        order = PaperOrder(
            order_id="p-1", market_id="m1", token_id="t1",
            side="BUY", price=0.55, size=10.0, status="open",
        )
        assert order.is_open is True

    def test_is_not_open_when_filled(self):
        order = PaperOrder(
            order_id="p-1", market_id="m1", token_id="t1",
            side="BUY", price=0.55, size=10.0, status="filled",
        )
        assert order.is_open is False

    def test_is_terminal(self):
        for status in ("filled", "cancelled", "rejected", "expired"):
            order = PaperOrder(
                order_id="p-1", market_id="m1", token_id="t1",
                side="BUY", price=0.55, size=10.0, status=status,
            )
            assert order.is_terminal is True

    def test_is_not_terminal_when_open(self):
        order = PaperOrder(
            order_id="p-1", market_id="m1", token_id="t1",
            side="BUY", price=0.55, size=10.0, status="open",
        )
        assert order.is_terminal is False

    def test_partial_status(self):
        order = PaperOrder(
            order_id="p-1", market_id="m1", token_id="t1",
            side="BUY", price=0.55, size=10.0, status="partial",
        )
        assert order.is_open is False
        assert order.is_terminal is False


class TestPaperPortfolio:
    """Test virtual portfolio for paper trading."""

    def _make_portfolio(self, capital=1000.0, config=None):
        if config is None:
            config = {}
        return PaperPortfolio(starting_capital=capital, config=config)

    def test_initial_state(self):
        pp = self._make_portfolio()
        assert pp.usdc == 1000.0
        assert pp.free_usdc == 1000.0
        assert pp.locked_usdc == 0.0
        assert len(pp.positions) == 0

    def test_lock_usdc(self):
        pp = self._make_portfolio()
        assert pp.lock_usdc(200.0) is True
        assert pp.free_usdc == 800.0
        assert pp.locked_usdc == 200.0

    def test_lock_insufficient(self):
        pp = self._make_portfolio(capital=100.0)
        assert pp.lock_usdc(200.0) is False

    def test_unlock_usdc(self):
        pp = self._make_portfolio()
        pp.lock_usdc(200.0)
        pp.unlock_usdc(100.0)
        assert pp.locked_usdc == 100.0
        assert pp.free_usdc == 900.0

    def test_unlock_cant_go_negative(self):
        pp = self._make_portfolio()
        pp.unlock_usdc(500.0)  # Unlock more than locked
        assert pp.locked_usdc == 0.0

    def test_process_fill_buy(self):
        pp = self._make_portfolio()
        pp.lock_usdc(5.50)
        fee_usd, rebate_usd = pp.process_fill("m1", "BUY", 0.55, 10.0, "finance")
        # Maker fee = 0% → fee_usd = 0
        assert fee_usd == 0.0
        # Rebate = price * size * taker_fee_pct * rebate_rate
        # finance: taker=0.01, rebate=0.50
        expected_rebate = 0.55 * 10.0 * 0.01 * 0.50
        assert abs(rebate_usd - expected_rebate) < 1e-8
        # Position should exist
        assert "m1" in pp.positions
        pos = pp.positions["m1"]
        assert abs(pos["size"] - 10.0) < 1e-8

    def test_process_fill_sell(self):
        pp = self._make_portfolio()
        # First buy to have a position
        pp.lock_usdc(5.50)
        pp.process_fill("m1", "BUY", 0.55, 10.0, "finance")
        # Then sell
        fee_usd, rebate_usd = pp.process_fill("m1", "SELL", 0.60, 10.0, "finance")
        # Maker fee = 0%
        assert fee_usd == 0.0
        # Position should be closed
        assert "m1" not in pp.positions
        # Realized P&L
        assert pp.realized_pnl != 0.0

    def test_total_value(self):
        pp = self._make_portfolio()
        pp.lock_usdc(5.50)
        pp.process_fill("m1", "BUY", 0.55, 10.0, "finance")
        # total_value = usdc + unrealized (position size * avg_price)
        assert pp.total_value > 0

    def test_get_position_nonexistent(self):
        pp = self._make_portfolio()
        assert pp.get_position("nonexistent") is None

    def test_get_position_exists(self):
        pp = self._make_portfolio()
        pp.lock_usdc(5.50)
        pp.process_fill("m1", "BUY", 0.55, 10.0, "finance")
        pos = pp.get_position("m1")
        assert pos is not None
        assert pos.size == 10.0
        assert pos.category == "finance"

    def test_record_equity(self):
        pp = self._make_portfolio()
        pp.record_equity(100.0)
        pp.record_equity(200.0)
        assert len(pp.equity_curve) == 2

    def test_get_stats(self):
        pp = self._make_portfolio()
        stats = pp.get_stats()
        assert stats["starting_capital"] == 1000.0
        assert stats["current_usdc"] == 1000.0
        assert stats["open_positions"] == 0
        assert "return_pct" in stats

    def test_custom_fee_config(self):
        config = {
            "taker_fees": {"custom_cat": 0.05},
            "rebate_rates": {"custom_cat": 0.30},
        }
        pp = PaperPortfolio(starting_capital=1000.0, config=config)
        pp.lock_usdc(5.0)
        fee_usd, rebate_usd = pp.process_fill("m1", "BUY", 0.50, 10.0, "custom_cat")
        # Maker → fee = 0
        assert fee_usd == 0.0
        # Rebate = 0.50*10*0.05*0.30 = 0.075
        expected_rebate = 0.50 * 10.0 * 0.05 * 0.30
        assert abs(rebate_usd - expected_rebate) < 1e-8

    def test_process_fill_rejects_sell_without_inventory(self):
        pp = self._make_portfolio()

        with pytest.raises(ValueError, match="Cannot paper-sell"):
            pp.process_fill("m1", "SELL", 0.60, 10.0, "finance")

        assert pp.usdc == 1000.0
        assert pp.realized_pnl == 0.0
        assert pp.positions == {}

    def test_process_fill_sell_realizes_only_against_existing_inventory(self):
        pp = self._make_portfolio()
        pp.lock_usdc(5.50)
        pp.process_fill("m1", "BUY", 0.55, 10.0, "finance")

        pp.process_fill("m1", "SELL", 0.60, 10.0, "finance")

        assert "m1" not in pp.positions
        assert pp.realized_pnl == pytest.approx(0.50)


class TestPaperTrade:
    """Test PaperTrade data structure."""

    def test_hold_time(self):
        trade = PaperTrade(
            market_id="m1",
            entry_side="BUY",
            entry_price=0.50,
            exit_price=0.60,
            size=10.0,
            pnl_usd=1.0,
            fee_usd=0.0,
            entry_time=100.0,
            exit_time=200.0,
        )
        assert trade.hold_time_sec == 100.0


class TestPaperExecutorFillLogic:
    """Test paper executor fill logic realism."""

    @pytest.fixture
    def setup_executor(self, sample_config):
        real_executor = MagicMock()
        real_executor.risk_manager = MagicMock()
        # Allow all orders by default
        real_executor.risk_manager.allow_order = AsyncMock(return_value=(True, ""))

        portfolio = PaperPortfolio(starting_capital=1000.0, config=sample_config)
        orderbook = MagicMock()

        # Fix fill probability to 100% and partial fill probability to 0% to avoid randomness in tests
        sample_config["paper_trading"] = {
            "fill_probability": 1.0,
            "partial_fill_probability": 0.0,
            "slippage_bps": 0.0,
        }

        executor = PaperExecutor(
            real_executor=real_executor,
            paper_portfolio=portfolio,
            orderbook_manager=orderbook,
            config=sample_config,
        )
        return executor, orderbook

    @pytest.mark.asyncio
    async def test_maker_order_does_not_fill_immediately(self, setup_executor):
        executor, orderbook = setup_executor

        # Set up orderbook snapshot: best_bid=0.49, best_ask=0.51
        from core.orderbook import OrderBookSnapshot, BookLevel
        snapshot = OrderBookSnapshot(
            market_id="m1",
            token_id="t1",
            bids=[BookLevel(price=0.49, size=100)],
            asks=[BookLevel(price=0.51, size=100)],
            last_update=100.0,
        )
        orderbook.get_snapshot.return_value = snapshot

        # Place BUY limit order at 0.48 (maker order, does not cross spread)
        order_id = await executor.place_order(
            market_id="m1",
            token_id="t1",
            side="BUY",
            price=0.48,
            size=10.0,
            category="finance",
            post_only=True,
        )

        assert order_id is not None
        order = executor._orders[order_id]
        assert order.status == "open"  # Sitting open in book
        assert order.placed_at_snapshot_time == 100.0

    @pytest.mark.asyncio
    async def test_taker_order_fills_immediately(self, setup_executor):
        executor, orderbook = setup_executor

        # Set up orderbook snapshot: best_bid=0.49, best_ask=0.51
        from core.orderbook import OrderBookSnapshot, BookLevel
        snapshot = OrderBookSnapshot(
            market_id="m1",
            token_id="t1",
            bids=[BookLevel(price=0.49, size=100)],
            asks=[BookLevel(price=0.51, size=100)],
            last_update=100.0,
        )
        orderbook.get_snapshot.return_value = snapshot

        # Place BUY limit order at 0.52 (taker order, crosses ask)
        order_id = await executor.place_order(
            market_id="m1",
            token_id="t1",
            side="BUY",
            price=0.52,
            size=10.0,
            category="finance",
            post_only=False, # not post_only
        )

        assert order_id is not None
        order = executor._orders[order_id]
        assert order.status == "filled"
        assert order.filled_price == 0.51  # Fills at the best ask (slippage_bps is 0)

    @pytest.mark.asyncio
    async def test_taker_order_post_only_rejected(self, setup_executor):
        executor, orderbook = setup_executor

        # Set up orderbook snapshot: best_bid=0.49, best_ask=0.51
        from core.orderbook import OrderBookSnapshot, BookLevel
        snapshot = OrderBookSnapshot(
            market_id="m1",
            token_id="t1",
            bids=[BookLevel(price=0.49, size=100)],
            asks=[BookLevel(price=0.51, size=100)],
            last_update=100.0,
        )
        orderbook.get_snapshot.return_value = snapshot

        # Place BUY limit order at 0.52 with post_only=True (should be rejected)
        order_id = await executor.place_order(
            market_id="m1",
            token_id="t1",
            side="BUY",
            price=0.52,
            size=10.0,
            category="finance",
            post_only=True,
        )

        assert order_id is not None
        order = executor._orders[order_id]
        assert order.status == "rejected"

    @pytest.mark.asyncio
    async def test_maker_order_no_fill_on_same_snapshot_even_if_matching_price(self, setup_executor):
        executor, orderbook = setup_executor

        # 1. Placement snapshot: best_bid=0.49, best_ask=0.51
        from core.orderbook import OrderBookSnapshot, BookLevel
        snapshot = OrderBookSnapshot(
            market_id="m1",
            token_id="t1",
            bids=[BookLevel(price=0.49, size=100)],
            asks=[BookLevel(price=0.51, size=100)],
            last_update=100.0,
        )
        orderbook.get_snapshot.return_value = snapshot

        order_id = await executor.place_order(
            market_id="m1",
            token_id="t1",
            side="BUY",
            price=0.48,
            size=10.0,
            category="finance",
            post_only=True,
        )

        assert order_id is not None
        order = executor._orders[order_id]
        assert order.status == "open"

        # 2. Modify snapshot prices to satisfy the fill condition (best_ask=0.48)
        # BUT keep last_update=100.0 (same snapshot)
        snapshot_same_time = OrderBookSnapshot(
            market_id="m1",
            token_id="t1",
            bids=[BookLevel(price=0.49, size=100)],
            asks=[BookLevel(price=0.48, size=100)],
            last_update=100.0,
        )
        orderbook.get_snapshot.return_value = snapshot_same_time

        # Trigger open orders processing
        filled_count = await executor.process_open_orders()
        assert filled_count == 0  # Should NOT fill because last_update is same
        assert order.status == "open"

        # 3. Modify snapshot to subsequent time (last_update=101.0)
        snapshot_subsequent = OrderBookSnapshot(
            market_id="m1",
            token_id="t1",
            bids=[BookLevel(price=0.49, size=100)],
            asks=[BookLevel(price=0.48, size=100)],
            last_update=101.0,
        )
        orderbook.get_snapshot.return_value = snapshot_subsequent

        # Trigger open orders processing
        filled_count2 = await executor.process_open_orders()
        assert filled_count2 == 1  # Should fill now!
        assert order.status == "filled"

    @pytest.mark.asyncio
    async def test_maker_order_fills_on_subsequent_snapshot(self, setup_executor):
        executor, orderbook = setup_executor

        # 1. Placement snapshot: best_bid=0.49, best_ask=0.51
        from core.orderbook import OrderBookSnapshot, BookLevel
        snapshot1 = OrderBookSnapshot(
            market_id="m1",
            token_id="t1",
            bids=[BookLevel(price=0.49, size=100)],
            asks=[BookLevel(price=0.51, size=100)],
            last_update=100.0,
        )
        orderbook.get_snapshot.return_value = snapshot1

        order_id = await executor.place_order(
            market_id="m1",
            token_id="t1",
            side="BUY",
            price=0.48,
            size=10.0,
            category="finance",
            post_only=True,
        )

        assert order_id is not None
        order = executor._orders[order_id]
        assert order.status == "open"

        # 2. Subsequent snapshot: best_bid=0.49, best_ask=0.48, last_update=101.0
        # (Trades through/touches our bid at 0.48)
        snapshot2 = OrderBookSnapshot(
            market_id="m1",
            token_id="t1",
            bids=[BookLevel(price=0.49, size=100)],
            asks=[BookLevel(price=0.48, size=100)],
            last_update=101.0,
        )
        orderbook.get_snapshot.return_value = snapshot2

        # Trigger open orders processing
        filled_count = await executor.process_open_orders()
        assert filled_count == 1
        assert order.status == "filled"


    @pytest.mark.asyncio
    async def test_naked_sell_order_is_rejected_without_false_pnl(self, setup_executor):
        """A paper SELL cannot create proceeds/P&L without existing inventory."""
        executor, orderbook = setup_executor

        from core.orderbook import OrderBookSnapshot, BookLevel
        snapshot = OrderBookSnapshot(
            market_id="m1",
            token_id="t1",
            bids=[BookLevel(price=0.49, size=100)],
            asks=[BookLevel(price=0.51, size=100)],
            last_update=100.0,
        )
        orderbook.get_snapshot.return_value = snapshot

        with pytest.raises(OrderRejectedByRisk, match="Insufficient inventory"):
            await executor.place_order(
                market_id="m1",
                token_id="t1",
                side="SELL",
                price=0.48,
                size=10.0,
                category="finance",
                post_only=False,
            )

        assert executor._orders == {}
        assert executor._total_fills == 0
        assert executor._total_rejected == 1
        assert executor.paper_portfolio.usdc == 1000.0
        assert executor.paper_portfolio.total_value == 1000.0
        assert executor.paper_portfolio.realized_pnl == 0.0

    @pytest.mark.asyncio
    async def test_sell_order_reserves_existing_inventory_until_cancelled(self, setup_executor):
        executor, orderbook = setup_executor
        executor.paper_portfolio.lock_usdc(5.0)
        executor.paper_portfolio.process_fill("m1", "BUY", 0.50, 10.0, "finance")

        from core.orderbook import OrderBookSnapshot, BookLevel
        snapshot = OrderBookSnapshot(
            market_id="m1",
            token_id="t1",
            bids=[BookLevel(price=0.49, size=100)],
            asks=[BookLevel(price=0.51, size=100)],
            last_update=100.0,
        )
        orderbook.get_snapshot.return_value = snapshot

        order_id = await executor.place_order(
            market_id="m1",
            token_id="t1",
            side="SELL",
            price=0.60,
            size=10.0,
            category="finance",
            post_only=True,
        )

        assert order_id is not None
        assert executor.paper_portfolio.available_position("m1") == 0.0
        with pytest.raises(OrderRejectedByRisk, match="Insufficient inventory"):
            await executor.place_order(
                market_id="m1",
                token_id="t1",
                side="SELL",
                price=0.61,
                size=1.0,
                category="finance",
                post_only=True,
            )

        assert await executor.cancel_order(order_id) is True
        assert executor.paper_portfolio.available_position("m1") == pytest.approx(10.0)
