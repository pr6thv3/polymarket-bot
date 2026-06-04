"""Tests for the paper-trading executor (core/paper_executor.py)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.paper_executor import (
    PaperOrder,
    PaperPortfolio,
    PaperTrade,
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
