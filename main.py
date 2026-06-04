"""Polymarket Trading Bot — Main entry point.

Phase 4: Multi-strategy orchestrator with cross-platform arbitrage,
whale tracking, AI signal trading, paper trading, and backtesting support.

Features:
- Windows asyncio event loop fix (ProactorEventLoop)
- Graceful shutdown on SIGINT/SIGTERM
- Structured logging + Prometheus metrics
- Telegram alerting
- Portfolio state persistence
- Health monitoring loop
- Market scanner (scores + ranks markets for MM)
- Multi-strategy dispatch: market making, cross-arb, whale tracking, AI signals
- Paper trading mode (execution.dry_run: true)
- Backtesting mode (--backtest CLI flag)
- Fill event processing loop
- Strategy orchestration with auto-recovery
"""

import argparse
import asyncio
import os
import signal
import sys
import time
from pathlib import Path
from typing import Dict, Optional

import structlog

# --- Windows asyncio fix ---
# On Windows, the default SelectorEventLoop doesn't support subprocesses
# and has issues with aiohttp. Force ProactorEventLoop.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from utils.helpers import load_config
from utils.logger import setup_logging, get_logger
from utils import metrics as m
from utils.alerting import Alerter
from core.client import ClobClient
from core.orderbook import OrderBookManager
from core.executor import Executor, OrderRejectedByRisk
from core.order_state import OrderStore
from core.portfolio import Portfolio
from core.risk import RiskManager
from data.market_scanner import MarketScanner
from strategies.market_making import MarketMakingStrategy

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class PolymarketBot:
    """Main bot orchestrator.

    Phase 4: Initializes all components, runs health checks,
    manages multi-strategy dispatch (MM, cross-arb, whale tracking, AI signals),
    handles paper trading mode, and manages graceful shutdown.
    """

    def __init__(self, config: dict, paper_mode: bool = False) -> None:
        """Initialize the bot with all components.

        Args:
            config: Full config dict loaded from config.yaml.
            paper_mode: If True, use PaperExecutor instead of real Executor.
        """
        self.config = config
        self.paper_mode = paper_mode or config.get("execution", {}).get("dry_run", False)
        self.logger = get_logger("bot")

        # Core components (Phase 1)
        self.client = ClobClient(config)
        self.portfolio = Portfolio(config)
        self.order_store = OrderStore(
            pending_timeout_sec=config.get("execution", {}).get("pending_timeout_sec", 5.0)
        )
        self.risk_manager = RiskManager(self.portfolio, config)
        self.orderbook = OrderBookManager(config)

        # Real executor (always available for risk checks)
        self.real_executor = Executor(
            client=self.client,
            order_store=self.order_store,
            portfolio=self.portfolio,
            risk_manager=self.risk_manager,
            config=config,
        )

        # Choose executor based on mode
        if self.paper_mode:
            from core.paper_executor import PaperExecutor, PaperPortfolio

            starting_capital = float(os.environ.get("STARTING_CAPITAL", "1000"))
            self.paper_portfolio = PaperPortfolio(starting_capital, config)
            self.executor = PaperExecutor(
                real_executor=self.real_executor,
                paper_portfolio=self.paper_portfolio,
                orderbook_manager=self.orderbook,
                config=config,
            )
            self.logger.info("🔄 Paper trading mode ENABLED — no real orders will be placed")
        else:
            self.executor = self.real_executor
            self.paper_portfolio = None

        self.alerter = Alerter(config)

        # Wire up alerter references
        self.client.alerter = self.alerter
        self.risk_manager.alerter = self.alerter

        # Phase 2: Market scanner
        self.scanner = MarketScanner(
            client=self.client,
            orderbook=self.orderbook,
            config=config,
        )

        # Phase 3: Multi-strategy registry
        self.strategies: Dict[str, object] = {}

        # ── Initialize strategies ──────────────────────────────────────

        self._init_market_making(config)
        self._init_cross_platform_arb(config)
        self._init_whale_tracking(config)
        self._init_ai_signals(config)

        # State
        self._running = False
        self._shutdown_event = asyncio.Event()

    # ── Strategy initializers ──────────────────────────────────────────

    def _init_market_making(self, config: dict) -> None:
        """Initialize the market-making strategy if enabled."""
        mm_cfg = config.get("strategies", {}).get("market_making", {})
        if mm_cfg.get("enabled", False):
            self.mm_strategy = MarketMakingStrategy(
                client=self.client,
                orderbook=self.orderbook,
                portfolio=self.portfolio,
                risk_manager=self.risk_manager,
                executor=self.executor,
                order_store=self.order_store,
                scanner=self.scanner,
                config=config,
            )
            self.strategies["market_making"] = self.mm_strategy
        else:
            self.mm_strategy = None
            self.logger.info("Market-making strategy disabled in config")

    def _init_cross_platform_arb(self, config: dict) -> None:
        """Initialize the cross-platform arbitrage strategy if enabled."""
        arb_cfg = config.get("strategies", {}).get("cross_arb", {})
        if arb_cfg.get("enabled", False):
            try:
                from strategies.cross_platform_arb import CrossPlatformArbStrategy
                from data.kalshi_client import KalshiClient

                kalshi_client = KalshiClient(config)

                self.arb_strategy = CrossPlatformArbStrategy(
                    client=self.client,
                    orderbook=self.orderbook,
                    portfolio=self.portfolio,
                    risk_manager=self.risk_manager,
                    executor=self.executor,
                    order_store=self.order_store,
                    kalshi_client=kalshi_client,
                    config=config,
                )
                self.strategies["cross_platform_arb"] = self.arb_strategy
                self.logger.info("Cross-platform arbitrage strategy enabled")
            except ImportError as exc:
                self.logger.error(
                    "Failed to import cross-platform arb strategy",
                    error=str(exc),
                )
            except Exception as exc:
                self.logger.error(
                    "Failed to initialize cross-platform arb strategy",
                    error=str(exc),
                )
        else:
            self.arb_strategy = None
            self.logger.info("Cross-platform arbitrage strategy disabled in config")

    def _init_whale_tracking(self, config: dict) -> None:
        """Initialize the whale tracking strategy if enabled."""
        wt_cfg = config.get("strategies", {}).get("whale_tracking", {})
        if wt_cfg.get("enabled", False):
            try:
                from strategies.whale_tracking import WhaleTrackingStrategy
                from data.whale_tracker import WhaleTracker

                whale_tracker = WhaleTracker(config)

                self.whale_strategy = WhaleTrackingStrategy(
                    client=self.client,
                    orderbook=self.orderbook,
                    portfolio=self.portfolio,
                    risk_manager=self.risk_manager,
                    executor=self.executor,
                    order_store=self.order_store,
                    whale_tracker=whale_tracker,
                    config=config,
                )
                self.strategies["whale_tracking"] = self.whale_strategy
                self.logger.info("Whale tracking strategy enabled")
            except ImportError as exc:
                self.logger.error(
                    "Failed to import whale tracking strategy",
                    error=str(exc),
                )
            except Exception as exc:
                self.logger.error(
                    "Failed to initialize whale tracking strategy",
                    error=str(exc),
                )
        else:
            self.whale_strategy = None
            self.logger.info("Whale tracking strategy disabled in config")

        def _init_ai_signals(self, config: dict) -> None:
            """Initialize the AI signal strategy if enabled."""
            ai_cfg = config.get("strategies", {}).get("ai_signals", {})
            if ai_cfg.get("enabled", False):
                try:
                    from strategies.ai_signals import AISignalsStrategy
                    from data.news_fetcher import NewsFetcher
                    from data.signal_model import SignalModel

                    news_fetcher = NewsFetcher(config)
                    signal_model = SignalModel(config)

                    self.ai_strategy = AISignalsStrategy(
                        client=self.client,
                        orderbook=self.orderbook,
                        portfolio=self.portfolio,
                        risk_manager=self.risk_manager,
                        executor=self.executor,
                        order_store=self.order_store,
                        scanner=self.scanner,
                        news_fetcher=news_fetcher,
                        signal_model=signal_model,
                        config=config,
                    )
                    self.strategies["ai_signals"] = self.ai_strategy
                    self.logger.info("AI signal strategy enabled")
                except ImportError as exc:
                    self.logger.error(
                        "Failed to import AI signal strategy",
                        error=str(exc),
                    )
                except Exception as exc:
                    self.logger.error(
                        "Failed to initialize AI signal strategy",
                        error=str(exc),
                    )
            else:
                self.ai_strategy = None
                self.logger.info("AI signal strategy disabled in config")

    # ── Initialization ─────────────────────────────────────────────────

    async def initialize(self) -> None:
        """Initialize all components and run startup checks."""
        mode_label = "PAPER" if self.paper_mode else "LIVE"
        self.logger.info(
            f"Initializing Polymarket Trading Bot (mode={mode_label})...",
            strategies=list(self.strategies.keys()),
        )

        # Load environment
        from dotenv import load_dotenv
        load_dotenv()

        # Initialize portfolio
        starting_capital = float(os.environ.get("STARTING_CAPITAL", "1000"))
        await self.portfolio.initialize(starting_capital=starting_capital)
        self.logger.info(
            "Portfolio initialized",
            starting_capital=starting_capital,
            free_usdc=self.portfolio.free_usdc,
        )

        # Start metrics server
        metrics_port = self.config.get("monitoring", {}).get("metrics_port", 9090)
        m.start_metrics_server(port=metrics_port)

        # Health check
        health = await self.client.health_check()
        self.logger.info("CLOB health check", **health)

        if health.get("status") == "circuit_breaker_open":
            self.logger.critical(
                "Circuit breaker is open at startup — waiting for recovery"
            )
            await self.alerter.send_alert(
                "connection_lost",
                "Bot started but CLOB circuit breaker is open. Will retry.",
            )

        # Initialize strategies
        for name, strategy in self.strategies.items():
            try:
                await strategy.start()
                self.logger.info("Strategy started", strategy=name)
            except Exception as exc:
                self.logger.error(
                    "Strategy failed to start",
                    strategy=name,
                    error=str(exc),
                )

        self.logger.info(
            "Bot initialization complete",
            active_strategies=list(self.strategies.keys()),
            paper_mode=self.paper_mode,
        )

    # ── Main loop ──────────────────────────────────────────────────────

    async def run(self) -> None:
        """Run the main bot loop.

        Phase 3: Infrastructure monitoring + multi-strategy orchestration.
        Each strategy runs in its own async task, with the bot
        supervising and handling graceful degradation.
        """
        self._running = True
        mode_label = "PAPER" if self.paper_mode else "LIVE"
        self.logger.info(f"Bot main loop started (mode={mode_label})")

        # Infrastructure tasks (always running)
        tasks = [
            asyncio.create_task(self._health_monitor_loop(), name="health_monitor"),
            asyncio.create_task(self._portfolio_save_loop(), name="portfolio_save"),
            asyncio.create_task(self._pending_timeout_loop(), name="pending_timeout"),
            asyncio.create_task(self._risk_summary_loop(), name="risk_summary"),
            asyncio.create_task(self._fill_processing_loop(), name="fill_processor"),
            asyncio.create_task(self._shutdown_waiter(), name="shutdown_waiter"),
        ]

        # Paper trading: open order fill simulation
        if self.paper_mode and hasattr(self.executor, "process_open_orders"):
            tasks.append(
                asyncio.create_task(
                    self._paper_fill_loop(), name="paper_fill_simulator"
                )
            )

        # Strategy tasks
        for name, strategy in self.strategies.items():
            tasks.append(
                asyncio.create_task(
                    self._strategy_loop(name, strategy),
                    name=f"strategy_{name}",
                )
            )

        # Wait for shutdown or first task to fail
        done, pending = await asyncio.wait(
            tasks,
            return_when=asyncio.FIRST_EXCEPTION,
        )

        # Check for exceptions
        for task in done:
            if task.exception() is not None:
                self.logger.error(
                    "Task failed unexpectedly",
                    task_name=task.get_name(),
                    error=str(task.exception()),
                )

        # Cancel remaining tasks
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    # ── Infrastructure loops ──────────────────────────────────────────

    async def _health_monitor_loop(self) -> None:
        """Periodically check CLOB connectivity."""
        interval = self.config.get("monitoring", {}).get("health_check_sec", 30)

        while self._running:
            try:
                health = await self.client.health_check()

                if health.get("status") != "ok":
                    self.logger.warning(
                        "CLOB health check failed",
                        status=health.get("status"),
                        latency=health.get("latency_sec"),
                    )
                    await self.alerter.send_alert(
                        "connection_lost",
                        f"CLOB health check: {health.get('status')}. "
                        f"Latency: {health.get('latency_sec', 'N/A')}s",
                    )

                # Update P&L metric
                m.update_pnl(self.portfolio.total_pnl)

            except Exception as exc:
                self.logger.error("Health monitor error", error=str(exc))

            await asyncio.sleep(interval)

    async def _portfolio_save_loop(self) -> None:
        """Periodically save portfolio state to disk."""
        interval = 60  # Save every 60 seconds

        while self._running:
            try:
                await self.portfolio.save_state()
            except Exception as exc:
                self.logger.error("Portfolio save error", error=str(exc))

            await asyncio.sleep(interval)

    async def _pending_timeout_loop(self) -> None:
        """Check for PENDING orders that should be promoted to OPEN."""
        interval = 5  # Check every 5 seconds

        while self._running:
            try:
                timed_out = await self.order_store.check_pending_timeouts()
                if timed_out:
                    self.logger.debug("PENDING timeouts resolved", count=len(timed_out))
            except Exception as exc:
                self.logger.error("Pending timeout check error", error=str(exc))

            await asyncio.sleep(interval)

    async def _risk_summary_loop(self) -> None:
        """Periodically log risk summary and strategy stats."""
        interval = 300  # Every 5 minutes

        while self._running:
            try:
                summary = self.risk_manager.get_risk_summary()
                self.logger.info("Risk summary", **summary)

                # Calculate and record holding rewards
                daily_reward = self.portfolio.calculate_daily_holding_reward()
                if daily_reward > 0:
                    m.record_holding_reward(daily_reward)
                    self.logger.info("Holding rewards estimate", daily_usd=daily_reward)

                # Log strategy summaries
                for name, strategy in self.strategies.items():
                    if hasattr(strategy, "get_mm_summary"):
                        mm_summary = strategy.get_mm_summary()
                        self.logger.info("MM summary", **mm_summary)

                # Paper trading stats
                if self.paper_mode and hasattr(self.executor, "get_stats"):
                    paper_stats = self.executor.get_stats()
                    self.logger.info("Paper trading stats", **paper_stats)

            except Exception as exc:
                self.logger.error("Risk summary error", error=str(exc))

            await asyncio.sleep(interval)

    async def _fill_processing_loop(self) -> None:
        """Poll for fill events and process them through the strategy.

        Checks for order state changes (fills) and notifies the
        market-making strategy for adverse selection tracking.
        """
        interval = 2  # Check every 2 seconds

        while self._running:
            try:
                # Poll the order store for newly filled orders
                filled_orders = (
                    self.order_store.get_recently_filled()
                    if hasattr(self.order_store, "get_recently_filled")
                    else []
                )

                for record in filled_orders:
                    # Notify MM strategy of fill for adverse selection tracking
                    if self.mm_strategy and self.mm_strategy.state.enabled:
                        self.mm_strategy.record_fill(
                            market_id=record.market_id,
                            side=record.side,
                        )

                    # Record rebate earned (maker rebate)
                    category = ""
                    if hasattr(record, "category"):
                        category = record.category
                    rebate = self.risk_manager.calculate_rebate_value(
                        notional=record.price * record.filled_size,
                        category=category,
                    )
                    if rebate > 0:
                        m.record_rebate_earned(rebate)

            except Exception as exc:
                self.logger.error("Fill processing error", error=str(exc))

            await asyncio.sleep(interval)

    async def _paper_fill_loop(self) -> None:
        """Paper trading: periodically simulate fills for open virtual orders."""
        interval = 3  # Check every 3 seconds

        while self._running:
            try:
                if hasattr(self.executor, "process_open_orders"):
                    filled = await self.executor.process_open_orders()
                    if filled > 0:
                        self.logger.debug(
                            "Paper fill simulation",
                            orders_filled=filled,
                        )
            except Exception as exc:
                self.logger.error("Paper fill simulation error", error=str(exc))

            await asyncio.sleep(interval)

    # ── Strategy orchestration ────────────────────────────────────────

    async def _strategy_loop(self, name: str, strategy) -> None:
        """Run a strategy's cycle loop with graceful degradation.

        Each strategy's run_cycle() is called at its configured interval.
        If the strategy auto-pauses due to consecutive errors, it will
        be restarted after a backoff period.

        Args:
            name: Strategy name for logging.
            strategy: Strategy instance.
        """
        restart_backoff = 60  # Seconds to wait before restarting a paused strategy
        last_restart_attempt = 0.0

        while self._running:
            try:
                # Check if strategy needs restart
                if not strategy.state.enabled and strategy.is_enabled:
                    now = time.monotonic()
                    if now - last_restart_attempt > restart_backoff:
                        self.logger.info(
                            "Attempting strategy restart",
                            strategy=name,
                        )
                        try:
                            await strategy.start()
                            last_restart_attempt = now
                            self.logger.info("Strategy restarted", strategy=name)
                        except Exception as exc:
                            self.logger.error(
                                "Strategy restart failed",
                                strategy=name,
                                error=str(exc),
                            )
                            last_restart_attempt = now
                            await asyncio.sleep(10)
                            continue

                if not strategy.state.enabled:
                    await asyncio.sleep(10)
                    continue

                # Run the strategy cycle if enough time has passed
                if strategy.should_run_cycle():
                    await strategy.safe_run_cycle()

                # Sleep for the remaining interval
                elapsed = strategy.get_time_since_last_cycle()
                remaining = max(0.1, strategy.cycle_interval_sec - elapsed)
                await asyncio.sleep(remaining)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.logger.error(
                    "Strategy loop error",
                    strategy=name,
                    error=str(exc),
                )
                await asyncio.sleep(5)

    # ── Shutdown ──────────────────────────────────────────────────────

    async def _shutdown_waiter(self) -> None:
        """Wait for the shutdown event."""
        await self._shutdown_event.wait()
        self._running = False

    async def shutdown(self) -> None:
        """Graceful shutdown sequence.

        1. Stop all strategies (cancel their orders)
        2. Stop accepting new orders
        3. Cancel all remaining open orders
        4. Save portfolio state
        5. Print paper trading report (if applicable)
        6. Close connections
        """
        self.logger.info("Shutting down...")
        self._running = False
        self._shutdown_event.set()

        # 1. Stop strategies (they cancel their own orders)
        for name, strategy in self.strategies.items():
            try:
                await strategy.stop()
                self.logger.info("Strategy stopped", strategy=name)
            except Exception as exc:
                self.logger.error(
                    "Strategy shutdown error",
                    strategy=name,
                    error=str(exc),
                )

        # 2. Emergency cancel any remaining orders
        try:
            cancelled = await self.executor.emergency_cancel_all()
            self.logger.info("Emergency cancel completed", orders_cancelled=cancelled)
        except Exception as exc:
            self.logger.error("Emergency cancel failed during shutdown", error=str(exc))

        # 3. Save portfolio state
        try:
            await self.portfolio.force_save()
        except Exception as exc:
            self.logger.error("Portfolio save failed during shutdown", error=str(exc))

        # 4. Paper trading session report
        if self.paper_mode and hasattr(self.executor, "get_session_report"):
            try:
                report = self.executor.get_session_report()
                self.logger.info(f"\n{report}")
            except Exception:
                pass

        # 5. Send daily summary alert
        try:
            await self.alerter.send_daily_summary(
                pnl_usd=self.portfolio.total_pnl,
                rebate_usd=0.0,  # Tracked by metrics
                holding_reward_usd=0.0,
                spread_captured_usd=0.0,
                total_fill_rate=0.0,
            )
        except Exception:
            pass

        # 6. Close connections
        try:
            await self.alerter.close()
        except Exception:
            pass

        self.logger.info("Shutdown complete")

    # ── Strategy status ───────────────────────────────────────────────

    def get_status(self) -> Dict[str, any]:
        """Get current bot status summary.

        Returns:
            Dict with strategy states, portfolio info, and mode.
        """
        status = {
            "mode": "PAPER" if self.paper_mode else "LIVE",
            "running": self._running,
            "strategies": {},
            "portfolio": {
                "usdc": self.portfolio.free_usdc,
                "total_pnl": self.portfolio.total_pnl,
            },
        }

        for name, strategy in self.strategies.items():
            status["strategies"][name] = {
                "enabled": strategy.state.enabled,
                "cycles": strategy.state.cycles_completed,
                "errors": strategy.state.errors_total,
                "last_cycle": strategy.state.last_cycle_at,
            }

        if self.paper_mode and hasattr(self.executor, "get_stats"):
            status["paper_stats"] = self.executor.get_stats()

        return status


