import json

from tools import gate_b_audit


def test_gate_b_audit_passes_technical_artifacts_without_live_approval():
    audit = gate_b_audit.build_audit()

    assert audit["live_trading_status"] == "NO-GO"
    assert audit["overall_status"] == "pass"
    assert all(item["status"] == "pass" for item in audit["items"])
    probe = next(item for item in audit["items"] if item["name"] == "read_only_authenticated_probe")
    assert probe["status"] == "pass"


def test_gate_b_audit_writes_markdown_and_json(tmp_path):
    audit = {
        "generated_at": "2026-06-29T00:00:00Z",
        "overall_status": "pass",
        "live_trading_status": "NO-GO",
        "interpretation": "fixture",
        "items": [
            {
                "name": "fixture",
                "status": "pass",
                "detail": "ok",
            }
        ],
    }
    md_path = tmp_path / "gate_b.md"
    json_path = tmp_path / "gate_b.json"

    gate_b_audit.write_audit(audit, md_path, json_path)

    assert "Live trading|NO-GO" in md_path.read_text(encoding="utf-8")
    assert json.loads(json_path.read_text(encoding="utf-8"))["overall_status"] == "pass"
