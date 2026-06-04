"""Backtesting engine — simulate strategy execution on historical data.

Provides a sandbox environment to test strategies against recorded market
data without risking real capital. Supports market making, arbitrage,
and signal-based strategies.

Architecture:
  BacktestEngine
    ├── BacktestMarketData (feeds historical orderbook snapshots)
    ├── BacktestExecutor (simulates order placement and fills)
    ├── BacktestPortfolio (tracks simulated positions and P&L)
    └── BacktestRiskManager (applies risk rules to simulated trades)

Data format:
  Expects JSONL files with one snapshot per line:
    {
      "timestamp": 1717000000,
      "market_id": "...",
      "bids": [[0.55, 100], [0.54, 200]],
      "asks": [[0.56, 80], [0.57, 150]],
      "mid": 0.555,
      "volume_24h": 5000
    }

Usage:
  engine = BacktestEngine(config, data_dir="data/backtest/")
  results = engine.run(strategy_class=MarketMakingStrategy)
  engine.print_report(results)
"""

import asyncio
import json
import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import structlog

logger = structlog.get_logger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "backtest")


# ── Data structures ────────────────────────────────────────────────────

@dataclass
class BacktestTick:
    """A single market data tick in the backtest."""

    timestamp: float
    market_id: str
    bids: List[Tuple[float, float]] = field(default_factory=list)  # (price, size)
    asks: List[Tuple[float, float]] = field(default_factory=list)
    mid: float = 0.0
    volume_24h: int = 0

    @property
    def best_bid(self) -> Optional[float]:
        return self.bids[0][0] if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        return self.asks[0][0] if self.asks else None


@dataclass
class BacktestFill:
    """A simulated fill in the backtest."""

    timestamp: float
    market_id: str
    side: str
    price: float
    size: float
    order_id: str = ""
    fee_usd: float = 0.0

    @property
    def cost(self) -> float:
        """Total cost including fee."""
        base = self.price * self.size
        if self.side == "BUY":
            return base + self.fee_usd
        return base - self.fee_usd


@dataclass
class BacktestTrade:
    """A completed round-trip trade in the backtest."""

    market_id: str
    entry_side: str = ""
    entry_price: float = 0.0
    exit_price: float = 0.0
    size: float = 0.0
    entry_time: float = 0.0
    exit_time: float = 0.0
    pnl_usd: float = 0.0
    fee_usd: float = 0.0

    @property
    def hold_time_sec(self) -> float:
        return self.exit_time - self.entry_time

    @property
    def return_pct(self) -> float:
        if self.entry_price <= 0:
            return 0.0
        return self.pnl_usd / (self.entry_price * self.size)


@dataclass
class BacktestResult:
    """Results from a completed backtest run."""

    strategy_name: str = ""
    start_time: float = 0.0
    end_time: float = 0.0
    total_ticks: int = 0

    # P&L
    starting_capital: float = 0.0
    ending_capital: float = 0.0
    total_pnl: float = 0.0
    total_fees: float = 0.0
    net_pnl: float = 0.0

    # Trade stats
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    avg_win_usd: float = 0.0
    avg_loss_usd: float = 0.0
    profit_factor: float = 0.0
    max_win_usd: float = 0.0
    max_loss_usd: float = 0.0

    # Drawdown
    max_drawdown_pct: float = 0.0
    max_drawdown_usd: float = 0.0

    # Risk
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0

    # Time
    avg_hold_time_sec: float = 0.0
    trades_per_day: float = 0.0

    # Detailed records
    equity_curve: List[Tuple[float, float]] = field(default_factory=list)  # (timestamp, equity)
    all_trades: List[BacktestTrade] = field(default_factory=list)
    fills: List[BacktestFill] = field(default_factory=list)


# ── Simulated components ──────────────────────────────────────────────