# ── Backtest runner ────────────────────────────────────────────────────

def run_backtest(config: dict, args: argparse.Namespace) -> None:
    """Run a backtest instead of live/paper trading.

    Args:
        config: Full config dict.
        args: Parsed CLI arguments.
    """
    from core.backtest import BacktestEngine

    logger = get_logger("backtest")
    engine = BacktestEngine(config)

    strategy_name = args.backtest_strategy or "market_making"
    data_dir = args.backtest_data or None
    capital = args.backtest_capital or 1000.0

    logger.info(
        "Starting backtest",
        strategy=strategy_name,
        capital=capital,
        data_dir=data_dir,
    )

    if strategy_name == "market_making":
        # Use sample data if no data directory provided
        if data_dir:
            # Load from file
            import glob
            data_files = glob.glob(os.path.join(data_dir, "*.jsonl"))
            if not data_files:
                logger.error("No .jsonl data files found", data_dir=data_dir)
                return

            all_ticks = []
            for f in data_files:
                market_id = os.path.splitext(os.path.basename(f))[0]
                ticks = engine.load_market_data(market_id, data_file=f)
                all_ticks.extend(ticks)

            all_ticks.sort(key=lambda t: t.timestamp)
        else:
            # Generate synthetic data
            logger.info("No data directory provided — generating synthetic data")
            all_ticks = engine.generate_sample_data(
                market_id="synthetic-test",
                start_price=0.50,
                num_ticks=args.backtest_ticks or 5000,
                volatility=0.02,
                spread_bps=200,
            )

        result = engine.run_market_making(
            ticks=all_ticks,
            starting_capital=capital,
            base_spread_bps=config.get("strategies", {}).get("market_making", {}).get("base_spread_bps", 200),
            order_size_usd=config.get("strategies", {}).get("market_making", {}).get("order_size_usd", 15.0),
        )

        report = engine.print_report(result)
        print(report)

        # Save results
        results_path = engine.save_results(result)
        logger.info("Backtest results saved", path=results_path)

    else:
        logger.error(
            "Unsupported backtest strategy",
            strategy=strategy_name,
            supported=["market_making"],
        )


