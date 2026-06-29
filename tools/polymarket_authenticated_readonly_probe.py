#!/usr/bin/env python3
"""Authenticated read-only Polymarket CLOB probe for Gate B.

This probe is disabled by default and does not create, post, amend, cancel, or score
orders. It only verifies that authenticated read-only account metadata can be fetched
with the current SDK and configured credentials.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.client import ClobClient
from utils.helpers import load_config


ALLOW_AUTH_READONLY_PROBE_ENV = "ALLOW_AUTH_READONLY_PROBE"
REPORT_JSON = PROJECT_ROOT / "reports" / "polymarket_authenticated_readonly_probe.json"


class AuthReadOnlyProbeBlocked(RuntimeError):
    """Raised when the probe is not explicitly enabled."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def require_probe_enabled() -> None:
    if os.environ.get(ALLOW_AUTH_READONLY_PROBE_ENV) != "TRUE":
        raise AuthReadOnlyProbeBlocked(
            f"{ALLOW_AUTH_READONLY_PROBE_ENV} must be exactly TRUE for authenticated reads"
        )


def run_probe(config_path: Path) -> dict[str, Any]:
    require_probe_enabled()
    config = load_config(str(config_path))
    client = ClobClient(config)
    sync_client = client._get_sync_client()
    if sync_client is None:
        raise AuthReadOnlyProbeBlocked("py_clob_client could not initialize")

    address = sync_client.get_address()
    api_keys = sync_client.get_api_keys()
    return {
        "generated_at": utc_now_iso(),
        "probe": "polymarket_authenticated_readonly",
        "write_methods_called": [],
        "address_present": bool(address),
        "api_key_count": len(api_keys) if isinstance(api_keys, list) else None,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config.yaml"))
    parser.add_argument("--json-output", default=str(REPORT_JSON))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_probe(Path(args.config))
    output = Path(args.json_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