class BacktestPortfolio:
    """Simulated portfolio for backtesting.

    Tracks:
    - USDC balance (starting capital + realized P&L)
    - Open positions per market
    - Locked USDC for pending orders
    - Equity curve over time
    """

    def __init__(self, starting_capital: float) -> None:
        self.starting_capital = starting_capital
        self.usdc = starting_capital
        self.locked_usdc = 0.0
        self.positions: Dict[str, Dict[str, float]] = {}  # market_id -> {size, avg_price}
        self.equity_curve: List[Tuple[float, float]] = []
        self._total_fees: float = 0.0
        self._peak_equity: float = starting_capital

    @property
    def free_usdc(self) -> float:
        return max(0.0, self.usdc - self.locked_usdc)

    @property
    def total_value(self) -> float:
        """Total portfolio value (USDC + position mark-to-market)."""
        return self.usdc  # Simplified: positions valued at entry cost

    def get_position(self, market_id: str) -> Optional[Any]:
        """Get position for a market."""
        if market_id in self.positions:
            pos_data = self.positions[market_id]

            class Pos:
                def __init__(self, data):
                    self.size = data.get("size", 0.0)
                    self.avg_price = data.get("avg_price", 0.0)

            return Pos(pos_data)
        return None

    async def lock_usdc(self, amount: float) -> bool:
        """Lock USDC for an order."""
        if amount > self.free_usdc:
            return False
        self.locked_usdc += amount
        return True

    async def unlock_usdc(self, amount: float) -> None:
        """Unlock USDC (order cancelled)."""
        self.locked_usdc = max(0.0, self.locked_usdc - amount)

    async def update_position(
        self, market_id: str, fill_size: float, fill_price: float, **kwargs
    ) -> None:
        """Update position after a fill."""
        if market_id not in self.positions:
            self.positions[market_id] = {"size": 0.0, "avg_price": 0.0}

        pos = self.positions[market_id]
        old_size = pos["size"]
        new_size = old_size + fill_size

        if fill_size > 0:  # BUY
            # Weighted average price
            if new_size > 0:
                pos["avg_price"] = (
                    (old_size * pos["avg_price"] + fill_size * fill_price) / new_size
                )
            cost = fill_size * fill_price
            self.usdc -= cost
            self.locked_usdc = max(0.0, self.locked_usdc - cost)
        else:  # SELL
            proceeds = abs(fill_size) * fill_price
            self.usdc += proceeds
            self.locked_usdc = max(0.0, self.locked_usdc - abs(fill_size) * pos["avg_price"])

        pos["size"] = new_size

        # Clean up zero positions
        if abs(new_size) < 1e-8:
            del self.positions[market_id]

    def get_total_value(self) -> float:
        return self.total_value

    def record_equity(self, timestamp: float) -> None:
        """Record current equity for the equity curve."""
        equity = self.total_value
        self.equity_curve.append((timestamp, equity))
        self._peak_equity = max(self._peak_equity, equity)

    def get_max_drawdown_pct(self) -> float:
        """Calculate max drawdown percentage from equity curve."""
        if not self.equity_curve:
            return 0.0

        peak = self.equity_curve[0][1]
        max_dd = 0.0

        for _, equity in self.equity_curve:
            peak = max(peak, equity)
            dd = (peak - equity) / peak if peak > 0 else 0.0
            max_dd = max(max_dd, dd)

        return max_dd * 100  # As percentage

    def add_fee(self, fee_usd: float) -> None:
        """Track fees paid."""
        self._total_fees += fee_usd
        self.usdc -= fee_usd

    @property
    def total_fees(self) -> float:
        return self._total_fees


