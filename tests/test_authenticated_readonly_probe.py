import pytest

from tools.polymarket_authenticated_readonly_probe import (
    AuthReadOnlyProbeBlocked,
    require_probe_enabled,
)


def test_authenticated_readonly_probe_requires_explicit_env_flag(monkeypatch):
    monkeypatch.delenv("ALLOW_AUTH_READONLY_PROBE", raising=False)

    with pytest.raises(AuthReadOnlyProbeBlocked, match="ALLOW_AUTH_READONLY_PROBE"):
        require_probe_enabled()


def test_authenticated_readonly_probe_accepts_exact_true(monkeypatch):
    monkeypatch.setenv("ALLOW_AUTH_READONLY_PROBE", "TRUE")

    require_probe_enabled()
