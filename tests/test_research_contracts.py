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
    assert "polymarket_gamma_v1:list_markets" in validated
    assert "kalshi_trade_api_v1:get_market" in validated
    assert "kalshi_trade_api_v1:get_market_orderbook" in validated
    assert "kalshi_trade_api_v1:get_series_fee_changes" in validated
    assert "kalshi_trade_api_v1:list_markets" in validated


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


def test_polymarket_gamma_root_array_listing_validates():
    contracts = load_contracts(DEFAULT_CONTRACT_DIR)
    payload = [
        {
            "conditionId": "0xcondition",
            "question": "Will France win the 2026 FIFA World Cup?",
            "tokens": [
                {"outcome": "Yes", "token_id": "0xyes"},
                {"outcome": "No", "token_id": "0xno"},
            ],
        }
    ]

    validate_payload(contracts["polymarket_gamma_v1"], "list_markets", payload)


def test_polymarket_gamma_wrapped_listing_validates():
    contracts = load_contracts(DEFAULT_CONTRACT_DIR)
    payload = {
        "markets": [
            {
                "condition_id": "0xcondition",
                "title": "Will France win the 2026 FIFA World Cup?",
                "outcomes": '["Yes", "No"]',
                "clobTokenIds": '["0xyes", "0xno"]',
            }
        ]
    }

    validate_payload(contracts["polymarket_gamma_v1"], "list_markets", payload)


def test_kalshi_list_markets_page_validates():
    contracts = load_contracts(DEFAULT_CONTRACT_DIR)
    payload = {
        "markets": [
            {
                "ticker": "KXFRANCE-26",
                "event_ticker": "KXFRANCE",
                "title": "France to win FIFA World Cup in 2026?",
                "close_time": "2026-07-20T00:00:00Z",
            }
        ],
        "cursor": "next-page",
    }

    validate_payload(contracts["kalshi_trade_api_v1"], "list_markets", payload)


def test_listing_validation_rejects_missing_fields():
    contracts = load_contracts(DEFAULT_CONTRACT_DIR)
    payload = {
        "markets": [
            {
                "ticker": "KXFRANCE-26",
                "event_ticker": "KXFRANCE",
                "close_time": "2026-07-20T00:00:00Z",
            }
        ],
        "cursor": None,
    }

    with pytest.raises(SourceContractError, match="kalshi_title_field"):
        validate_payload(contracts["kalshi_trade_api_v1"], "list_markets", payload)


def test_polymarket_alternative_token_format_must_be_complete():
    contracts = load_contracts(DEFAULT_CONTRACT_DIR)
    incomplete = [
        {
            "conditionId": "0xcondition",
            "question": "Will France win the 2026 FIFA World Cup?",
            "outcomes": '["Yes", "No"]',
        }
    ]

    with pytest.raises(SourceContractError, match="polymarket_token_format"):
        validate_payload(contracts["polymarket_gamma_v1"], "list_markets", incomplete)

    complete = copy.deepcopy(incomplete)
    complete[0]["clob_token_ids"] = '["0xyes", "0xno"]'
    validate_payload(contracts["polymarket_gamma_v1"], "list_markets", complete)
