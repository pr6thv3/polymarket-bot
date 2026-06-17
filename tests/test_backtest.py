"""Tests for the backtesting engine (core/backtest.py)."""

import asyncio
import json
import os
import tempfile
from unittest.mock import MagicMock

import pytest

from core.backtest import (
    BacktestEngine,
    BacktestFill,
    BacktestPortfolio,
    BacktestResult,
    BacktestRiskManager,
    BacktestTick,
    BacktestTrade,
)


class TestBacktestTick:
    """Test BacktestTick data structure."""

    def test_best_bid(self):
        tick = BacktestTick(
            timestamp=1000.0,
            market_id="m1",
            bids=[(0.55, 100), (0.54, 200)],
            asks=[(0.56, 80)],
        )
        assert tick.best_bid == 0.55

    def test_best_ask(self):
        tick = BacktestTick(
            timestamp=1000.0,
            market_id="m1",
            bids=[(0.55, 100)],
            asks=[(0.56, 80), (0.57, 150)],
        )
        assert tick.best_ask == 0.56

    def test_empty_book(self):
        tick = BacktestTick(
            timestamp=1000.0,
            market_id="m1",
        )
        assert tick.best_bid is None
        assert tick.best_ask is None


class TestBacktestFill:
    """Test BacktestFill cost calculation."""

    def test_buy_cost_includes_fee(self):
        fill = BacktestFill(
            timestamp=1000.0,
            market_id="m1",
            side="BUY",
            price=0.55,
            size=10.0,
            fee_usd=0.50,
        )
        expected = 0.55 * 10.0 + 0.50
        assert abs(fill.cost - expected) < 1e-8

    def test_sell_cost_subtracts_fee(self):
        fill = BacktestFill(
            timestamp=1000.0,
            market_id="m1",
            side="SELL",
            price=0.45,
            size=10.0,
            fee_usd=0.30,
        )
        expected = 0.45 * 10.0 - 0.30
        assert abs(fill.cost - expected) < 1e-8


class TestBacktestTrade:
    """Test BacktestTrade calculations."""

    def test_hold_time(self):
        trade = BacktestTrade(
            market_id="m1",
            entry_price=0.50,
            exit_price=0.60,
            size=10.0,
            entry_time=100.0,
            exit_time=200.0,
            pnl_usd=1.0,
        )
        assert trade.hold_time_sec == 100.0

    def test_return_pct(self):
        trade = BacktestTrade(
            market_id="m1",
            entry_price=0.50,
            exit_price=0.60,
            size=10.0,
            pnl_usd=1.0,
        )
        expected = 1.0 / (0.50 * 10.0)
        assert abs(trade.return_pct - expected) < 1e-8

    def test_zero_entry_price(self):
        trade = BacktestTrade(market_id="m1", entry_price=0.0)
        assert trade.return_pct == 0.0


