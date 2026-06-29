#!/usr/bin/env python3
"""Static, read-only Gate B audit for legacy Polymarket execution safety.

Gate B checks technical safety artifacts. It does not approve live trading and does
not override legal/compliance review, paper-profit evidence, or explicit user approval.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_MD = PROJECT_ROOT / "reports" / "gate_b_audit.md"
REPORT_JSON = PROJECT_ROOT / "reports" / "gate_b_audit.json"


@dataclass(frozen=True)
class AuditItem:
    name: str
    status: str
    detail: str
    evidence: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
        }
        if self.evidence:
            payload["evidence"] = self.evidence
        return payload


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def audit_sdk_lock() -> AuditItem:
    lock = read(PROJECT_ROOT / "requirements.lock")
    match = re.search(r"^py_clob_client==(?P<version>[^\s]+)$", lock, flags=re.MULTILINE)
    if not match:
        return AuditItem(
            "current_sdk_lock",
            "fail",
            "requirements.lock does not pin py_clob_client",
        )
    return AuditItem(
        "current_sdk_lock",
        "pass",
        f"requirements.lock pins py_clob_client=={match.group('version')}",
        {"version": match.group("version")},
    )


def audit_deprecated_order_fields() -> AuditItem:
    client = read(PROJECT_ROOT / "core" / "client.py")
    deprecated = {
        "feeRateBps": "legacy fee-rate field",
        "USDC.e": "legacy collateral symbol assumption",
        "get_next_nonce": "local nonce cache should not be used by the legacy wrapper",
    }
    found = {field: reason for field, reason in deprecated.items() if field in client}
    if found:
        return AuditItem(
            "deprecated_execution_fields",
            "fail",
            "legacy client contains deprecated execution fields",
            {"found": found},
        )
    return AuditItem(
        "deprecated_execution_fields",
        "pass",
        "no known deprecated literal fields or local nonce cache found in core/client.py",
    )


def audit_auth_domain_and_signature() -> AuditItem:
    client = read(PROJECT_ROOT / "core" / "client.py")
    guard = read(PROJECT_ROOT / "core" / "live_guard.py")
    evidence = {
        "configurable_clob_host": "self.clob_host" in client and "POLYMARKET_CLOB_HOST" in client,
        "configurable_signature_type": "self.signature_type" in client
        and "signature_type=self.signature_type" in client,
        "live_guard_requires_official_host": "OFFICIAL_POLYMARKET_CLOB_HOST" in guard,
    }
    return AuditItem(
        "auth_domain_signature_assumptions",
        "pass" if all(evidence.values()) else "fail",
        "legacy auth/domain/signature assumptions are explicit and guarded",
        evidence,
    )


def audit_live_guard_controls() -> AuditItem:
    guard = read(PROJECT_ROOT / "core" / "live_guard.py")
    config = read(PROJECT_ROOT / "config.yaml")
    evidence = {
        "exact_live_env_flag": 'ALLOW_LIVE_TRADING_VALUE = "TRUE"' in guard,
        "hard_order_cap": "HARD_MAX_LIVE_ORDER_NOTIONAL_USD = 5.0" in guard,
        "hard_daily_loss_cap": "HARD_MAX_LIVE_DAILY_LOSS_USD = 5.0" in guard,
        "hard_error_cap": "HARD_MAX_CONSECUTIVE_NETWORK_ERRORS = 3" in guard,
        "config_canary_disabled": "approved_canary: false" in config,
        "config_live_caps_present": "max_order_notional_usd: 5.0" in config
        and "max_daily_loss_usd: 5.0" in config,
    }
    return AuditItem(
        "live_guard_controls",
        "pass" if all(evidence.values()) else "fail",
        "hard canary limits and explicit live opt-in are present",
        evidence,
    )


def audit_post_only_forwarding() -> AuditItem:
    client = read(PROJECT_ROOT / "core" / "client.py")
    guard = read(PROJECT_ROOT / "core" / "live_guard.py")
    evidence = {
        "post_only_guard": "live canary orders must be post_only" in guard,
        "sdk_post_order_receives_post_only": (
            "client.post_order, signed_order, OrderType.GTD, post_only=post_only" in client
        ),
    }
    return AuditItem(
        "post_only_forwarding",
        "pass" if all(evidence.values()) else "fail",
        "legacy client forwards post_only into the SDK post_order call",
        evidence,
    )


def audit_read_only_authenticated_probe() -> AuditItem:
    path = PROJECT_ROOT / "tools" / "polymarket_authenticated_readonly_probe.py"
    text = read(path)
    evidence = {
        "probe_file_exists": path.exists(),
        "explicit_env_flag": "ALLOW_AUTH_READONLY_PROBE" in text,
        "uses_readonly_get_api_keys": "get_api_keys()" in text,
        "no_write_method_calls": all(
            token not in text
            for token in (".create_order(", ".post_order(", ".cancel(", ".amend_order(")
        ),
    }
    return AuditItem(
        "read_only_authenticated_probe",
        "pass" if all(evidence.values()) else "fail",
        "authenticated read-only probe is implemented and disabled by default",
        evidence,
    )


def audit_rfq_combos_awareness() -> AuditItem:
    path = PROJECT_ROOT / "docs" / "legacy-execution-api-review.md"
    lower = read(path).lower()
    evidence = {
        "review_doc_exists": path.exists(),
        "rfq_covered": "rfq" in lower,
        "combos_covered": "combos" in lower,
        "excluded_from_canary": "excluded from the live canary scope" in lower,
    }
    return AuditItem(
        "rfq_combos_awareness",
        "pass" if all(evidence.values()) else "fail",
        "RFQ/Combos implications are documented and excluded from canary scope",
        evidence,
    )


def build_audit() -> dict[str, Any]:
    items = [
        audit_sdk_lock(),
        audit_deprecated_order_fields(),
        audit_auth_domain_and_signature(),
        audit_live_guard_controls(),
        audit_post_only_forwarding(),
        audit_read_only_authenticated_probe(),
        audit_rfq_combos_awareness(),
    ]
    status = "pass" if all(item.status == "pass" for item in items) else "fail"
    return {
        "generated_at": utc_now_iso(),
        "overall_status": status,
        "live_trading_status": "NO-GO",
        "interpretation": (
            "Gate B technical safety artifacts are present. This does not override Gate A "
            "legal/compliance review, Gate 2 profitability evidence, or explicit user approval."
        ),
        "items": [item.to_dict() for item in items],
    }


def render_markdown(audit: dict[str, Any]) -> str:
    rows = "\n".join(
        f"|{item['name']}|{item['status'].upper()}|{item['detail']}|"
        for item in audit["items"]
    )
    return f"""# Gate B Technical Execution Audit

Generated at: `{audit['generated_at']}`

|Field|Status|
|---|---|
|Overall Gate B technical status|{audit['overall_status'].upper()}|
|Live trading|{audit['live_trading_status']}|

## Items

|Item|Status|Detail|
|---|---|---|
{rows}

## Interpretation

{audit['interpretation']}

Any `FAIL` item blocks Gate B. A `PASS` here means technical safety artifacts are
present; it is not permission to trade live.
"""


def write_audit(audit: dict[str, Any], md_path: Path, json_path: Path) -> None:
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_markdown(audit), encoding="utf-8")
    json_path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--markdown-output", default=str(REPORT_MD))
    parser.add_argument("--json-output", default=str(REPORT_JSON))
    parser.add_argument("--allow-fail", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    audit = build_audit()
    write_audit(audit, Path(args.markdown_output), Path(args.json_output))
    print(Path(args.markdown_output))
    print(Path(args.json_output))
    return 0 if args.allow_fail or audit["overall_status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
