#!/usr/bin/env python3
"""Generate a read-only software health report.

This command proves that the repository's research/paper infrastructure is
operational. It intentionally does not prove profitability and must not touch
live order paths.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
import tempfile
import types
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.contracts import DEFAULT_CONTRACT_DIR, validate_contract_fixtures
from research.replay import replay_run
from research.safety import ResearchSafetyError, assert_read_only_config
from research.transport import ReadOnlyTransport


REPORT_MD = PROJECT_ROOT / "reports" / "software_health_report.md"
REPORT_JSON = PROJECT_ROOT / "reports" / "software_health_report.json"
DEFAULT_IMPORT_POLICY_FILES = (
    PROJECT_ROOT / "research",
    PROJECT_ROOT / "tools" / "cross_venue_research.py",
    PROJECT_ROOT / "tools" / "generate_candidates.py",
    PROJECT_ROOT / "tools" / "software_health_report.py",
    PROJECT_ROOT / "tools" / "gate_b_audit.py",
    PROJECT_ROOT / "tools" / "block0_decision_check.py",
)
BANNED_RESEARCH_IMPORT_ROOTS = {"core", "strategies", "main", "data"}


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    detail: str
    evidence: dict[str, Any] | None = None

    @property
    def passed(self) -> bool:
        return self.status == "pass"

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


def load_config(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"config must be a YAML object: {path}")
    return payload


def check_source_contracts(contract_dir: Path) -> CheckResult:
    validated = validate_contract_fixtures(contract_dir)
    return CheckResult(
        name="source_contract_fixture_verification",
        status="pass",
        detail=f"validated {len(validated)} pinned source-contract fixtures",
        evidence={"validated": validated},
    )


def check_config_safety(config_path: Path) -> CheckResult:
    config = load_config(config_path)
    assert_read_only_config(config)
    strategies = config.get("strategies", {})
    disabled = sorted(
        name
        for name, settings in strategies.items()
        if isinstance(settings, dict) and settings.get("enabled") is False
    )
    return CheckResult(
        name="read_only_config_safety",
        status="pass",
        detail="execution.dry_run is true and execution-capable strategies are disabled",
        evidence={"disabled_strategies": disabled, "dry_run": True},
    )


def _iter_python_files(path: Path) -> list[Path]:
    if path.is_dir():
        return sorted(child for child in path.rglob("*.py") if child.is_file())
    return [path]


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def check_import_policy(paths: tuple[Path, ...] = DEFAULT_IMPORT_POLICY_FILES) -> CheckResult:
    offenders: list[str] = []
    inspected: list[str] = []
    for root in paths:
        for path in _iter_python_files(root):
            display = _display_path(path)
            inspected.append(display)
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                else:
                    continue
                for name in names:
                    if name.split(".")[0] in BANNED_RESEARCH_IMPORT_ROOTS:
                        offenders.append(f"{display}:{name}")
    if offenders:
        return CheckResult(
            name="research_import_policy",
            status="fail",
            detail="research/read-only tools import execution-capable modules",
            evidence={"offenders": offenders, "inspected": inspected},
        )
    return CheckResult(
        name="research_import_policy",
        status="pass",
        detail="research/read-only tools do not import legacy execution-capable modules",
        evidence={"inspected": inspected},
    )


def check_credential_isolation() -> CheckResult:
    rejected_credentials: list[str] = []
    for key in ("POLYMARKET_PRIVATE_KEY", "POLYMARKET_API_KEY", "KALSHI_PRIVATE_KEY"):
        try:
            ReadOnlyTransport(
                {"example.com"},
                environ={key: "injected-test-secret"},
            )
        except ResearchSafetyError:
            rejected_credentials.append(key)
        else:
            return CheckResult(
                name="credential_isolation",
                status="fail",
                detail=f"read-only transport accepted injected trading credential {key}",
            )
    return CheckResult(
        name="credential_isolation",
        status="pass",
        detail="read-only transport rejects injected trading credentials before network use",
        evidence={"rejected_credentials": rejected_credentials},
    )


def check_order_path_isolation() -> CheckResult:
    def fail_order(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("research touched an order path")

    old_modules = {name: sys.modules.get(name) for name in ("core", "core.client", "core.executor")}
    old_env = os.environ.get("POLYMARKET_PRIVATE_KEY")
    try:
        core_module = types.ModuleType("core")
        client_module = types.ModuleType("core.client")
        executor_module = types.ModuleType("core.executor")
        client_module.create_order = fail_order
        executor_module.place_order = fail_order
        sys.modules["core"] = core_module
        sys.modules["core.client"] = client_module
        sys.modules["core.executor"] = executor_module
        os.environ["POLYMARKET_PRIVATE_KEY"] = "present-but-offline-replay-must-ignore-it"
        with tempfile.TemporaryDirectory() as tmp:
            report = replay_run(Path(tmp))
    finally:
        if old_env is None:
            os.environ.pop("POLYMARKET_PRIVATE_KEY", None)
        else:
            os.environ["POLYMARKET_PRIVATE_KEY"] = old_env
        for name, module in old_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    return CheckResult(
        name="offline_replay_order_path_isolation",
        status="pass",
        detail="offline replay completed with poisoned order modules and injected credential",
        evidence={
            "snapshot_count": report.get("snapshot_count"),
            "accepted_route_count": report.get("accepted_route_count"),
        },
    )


def run_tests(python_exe: str, pytest_args: list[str]) -> CheckResult:
    command = [python_exe, "-m", "pytest", *pytest_args]
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    output = completed.stdout.strip()
    summary = output.splitlines()[-1] if output else ""
    status = "pass" if completed.returncode == 0 else "fail"
    return CheckResult(
        name="pytest_full_suite",
        status=status,
        detail=summary or f"pytest exited {completed.returncode}",
        evidence={
            "command": command,
            "returncode": completed.returncode,
            "summary": summary,
        },
    )


def build_report(
    *,
    config_path: Path,
    contract_dir: Path,
    include_tests: bool,
    python_exe: str,
    pytest_args: list[str],
) -> dict[str, Any]:
    checks = [
        check_source_contracts(contract_dir),
        check_config_safety(config_path),
        check_import_policy(),
        check_credential_isolation(),
        check_order_path_isolation(),
    ]
    if include_tests:
        checks.append(run_tests(python_exe, pytest_args))
    else:
        checks.append(
            CheckResult(
                name="pytest_full_suite",
                status="skip",
                detail="skipped by --skip-tests",
            )
        )

    overall = "pass" if all(check.status in {"pass", "skip"} for check in checks) else "fail"
    if include_tests and any(check.status == "skip" for check in checks):
        overall = "fail"
    return {
        "generated_at": utc_now_iso(),
        "overall_status": overall,
        "claim": (
            "software infrastructure working"
            if overall == "pass"
            else "software infrastructure not proven working"
        ),
        "profitability_claim": "not proven",
        "live_trading_status": "NO-GO",
        "checks": [check.to_dict() for check in checks],
        "next_profitability_gate": (
            "approve mappings, run forward paper capture, and produce a profitability evidence pack"
        ),
    }


def render_markdown(report: dict[str, Any]) -> str:
    rows = "\n".join(
        f"|{check['name']}|{check['status'].upper()}|{check['detail']}|"
        for check in report["checks"]
    )
    return f"""# Software Health Report