class TestBacktestPortfolio:
    """Test simulated portfolio for backtesting."""

    def test_initial_state(self):
        portfolio = BacktestPortfolio(starting_capital=1000.0)
        assert portfolio.usdc == 1000.0
        assert portfolio.free_usdc == 1000.0
        assert portfolio.locked_usdc == 0.0
        assert len(portfolio.positions) == 0

    @pytest.mark.asyncio
    async def test_lock_usdc(self):
        portfolio = BacktestPortfolio(starting_capital=1000.0)
        assert await portfolio.lock_usdc(200.0) is True
        assert portfolio.free_usdc == 800.0
        assert portfolio.locked_usdc == 200.0

    @pytest.mark.asyncio
    async def test_lock_insufficient_usdc(self):
        portfolio = BacktestPortfolio(starting_capital=100.0)
        assert await portfolio.lock_usdc(200.0) is False

    @pytest.mark.asyncio
    async def test_unlock_usdc(self):
        portfolio = BacktestPortfolio(starting_capital=1000.0)
        await portfolio.lock_usdc(200.0)
        await portfolio.unlock_usdc(100.0)
        assert portfolio.locked_usdc == 100.0
        assert portfolio.free_usdc == 900.0

    @pytest.mark.asyncio
    async def test_update_position_buy(self):
        portfolio = BacktestPortfolio(starting_capital=1000.0)
        await portfolio.lock_usdc(50.0)
        await portfolio.update_position("m1", 10.0, 0.50)
        pos = portfolio.positions.get("m1")
        assert pos is not None
        assert abs(pos["size"] - 10.0) < 1e-8
        assert abs(pos["avg_price"] - 0.50) < 1e-8

    @pytest.mark.asyncio
    async def test_update_position_sell_closes(self):
        portfolio = BacktestPortfolio(starting_capital=1000.0)
        await portfolio.lock_usdc(50.0)
        await portfolio.update_position("m1", 10.0, 0.50)
        await portfolio.update_position("m1", -10.0, 0.60)
        # Position should be cleaned up at zero
        assert "m1" not in portfolio.positions

    def test_get_position(self):
        portfolio = BacktestPortfolio(starting_capital=1000.0)

        @pytest.mark.asyncio
        async def _inner():
            await portfolio.lock_usdc(50.0)
            await portfolio.update_position("m1", 10.0, 0.50)
            pos = portfolio.get_position("m1")
            assert pos is not None
            assert pos.size == 10.0

        asyncio.run(_inner())

    def test_get_position_nonexistent(self):
        portfolio = BacktestPortfolio(starting_capital=1000.0)
        assert portfolio.get_position("nonexistent") is None

    def test_record_equity(self):
        portfolio = BacktestPortfolio(starting_capital=1000.0)
        portfolio.record_equity(100.0)
        portfolio.record_equity(200.0)
        assert len(portfolio.equity_curve) == 2

    def test_max_drawdown_pct(self):
        portfolio = BacktestPortfolio(starting_capital=1000.0)
        portfolio.record_equity(100.0)  # equity=1000
        portfolio.usdc = 900.0
        portfolio.record_equity(200.0)  # equity=900
        portfolio.usdc = 950.0
        portfolio.record_equity(300.0)  # equity=950
        dd = portfolio.get_max_drawdown_pct()
        assert dd > 0  # Should have a drawdown

    def test_add_fee(self):
        portfolio = BacktestPortfolio(starting_capital=1000.0)
        portfolio.add_fee(1.50)
        assert portfolio.usdc == 998.5
        assert portfolio.total_fees == 1.50


class TestBacktestRiskManager:
    """Test risk manager for backtesting."""

    @pytest.mark.asyncio
    async def test_allow_order_default(self):
        risk = BacktestRiskManager({})
        ok, reason = await risk.allow_order("m1", "BUY", 0.5, 10.0)
        assert ok is True
        assert reason == ""

    def test_halt_trigger(self):
        config = {"risk_management": {"halt_at_loss_pct": 0.40}}
        risk = BacktestRiskManager(config)
        portfolio = BacktestPortfolio(starting_capital=1000.0)
        portfolio.usdc = 500.0  # 50% loss
        assert risk.check_halt(portfolio) is True
        assert risk._halted is True

    def test_halt_not_triggered(self):
        config = {"risk_management": {"halt_at_loss_pct": 0.40}}
        risk = BacktestRiskManager(config)
        portfolio = BacktestPortfolio(starting_capital=1000.0)
        portfolio.usdc = 900.0  # 10% loss
        assert risk.check_halt(portfolio) is False

    @pytest.mark.asyncio
    async def test_halted_rejects_orders(self):
        risk = BacktestRiskManager({})
        risk._halted = True
        ok, reason = await risk.allow_order("m1", "BUY", 0.5, 10.0)
        assert ok is False


