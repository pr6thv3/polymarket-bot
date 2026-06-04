"""Tests for the order state machine (core/order_state.py)."""

import asyncio
import time
import pytest

from core.order_state import (
    VALID_TRANSITIONS,
    InvalidTransition,
    OrderRecord,
    OrderState,
    OrderStore,
)


class TestOrderState:
    """Test OrderState enum and transitions."""

    def test_valid_transitions_from_pending(self):
        """PENDING can transition to OPEN, REJECTED, or CANCELLED."""
        valid = {OrderState.OPEN, OrderState.REJECTED, OrderState.CANCELLED}
        assert valid == VALID_TRANSITIONS[OrderState.PENDING]

    def test_pending_state(self):
        assert OrderState.PENDING.value == "pending"

    def test_open_state(self):
        assert OrderState.OPEN.value == "open"

    def test_filled_is_terminal(self):
        record = OrderRecord(
            order_id="test-1",
            market_id="market-1",
            side="BUY",
            price=0.50,
            size=10.0,
            state=OrderState.FILLED,
        )
        assert record.is_terminal is True
        assert record.is_active is False

    def test_pending_is_active(self):
        record = OrderRecord(
            order_id="test-2",
            market_id="market-1",
            side="SELL",
            price=0.60,
            size=5.0,
            state=OrderState.PENDING,
        )
        assert record.is_terminal is False
        assert record.is_active is True

    def test_unfilled_size(self):
        record = OrderRecord(
            order_id="test-3",
            market_id="market-1",
            side="BUY",
            price=0.50,
            size=100.0,
            filled_size=30.0,
            state=OrderState.PARTIALLY_FILLED,
        )
        assert record.unfilled_size == 70.0


