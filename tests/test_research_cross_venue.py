from decimal import Decimal
from pathlib import Path

from research.adapters import build_kalshi_snapshot
from research.event_log import ResearchRunLog
from research.mapping import ContractMapping, MappingCatalog
from research.quotes import FeeRule, OutcomeQuote, PairedSnapshot, VenueSnapshot
from research.replay import QualityPolicy, evaluate_complement_route, replay_run


def mapping() -> ContractMapping:
    return ContractMapping(
        mapping_id="fixture",
        version=1,
        status="approved",
        polymarket_condition_id="0xcondition",
        polymarket_yes_token_id="0xyes",
        polymarket_no_token_id="0xno",
        kalshi_event_ticker="KX-FIXTURE",
        kalshi_market_ticker="KX-FIXTURE-26",
        kalshi_series_ticker="KX",
        canonical_proposition="Fixture proposition",
        yes_predicate="Fixture YES",
        resolution_source="Fixture evidence",
        cutoff_utc="2026-06-26T00:00:00Z",
        timezone="UTC",
        payout_convention="Binary",
        invalidation_behavior="Reject on mismatch",
        resolution_risk_checklist=(
            "Contract wording compared",
            "Resolution timing compared",
            "Payout and invalidation behavior compared",
        ),
        review_evidence=("https://example.invalid",),
        reviewer="test",
        reviewed_at="2026-06-25T13:10:38Z",
    )


def fee_rule(venue: str, rate: str = "0", rounding: str | None = None) -> FeeRule:
    return FeeRule(
        venue=venue,
        formula="c_p_one_minus_p",
        rate=Decimal(rate),
        schedule_reference="fixture",
        source_contract_version=f"{venue}_fixture",
        verified=True,
        rounding_increment_usd=Decimal(rounding) if rounding else None,
    )


def quote(ask: str, size: str) -> OutcomeQuote:
    return OutcomeQuote(
        bid_price=None,
        bid_size=None,
        ask_price=Decimal(ask),
        ask_size=Decimal(size),
        ask_source="fixture",
    )


def test_kalshi_explicit_asks_take_precedence_over_reciprocal_book():
    snapshot = build_kalshi_snapshot(
        mapping=mapping(),
        market_payload={
            "market": {
                "ticker": "KX-FIXTURE-26",
                "updated_time": "2026-06-25T13:10:38Z",
                "yes_ask_dollars": "0.4400",
                "yes_ask_count": "7.00",
                "no_ask_dollars": "0.5800",
                "no_ask_count": "9.00",
            }
        },
        orderbook_payload={
            "orderbook_fp": {
                "yes_dollars": [["0.1000", "3.00"]],
                "no_dollars": [["0.9000", "4.00"]],
            }
        },
        receipt_timestamp="2026-06-25T13:10:38Z",
        source_contract_version="kalshi_trade_api_v1",
        fee_rule=None,
        fee_schedule_reference=None,
    )

    assert snapshot.yes.ask_source == "yes_ask_dollars"
    assert snapshot.yes.ask_price == Decimal("0.4400")
    assert snapshot.yes.ask_size == Decimal("7.00")
    assert snapshot.no.ask_source == "no_ask_dollars"
    assert snapshot.no.ask_price == Decimal("0.5800")


def test_kalshi_reciprocal_ask_uses_opposite_bid_in_same_orderbook():
    snapshot = build_kalshi_snapshot(
        mapping=mapping(),
        market_payload={
            "market": {
                "ticker": "KX-FIXTURE-26",
                "updated_time": "2026-06-25T13:10:38Z",
                "yes_ask_dollars": None,
                "no_ask_dollars": None,
            }
        },
        orderbook_payload={
            "orderbook_fp": {
                "yes_dollars": [["0.4000", "5.00"]],
                "no_dollars": [["0.5500", "6.00"]],
            }
        },
        receipt_timestamp="2026-06-25T13:10:38Z",
        source_contract_version="kalshi_trade_api_v1",
        fee_rule=None,
        fee_schedule_reference=None,
    )

    assert snapshot.yes.ask_source == "reciprocal_no_bid"
    assert snapshot.yes.ask_price == Decimal("0.4500")
    assert snapshot.yes.ask_size == Decimal("6.00")
    assert snapshot.no.ask_source == "reciprocal_yes_bid"
    assert snapshot.no.ask_price == Decimal("0.6000")
    assert snapshot.no.ask_size == Decimal("5.00")


