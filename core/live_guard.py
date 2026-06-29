"""Fail-closed controls for any legacy live execution path.

This module does not approve live trading. It provides hard technical controls that
must pass before a legacy write path can even attempt to reach an exchange client.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


ALLOW_LIVE_TRADING_ENV = "ALLOW_LIVE_TRADING"
ALLOW_LIVE_TRADING_VALUE = "TRUE"
OFFICIAL_POLYMARKET_CLOB_HOST = "https://clob.polymarket.com"
HARD_MAX_LIVE_ORDER_NOTIONAL_USD = 5.0
HARD_MAX_LIVE_DAILY_LOSS_USD = 5.0
HARD_MAX_CONSECUTIVE_NETWORK_ERRORS = 3


class LiveTradingBlocked(RuntimeError):
    """Raised when a live-capable action fails the hard safety gate."""


@dataclass(frozen=True)
class LiveTradingGuard:
    """Hard live-execution gate for the legacy bot runtime."""

    config: Mapping[str, Any]
    environ: Mapping[str, str] | None = None

    @property
    def _env(self) -> Mapping[str, str]:
        return self.environ if self.environ is not None else os.environ

    @property
    def execution(self) -> Mapping[str, Any]:
        value = self.config.get("execution", {})
        return value if isinstance(value, Mapping) else {}

    @property
    def live(self) -> Mapping[str, Any]:
        value = self.execution.get("live", {})
        return value if isinstance(value, Mapping) else {}

    def assert_live_enabled(self) -> None:
        """Require explicit opt-in and production-only live settings."""
        if self._env.get(ALLOW_LIVE_TRADING_ENV) != ALLOW_LIVE_TRADING_VALUE:
            raise LiveTradingBlocked(
                f"{ALLOW_LIVE_TRADING_ENV} must be exactly {ALLOW_LIVE_TRADING_VALUE}"
            )
        if self.execution.get("dry_run") is not False:
            raise LiveTradingBlocked("execution.dry_run must be false for live trading")
        if self.live.get("approved_canary") is not True:
            raise LiveTradingBlocked("execution.live.approved_canary must be true")

        clob_host = str(self.execution.get("clob_host") or "").rstrip("/")
        if clob_host != OFFICIAL_POLYMARKET_CLOB_HOST:
            raise LiveTradingBlocked(
                f"live trading requires official CLOB host {OFFICIAL_POLYMARKET_CLOB_HOST}"
            )

        required_env = (
            "POLYGON_PRIVATE_KEY",
            "POLYMARKET_API_KEY",
            "POLYMARKET_API_SECRET",
            "POLYMARKET_API_PASSPHRASE",
        )
        missing = [name for name in required_env if not self._env.get(name)]
        if missing:
            raise LiveTradingBlocked("missing live credential env vars: " + ", ".join(missing))

        max_order = float(self.live.get("max_order_notional_usd", 0))
        if max_order <= 0 or max_order > HARD_MAX_LIVE_ORDER_NOTIONAL_USD:
            raise LiveTradingBlocked(
                f"execution.live.max_order_notional_usd must be > 0 and <= "
                f"{HARD_MAX_LIVE_ORDER_NOTIONAL_USD}"
            )

        max_daily_loss = float(self.live.get("max_daily_loss_usd", 0))
        if max_daily_loss <= 0 or max_daily_loss > HARD_MAX_LIVE_DAILY_LOSS_USD:
            raise LiveTradingBlocked(
                f"execution.live.max_daily_loss_usd must be > 0 and <= "
                f"{HARD_MAX_LIVE_DAILY_LOSS_USD}"
            )

        max_errors = int(self.live.get("max_consecutive_network_errors", 0))
        if max_errors <= 0 or max_errors > HARD_MAX_CONSECUTIVE_NETWORK_ERRORS:
            raise LiveTradingBlocked(
                f"execution.live.max_consecutive_network_errors must be > 0 and <= "
                f"{HARD_MAX_CONSECUTIVE_NETWORK_ERRORS}"
            )

    def assert_order_allowed(self, *, price: float, size: float, post_only: bool) -> None:
        """Require live enablement and hard canary order limits."""
        self.assert_live_enabled()
        if not post_only:
            raise LiveTradingBlocked("live canary orders must be post_only")
        if price <= 0 or price >= 1:
            raise LiveTradingBlocked("live order price must be inside (0, 1)")
        if size <= 0:
            raise LiveTradingBlocked("live order size must be positive")
        notional = price * size
        max_order = float(self.live["max_order_notional_usd"])
        if notional > max_order:
            raise LiveTradingBlocked(
                f"live order notional {notional:.4f} exceeds canary cap {max_order:.4f}"
            )
