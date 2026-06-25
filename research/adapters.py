"""Read-only venue adapters for Polymarket and Kalshi public REST payloads."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any

from research.mapping import ContractMapping
from research.quotes import (
    ONE,
    ZERO,
    BookLevel,
    FeeRule,
    OutcomeQuote,
    VenueSnapshot,
    decimal_or_none,
    normalize_probability,
)
from research.transport import ReadOnlyTransport


POLYMARKET_CLOB_BASE = "https://clob.polymarket.com"
KALSHI_TRADE_API_BASE = "https://external-api.kalshi.com/trade-api/v2"


class AdapterPayloadError(ValueError):
    """Raised when a public venue payload lacks fields needed for research."""


def canonical_payload_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _first_present(mapping: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if name in mapping:
            return mapping[name]
    return None


def _parse_level(raw: Any) -> BookLevel | None:
    if isinstance(raw, dict):
        price = normalize_probability(_first_present(raw, ("price", "price_dollars", "p")))
        size = decimal_or_none(_first_present(raw, ("size", "quantity", "count", "contracts")))
    elif isinstance(raw, (list, tuple)) and len(raw) >= 2:
        price = normalize_probability(raw[0])
        size = decimal_or_none(raw[1])
    else:
        return None
    if price is None or size is None or size <= ZERO:
        return None
    return BookLevel(price=price, size=size)


def parse_book_levels(raw_levels: Any, *, side: str) -> list[BookLevel]:
    if not isinstance(raw_levels, list):
        return []
    levels = [level for item in raw_levels if (level := _parse_level(item)) is not None]
    reverse = side == "bid"
    return sorted(levels, key=lambda level: level.price, reverse=reverse)


def parse_polymarket_book_quote(payload: dict[str, Any]) -> OutcomeQuote:
    """Parse one Polymarket token order book using actual asks and sizes."""
    bids = parse_book_levels(payload.get("bids", []), side="bid")
    asks = parse_book_levels(payload.get("asks", []), side="ask")
    best_bid = bids[0] if bids else None
    best_ask = asks[0] if asks else None
    return OutcomeQuote(
        bid_price=best_bid.price if best_bid else None,
        bid_size=best_bid.size if best_bid else None,
        ask_price=best_ask.price if best_ask else None,
        ask_size=best_ask.size if best_ask else None,
        ask_source="book_ask",
        missing_depth=best_ask is None,
    )


def build_polymarket_snapshot(
    *,
    mapping: ContractMapping,
    yes_payload: dict[str, Any],
    no_payload: dict[str, Any],
    receipt_timestamp: str,
    source_contract_version: str,
    fee_rule: FeeRule | None,
    fee_schedule_reference: str | None,
) -> VenueSnapshot:
    yes_asset = str(yes_payload.get("asset_id") or "")
    no_asset = str(no_payload.get("asset_id") or "")
    if yes_asset and yes_asset != mapping.polymarket_yes_token_id:
        raise AdapterPayloadError("Polymarket YES token fixture does not match mapping")
    if no_asset and no_asset != mapping.polymarket_no_token_id:
        raise AdapterPayloadError("Polymarket NO token fixture does not match mapping")

    yes_source_ts = str(yes_payload.get("timestamp")) if yes_payload.get("timestamp") else None
    no_source_ts = str(no_payload.get("timestamp")) if no_payload.get("timestamp") else None
    source_timestamp = yes_source_ts if yes_source_ts == no_source_ts else None
    min_order_size = decimal_or_none(
        yes_payload.get("min_order_size") or no_payload.get("min_order_size")
    )
    return VenueSnapshot(
        venue="polymarket",
        market_id=mapping.polymarket_condition_id,
        yes=parse_polymarket_book_quote(yes_payload),
        no=parse_polymarket_book_quote(no_payload),
        receipt_timestamp=receipt_timestamp,
        source_timestamp=source_timestamp,
        raw_payload_hash=canonical_payload_hash({"yes": yes_payload, "no": no_payload}),
        source_contract_version=source_contract_version,
        fee_rule=fee_rule,
        fee_schedule_reference=fee_schedule_reference,
        min_order_size=min_order_size,
    )


def _market_object(payload: dict[str, Any]) -> dict[str, Any]:
    market = payload.get("market", payload)
    if not isinstance(market, dict):
        raise AdapterPayloadError("Kalshi market payload is not an object")
    return market


def _kalshi_orderbook_object(payload: dict[str, Any]) -> dict[str, Any]:
    orderbook = (
        payload.get("orderbook_fp")
        or payload.get("orderbook")
        or payload.get("order_book")
        or payload
    )
    if not isinstance(orderbook, dict):
        raise AdapterPayloadError("Kalshi orderbook payload is not an object")
    return orderbook


def _kalshi_bid_levels(orderbook_payload: dict[str, Any], outcome: str) -> list[BookLevel]:
    orderbook = _kalshi_orderbook_object(orderbook_payload)
    raw_levels = (
        orderbook.get(f"{outcome}_dollars")
        or orderbook.get(outcome)
        or orderbook.get(f"{outcome}_bids")
        or []
    )
    return parse_book_levels(raw_levels, side="bid")


def _kalshi_explicit_ask(market: dict[str, Any], outcome: str) -> tuple[Decimal | None, Decimal | None]:
    price = normalize_probability(
        _first_present(market, (f"{outcome}_ask_dollars", f"{outcome}_ask"))
    )
    size = decimal_or_none(
        _first_present(
            market,
            (
                f"{outcome}_ask_size",
                f"{outcome}_ask_count",
                f"{outcome}_ask_count_fp",
                f"{outcome}_ask_quantity",
            ),
        )
    )
    return price, size


def _kalshi_outcome_quote(
    *,
    market: dict[str, Any],
    orderbook_payload: dict[str, Any],
    outcome: str,
) -> OutcomeQuote:
    same_bids = _kalshi_bid_levels(orderbook_payload, outcome)
    opposite = "no" if outcome == "yes" else "yes"
    opposite_bids = _kalshi_bid_levels(orderbook_payload, opposite)
    best_bid = same_bids[0] if same_bids else None

    explicit_ask, explicit_size = _kalshi_explicit_ask(market, outcome)
    if explicit_ask is not None:
        return OutcomeQuote(
            bid_price=best_bid.price if best_bid else None,
            bid_size=best_bid.size if best_bid else None,
            ask_price=explicit_ask,
            ask_size=explicit_size,
            ask_source=f"{outcome}_ask_dollars",
            missing_depth=explicit_size is None or explicit_size <= ZERO,
        )

    best_opposite_bid = opposite_bids[0] if opposite_bids else None
    reciprocal_ask = ONE - best_opposite_bid.price if best_opposite_bid else None
    return OutcomeQuote(
        bid_price=best_bid.price if best_bid else None,
        bid_size=best_bid.size if best_bid else None,
        ask_price=reciprocal_ask,
        ask_size=best_opposite_bid.size if best_opposite_bid else None,
        ask_source=f"reciprocal_{opposite}_bid",
        missing_depth=best_opposite_bid is None,
    )


def build_kalshi_snapshot(
    *,
    mapping: ContractMapping,
    market_payload: dict[str, Any],
    orderbook_payload: dict[str, Any],
    receipt_timestamp: str,
    source_contract_version: str,
    fee_rule: FeeRule | None,
    fee_schedule_reference: str | None,
) -> VenueSnapshot:
    market = _market_object(market_payload)
    ticker = str(market.get("ticker") or "")
    if ticker and ticker != mapping.kalshi_market_ticker:
        raise AdapterPayloadError("Kalshi market fixture does not match mapping")
    source_timestamp = (
        str(market.get("updated_time"))
        if market.get("updated_time")
        else str(market.get("last_updated_time"))
        if market.get("last_updated_time")
        else None
    )
    min_order_size = decimal_or_none(
        market.get("minimum_order_size") or market.get("min_order_size")
    )
    return VenueSnapshot(
        venue="kalshi",
        market_id=mapping.kalshi_market_ticker,
        yes=_kalshi_outcome_quote(
            market=market, orderbook_payload=orderbook_payload, outcome="yes"
        ),
        no=_kalshi_outcome_quote(
            market=market, orderbook_payload=orderbook_payload, outcome="no"
        ),
        receipt_timestamp=receipt_timestamp,
        source_timestamp=source_timestamp,
        raw_payload_hash=canonical_payload_hash(
            {"market": market_payload, "orderbook": orderbook_payload}
        ),
        source_contract_version=source_contract_version,
        fee_rule=fee_rule,
        fee_schedule_reference=fee_schedule_reference,
        min_order_size=min_order_size,
    )


def fetch_polymarket_book(transport: ReadOnlyTransport, token_id: str) -> dict[str, Any]:
    return transport.get_json(f"{POLYMARKET_CLOB_BASE}/book", params={"token_id": token_id})


def fetch_kalshi_market(transport: ReadOnlyTransport, ticker: str) -> dict[str, Any]:
    return transport.get_json(f"{KALSHI_TRADE_API_BASE}/markets/{ticker}")


def fetch_kalshi_orderbook(transport: ReadOnlyTransport, ticker: str) -> dict[str, Any]:
    return transport.get_json(f"{KALSHI_TRADE_API_BASE}/markets/{ticker}/orderbook")


def fetch_kalshi_fee_changes(
    transport: ReadOnlyTransport, series_ticker: str | None = None
) -> dict[str, Any]:
    params = {"series_ticker": series_ticker} if series_ticker else None
    return transport.get_json(f"{KALSHI_TRADE_API_BASE}/series/fee_changes", params=params)