def test_fee_rule_supports_kalshi_next_cent_rounding():
    kalshi = fee_rule("kalshi", rate="0.07", rounding="0.01")

    assert kalshi.cost(Decimal("100"), Decimal("0.50")) == Decimal("1.75")
    assert kalshi.cost(Decimal("1"), Decimal("0.50")) == Decimal("0.02")


def test_route_rejects_missing_fee_rule_and_accepts_verified_edge():
    missing_fee = evaluate_complement_route(
        mapping_id="fixture",
        route_id="pm_yes_ks_no",
        yes_venue="polymarket",
        yes_quote=quote("0.40", "10"),
        yes_fee_rule=None,
        yes_min_order_size=Decimal("1"),
        no_venue="kalshi",
        no_quote=quote("0.50", "10"),
        no_fee_rule=fee_rule("kalshi"),
        no_min_order_size=Decimal("1"),
    )
    assert missing_fee.rejected_reason == "missing_fee_data"

    accepted = evaluate_complement_route(
        mapping_id="fixture",
        route_id="pm_yes_ks_no",
        yes_venue="polymarket",
        yes_quote=quote("0.40", "10"),
        yes_fee_rule=fee_rule("polymarket"),
        yes_min_order_size=Decimal("1"),
        no_venue="kalshi",
        no_quote=quote("0.50", "10"),
        no_fee_rule=fee_rule("kalshi"),
        no_min_order_size=Decimal("1"),
    )
    assert accepted.rejected_reason is None
    assert accepted.edge == Decimal("1.00")


def test_append_only_idempotency_and_deterministic_replay(tmp_path: Path):
    log = ResearchRunLog(tmp_path, "run-1", metadata={"test": True})
    now = "2026-06-25T13:10:38Z"
    pm = VenueSnapshot(
        venue="polymarket",
        market_id="0xcondition",
        yes=quote("0.40", "10"),
        no=quote("0.61", "10"),
        receipt_timestamp=now,
        source_timestamp=now,
        raw_payload_hash="pmhash",
        source_contract_version="polymarket_clob_v1",
        fee_rule=fee_rule("polymarket"),
        fee_schedule_reference="fixture",
        min_order_size=Decimal("1"),
    )
    ks = VenueSnapshot(
        venue="kalshi",
        market_id="KX-FIXTURE-26",
        yes=quote("0.52", "10"),
        no=quote("0.50", "10"),
        receipt_timestamp=now,
        source_timestamp=now,
        raw_payload_hash="kshash",
        source_contract_version="kalshi_trade_api_v1",
        fee_rule=fee_rule("kalshi"),
        fee_schedule_reference="fixture",
        min_order_size=Decimal("1"),
    )
    snapshot = PairedSnapshot(
        mapping_id="fixture",
        mapping_version=1,
        mapping_digest=mapping().digest,
        captured_at=now,
        pair_skew_ms=0,
        polymarket=pm,
        kalshi=ks,
    ).to_dict()

    first = log.append_snapshot(snapshot)
    second = log.append_snapshot(snapshot)

    assert first.appended is True
    assert second.appended is False
    assert len((tmp_path / "run-1" / ResearchRunLog.SNAPSHOT_FILE).read_text().splitlines()) == 1

    catalog = MappingCatalog(version=1, mappings=(mapping(),))
    report_one = replay_run(tmp_path / "run-1", mapping_catalog=catalog, policy=QualityPolicy())
    report_two = replay_run(tmp_path / "run-1", mapping_catalog=catalog, policy=QualityPolicy())

    assert report_one == report_two
    assert report_one["accepted_route_count"] == 1
    assert report_one["rejection_reasons"]["non_positive_edge"] == 1
