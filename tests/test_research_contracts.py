import copy

import pytest

from research.contracts import (
    DEFAULT_CONTRACT_DIR,
    SourceContractError,
    load_contracts,
    validate_contract_fixtures,
    validate_payload,
)


def test_committed_source_contract_fixtures_validate():
    validated = validate_contract_fixtures(DEFAULT_CONTRACT_DIR)

    assert "polymarket_clob_v1:get_order_book" in validated
    assert "kalshi_trade_api_v1:get_market" in validated
    assert "kalshi_trade_api_v1:get_market_orderbook" in validated
    assert "kalshi_trade_api_v1:get_series_fee_changes" in validated


def test_contract_validation_rejects_missing_consumed_field():
    contracts = load_contracts(DEFAULT_CONTRACT_DIR)
    payload = copy.deepcopy(
        {
            "market": {
                "ticker": "KX-FIXTURE-26",
                "event_ticker": "KX-FIXTURE",
                "yes_ask_dollars": "0.4400",
                "no_ask_dollars": "0.5600",
                "updated_time": "2026-06-25T13:10:38Z",
            }
        }
    )
    del payload["market"]["yes_ask_dollars"]

    with pytest.raises(SourceContractError, match="yes_ask_dollars"):
        validate_payload(contracts["kalshi_trade_api_v1"], "get_market", payload)


def test_contract_validation_rejects_type_drift():
    contracts = load_contracts(DEFAULT_CONTRACT_DIR)
    payload = {
        "market": "not-object",
        "asset_id": "0xtoken",
        "timestamp": "1",
        "hash": "hash",
        "bids": {},
        "asks": [],
        "min_order_size": "1",
    }

    with pytest.raises(SourceContractError, match="bids"):
        validate_payload(contracts["polymarket_clob_v1"], "get_order_book", payload)
