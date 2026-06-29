"""Retry configuration tests for the CLOB client."""

import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock, patch

import pytest

from core.live_guard import LiveTradingBlocked, LiveTradingGuard
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


def live_canary_config():
    return {
        "execution": {
            "dry_run": False,
            "clob_host": "https://clob.polymarket.com",
            "signature_type": 0,
            "chain_id": 137,
            "rate_limit_per_min": 999999,
            "retry_max_attempts": 1,
            "retry_backoff_base_sec": 1,
            "retry_backoff_max_sec": 1,
            "error_circuit_breaker": {
                "threshold": 999,
                "window_sec": 60,
                "pause_sec": 30,
            },
            "live": {
                "approved_canary": True,
                "max_order_notional_usd": 5.0,
                "max_daily_loss_usd": 5.0,
                "max_consecutive_network_errors": 3,
            },
        }
    }


def live_env():
    return {
        "ALLOW_LIVE_TRADING": "TRUE",
        "POLYGON_PRIVATE_KEY": "0xabc",
        "POLYMARKET_API_KEY": "key",
        "POLYMARKET_API_SECRET": "secret",
        "POLYMARKET_API_PASSPHRASE": "passphrase",
    }


def test_live_guard_rejects_unset_flag_and_oversized_orders():
    guard = LiveTradingGuard(live_canary_config(), environ={})

    with pytest.raises(LiveTradingBlocked, match="ALLOW_LIVE_TRADING"):
        guard.assert_order_allowed(price=0.5, size=2.0, post_only=True)

    guard = LiveTradingGuard(live_canary_config(), environ=live_env())
    with pytest.raises(LiveTradingBlocked, match="exceeds canary cap"):
        guard.assert_order_allowed(price=0.9, size=10.0, post_only=True)


@pytest.mark.asyncio
async def test_clob_client_blocks_order_before_sdk_initialization_without_live_flag(monkeypatch):
    monkeypatch.delenv("ALLOW_LIVE_TRADING", raising=False)
    client = ClobClient(live_canary_config())

    def fail_sync_client():
        raise AssertionError("sync client must not initialize when live guard blocks")

    client._get_sync_client = fail_sync_client

    result = await client.create_order(
        token_id="token",
        side="BUY",
        price=0.5,
        size=2.0,
        post_only=True,
    )

    assert result is None


@pytest.mark.asyncio
async def test_clob_client_forwards_post_only_to_sdk_post_order(monkeypatch):
    for key, value in live_env().items():
        monkeypatch.setenv(key, value)

    class FakeSyncClient:
        def __init__(self):
            self.post_only = None

        def create_order(self, order_args):
            return {"signed": order_args.token_id}

        def post_order(self, signed_order, order_type, post_only=False):
            self.post_only = post_only
            return {"orderID": f"posted-{signed_order['signed']}"}

    fake = FakeSyncClient()
    client = ClobClient(live_canary_config())
    client._sync_client = fake

    result = await client.create_order(
        token_id="token",
        side="BUY",
        price=0.5,
        size=2.0,
        post_only=True,
    )

    assert result == "posted-token"
    assert fake.post_only is True
