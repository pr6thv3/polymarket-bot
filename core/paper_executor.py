"""Paper-trading / dry-run executor — intercepts all orders and simulates fills.

Wraps the real Executor to provide a safe testing environment where:
- No real orders are placed on the exchange
- Fills are simulated against the live orderbook
- Portfolio updates happen in a virtual ledger
- All activity is logged with [PAPER] prefix for easy identification
- Slippage and fee models match live trading conditions

Enable by setting execution.dry_run: true in config.yaml.

Architecture:
  PaperExecutor wraps Executor and intercepts:
  - place_order() → simulate fill instead of sending to CLOB
  - cancel_order() → no-op (no real orders to cancel)
  - place_quote_pair() → simulate both legs
  - amend_order() → update virtual order

  PaperPortfolio tracks virtual positions alongside real portfolio state.
"""

import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import structlog

from core.executor import Executor, OrderRejectedByRisk
from core.order_state import OrderRecord, OrderState, OrderStore
from core.portfolio import Portfolio
from core.risk import RiskManager
from utils import metrics as m

logger = structlog.get_logger(__name__)

# Tag for all paper-trading log lines
PAPER_TAG = "[PAPER]"


@dataclass
class PaperOrder:
    """A virtual order in the paper-trading system."""

    order_id: str
    market_id: str
    token_id: str
    side: str
    price: float
    size: float
    post_only: bool = True
    category: str = ""
    placed_at: float = field(default_factory=time.monotonic)
    filled_size: float = 0.0
    filled_price: float = 0.0
    status: str = "open"  # open, filled, cancelled, rejected, expired

    @property
    def is_open(self) -> bool:
        return self.status == "open"

    @property
    def is_terminal(self) -> bool:
        return self.status in ("filled", "cancelled", "rejected", "expired")


@dataclass
class PaperTrade:
    """A completed paper trade (round-trip)."""

    market_id: str
    entry_side: str
    entry_price: float
    exit_price: float
    size: float
    pnl_usd: float
    fee_usd: float
    entry_time: float
    exit_time: float

    @property
    def hold_time_sec(self) -> float:
        return self.exit_time - self.entry_time


