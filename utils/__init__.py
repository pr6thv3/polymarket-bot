"""Utilities: metrics, alerts, logging, and helpers."""

__all__ = [
    "setup_logging",
    "get_logger",
    "update_pnl",
    "record_signal_generated",
    "start_metrics_server",
    "Alerter",
]


def __getattr__(name):
    """Lazy import to avoid circular dependency chains."""
    if name in __all__:
        import importlib
        module_map = {
            "setup_logging": "utils.logger",
            "get_logger": "utils.logger",
            "update_pnl": "utils.metrics",
            "record_signal_generated": "utils.metrics",
            "start_metrics_server": "utils.metrics",
            "Alerter": "utils.alerting",
        }
        mod = importlib.import_module(module_map[name])
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