class BacktestExecutor:
    """Simulated order executor for backtesting.

    Simulates:
    - Order placement (instant or with configurable latency)
    - Fill against historical orderbook (conservative: fill at best opposite side)
    - Partial fills
    - POST_ONLY rejections (order would take)
    - Slippage model
    """

    def __init__(
        self,
        portfolio: BacktestPortfolio,
        config: dict,
        slippage_bps: float = 5.0,
        fill_latency_sec: float = 0.0,
    ) -> None:
        self.portfolio = portfolio
        self.config = config
        self.slippage_bps = slippage_bps
        self.fill_latency_sec = fill_latency_sec

        self._next_order_id = 1
        self._open_orders: Dict[str, Dict] = {}
        self._fills: List[BacktestFill] = []

        # Fee structure
        self.maker_fee_pct = 0.0  # 0% maker
        self.taker_fee_pct = {
            "crypto": 0.018,
            "sports": 0.0075,
            "finance": 0.01,
            "politics": 0.01,
            "economics": 0.015,
            "geopolitics": 0.0,
        }

    async def place_order(
        self,
        market_id: str,
        token_id: str,
        side: str,
        price: float,
        size: float,
        category: str = "",
        post_only: bool = True,
    ) -> Optional[str]:
        """Simulate order placement and immediate fill check.

        Args:
            market_id: Market ID.
            token_id: Token ID.
            side: "BUY" or "SELL".
            price: Limit price.
            size: Order size.
            category: Market category for fee calculation.
            post_only: If True, reject if order would take.

        Returns:
            Order ID if placed/filled, None if rejected.
        """
        order_id = f"bt-{self._next_order_id}"
        self._next_order_id += 1

        # Check if the order would take (for POST_ONLY)
        current_tick = self._current_tick.get(market_id) if hasattr(self, '_current_tick') else None

        if post_only and current_tick:
            if side == "BUY" and current_tick.best_ask and price >= current_tick.best_ask:
                # Would take — reject
                return None
            if side == "SELL" and current_tick.best_bid and price <= current_tick.best_bid:
                return None

        # Simulate fill
        filled = False
        fill_price = price

        if current_tick:
            if side == "BUY" and current_tick.best_ask:
                # Buy: fill at best ask (or better)
                if price >= current_tick.best_ask:
                    fill_price = current_tick.best_ask
                    # Apply slippage
                    fill_price *= (1 + self.slippage_bps / 10_000)
                    filled = True
            elif side == "SELL" and current_tick.best_bid:
                # Sell: fill at best bid (or better)
                if price <= current_tick.best_bid:
                    fill_price = current_tick.best_bid
                    fill_price *= (1 - self.slippage_bps / 10_000)
                    filled = True

        if filled:
            # Calculate fee
            fee_pct = self.taker_fee_pct.get(category, 0.01)
            fee_usd = fill_price * size * fee_pct

            fill = BacktestFill(
                timestamp=current_tick.timestamp if current_tick else time.monotonic(),
                market_id=market_id,
                side=side,
                price=fill_price,
                size=size,
                order_id=order_id,
                fee_usd=fee_usd,
            )
            self._fills.append(fill)

            # Update portfolio
            fill_signed = size if side == "BUY" else -size
            await self.portfolio.update_position(
                market_id=market_id,
                fill_size=fill_signed,
                fill_price=fill_price,
            )
            self.portfolio.add_fee(fee_usd)

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
        """Simulate placing a bid/ask pair (for market making)."""
        bid_id = await self.place_order(
            market_id, token_id, "BUY", bid_price, size, category, post_only=True
        )
        ask_id = await self.place_order(
            market_id, token_id, "SELL", ask_price, size, category, post_only=True
        )
        return bid_id, ask_id

    async def cancel_order(self, order_id: str) -> bool:
        """Simulate order cancellation."""
        self._open_orders.pop(order_id, None)
        return True

    async def cancel_all_for_market(self, market_id: str) -> int:
        """Cancel all orders for a market."""
        count = sum(
            1 for o in self._open_orders.values()
            if o.get("market_id") == market_id
        )
        self._open_orders = {
            k: v for k, v in self._open_orders.items()
            if v.get("market_id") != market_id
        }
        return count

    def set_current_tick(self, tick: BacktestTick) -> None:
        """Set the current market data tick (called by engine)."""
        self._current_tick = {tick.market_id: tick}  # type: ignore

    def get_fills(self) -> List[BacktestFill]:
        """Get all simulated fills."""
        return list(self._fills)