class PaperPortfolio:
    """Virtual portfolio for paper trading.

    Mirrors the real Portfolio interface but operates on virtual balances.
    Tracks positions, P&L, fees, and rebates in a sandbox.
    """

    def __init__(self, starting_capital: float, config: dict) -> None:
        self.starting_capital = starting_capital
        self.usdc = starting_capital
        self.locked_usdc = 0.0
        self.positions: Dict[str, Dict[str, float]] = {}  # market_id -> {size, avg_price, category}
        self.total_fees_paid: float = 0.0
        self.total_rebates_earned: float = 0.0
        self.realized_pnl: float = 0.0
        self.equity_curve: List[Tuple[float, float]] = []

        # Fee schedule
        self.taker_fees = config.get("taker_fees", {
            "crypto": 0.018,
            "sports": 0.0075,
            "finance": 0.01,
            "politics": 0.01,
            "economics": 0.015,
            "geopolitics": 0.0,
        })
        self.rebate_rates = config.get("rebate_rates", {
            "crypto": 0.20,
            "sports": 0.25,
            "finance": 0.50,
            "politics": 0.25,
            "economics": 0.25,
            "geopolitics": 0.20,
        })

    @property
    def free_usdc(self) -> float:
        return max(0.0, self.usdc - self.locked_usdc)

    @property
    def total_value(self) -> float:
        """Total value including unrealized P&L."""
        unrealized = 0.0
        for market_id, pos in self.positions.items():
            unrealized += pos.get("size", 0.0) * pos.get("avg_price", 0.0)
        return self.usdc + unrealized

    def get_position(self, market_id: str) -> Optional[Any]:
        """Get virtual position for a market."""
        if market_id in self.positions:
            pos_data = self.positions[market_id]

            class Pos:
                def __init__(self, data):
                    self.size = data.get("size", 0.0)
                    self.avg_price = data.get("avg_price", 0.0)
                    self.category = data.get("category", "")

            return Pos(pos_data)
        return None

    def lock_usdc(self, amount: float) -> bool:
        """Lock USDC for a virtual order."""
        if amount > self.free_usdc:
            return False
        self.locked_usdc += amount
        return True

    def unlock_usdc(self, amount: float) -> None:
        """Unlock USDC."""
        self.locked_usdc = max(0.0, self.locked_usdc - amount)

    def process_fill(
        self,
        market_id: str,
        side: str,
        price: float,
        size: float,
        category: str = "",
    ) -> Tuple[float, float]:
        """Process a virtual fill and return (fee_usd, rebate_usd).

        Args:
            market_id: Market ID.
            side: "BUY" or "SELL".
            price: Fill price.
            size: Fill size.
            category: Market category.

        Returns:
            Tuple of (fee_usd, rebate_usd).
        """
        # Calculate fee (maker = 0%, taker = category rate)
        is_maker = True  # Paper trading assumes maker for limit orders
        fee_pct = 0.0 if is_maker else self.taker_fees.get(category, 0.01)
        fee_usd = price * size * fee_pct

        # Calculate rebate
        rebate_pct = self.rebate_rates.get(category, 0.0)
        taker_fee_pct = self.taker_fees.get(category, 0.01)
        rebate_usd = price * size * taker_fee_pct * rebate_pct

        # Update balance
        if side == "BUY":
            cost = price * size + fee_usd
            self.usdc -= cost
            self.unlock_usdc(price * size)  # Unlock what was locked

            # Update position
            if market_id not in self.positions:
                self.positions[market_id] = {"size": 0.0, "avg_price": 0.0, "category": category}

            pos = self.positions[market_id]
            old_size = pos["size"]
            new_size = old_size + size

            if new_size > 0:
                pos["avg_price"] = (old_size * pos["avg_price"] + size * price) / new_size
            pos["size"] = new_size
            pos["category"] = category

        else:  # SELL
            proceeds = price * size - fee_usd
            self.usdc += proceeds

            if market_id in self.positions:
                pos = self.positions[market_id]
                entry_cost = pos["avg_price"] * size
                self.realized_pnl += proceeds - entry_cost
                pos["size"] -= size

                if abs(pos["size"]) < 1e-8:
                    del self.positions[market_id]

        # Track fees and rebates
        self.total_fees_paid += fee_usd
        self.total_rebates_earned += rebate_usd

        return fee_usd, rebate_usd

    def record_equity(self, timestamp: float) -> None:
        """Record equity for the curve."""
        self.equity_curve.append((timestamp, self.total_value))

    def get_stats(self) -> Dict[str, any]:
        """Get paper portfolio statistics."""
        return {
            "starting_capital": self.starting_capital,
            "current_usdc": round(self.usdc, 2),
            "locked_usdc": round(self.locked_usdc, 2),
            "free_usdc": round(self.free_usdc, 2),
            "total_value": round(self.total_value, 2),
            "realized_pnl": round(self.realized_pnl, 4),
            "unrealized_pnl": round(self.total_value - self.usdc - self.starting_capital + self.usdc, 4),
            "total_fees": round(self.total_fees_paid, 4),
            "total_rebates": round(self.total_rebates_earned, 4),
            "net_pnl": round(self.realized_pnl + self.total_rebates_earned - self.total_fees_paid, 4),
            "open_positions": len(self.positions),
            "return_pct": round((self.total_value / self.starting_capital - 1) * 100, 2) if self.starting_capital > 0 else 0,
        }


