"""Tests for the executor (core/executor.py)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.client import ClobClient
from core.executor import Executor, OrderRejectedByRisk
from core.order_state import OrderRecord, OrderState, OrderStore
from core.portfolio import Portfolio
from core.risk import RiskManager


class TestExecutor:
    """Test Executor order placement and management."""

    def _make_executor(self, sample_config, mock_portfolio):
        """Create an Executor with mock components."""
        client = MagicMock(spec=ClobClient)
        client.create_order = AsyncMock(return_value="order-123")
        client.cancel_order = AsyncMock(return_value=True)
        client.amend_order = AsyncMock(return_value=True)
        client.cancel_all_for_market = AsyncMock(return_value=2)

        order_store = OrderStore()
        risk_manager = RiskManager(mock_portfolio, sample_config)

        executor = Executor(
            client=client,
            order_store=order_store,
            portfolio=mock_portfolio,
            risk_manager=risk_manager,
            config=sample_config,
        )
        return executor, client, order_store, risk_manager

    @pytest.mark.asyncio
    async def test_place_order_success(self, sample_config, mock_portfolio):
        executor, client, order_store, _ = self._make_executor(sample_config, mock_portfolio)

        order_id = await executor.place_order(
            market_id="m1",
            token_id="token-1",
            side="BUY",
            price=0.50,
            size=10.0,
            category="finance",
        )

        assert order_id == "order-123"
        client.create_order.assert_called_once_with(
            token_id="token-1",
            side="BUY",
            price=0.50,
            size=10.0,
            post_only=True,  # POST_ONLY by default
        )

        # Order should be in the store
        record = order_store.get("order-123")
        assert record is not None
        assert record.state == OrderState.OPEN

    @pytest.mark.asyncio
    async def test_place_order_post_only_by_default(self, sample_config, mock_portfolio):
        executor, client, _, _ = self._make_executor(sample_config, mock_portfolio)

        await executor.place_order(
            market_id="m1",
            token_id="token-1",
            side="BUY",
            price=0.50,
            size=10.0,
        )

        # Check post_only was True in the call
        call_kwargs = client.create_order.call_args
        assert call_kwargs.kwargs.get("post_only", True) is True

    @pytest.mark.asyncio
    async def test_place_order_rejected_by_risk(self, sample_config, mock_portfolio):
        executor, client, _, risk_manager = self._make_executor(sample_config, mock_portfolio)

        # Trigger a halt
        risk_manager._halt_triggered = True
        risk_manager._halt_reason = "Test halt"

        with pytest.raises(OrderRejectedByRisk):
            await executor.place_order(
                market_id="m1",
                token_id="token-1",
                side="BUY",
                price=0.50,
                size=10.0,
            )

        # No order should have been placed
        client.create_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_place_order_returns_none_on_failure(self, sample_config, mock_portfolio):
        executor, client, _, _ = self._make_executor(sample_config, mock_portfolio)

        # Simulate POST_ONLY rejection (returns None)
        client.create_order = AsyncMock(return_value=None)

        order_id = await executor.place_order(
            market_id="m1",
            token_id="token-1",
            side="BUY",
            price=0.50,
            size=10.0,
        )

        assert order_id is None

    @pytest.mark.asyncio
    async def test_cancel_order(self, sample_config, mock_portfolio):
        executor, client, order_store, _ = self._make_executor(sample_config, mock_portfolio)

        # Add an order first
        record = OrderRecord(
            order_id="order-cancel",
            market_id="m1",
            side="BUY",
            price=0.50,
            size=10.0,
            state=OrderState.OPEN,
        )
        await order_store.add(record)

        result = await executor.cancel_order("order-cancel")
        assert result is True
        client.cancel_order.assert_called_once_with("order-cancel")

    @pytest.mark.asyncio
    async def test_cancel_all_for_market(self, sample_config, mock_portfolio):
        executor, client, order_store, _ = self._make_executor(sample_config, mock_portfolio)

        # Add two open orders
        for oid in ["o1", "o2"]:
            record = OrderRecord(
                order_id=oid,
                market_id="m1",
                side="BUY",
                price=0.50,
                size=10.0,
                state=OrderState.OPEN,
            )
            await order_store.add(record)

        count = await executor.cancel_all_for_market("m1")
        client.cancel_all_for_market.assert_called_once_with("m1")

    @pytest.mark.asyncio
    async def test_amend_order_success(self, sample_config, mock_portfolio):
        executor, client, order_store, _ = self._make_executor(sample_config, mock_portfolio)

        # Add an order
        record = OrderRecord(
            order_id="order-amend",
            market_id="m1",
            side="BUY",
            price=0.50,
            size=10.0,
            state=OrderState.OPEN,
        )
        await order_store.add(record)

        result = await executor.amend_order("order-amend", 0.55, 15.0)
        assert result is True
        client.amend_order.assert_called_once_with("order-amend", 0.55, 15.0)

    @pytest.mark.asyncio
    async def test_place_quote_pair(self, sample_config, mock_portfolio):
        executor, client, _, _ = self._make_executor(sample_config, mock_portfolio)

        # Mock create_order to return different IDs for each call
        client.create_order = AsyncMock(side_effect=["bid-1", "ask-1"])

        bid_id, ask_id = await executor.place_quote_pair(
            market_id="m1",
            token_id="token-1",
            bid_price=0.48,
            ask_price=0.52,
            size=10.0,
            category="finance",
        )

        assert bid_id == "bid-1"
        assert ask_id == "ask-1"
        assert client.create_order.call_count == 2

    @pytest.mark.asyncio
    async def test_process_fill(self, sample_config, mock_portfolio):
        executor, client, order_store, _ = self._make_executor(sample_config, mock_portfolio)

        # Add an order that will be filled
        record = OrderRecord(
            order_id="order-fill",
            market_id="m1",
            side="BUY",
            price=0.50,
            size=100.0,
            state=OrderState.OPEN,
        )
        await order_store.add(record)

        await executor.process_fill(
            order_id="order-fill",
            filled_size=100.0,
            filled_price=0.50,
            market_id="m1",
            category="finance",
        )

        # Order should be FILLED
        updated = order_store.get("order-fill")
        assert updated.state == OrderState.FILLED

    @pytest.mark.asyncio
    async def test_emergency_cancel_all(self, sample_config, mock_portfolio):
        executor, client, order_store, _ = self._make_executor(sample_config, mock_portfolio)

        # Add orders across multiple markets
        for i, market in enumerate(["m1", "m1", "m2"]):
            record = OrderRecord(
                order_id=f"e-{i}",
                market_id=market,
                side="BUY",
                price=0.50,
                size=10.0,
                state=OrderState.OPEN,
            )
            await order_store.add(record)

        count = await executor.emergency_cancel_all()
        # Should have called cancel_all_for_market for each unique market
        assert client.cancel_all_for_market.call_count == 2

    @pytest.mark.asyncio
    async def test_insufficient_usdc_rejection(self, sample_config, mock_portfolio):
        executor, client, _, _ = self._make_executor(sample_config, mock_portfolio)

        # The executor checks risk first, then tries to lock USDC.
        # Risk checks: position limit = 5% of portfolio_value.
        # We need: order notional < 5% of portfolio_value (to pass risk),
        # but free_usdc < order notional (to fail the USDC lock).
        #
        # Set free_usdc = 10000, initial_capital = 10000 → loss% = 0 ✓
        # But then free_usdc is $10k — can't trigger USDC shortage.
        #
        # Trick: set locked_usdc high so free_usdc is low while
        # portfolio_value (free + locked) is high enough for the position limit.
        # free_usdc = 1.0, locked_usdc = 9999.0, no positions
        # portfolio_value = 1.0 + 9999.0 = 10,000
        # 5% of $10k = $500. Order $50 notional → 0.5% → passes position limit ✓
        # free_usdc = $1.0, order_cost = $50 → USDC lock fails ✓
        mock_portfolio._free_usdc = 1.0
        mock_portfolio._initial_capital = 10000.0
        mock_portfolio._locked_usdc = 9999.0
        mock_portfolio._positions = {}

        with pytest.raises(OrderRejectedByRisk, match="Insufficient USDC"):
            await executor.place_order(
                market_id="m1",
                token_id="token-1",
                side="BUY",
                price=0.50,
                size=100.0,  # $50 needed, only $1.0 available
            )
