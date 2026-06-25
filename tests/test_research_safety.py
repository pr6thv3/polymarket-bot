import ast
import sys
import types
from pathlib import Path

import pytest
import yaml

from research.replay import replay_run
from research.safety import ResearchSafetyError, assert_read_only_config
from research.transport import ReadOnlyTransport, UnsafeResearchRequest


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {}


class FakeClient:
    def __init__(self):
        self.calls = []

    def request(self, method, url, params=None, headers=None):
        self.calls.append((method, url, params, headers))
        return FakeResponse()


def test_transport_is_get_head_only_without_bodies_or_auth_headers():
    client = FakeClient()
    transport = ReadOnlyTransport({"example.com"}, client=client, environ={})

    transport.request("GET", "https://example.com/read")
    assert client.calls[0][0] == "GET"

    with pytest.raises(UnsafeResearchRequest, match="POST"):
        transport.request("POST", "https://example.com/write")
    with pytest.raises(UnsafeResearchRequest, match="bodies"):
        transport.request("GET", "https://example.com/read", body={"x": 1})
    with pytest.raises(UnsafeResearchRequest, match="header"):
        transport.request(
            "GET",
            "https://example.com/read",
            headers={"KALSHI-ACCESS-KEY": "secret"},
        )
    with pytest.raises(UnsafeResearchRequest, match="not allowlisted"):
        transport.request("GET", "https://evil.example/read")


def test_transport_refuses_inherited_trading_credentials():
    with pytest.raises(ResearchSafetyError, match="POLYMARKET_PRIVATE_KEY"):
        ReadOnlyTransport(
            {"example.com"},
            client=FakeClient(),
            environ={"POLYMARKET_PRIVATE_KEY": "do-not-use"},
        )


def test_read_only_config_requires_dry_run_and_disabled_strategies():
    config = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
    assert_read_only_config(config)

    with pytest.raises(ResearchSafetyError, match="dry_run"):
        assert_read_only_config({"execution": {"dry_run": False}, "strategies": {}})
    with pytest.raises(ResearchSafetyError, match="strategy"):
        assert_read_only_config(
            {
                "execution": {"dry_run": True},
                "strategies": {"market_making": {"enabled": True}},
            }
        )


def test_research_package_and_cli_have_no_execution_imports():
    banned_roots = {"core", "strategies", "main", "data"}
    files = list(Path("research").glob("*.py")) + [Path("tools/cross_venue_research.py")]
    offenders = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                if name.split(".")[0] in banned_roots:
                    offenders.append(f"{path}:{name}")
    assert offenders == []


def test_replay_does_not_touch_poisoned_order_paths_with_credentials(monkeypatch, tmp_path):
    def fail_order(*args, **kwargs):
        raise AssertionError("research replay touched an order path")

    core_module = types.ModuleType("core")
    client_module = types.ModuleType("core.client")
    executor_module = types.ModuleType("core.executor")
    client_module.create_order = fail_order
    executor_module.place_order = fail_order
    monkeypatch.setitem(sys.modules, "core", core_module)
    monkeypatch.setitem(sys.modules, "core.client", client_module)
    monkeypatch.setitem(sys.modules, "core.executor", executor_module)
    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "present-but-replay-is-offline")

    report = replay_run(tmp_path)

    assert report["snapshot_count"] == 0
    assert report["accepted_route_count"] == 0
