"""Strategy layer: base class and concrete trading strategies."""

__all__ = [
    "Strategy",
    "StrategyState",
    "MarketMakingStrategy",
    "AISignalsStrategy",
    "WhaleTrackingStrategy",
    "CrossPlatformArbStrategy",
]


def __getattr__(name):
    """Lazy import to avoid circular dependency chains."""
    if name in __all__:
        import importlib
        module_map = {
            "Strategy": "strategies.base",
            "StrategyState": "strategies.base",
            "MarketMakingStrategy": "strategies.market_making",
            "AISignalsStrategy": "strategies.ai_signals",
            "WhaleTrackingStrategy": "strategies.whale_tracking",
            "CrossPlatformArbStrategy": "strategies.cross_platform_arb",
        }
        mod = importlib.import_module(module_map[name])
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
