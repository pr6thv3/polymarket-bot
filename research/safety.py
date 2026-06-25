"""Fail-closed safety checks for the read-only research runtime."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class ResearchSafetyError(RuntimeError):
    """Raised when a research process could access trading capability."""


TRADING_CREDENTIAL_ENV_VARS = frozenset(
    {
        "PRIVATE_KEY",
        "POLYMARKET_PRIVATE_KEY",
        "POLYMARKET_API_KEY",
        "POLYMARKET_API_SECRET",
        "POLYMARKET_API_PASSPHRASE",
        "KALSHI_API_KEY",
        "KALSHI_API_SECRET",
        "KALSHI_PRIVATE_KEY",
    }
)

SENSITIVE_HEADER_NAMES = frozenset(
    {
        "authorization",
        "x-api-key",
        "x-api-secret",
        "x-api-passphrase",
        "kalshi-access-key",
        "kalshi-access-signature",
        "kalshi-access-timestamp",
        "poly-address",
        "poly-signature",
        "poly-timestamp",
        "poly-api-key",
        "poly-passphrase",
    }
)


def assert_no_trading_credentials(environ: Mapping[str, str]) -> None:
    """Reject a process that inherited any known trading credential."""
    present = sorted(
        key for key in TRADING_CREDENTIAL_ENV_VARS if environ.get(key, "").strip()
    )
    if present:
        raise ResearchSafetyError(
            "Read-only research refuses a process with trading credentials: "
            + ", ".join(present)
        )


def assert_read_only_config(config: Mapping[str, Any]) -> None:
    """Require dry-run and explicit disablement of every strategy."""
    execution = config.get("execution", {})
    if execution.get("dry_run") is not True:
        raise ResearchSafetyError("research requires execution.dry_run: true")

    enabled = [
        name
        for name, settings in config.get("strategies", {}).items()
        if isinstance(settings, Mapping) and settings.get("enabled") is True
    ]
    if enabled:
        raise ResearchSafetyError(
            "research requires every execution-capable strategy disabled: "
            + ", ".join(sorted(enabled))
        )