class BacktestRiskManager:
    """Simplified risk manager for backtesting.

    Applies the same rules as the real RiskManager but operates on
    the simulated portfolio.
    """

    def __init__(self, config: dict) -> None:
        risk_cfg = config.get("risk_management", {})
        self.max_position_pct = risk_cfg.get("max_position_pct", 0.05)
        self.daily_loss_limit_pct = risk_cfg.get("daily_loss_limit_pct", 0.05)
        self.halt_at_loss_pct = risk_cfg.get("halt_at_loss_pct", 0.40)
        self._halted = False

    async def allow_order(
        self, market_id: str, side: str, price: float, size: float, category: str = ""
    ) -> Tuple[bool, str]:
        """Check if an order is allowed by risk rules."""
        if self._halted:
            return False, "Risk halt active"
        return True, ""

    def get_size_multiplier(self) -> float:
        """Get the current size multiplier."""
        return 1.0

    def check_halt(self, portfolio: BacktestPortfolio) -> bool:
        """Check if a risk halt should be triggered.

        Args:
            portfolio: Simulated portfolio.

        Returns:
            True if halt triggered.
        """
        total_loss = portfolio.starting_capital - portfolio.total_value
        loss_pct = total_loss / portfolio.starting_capital if portfolio.starting_capital > 0 else 0

        if loss_pct >= self.halt_at_loss_pct:
            self._halted = True
            logger.warning("Backtest risk halt triggered", loss_pct=f"{loss_pct:.1%}")
            return True
        return False


# ── Main engine ────────────────────────────────────────────────────────