class TestOrderStore:
    """Test OrderStore state machine enforcement."""

    @pytest.mark.asyncio
    async def test_add_and_get(self):
        store = OrderStore()
        record = OrderRecord(
            order_id="o1",
            market_id="m1",
            side="BUY",
            price=0.50,
            size=10.0,
        )
        await store.add(record)
        assert store.get("o1") is not None
        assert store.get("o1").order_id == "o1"

    @pytest.mark.asyncio
    async def test_valid_transition_pending_to_open(self):
        store = OrderStore()
        record = OrderRecord(
            order_id="o2",
            market_id="m1",
            side="BUY",
            price=0.50,
            size=10.0,
            state=OrderState.PENDING,
        )
        await store.add(record)
        await store.transition("o2", OrderState.OPEN)
        assert store.get("o2").state == OrderState.OPEN

    @pytest.mark.asyncio
    async def test_valid_transition_open_to_filled(self):
        store = OrderStore()
        record = OrderRecord(
            order_id="o3",
            market_id="m1",
            side="BUY",
            price=0.50,
            size=10.0,
            state=OrderState.OPEN,
        )
        await store.add(record)
        await store.transition("o3", OrderState.FILLED)
        assert store.get("o3").state == OrderState.FILLED
        assert store.get("o3").is_terminal is True

    @pytest.mark.asyncio
    async def test_invalid_transition_filled_to_open(self):
        store = OrderStore()
        record = OrderRecord(
            order_id="o4",
            market_id="m1",
            side="BUY",
            price=0.50,
            size=10.0,
            state=OrderState.FILLED,
        )
        await store.add(record)
        with pytest.raises(InvalidTransition):
            await store.transition("o4", OrderState.OPEN)

    @pytest.mark.asyncio
    async def test_invalid_transition_cancelled_to_open(self):
        store = OrderStore()
        record = OrderRecord(
            order_id="o5",
            market_id="m1",
            side="BUY",
            price=0.50,
            size=10.0,
            state=OrderState.CANCELLED,
        )
        await store.add(record)
        with pytest.raises(InvalidTransition):
            await store.transition("o5", OrderState.OPEN)

    @pytest.mark.asyncio
    async def test_transition_with_fill_update(self):
        store = OrderStore()
        record = OrderRecord(
            order_id="o6",
            market_id="m1",
            side="BUY",
            price=0.50,
            size=100.0,
            state=OrderState.OPEN,
        )
        await store.add(record)
        await store.transition("o6", OrderState.PARTIALLY_FILLED, filled_size=30.0)
        assert store.get("o6").filled_size == 30.0
        assert store.get("o6").state == OrderState.PARTIALLY_FILLED

    @pytest.mark.asyncio
    async def test_transition_nonexistent_order(self):
        store = OrderStore()
        with pytest.raises(KeyError):
            await store.transition("nonexistent", OrderState.OPEN)

    @pytest.mark.asyncio
    async def test_rejected_state_is_terminal(self):
        store = OrderStore()
        record = OrderRecord(
            order_id="o7",
            market_id="m1",
            side="BUY",
            price=0.50,
            size=10.0,
            state=OrderState.PENDING,
        )
        await store.add(record)
        await store.transition("o7", OrderState.REJECTED)
        assert store.get("o7").is_terminal is True

    @pytest.mark.asyncio
    async def test_get_open_orders(self):
        store = OrderStore()
        # Add multiple orders in different states
        for i, state in enumerate([OrderState.PENDING, OrderState.OPEN, OrderState.FILLED]):
            record = OrderRecord(
                order_id=f"o{i}",
                market_id="m1",
                side="BUY",
                price=0.50,
                size=10.0,
                state=state,
            )
            await store.add(record)

        open_orders = await store.get_open_orders()
        assert len(open_orders) == 2  # PENDING and OPEN

    @pytest.mark.asyncio
    async def test_get_open_orders_filtered_by_market(self):
        store = OrderStore()
        for i, market in enumerate(["m1", "m1", "m2"]):
            record = OrderRecord(
                order_id=f"o{i}",
                market_id=market,
                side="BUY",
                price=0.50,
                size=10.0,
                state=OrderState.OPEN,
            )
            await store.add(record)

        m1_orders = await store.get_open_orders(market_id="m1")
        assert len(m1_orders) == 2

    @pytest.mark.asyncio
    async def test_pending_timeout(self):
        store = OrderStore(pending_timeout_sec=0.1)
        record = OrderRecord(
            order_id="o-timeout",
            market_id="m1",
            side="BUY",
            price=0.50,
            size=10.0,
            state=OrderState.PENDING,
        )
        # Manually set created_at to the past
        record.created_at = time.monotonic() - 1.0
        await store.add(record)

        timed_out = await store.check_pending_timeouts()
        assert "o-timeout" in timed_out
        assert store.get("o-timeout").state == OrderState.OPEN

    @pytest.mark.asyncio
    async def test_remove_terminal(self):
        store = OrderStore()
        # Add a terminal order with old timestamp
        record = OrderRecord(
            order_id="o-old",
            market_id="m1",
            side="BUY",
            price=0.50,
            size=10.0,
            state=OrderState.FILLED,
        )
        record.updated_at = time.monotonic() - 7200  # 2 hours ago
        await store.add(record)

        # Add a recent terminal order
        record2 = OrderRecord(
            order_id="o-recent",
            market_id="m1",
            side="BUY",
            price=0.50,
            size=10.0,
            state=OrderState.CANCELLED,
        )
        await store.add(record2)

        removed = await store.remove_terminal(max_age_sec=3600)
        assert removed == 1
        assert store.get("o-old") is None
        assert store.get("o-recent") is not None

    @pytest.mark.asyncio
    async def test_size_and_active_count(self):
        store = OrderStore()
        assert store.size == 0
        assert store.active_count == 0

        record = OrderRecord(
            order_id="o-count",
            market_id="m1",
            side="BUY",
            price=0.50,
            size=10.0,
            state=OrderState.OPEN,
        )
        await store.add(record)
        assert store.size == 1
        assert store.active_count == 1

        await store.transition("o-count", OrderState.FILLED)
        assert store.size == 1
        assert store.active_count == 0
