#!/usr/bin/env python3
"""Static, read-only Gate B audit for legacy Polymarket execution assumptions.

Gate B does not approve live trading. It identifies execution-path assumptions that
must be reviewed against current official venue APIs before any live canary discussion.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
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
    }
    found = {field: reason for field, reason in deprecated.items() if field in client}
    nonce_lines = [
        index
        for index, line in enumerate(client.splitlines(), start=1)
        if "nonce" in line.lower()
    ]
    if found or nonce_lines:
        return AuditItem(
            "deprecated_execution_fields",
            "review",
            "legacy client contains fields or nonce handling that require current API review",
            {"found": found, "nonce_line_count": len(nonce_lines)},
        )
    return AuditItem(
        "deprecated_execution_fields",
        "pass",
        "no known deprecated literal fields found in core/client.py",
    )


def audit_auth_domain_and_signature() -> AuditItem:
    client = read(PROJECT_ROOT / "core" / "client.py")
    evidence = {
        "uses_clob_host": "clob.polymarket.com" in client,
        "hardcoded_signature_type": "signature_type=0" in client.replace(" ", ""),
        "hardcoded_chain_id_137": "chain_id = 137" in client,
    }
    status = "review" if any(evidence.values()) else "fail"
    return AuditItem(
        "auth_domain_signature_assumptions",
        status,
        "legacy auth/domain/signature assumptions need current official API verification",
        evidence,
    )


def audit_read_only_authenticated_probe() -> AuditItem:
    paths = [
        path
        for path in (PROJECT_ROOT / "tools").glob("*.py")
        if path.name != "gate_b_audit.py"
    ]
    text = "\n".join(read(path) for path in paths)
    if "read-only authenticated" in text.lower() or "authenticated_probe" in text:
        return AuditItem(
            "read_only_authenticated_probe",
            "review",
            "authenticated read-only probe text exists but still requires manual verification",
        )
    return AuditItem(
        "read_only_authenticated_probe",
        "fail",
        "no current authenticated read-only probe is implemented for legacy execution audit",
    )


def audit_rfq_combos_awareness() -> AuditItem:
    corpus = "\n".join(
        read(path)
        for root in ("core", "strategies", "data", "tools", "docs")
        for path in (PROJECT_ROOT / root).rglob("*")
        if path.is_file() and path.suffix in {".py", ".md"} and path.name != "gate_b_audit.py"
    )
    lower = corpus.lower()
    evidence = {"rfq": "rfq" in lower, "combos": "combo" in lower or "combos" in lower}
    if all(evidence.values()):
        return AuditItem(
            "rfq_combos_awareness",
            "review",
            "RFQ/Combos are mentioned, but execution-path handling still needs current API review",
            evidence,
        )
    return AuditItem(
        "rfq_combos_awareness",
        "fail",
        "legacy execution path does not document current RFQ/Combos implications",
        evidence,
    )


def build_audit() -> dict[str, Any]:
    items = [
        audit_sdk_lock(),
        audit_deprecated_order_fields(),
        audit_auth_domain_and_signature(),
        audit_read_only_authenticated_probe(),
        audit_rfq_combos_awareness(),
    ]
    status = "pass" if all(item.status == "pass" for item in items) else "fail"
    return {
        "generated_at": utc_now_iso(),
        "overall_status": status,
        "live_trading_status": "NO-GO",
        "interpretation": "Gate B is an audit gate only and does not approve live trading.",
        "items": [item.to_dict() for item in items],
    }


def render_markdown(audit: dict[str, Any]) -> str:
    rows = "\n".join(
        f"|{item['name']}|{item['status'].upper()}|{item['detail']}|"
        for item in audit["items"]
    )
    return f"""# Gate B Legacy Execution Audit

Generated at: `{audit['generated_at']}`

|Field|Status|
|---|---|
|Overall Gate B status|{audit['overall_status'].upper()}|
|Live trading|{audit['live_trading_status']}|

## Items

|Item|Status|Detail|
|---|---|---|
{rows}

## Interpretation

{audit['interpretation']}

Any `FAIL` or `REVIEW` item blocks live-readiness discussion until resolved against
current official venue sources.
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