class TestBacktestEngine:
    """Test the main backtesting engine."""

    def _make_engine(self) -> BacktestEngine:
        config = {
            "backtesting": {
                "starting_capital": 1000.0,
                "slippage_bps": 5.0,
            },
        }
        return BacktestEngine(config)

    def test_generate_sample_data(self):
        engine = self._make_engine()
        ticks = engine.generate_sample_data(
            market_id="test",
            start_price=0.50,
            num_ticks=100,
        )
        assert len(ticks) == 100
        assert all(t.market_id == "test" for t in ticks)
        # Prices should be in (0.01, 0.99)
        assert all(0.01 <= t.mid <= 0.99 for t in ticks)

    def test_load_nonexistent_file(self):
        engine = self._make_engine()
        ticks = engine.load_market_data("nonexistent_market")
        assert ticks == []

    def test_load_valid_jsonl(self):
        engine = self._make_engine()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            f.write(json.dumps({
                "timestamp": 1717000000,
                "market_id": "m1",
                "bids": [[0.54, 100], [0.53, 200]],
                "asks": [[0.56, 80], [0.57, 150]],
                "mid": 0.55,
                "volume_24h": 5000,
            }) + "\n")
            f.write(json.dumps({
                "timestamp": 1717000005,
                "market_id": "m1",
                "bids": [[0.55, 100]],
                "asks": [[0.56, 80]],
                "mid": 0.555,
                "volume_24h": 5500,
            }) + "\n")
            tmppath = f.name

        try:
            ticks = engine.load_market_data("m1", data_file=tmppath)
            assert len(ticks) == 2
            assert ticks[0].timestamp < ticks[1].timestamp
            assert ticks[0].best_bid == 0.54
            assert ticks[0].best_ask == 0.56
        finally:
            os.unlink(tmppath)

    @pytest.mark.asyncio
    async def test_run_market_making(self):
        engine = self._make_engine()
        ticks = engine.generate_sample_data(
            market_id="test",
            start_price=0.50,
            num_ticks=500,
            volatility=0.01,
            spread_bps=200,
        )
        result = await engine.run_market_making(
            ticks=ticks,
            starting_capital=1000.0,
            base_spread_bps=200,
            order_size_usd=15.0,
        )
        assert result.strategy_name == "MarketMaking"
        assert result.starting_capital == 1000.0
        assert result.total_ticks == 500
        assert len(result.equity_curve) > 0

    def test_print_report(self):
        engine = self._make_engine()
        result = BacktestResult(
            strategy_name="Test",
            starting_capital=1000.0,
            ending_capital=1050.0,
            total_pnl=50.0,
            total_fees=1.0,
            net_pnl=49.0,
            total_trades=10,
            winning_trades=7,
            losing_trades=3,
            win_rate=0.7,
            profit_factor=2.5,
        )
        report = engine.print_report(result)
        assert "Test" in report
        assert "1,000.00" in report
        assert "50.00" in report

    def test_save_results(self):
        engine = self._make_engine()
        result = BacktestResult(
            strategy_name="Test",
            starting_capital=1000.0,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = engine.save_results(result, output_dir=tmpdir)
            assert os.path.exists(path)
            with open(path, "r") as f:
                data = json.load(f)
            assert data["strategy_name"] == "Test"
            assert data["starting_capital"] == 1000.0

    def test_compute_trade_stats_empty(self):
        engine = self._make_engine()
        result = BacktestResult()
        engine._compute_trade_stats(result, [])
        assert result.total_trades == 0
        assert result.win_rate == 0.0

    def test_compute_trade_stats_with_trades(self):
        engine = self._make_engine()
        result = BacktestResult()
        trades = [
            BacktestTrade(market_id="m1", pnl_usd=1.0, entry_price=0.50, exit_price=0.60, size=10.0, entry_time=100, exit_time=200),
            BacktestTrade(market_id="m1", pnl_usd=-0.5, entry_price=0.50, exit_price=0.45, size=10.0, entry_time=300, exit_time=400),
            BacktestTrade(market_id="m1", pnl_usd=2.0, entry_price=0.50, exit_price=0.70, size=10.0, entry_time=500, exit_time=600),
        ]
        engine._compute_trade_stats(result, trades)
        assert result.total_trades == 3
        assert result.winning_trades == 2
        assert result.losing_trades == 1
        assert abs(result.win_rate - 2 / 3) < 1e-8
        assert result.profit_factor > 1.0  # More profit than loss
