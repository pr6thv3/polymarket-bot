"""Order executor with POST_ONLY enforcement, amendment, and risk hooks."""

import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple

import structlog

from core.client import ClobClient
from core.order_state import OrderRecord, OrderState, OrderStore
from core.portfolio import Portfolio
from core.risk import RiskManager
from utils import metrics as m

logger = structlog.get_logger(__name__)


class OrderRejectedByRisk(Exception):
    """Raised when the risk manager rejects an order."""


class Executor:
    """Order execution engine with risk pre-flight checks.

    Every order passes through the risk manager BEFORE being sent to the
    exchange. The risk manager can reject orders that violate position limits,
    daily loss caps, or other constraints.

    Features:
    - POST_ONLY on every order by default (NEVER accidentally take)
    - Pre-flight risk check via RiskManager.allow_order()
    - Amend existing orders (preferred over cancel+replace)
    - Batch cancel all orders for a market
    - Fill processing with portfolio + state updates
    - Re-quote: cancel old + place new when midpoint moves
    """

    def __init__(
        self,
        client: ClobClient,
        order_store: OrderStore,
        portfolio: Portfolio,
        risk_manager: RiskManager,
        config: dict,
    ) -> None:
        """Initialize the executor.

        Args:
            client: CLOB client wrapper.
            order_store: Order state machine store.
            portfolio: Portfolio tracker.
            risk_manager: Risk manager for pre-flight checks.
            config: Full config dict.
        """
        self.client = client
        self.order_store = order_store
        self.portfolio = portfolio
        self.risk_manager = risk_manager
        self.config = config

        exec_cfg = config.get("execution", {})
        self.default_post_only = exec_cfg.get("post_only_default", True)
        self.amend_timeout_sec = exec_cfg.get("amend_timeout_sec", 2.0)

    async def place_order(
        self,
        market_id: str,
        token_id: str,
        side: str,
        price: float,
        size: float,
        category: str = "",
        post_only: Optional[bool] = None,
    ) -> Optional[str]:
        """Place an order with pre-flight risk check.

        Args:
            market_id: Market/condition ID.
            token_id: Token ID to trade.
            side: "BUY" or "SELL".
            price: Limit price (0.00 to 1.00).
            size: Order size in shares.
            category: Market category for fee calculation.
            post_only: Override POST_ONLY flag. Defaults to True.

        Returns:
            Order ID if successful, None if rejected or failed.

        Raises:
            OrderRejectedByRisk: If the risk manager rejects the order.
        """
        # Force post_only for market making
        if post_only is None:
            post_only = self.default_post_only

        # --- PRE-FLIGHT RISK CHECK ---
        risk_ok, risk_reason = await self.risk_manager.allow_order(
            market_id=market_id,
            side=side,
            price=price,
            size=size,
            category=category,
        )
        if not risk_ok:
            logger.warning(
                "Order rejected by risk manager",
                market_id=market_id,
                side=side,
                price=price,
                size=size,
                reason=risk_reason,
            )
            raise OrderRejectedByRisk(risk_reason)

        # Lock USDC for the order
        order_cost = price * size if side == "BUY" else size * (1.0 - price)
        locked = await self.portfolio.lock_usdc(order_cost)
        if not locked:
            logger.warning(
                "Insufficient free USDC for order",
                market_id=market_id,
                side=side,
                cost=order_cost,
                free_usdc=self.portfolio.free_usdc,
            )
            raise OrderRejectedByRisk(
                f"Insufficient USDC: need {order_cost:.2f}, have {self.portfolio.free_usdc:.2f}"
            )

        # Create order record in PENDING state
        order_id_placeholder = f"pending-{market_id}-{int(time.monotonic()*1e6)}"

        # Place the order via CLOB client
        order_id = await self.client.create_order(
            token_id=token_id,
            side=side,
            price=price,
            size=size,
            post_only=post_only,
        )

        if order_id is None:
            # Order failed or was POST_ONLY rejected (expected in MM)
            await self.portfolio.unlock_usdc(order_cost)

            # Record in order store as REJECTED (POST_ONLY rejections are normal)
            record = OrderRecord(
                order_id=order_id_placeholder,
                market_id=market_id,
                side=side,
                price=price,
                size=size,
                state=OrderState.REJECTED,
            )
            await self.order_store.add(record)
            return None

        # Record in order store
        record = OrderRecord(
            order_id=order_id,
            market_id=market_id,
            side=side,
            price=price,
            size=size,
            state=OrderState.OPEN,
        )
        await self.order_store.add(record)

        # Metrics
        m.record_order_placed(market_id=market_id, side=side.lower())

        logger.info(
            "Order placed",
            order_id=order_id,
            market_id=market_id,
            side=side,
            price=price,
            size=size,
            post_only=post_only,
        )
        return order_id

    async def place_quote_pair(
        self,
        market_id: str,
        token_id: str,
        bid_price: float,
        ask_price: float,
        size: float,
        category: str = "",
    ) -> Tuple[Optional[str], Optional[str]]:
        """Place a bid/ask quote pair for market making.

        Both orders go through risk checks independently. If one fails,
        the other is still placed (partial quote is acceptable).

        Args:
            market_id: Market/condition ID.
            token_id: Token ID for the YES side.
            bid_price: Price for the BUY order.
            ask_price: Price for the SELL order.
            size: Size for each side.
            category: Market category.

        Returns:
            Tuple of (bid_order_id, ask_order_id). Either can be None.
        """
        bid_id = None
        ask_id = None

        try:
            bid_id = await self.place_order(
                market_id=market_id,
                token_id=token_id,
                side="BUY",
                price=bid_price,
                size=size,
                category=category,
                post_only=True,
            )
        except OrderRejectedByRisk as exc:
            logger.warning("Bid rejected by risk", market_id=market_id, reason=str(exc))

        try:
            ask_id = await self.place_order(
                market_id=market_id,
                token_id=token_id,
                side="SELL",
                price=ask_price,
                size=size,
                category=category,
                post_only=True,
            )
        except OrderRejectedByRisk as exc:
            logger.warning("Ask rejected by risk", market_id=market_id, reason=str(exc))

        return bid_id, ask_id

    async def amend_order(
        self,
        order_id: str,
        new_price: float,
        new_size: float,
    ) -> bool:
        """Amend an existing order. Falls back to cancel+replace if amend fails.

        Args:
            order_id: The order ID to amend.
            new_price: New limit price.
            new_size: New order size.

        Returns:
            True if amendment (or cancel+replace) succeeded.
        """
        # Try amend first (atomic, faster)
        success = await self.client.amend_order(order_id, new_price, new_size)

        if success:
            # Update order store
            record = self.order_store.get(order_id)
            if record:
                record.price = new_price
                record.size = new_size
            logger.info(
                "Order amended",
                order_id=order_id,
                new_price=new_price,
                new_size=new_size,
            )
            return True

        # Fallback: cancel + replace
        logger.info("Amend failed, falling back to cancel+replace", order_id=order_id)
        record = self.order_store.get(order_id)

        if record is None:
            logger.error("Cannot cancel+replace: order not found in store", order_id=order_id)
            return False

        cancelled = await self.client.cancel_order(order_id)
        if not cancelled:
            logger.error("Cancel failed in cancel+replace fallback", order_id=order_id)
            return False

        # Transition to cancelled in store
        try:
            await self.order_store.transition(order_id, OrderState.CANCELLED)
        except Exception:
            pass  # Already might be cancelled

        # Place replacement order
        new_id = await self.client.create_order(
            token_id=record.market_id,  # Note: we'd need token_id here
            side=record.side,
            price=new_price,
            size=new_size,
            post_only=True,
        )

        if new_id:
            new_record = OrderRecord(
                order_id=new_id,
                market_id=record.market_id,
                side=record.side,
                price=new_price,
                size=new_size,
                state=OrderState.OPEN,
            )
            await self.order_store.add(new_record)
            logger.info(
                "Cancel+replace succeeded",
                old_order_id=order_id,
                new_order_id=new_id,
            )
            return True

        return False

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a single order and update state.

        Args:
            order_id: The order ID to cancel.

        Returns:
            True if cancellation succeeded.
        """
        record = self.order_store.get(order_id)
        if record and record.is_terminal:
            logger.debug("Order already terminal, skipping cancel", order_id=order_id)
            return True

        success = await self.client.cancel_order(order_id)

        if success and record:
            try:
                await self.order_store.transition(order_id, OrderState.CANCELLED)
            except Exception:
                pass  # State might already be cancelled

            # Unlock USDC
            order_cost = record.price * record.size if record.side == "BUY" else record.size * (1.0 - record.price)
            await self.portfolio.unlock_usdc(order_cost)

        return success

    async def cancel_all_for_market(self, market_id: str) -> int:
        """Cancel all open orders for a market.

        Args:
            market_id: The market/condition ID.

        Returns:
            Number of orders cancelled.
        """
        # Cancel via API
        count = await self.client.cancel_all_for_market(market_id)

        # Update order store
        open_orders = await self.order_store.get_open_orders(market_id)
        for record in open_orders:
            try:
                await self.order_store.transition(record.order_id, OrderState.CANCELLED)
            except Exception:
                pass

            # Unlock USDC
            order_cost = record.price * record.size if record.side == "BUY" else record.size * (1.0 - record.price)
            await self.portfolio.unlock_usdc(order_cost)

        logger.info("All orders cancelled for market", market_id=market_id, count=count)
        return count

    async def process_fill(
        self,
        order_id: str,
        filled_size: float,
        filled_price: float,
        market_id: str,
        category: str = "",
        days_to_resolution: int = 0,
    ) -> None:
        """Process a fill event — update order state, portfolio, and metrics.

        Args:
            order_id: The order that was filled.
            filled_size: Size of the fill.
            filled_price: Price of the fill.
            market_id: Market ID.
            category: Market category.
            days_to_resolution: Days to market resolution.
        """
        record = self.order_store.get(order_id)
        if record is None:
            logger.warning("Fill for unknown order", order_id=order_id)
            return

        # Update order state
        new_filled = record.filled_size + filled_size
        if new_filled >= record.size - 1e-8:
            new_state = OrderState.FILLED
        else:
            new_state = OrderState.PARTIALLY_FILLED

        try:
            await self.order_store.transition(order_id, new_state, filled_size=new_filled)
        except Exception as exc:
            logger.error("Failed to update order state on fill", error=str(exc))

        # Update portfolio
        fill_signed = filled_size if record.side == "BUY" else -filled_size
        await self.portfolio.update_position(
            market_id=market_id,
            fill_size=fill_signed,
            fill_price=filled_price,
            category=category,
            days_to_resolution=days_to_resolution,
        )

        # Calculate and record spread captured
        if record.side == "BUY":
            # Spread = (exit_price - entry_price) for buy side
            # For MM: spread captured = (mid - bid) when filled
            pass  # Spread tracking handled by strategy layer

        # Metrics
        m.record_order_filled(market_id=market_id, side=record.side.lower())

        # Unlock USDC for unfilled portion
        if new_state == OrderState.FILLED:
            unfilled_cost = (record.size - filled_size) * record.price if record.side == "BUY" else 0
            if unfilled_cost > 0:
                await self.portfolio.unlock_usdc(unfilled_cost)

        logger.info(
            "Fill processed",
            order_id=order_id,
            market_id=market_id,
            side=record.side,
            filled_size=filled_size,
            filled_price=filled_price,
            new_state=new_state.value,
        )

    async def requote(
        self,
        market_id: str,
        token_id: str,
        old_bid_id: Optional[str],
        old_ask_id: Optional[str],
        new_bid_price: float,
        new_ask_price: float,
        size: float,
        category: str = "",
    ) -> Tuple[Optional[str], Optional[str]]:
        """Re-quote: cancel old orders and place new ones.

        This is the core market-making loop operation. Called when the
        midpoint moves beyond the re-quote threshold.

        Args:
            market_id: Market/condition ID.
            token_id: Token ID.
            old_bid_id: Previous bid order ID (to cancel).
            old_ask_id: Previous ask order ID (to cancel).
            new_bid_price: New bid price.
            new_ask_price: New ask price.
            size: Order size.
            category: Market category.

        Returns:
            Tuple of (new_bid_id, new_ask_id).
        """
        # Cancel old orders concurrently
        cancel_tasks = []
        if old_bid_id:
            cancel_tasks.append(self.cancel_order(old_bid_id))
        if old_ask_id:
            cancel_tasks.append(self.cancel_order(old_ask_id))

        if cancel_tasks:
            await asyncio.gather(*cancel_tasks, return_exceptions=True)

        # Place new quote pair
        return await self.place_quote_pair(
            market_id=market_id,
            token_id=token_id,
            bid_price=new_bid_price,
            ask_price=new_ask_price,
            size=size,
            category=category,
        )

    async def emergency_cancel_all(self) -> int:
        """Emergency: cancel ALL open orders across ALL markets.

        Called when risk manager triggers a halt.

        Returns:
            Total number of orders cancelled.
        """
        open_orders = await self.order_store.get_open_orders()
        total_cancelled = 0

        markets = set(record.market_id for record in open_orders)
        for market_id in markets:
            count = await self.cancel_all_for_market(market_id)
            total_cancelled += count

        logger.critical(
            "Emergency cancel all completed",
            markets_affected=len(markets),
            total_cancelled=total_cancelled,
        )
        return total_cancelled
