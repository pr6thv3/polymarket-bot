import json
from pathlib import Path

import yaml

from tools import software_health_report as health


def test_build_report_without_recursive_pytest_marks_software_checks_passed():
    report = health.build_report(
        config_path=Path("config.yaml"),
        contract_dir=Path("research_contracts"),
        include_tests=False,
        python_exe="python",
        pytest_args=["tests/", "-q"],
    )

    statuses = {check["name"]: check["status"] for check in report["checks"]}

    assert report["overall_status"] == "pass"
    assert report["profitability_claim"] == "not proven"
    assert report["live_trading_status"] == "NO-GO"
    assert statuses["source_contract_fixture_verification"] == "pass"
    assert statuses["read_only_config_safety"] == "pass"
    assert statuses["research_import_policy"] == "pass"
    assert statuses["credential_isolation"] == "pass"
    assert statuses["offline_replay_order_path_isolation"] == "pass"
    assert statuses["pytest_full_suite"] == "skip"


def test_report_writes_markdown_and_json(tmp_path):
    report = {
        "generated_at": "2026-06-29T00:00:00Z",
        "overall_status": "pass",
        "claim": "software infrastructure working",
        "profitability_claim": "not proven",
        "live_trading_status": "NO-GO",
        "next_profitability_gate": "fixture",
        "checks": [
            {
                "name": "example",
                "status": "pass",
                "detail": "ok",
            }
        ],
    }
    md_path = tmp_path / "health.md"
    json_path = tmp_path / "health.json"

    health.write_report(report, md_path, json_path)

    assert "Profitability claim|not proven" in md_path.read_text(encoding="utf-8")
    assert json.loads(json_path.read_text(encoding="utf-8"))["live_trading_status"] == "NO-GO"


def test_import_policy_detects_execution_import(tmp_path):
    bad_file = tmp_path / "bad_tool.py"
    bad_file.write_text("from core.executor import Executor\n", encoding="utf-8")

    result = health.check_import_policy((bad_file,))

    assert result.status == "fail"
    assert result.evidence is not None
    assert result.evidence["offenders"]


def test_read_only_config_check_fails_when_strategy_enabled(tmp_path):
    config = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
    config["strategies"]["market_making"]["enabled"] = True
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    try:
        health.check_config_safety(config_path)
    except Exception as exc:
        assert "strategy" in str(exc)
    else:
        raise AssertionError("expected config safety failure")
