"""Core layer: order lifecycle, execution, risk management, and portfolio tracking."""

__all__ = [
    "OrderStore",
    "OrderRecord",
    "OrderState",
    "RiskManager",
    "OrderExecutor",
    "PaperExecutor",
    "OrderBookManager",
    "PortfolioTracker",
    "ClobClient",
    "BacktestEngine",
]


def __getattr__(name):
    """Lazy import to avoid circular dependency chains."""
    if name in __all__:
        import importlib
        module_map = {
            "OrderStore": "core.order_state",
            "OrderRecord": "core.order_state",
            "OrderState": "core.order_state",
            "RiskManager": "core.risk",
            "OrderExecutor": "core.executor",
            "PaperExecutor": "core.paper_executor",
            "OrderBookManager": "core.orderbook",
            "PortfolioTracker": "core.portfolio",
            "ClobClient": "core.client",
            "BacktestEngine": "core.backtest",
        }
        mod = importlib.import_module(module_map[name])
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