class BacktestEngine:
    """Backtesting engine: replay historical data through a strategy.

    Usage:
        engine = BacktestEngine(config)
        results = engine.run_market_making(
            data_dir="data/backtest/",
            starting_capital=1000.0,
        )
        engine.print_report(results)
    """

    def __init__(self, config: dict) -> None:
        """Initialize the backtesting engine.

        Args:
            config: Full config dict (same as live trading config).
        """
        self.config = config
        bt_cfg = config.get("backtesting", {})

        self.data_dir = bt_cfg.get("data_dir", DATA_DIR)
        self.default_capital = bt_cfg.get("starting_capital", 1000.0)
        self.slippage_bps = bt_cfg.get("slippage_bps", 5.0)
        self.fill_latency_sec = bt_cfg.get("fill_latency_sec", 0.0)

    # ── Data loading ──────────────────────────────────────────────────

    def load_market_data(
        self, market_id: str, data_file: Optional[str] = None
    ) -> List[BacktestTick]:
        """Load historical market data from a JSONL file.

        Args:
            market_id: Market ID to load data for.
            data_file: Optional explicit file path.

        Returns:
            List of BacktestTick objects sorted by timestamp.
        """
        if data_file is None:
            data_file = os.path.join(self.data_dir, f"{market_id}.jsonl")

        if not os.path.exists(data_file):
            logger.error("Backtest data file not found", path=data_file)
            return []

        ticks = []
        with open(data_file, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                try:
                    data = json.loads(line)

                    bids = [(float(b[0]), float(b[1])) for b in data.get("bids", [])]
                    asks = [(float(a[0]), float(a[1])) for a in data.get("asks", [])]

                    # Sort bids descending, asks ascending
                    bids.sort(key=lambda x: x[0], reverse=True)
                    asks.sort(key=lambda x: x[0])

                    tick = BacktestTick(
                        timestamp=float(data.get("timestamp", 0)),
                        market_id=data.get("market_id", market_id),
                        bids=bids,
                        asks=asks,
                        mid=float(data.get("mid", 0)),
                        volume_24h=int(data.get("volume_24h", 0)),
                    )
                    ticks.append(tick)

                except (json.JSONDecodeError, ValueError, IndexError) as exc:
                    logger.warning(
                        "Skipping malformed backtest line",
                        file=data_file,
                        line=line_num,
                        error=str(exc),
                    )

        # Sort by timestamp
        ticks.sort(key=lambda t: t.timestamp)

        logger.info(
            "Backtest data loaded",
            market_id=market_id,
            ticks=len(ticks),
            file=data_file,
        )
        return ticks

    def generate_sample_data(
        self,
        market_id: str,
        start_price: float = 0.50,
        num_ticks: int = 1000,
        volatility: float = 0.02,
        spread_bps: float = 200,
    ) -> List[BacktestTick]:
        """Generate synthetic market data for testing.

        Creates a random walk with configurable volatility and spread.

        Args:
            market_id: Market ID for the generated data.
            start_price: Starting midpoint price.
            num_ticks: Number of ticks to generate.
            volatility: Price volatility per tick (std dev of returns).
            spread_bps: Bid-ask spread in basis points.

        Returns:
            List of BacktestTick objects.
        """
        import random

        ticks = []
        price = start_price
        base_ts = time.time() - num_ticks * 5  # 5 seconds apart

        for i in range(num_ticks):
            # Random walk
            price *= (1 + random.gauss(0, volatility))
            price = max(0.01, min(0.99, price))

            half_spread = price * spread_bps / 20_000

            bid = price - half_spread
            ask = price + half_spread

            tick = BacktestTick(
                timestamp=base_ts + i * 5,
                market_id=market_id,
                bids=[(round(bid, 4), random.randint(50, 200))],
                asks=[(round(ask, 4), random.randint(50, 200))],
                mid=round(price, 4),
                volume_24h=random.randint(1000, 10000),
            )
            ticks.append(tick)

        return ticks

    # ── Backtest runner ───────────────────────────────────────────────

    def run_market_making(
        self,
        ticks: List[BacktestTick],
        starting_capital: Optional[float] = None,
        kappa: float = 0.5,
        delta: float = 0.002,
        base_spread_bps: float = 200,
        order_size_usd: float = 15.0,
    ) -> BacktestResult:
        """Run a market-making backtest on the provided ticks.

        Simulates the Avellaneda-Stoikov strategy logic without
        requiring the full strategy class (lightweight mode).

        Args:
            ticks: Historical market data ticks.
            starting_capital: Starting USDC balance.
            kappa: Risk aversion parameter.
            delta: Inventory skew factor.
            base_spread_bps: Base spread in basis points.
            order_size_usd: Size per order in USD.

        Returns:
            BacktestResult with full performance metrics.
        """
        capital = starting_capital or self.default_capital
        portfolio = BacktestPortfolio(capital)
        executor = BacktestExecutor(
            portfolio, self.config,
            slippage_bps=self.slippage_bps,
        )
        risk_mgr = BacktestRiskManager(self.config)

        result = BacktestResult(
            strategy_name="MarketMaking",
            starting_capital=capital,
        )

        inventory = 0.0
        trade_log: List[BacktestTrade] = []
        open_entry: Optional[Dict] = None

        for tick in ticks:
            executor.set_current_tick(tick)
            portfolio.record_equity(tick.timestamp)

            # Risk halt check
            if risk_mgr.check_halt(portfolio):
                break

            mid = tick.mid
            if mid <= 0:
                continue

            # ── Compute AS quotes ──
            reservation = mid - inventory * delta
            half_spread = (base_spread_bps / 20_000) + kappa * 0.01  # Simplified vol

            bid_price = reservation - half_spread
            ask_price = reservation + half_spread

            # Clamp
            bid_price = max(0.01, min(0.99, bid_price))
            ask_price = max(0.01, min(0.99, ask_price))

            if bid_price >= ask_price:
                continue

            # ── Simulate fills ──
            size = order_size_usd / mid if mid > 0 else 0

            # Buy fill: our bid >= best ask? (someone sells to us)
            if tick.best_ask and bid_price >= tick.best_ask:
                fill_price = tick.best_ask * (1 + self.slippage_bps / 10_000)
                fee = fill_price * size * 0.0  # Maker fee = 0

                portfolio.usdc -= fill_price * size
                inventory += size
                portfolio.add_fee(fee)

                result.fills.append(BacktestFill(
                    timestamp=tick.timestamp,
                    market_id=tick.market_id,
                    side="BUY",
                    price=fill_price,
                    size=size,
                    fee_usd=fee,
                ))

                if not open_entry:
                    open_entry = {
                        "market_id": tick.market_id,
                        "side": "BUY",
                        "price": fill_price,
                        "size": size,
                        "time": tick.timestamp,
                        "fee": fee,
                    }

            # Sell fill: our ask <= best bid? (someone buys from us)
            elif tick.best_bid and ask_price <= tick.best_bid:
                fill_price = tick.best_bid * (1 - self.slippage_bps / 10_000)
                fee = fill_price * size * 0.0  # Maker fee = 0

                portfolio.usdc += fill_price * size
                inventory -= size
                portfolio.add_fee(fee)

                result.fills.append(BacktestFill(
                    timestamp=tick.timestamp,
                    market_id=tick.market_id,
                    side="SELL",
                    price=fill_price,
                    size=size,
                    fee_usd=fee,
                ))

                # Close trade if we had an open entry
                if open_entry and open_entry["side"] == "BUY":
                    pnl = (fill_price - open_entry["price"]) * open_entry["size"] - open_entry["fee"] - fee
                    trade = BacktestTrade(
                        market_id=tick.market_id,
                        entry_side="BUY",
                        entry_price=open_entry["price"],
                        exit_price=fill_price,
                        size=open_entry["size"],
                        entry_time=open_entry["time"],
                        exit_time=tick.timestamp,
                        pnl_usd=pnl,
                        fee_usd=open_entry["fee"] + fee,
                    )
                    trade_log.append(trade)
                    open_entry = None

            result.total_ticks += 1

        # ── Compute results ──
        result.end_time = ticks[-1].timestamp if ticks else 0
        result.start_time = ticks[0].timestamp if ticks else 0
        result.ending_capital = portfolio.total_value
        result.total_pnl = result.ending_capital - result.starting_capital
        result.total_fees = portfolio.total_fees
        result.net_pnl = result.total_pnl - result.total_fees
        result.all_trades = trade_log
        result.equity_curve = portfolio.equity_curve
        result.max_drawdown_pct = portfolio.get_max_drawdown_pct()
        result.max_drawdown_usd = (
            result.max_drawdown_pct / 100 * result.starting_capital
        )

        # Trade statistics
        self._compute_trade_stats(result, trade_log)

        return result

    # ── Results computation ────────────────────────────────────────────

    def _compute_trade_stats(self, result: BacktestResult, trades: List[BacktestTrade]) -> None:
        """Compute detailed trade statistics for a backtest result.

        Args:
            result: Result object to populate.
            trades: List of completed trades.
        """
        result.total_trades = len(trades)

        if not trades:
            return

        wins = [t for t in trades if t.pnl_usd > 0]
        losses = [t for t in trades if t.pnl_usd <= 0]

        result.winning_trades = len(wins)
        result.losing_trades = len(losses)
        result.win_rate = len(wins) / len(trades) if trades else 0

        result.avg_win_usd = sum(t.pnl_usd for t in wins) / len(wins) if wins else 0
        result.avg_loss_usd = sum(abs(t.pnl_usd) for t in losses) / len(losses) if losses else 0

        result.max_win_usd = max((t.pnl_usd for t in trades), default=0)
        result.max_loss_usd = min((t.pnl_usd for t in trades), default=0)

        gross_profit = sum(t.pnl_usd for t in wins)
        gross_loss = sum(abs(t.pnl_usd) for t in losses)
        result.profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # Average hold time
        hold_times = [t.hold_time_sec for t in trades if t.hold_time_sec > 0]
        result.avg_hold_time_sec = sum(hold_times) / len(hold_times) if hold_times else 0

        # Trades per day
        if result.start_time > 0 and result.end_time > result.start_time:
            duration_days = (result.end_time - result.start_time) / 86400
            result.trades_per_day = len(trades) / duration_days if duration_days > 0 else 0

        # Sharpe ratio (simplified: assumes risk-free rate = 0)
        if len(trades) > 1:
            import math
            returns = [t.return_pct for t in trades]
            mean_return = sum(returns) / len(returns)
            variance = sum((r - mean_return) ** 2 for r in returns) / (len(returns) - 1)
            std_return = math.sqrt(variance) if variance > 0 else 0

            result.sharpe_ratio = mean_return / std_return if std_return > 0 else 0

            # Sortino: only downside deviation
            downside = [r for r in returns if r < 0]
            if downside:
                downside_var = sum(r ** 2 for r in downside) / len(downside)
                downside_std = math.sqrt(downside_var)
                result.sortino_ratio = mean_return / downside_std if downside_std > 0 else 0

    # ── Reporting ─────────────────────────────────────────────────────

    def print_report(self, result: BacktestResult) -> str:
        """Generate a formatted backtest report.

        Args:
            result: Backtest result to report.

        Returns:
            Formatted report string.
        """
        lines = [
            "=" * 60,
            f"  BACKTEST REPORT — {result.strategy_name}",
            "=" * 60,
            "",
            "  CAPITAL & P&L",
            f"    Starting Capital:   ${result.starting_capital:,.2f}",
            f"    Ending Capital:     ${result.ending_capital:,.2f}",
            f"    Total P&L:          ${result.total_pnl:+,.2f}",
            f"    Total Fees:         ${result.total_fees:,.2f}",
            f"    Net P&L:            ${result.net_pnl:+,.2f}",
            "",
            "  TRADE STATISTICS",
            f"    Total Trades:       {result.total_trades}",
            f"    Winning:            {result.winning_trades}",
            f"    Losing:             {result.losing_trades}",
            f"    Win Rate:           {result.win_rate:.1%}",
            f"    Avg Win:            ${result.avg_win_usd:,.4f}",
            f"    Avg Loss:           ${result.avg_loss_usd:,.4f}",
            f"    Profit Factor:      {result.profit_factor:.2f}x",
            f"    Max Win:            ${result.max_win_usd:,.4f}",
            f"    Max Loss:           ${result.max_loss_usd:,.4f}",
            "",
            "  RISK METRICS",
            f"    Max Drawdown:       {result.max_drawdown_pct:.2f}%",
            f"    Max Drawdown $:     ${result.max_drawdown_usd:,.2f}",
            f"    Sharpe Ratio:       {result.sharpe_ratio:.3f}",
            f"    Sortino Ratio:      {result.sortino_ratio:.3f}",
            "",
            "  TIMING",
            f"    Avg Hold Time:      {result.avg_hold_time_sec:.0f}s",
            f"    Trades/Day:         {result.trades_per_day:.1f}",
            f"    Total Ticks:        {result.total_ticks}",
            "",
            "=" * 60,
        ]

        report = "\n".join(lines)
        logger.info("Backtest report generated", strategy=result.strategy_name)
        return report

    def save_results(self, result: BacktestResult, output_dir: Optional[str] = None) -> str:
        """Save backtest results to JSON.

        Args:
            result: Backtest result to save.
            output_dir: Output directory (defaults to data/backtest/results/).

        Returns:
            Path to the saved results file.
        """
        out_dir = output_dir or os.path.join(self.data_dir, "results")
        os.makedirs(out_dir, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"{result.strategy_name}_{timestamp}.json"
        filepath = os.path.join(out_dir, filename)

        data = {
            "strategy_name": result.strategy_name,
            "starting_capital": result.starting_capital,
            "ending_capital": result.ending_capital,
            "total_pnl": result.total_pnl,
            "total_fees": result.total_fees,
            "net_pnl": result.net_pnl,
            "total_trades": result.total_trades,
            "win_rate": result.win_rate,
            "profit_factor": result.profit_factor,
            "max_drawdown_pct": result.max_drawdown_pct,
            "sharpe_ratio": result.sharpe_ratio,
            "sortino_ratio": result.sortino_ratio,
            "trades": [
                {
                    "market_id": t.market_id,
                    "entry_price": t.entry_price,
                    "exit_price": t.exit_price,
                    "size": t.size,
                    "pnl_usd": t.pnl_usd,
                    "fee_usd": t.fee_usd,
                    "hold_time_sec": t.hold_time_sec,
                }
                for t in result.all_trades
            ],
            "equity_curve_sampled": result.equity_curve[::10],  # Sample every 10th point
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

        logger.info("Backtest results saved", path=filepath)
        return filepath