Generated at: `{report['generated_at']}`

|Field|Status|
|---|---|
|Overall software health|{report['overall_status'].upper()}|
|Supported claim|{report['claim']}|
|Profitability claim|{report['profitability_claim']}|
|Live trading|{report['live_trading_status']}|

## Checks

|Check|Status|Detail|
|---|---|---|
{rows}

## Interpretation

This report proves only the read-only research/paper infrastructure state. It does
not prove strategy profitability, reward capture, or live readiness.

The next profitability gate is: {report['next_profitability_gate']}.
"""


def write_report(report: dict[str, Any], md_path: Path, json_path: Path) -> None:
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_markdown(report), encoding="utf-8")
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config.yaml"))
    parser.add_argument("--contract-dir", default=str(DEFAULT_CONTRACT_DIR))
    parser.add_argument("--markdown-output", default=str(REPORT_MD))
    parser.add_argument("--json-output", default=str(REPORT_JSON))
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--pytest-args", nargs="*", default=["tests/", "-q"])
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip the full pytest run. Intended for unit tests of this reporter only.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = build_report(
        config_path=Path(args.config),
        contract_dir=Path(args.contract_dir),
        include_tests=not args.skip_tests,
        python_exe=args.python,
        pytest_args=list(args.pytest_args),
    )
    write_report(report, Path(args.markdown_output), Path(args.json_output))
    print(Path(args.markdown_output))
    print(Path(args.json_output))
    return 0 if report["overall_status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