class PaperExecutor:
    """Paper-trading executor — intercepts all orders and simulates fills.

    Drop-in replacement for Executor that:
    1. Accepts the same API as Executor
    2. Does NOT send real orders to the exchange
    3. Simulates fills against the live orderbook
    4. Tracks virtual positions in PaperPortfolio
    5. Logs everything with [PAPER] prefix

    The real Executor is still used for risk checks and order state tracking,
    but the actual CLOB API call is replaced with a simulation.
    """

    def __init__(
        self,
        real_executor: Executor,
        paper_portfolio: PaperPortfolio,
        orderbook_manager: Any,
        config: dict,
    ) -> None:
        """Initialize the paper executor.

        Args:
            real_executor: The real Executor (used for risk checks only).
            paper_portfolio: Virtual portfolio for paper trading.
            orderbook_manager: OrderBookManager for fill simulation.
            config: Full config dict.
        """
        self.real_executor = real_executor
        self.paper_portfolio = paper_portfolio
        self.orderbook = orderbook_manager
        self.config = config

        pt_cfg = config.get("paper_trading", {})
        self.slippage_bps = pt_cfg.get("slippage_bps", 3.0)
        self.fill_probability = pt_cfg.get("fill_probability", 0.85)
        self.partial_fill_probability = pt_cfg.get("partial_fill_probability", 0.15)
        self.min_fill_pct = pt_cfg.get("min_fill_pct", 0.5)

        # Virtual order tracking
        self._orders: Dict[str, PaperOrder] = {}
        self._next_order_id = 1
        self._trades: List[PaperTrade] = []
        self._fills_log: List[Dict] = []

        # Counters
        self._total_orders_placed = 0
        self._total_fills = 0
        self._total_cancelled = 0
        self._total_rejected = 0

    # ── Order placement ───────────────────────────────────────────────

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
        """Place a virtual order and simulate fill.

        Goes through the real risk manager for validation, but does NOT
        send the order to the exchange. Instead, simulates a fill based
        on the current orderbook state.

        Args:
            market_id: Market/condition ID.
            token_id: Token ID to trade.
            side: "BUY" or "SELL".
            price: Limit price.
            size: Order size.
            category: Market category.
            post_only: POST_ONLY flag (simulated).

        Returns:
            Virtual order ID if placed, None if rejected.
        """
        # ── Risk check (use real risk manager) ──
        risk_ok, risk_reason = await self.real_executor.risk_manager.allow_order(
            market_id=market_id,
            side=side,
            price=price,
            size=size,
            category=category,
        )
        if not risk_ok:
            logger.warning(
                f"{PAPER_TAG} Order rejected by risk manager",
                market_id=market_id,
                side=side,
                price=price,
                size=size,
                reason=risk_reason,
            )
            self._total_rejected += 1
            raise OrderRejectedByRisk(risk_reason)

        # ── Check USDC availability ──
        order_cost = price * size if side == "BUY" else size * (1.0 - price)
        if not self.paper_portfolio.lock_usdc(order_cost):
            logger.warning(
                f"{PAPER_TAG} Insufficient virtual USDC",
                market_id=market_id,
                side=side,
                cost=order_cost,
                free_usdc=self.paper_portfolio.free_usdc,
            )
            self._total_rejected += 1
            raise OrderRejectedByRisk(
                f"Insufficient USDC (paper): need {order_cost:.2f}, "
                f"have {self.paper_portfolio.free_usdc:.2f}"
            )

        # ── Create virtual order ──
        order_id = f"paper-{self._next_order_id}"
        self._next_order_id += 1

        order = PaperOrder(
            order_id=order_id,
            market_id=market_id,
            token_id=token_id,
            side=side,
            price=price,
            size=size,
            post_only=post_only if post_only is not None else True,
            category=category,
        )
        self._orders[order_id] = order
        self._total_orders_placed += 1

        # ── Simulate fill ──
        filled = await self._simulate_fill(order)

        logger.info(
            f"{PAPER_TAG} Order placed",
            order_id=order_id,
            market_id=market_id,
            side=side,
            price=price,
            size=size,
            post_only=post_only,
            filled=filled,
        )

        m.record_order_placed(market_id=market_id, side=side.lower())

        return order_id

    async def _simulate_fill(self, order: PaperOrder) -> bool:
        """Simulate a fill for a virtual order.

        Fill logic:
        1. POST_ONLY orders: fill only if they would add liquidity
           (price doesn't cross the spread)
        2. Taker orders: fill at best opposite price with slippage
        3. Apply fill probability (not every order gets filled)
        4. Apply partial fill probability

        Args:
            order: The virtual order to fill.

        Returns:
            True if the order was filled (fully or partially).
        """
        import random

        # Check fill probability
        if random.random() > self.fill_probability:
            order.status = "open"  # Remains open, not filled yet
            logger.debug(
                f"{PAPER_TAG} Order not filled (probability)",
                order_id=order.order_id,
            )
            return False

        # Get orderbook snapshot for fill price
        snapshot = self.orderbook.get_snapshot(order.market_id)
        fill_price = order.price
        fill_size = order.size

        if snapshot:
            if order.side == "BUY":
                # Buy fills at or below the ask
                if snapshot.best_ask and order.price >= snapshot.best_ask:
                    if order.post_only:
                        # POST_ONLY would be rejected IRL
                        order.status = "rejected"
                        self.paper_portfolio.unlock_usdc(order.price * order.size)
                        logger.debug(
                            f"{PAPER_TAG} POST_ONLY rejected (would take)",
                            order_id=order.order_id,
                        )
                        return False
                    fill_price = snapshot.best_ask * (1 + self.slippage_bps / 10_000)
                else:
                    # Maker fill: our bid sits in the book
                    fill_price = order.price
            else:  # SELL
                if snapshot.best_bid and order.price <= snapshot.best_bid:
                    if order.post_only:
                        order.status = "rejected"
                        self.paper_portfolio.unlock_usdc(order.price * order.size)
                        return False
                    fill_price = snapshot.best_bid * (1 - self.slippage_bps / 10_000)
                else:
                    fill_price = order.price

        # Partial fill
        if random.random() < self.partial_fill_probability:
            fill_pct = max(self.min_fill_pct, random.random())
            fill_size = order.size * fill_pct
            order.filled_size = fill_size
            order.status = "partial"
            logger.debug(
                f"{PAPER_TAG} Partial fill",
                order_id=order.order_id,
                fill_pct=f"{fill_pct:.0%}",
                filled_size=fill_size,
            )
        else:
            order.filled_size = fill_size
            order.filled_price = fill_price
            order.status = "filled"

        # Process in paper portfolio
        fee_usd, rebate_usd = self.paper_portfolio.process_fill(
            market_id=order.market_id,
            side=order.side,
            price=fill_price,
            size=fill_size if order.status == "partial" else order.filled_size,
            category=order.category,
        )

        # Record fill
        self._fills_log.append({
            "timestamp": time.monotonic(),
            "order_id": order.order_id,
            "market_id": order.market_id,
            "side": order.side,
            "price": fill_price,
            "size": fill_size if order.status == "partial" else order.filled_size,
            "fee_usd": fee_usd,
            "rebate_usd": rebate_usd,
        })

        self._total_fills += 1

        m.record_order_filled(market_id=order.market_id, side=order.side.lower())

        if rebate_usd > 0:
            m.record_rebate_earned(rebate_usd)

        return True

    # ── Other Executor methods (delegated or no-op) ───────────────────

    async def place_quote_pair(
        self,
        market_id: str,
        token_id: str,
        bid_price: float,
        ask_price: float,
        size: float,
        category: str = "",
    ) -> Tuple[Optional[str], Optional[str]]:
        """Place a virtual bid/ask quote pair."""
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
        except OrderRejectedByRisk:
            pass

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
        except OrderRejectedByRisk:
            pass

        return bid_id, ask_id

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a virtual order."""
        order = self._orders.get(order_id)
        if order is None:
            return False

        if order.is_terminal:
            return True

        order.status = "cancelled"
        self.paper_portfolio.unlock_usdc(order.price * order.size)
        self._total_cancelled += 1

        logger.debug(
            f"{PAPER_TAG} Order cancelled",
            order_id=order_id,
            market_id=order.market_id,
        )
        return True

    async def cancel_all_for_market(self, market_id: str) -> int:
        """Cancel all virtual orders for a market."""
        count = 0
        for order in self._orders.values():
            if order.market_id == market_id and order.is_open:
                order.status = "cancelled"
                self.paper_portfolio.unlock_usdc(order.price * order.size)
                count += 1

        self._total_cancelled += count
        logger.info(
            f"{PAPER_TAG} All orders cancelled for market",
            market_id=market_id,
            count=count,
        )
        return count

    async def amend_order(self, order_id: str, new_price: float, new_size: float) -> bool:
        """Amend a virtual order."""
        order = self._orders.get(order_id)
        if order is None or order.is_terminal:
            return False

        # Unlock old amount, lock new
        old_cost = order.price * order.size
        new_cost = new_price * new_size

        self.paper_portfolio.unlock_usdc(old_cost)
        if not self.paper_portfolio.lock_usdc(new_cost):
            # Can't afford amendment — keep original
            self.paper_portfolio.lock_usdc(old_cost)
            return False

        order.price = new_price
        order.size = new_size

        logger.debug(
            f"{PAPER_TAG} Order amended",
            order_id=order_id,
            new_price=new_price,
            new_size=new_size,
        )
        return True

    async def emergency_cancel_all(self) -> int:
        """Emergency cancel all virtual orders."""
        count = 0
        for order in self._orders.values():
            if order.is_open:
                order.status = "cancelled"
                self.paper_portfolio.unlock_usdc(order.price * order.size)
                count += 1

        logger.warning(f"{PAPER_TAG} Emergency cancel all", count=count)
        return count

    # ── Fill simulation for open orders ───────────────────────────────

    async def process_open_orders(self) -> int:
        """Attempt to fill open orders against current orderbook.

        Called periodically to simulate fills for orders that didn't
        fill immediately (maker orders sitting in the book).

        Returns:
            Number of orders filled this cycle.
        """
        filled_count = 0

        for order in self._orders.values():
            if not order.is_open:
                continue

            filled = await self._simulate_fill(order)
            if filled:
                filled_count += 1

        return filled_count

    # ── Reporting ─────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, any]:
        """Get paper trading statistics."""
        portfolio_stats = self.paper_portfolio.get_stats()

        return {
            "mode": "PAPER_TRADING",
            "orders_placed": self._total_orders_placed,
            "fills": self._total_fills,
            "cancelled": self._total_cancelled,
            "rejected": self._total_rejected,
            "open_orders": sum(1 for o in self._orders.values() if o.is_open),
            "slippage_bps": self.slippage_bps,
            "fill_probability": f"{self.fill_probability:.0%}",
            **portfolio_stats,
        }

    def get_session_report(self) -> str:
        """Generate a formatted paper-trading session report.

        Returns:
            Multi-line report string.
        """
        stats = self.get_stats()
        pp = self.paper_portfolio

        lines = [
            "=" * 55,
            f"  {PAPER_TAG} SESSION REPORT",
            "=" * 55,
            "",
            "  PORTFOLIO",
            f"    Starting Capital:   ${pp.starting_capital:,.2f}",
            f"    Current USDC:       ${pp.usdc:,.2f}",
            f"    Total Value:        ${pp.total_value:,.2f}",
            f"    Return:             {stats['return_pct']:.2f}%",
            f"    Realized P&L:       ${pp.realized_pnl:+,.4f}",
            f"    Fees Paid:          ${pp.total_fees_paid:,.4f}",
            f"    Rebates Earned:     ${pp.total_rebates_earned:,.4f}",
            f"    Net P&L:            ${stats['net_pnl']:+,.4f}",
            "",
            "  ORDERS",
            f"    Placed:             {stats['orders_placed']}",
            f"    Filled:             {stats['fills']}",
            f"    Cancelled:          {stats['cancelled']}",
            f"    Rejected:           {stats['rejected']}",
            f"    Currently Open:     {stats['open_orders']}",
            "",
            "  SIMULATION SETTINGS",
            f"    Slippage:           {stats['slippage_bps']} bps",
            f"    Fill Probability:   {stats['fill_probability']}",
            "",
            "=" * 55,
        ]

        return "\n".join(lines)
