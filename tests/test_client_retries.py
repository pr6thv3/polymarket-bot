"""Retry configuration tests for the CLOB client."""

import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock, patch

from core.client import ClobClient
from utils.helpers import load_config


def test_production_config_sets_api_retries_to_100():
    config = load_config("config.yaml")

    assert config["execution"]["retry_max_attempts"] == 100
    assert config["execution"]["retry_backoff_max_sec"] == 30


def test_retry_backoff_is_capped(sample_config):
    config = deepcopy(sample_config)
    config["execution"].update(
        {
            "rate_limit_per_min": 999999,
            "retry_max_attempts": 3,
            "retry_backoff_base_sec": 10,
            "retry_backoff_max_sec": 7,
            "error_circuit_breaker": {
                "threshold": 999,
                "window_sec": 60,
                "pause_sec": 30,
            },
        }
    )
    client = ClobClient(config)
    calls = {"count": 0}

    def flaky_call():
        calls["count"] += 1
        if calls["count"] < 3:
            raise Exception("503 temporary upstream failure")
        return {"ok": True}

    sleep_mock = AsyncMock()
    with patch("asyncio.sleep", sleep_mock):
        result = asyncio.run(client._call_with_protection(flaky_call))

    assert result == {"ok": True}
    assert calls["count"] == 3
    assert [call.args[0] for call in sleep_mock.await_args_list] == [7, 7]