# ── CLI ────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Polymarket Trading Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                        # Live trading (default)
  python main.py --paper                # Paper trading mode
  python main.py --backtest             # Run backtest with synthetic data
  python main.py --backtest --backtest-data ./data/backtest/
  python main.py --backtest --backtest-capital 5000
  python main.py --status               # Print bot status and exit
        """,
    )

    # Mode flags
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--paper",
        action="store_true",
        help="Run in paper trading mode (no real orders)",
    )
    mode_group.add_argument(
        "--backtest",
        action="store_true",
        help="Run backtest instead of live trading",
    )
    mode_group.add_argument(
        "--status",
        action="store_true",
        help="Print current bot status and exit",
    )

    # Backtest options
    bt_group = parser.add_argument_group("Backtest options")
    bt_group.add_argument(
        "--backtest-strategy",
        default="market_making",
        choices=["market_making", "ai_signals"],
        help="Strategy to backtest (default: market_making)",
    )
    bt_group.add_argument(
        "--backtest-data",
        default=None,
        help="Directory with .jsonl backtest data files",
    )
    bt_group.add_argument(
        "--backtest-capital",
        type=float,
        default=1000.0,
        help="Starting capital for backtest (default: 1000)",
    )
    bt_group.add_argument(
        "--backtest-ticks",
        type=int,
        default=5000,
        help="Number of synthetic ticks when no data dir (default: 5000)",
    )

    return parser.parse_args()


# ── Entry point ────────────────────────────────────────────────────────

async def main() -> None:
    """Main entry point."""
    args = parse_args()

    # Load config
    config = load_config()

    # Setup logging
    setup_logging(config)
    logger = get_logger("main")

    # ── Backtest mode ──
    if args.backtest:
        logger.info("Running in backtest mode")
        run_backtest(config, args)
        return

    # ── Determine paper mode ──
    paper_mode = args.paper or config.get("execution", {}).get("dry_run", False)

    if paper_mode:
        logger.info("🔄 Paper trading mode — no real orders will be placed")
    else:
        logger.info("🔴 LIVE trading mode — real orders will be placed")

    logger.info(
        "Starting Polymarket Trading Bot (Phase 4 — Multi-Strategy + AI Signals)",
        strategies=list(config.get("strategies", {}).keys()),
    )

    # Create bot
    bot = PolymarketBot(config, paper_mode=paper_mode)

    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()

    def _signal_handler() -> None:
        logger.info("Shutdown signal received")
        asyncio.ensure_future(bot.shutdown())

    # On Windows, SIGINT works but SIGTERM may not
    try:
        loop.add_signal_handler(signal.SIGINT, _signal_handler)
        loop.add_signal_handler(signal.SIGTERM, _signal_handler)
    except NotImplementedError:
        # Windows fallback — just handle KeyboardInterrupt in the try/except below
        pass

    try:
        await bot.initialize()
        await bot.run()
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received, shutting down")
        await bot.shutdown()
    except Exception as exc:
        logger.critical("Bot crashed", error=str(exc), exc_info=True)
        await bot.shutdown()
        raise


if __name__ == "__main__":
    asyncio.run(main())
