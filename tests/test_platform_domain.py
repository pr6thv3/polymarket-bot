from decimal import Decimal

import pytest

from libs.domain.enums import (
    ExecutionMode,
    OrderSide,
    ProposalSide,
    ProposalType,
    StrategyMode,
    VenueId,
)
from libs.domain.events import OrderIntent, SignalProposal
from libs.domain.models import InstrumentRef, MarketRelation


def test_signal_proposal_is_a_non_transmitting_strategy_contract() -> None:
    proposal = SignalProposal(
        strategy_name="cross_venue_arb",
        proposal_type=ProposalType.CROSS_VENUE_ARB,
        side=ProposalSide.BUY_YES,
        edge_bps=Decimal("12.5"),
        confidence=Decimal("0.71"),
        max_notional_usd=Decimal("25"),
        fresh_until="2026-06-30T12:01:00Z",
        relation_id="relation-1",
        mode=StrategyMode.PAPER,
        payload={"source": "fixture"},
    )

    serialized = proposal.to_dict()

    assert serialized["proposal_type"] == "cross_venue_arb"
    assert serialized["side"] == "buy_yes"
    assert serialized["edge_bps"] == "12.5"
    assert serialized["mode"] == "paper"
    assert "order" not in serialized
    assert "client" not in serialized


def test_signal_proposal_requires_positive_edge_and_an_auditable_target() -> None:
    with pytest.raises(ValueError, match="edge_bps"):
        SignalProposal(
            strategy_name="bad",
            proposal_type=ProposalType.CROSS_VENUE_ARB,
            side=ProposalSide.BUY_YES,
            edge_bps=Decimal("0"),
            confidence=Decimal("0.5"),
            max_notional_usd=Decimal("10"),
            fresh_until="2026-06-30T12:01:00Z",
            relation_id="relation-1",
        )

    with pytest.raises(ValueError, match="instrument_ids or relation_id"):
        SignalProposal(
            strategy_name="bad",
            proposal_type=ProposalType.CROSS_VENUE_ARB,
            side=ProposalSide.BUY_YES,
            edge_bps=Decimal("1"),
            confidence=Decimal("0.5"),
            max_notional_usd=Decimal("10"),
            fresh_until="2026-06-30T12:01:00Z",
        )


def test_order_intent_is_a_serializable_plan_not_a_venue_order() -> None:
    proposal = SignalProposal(
        strategy_name="cross_venue_arb",
        proposal_type=ProposalType.CROSS_VENUE_ARB,
        side=ProposalSide.BUY_NO,
        edge_bps=Decimal("4"),
        confidence=Decimal("0.6"),
        max_notional_usd=Decimal("30"),
        fresh_until="2026-06-30T12:01:00Z",
        relation_id="relation-1",
        mode=StrategyMode.PAPER,
    )
    intent = OrderIntent(
        proposal_id=proposal.proposal_id,
        venue_id=VenueId.POLYMARKET,
        instrument_id="token-yes",
        side=OrderSide.BUY,
        price=Decimal("0.40"),
        quantity=Decimal("75"),
        post_only=True,
        execution_mode=ExecutionMode.PAPER,
        payload={"transmission": "disabled"},
    )

    assert intent.notional_usd == Decimal("30.00")
    assert intent.to_dict()["notional_usd"] == "30.00"
    assert intent.to_dict()["payload"]["transmission"] == "disabled"


def test_canary_order_intents_must_be_post_only() -> None:
    with pytest.raises(ValueError, match="canary"):
        OrderIntent(
            proposal_id=SignalProposal(
                strategy_name="canary_candidate",
                proposal_type=ProposalType.CROSS_VENUE_ARB,
                side=ProposalSide.BUY_YES,
                edge_bps=Decimal("4"),
                confidence=Decimal("0.6"),
                max_notional_usd=Decimal("30"),
                fresh_until="2026-06-30T12:01:00Z",
                relation_id="relation-1",
            ).proposal_id,
            venue_id=VenueId.KALSHI,
            instrument_id="KXTEST-26",
            side=OrderSide.BUY,
            price=Decimal("0.51"),
            quantity=Decimal("10"),
            post_only=False,
            execution_mode=ExecutionMode.CANARY,
        )


def test_market_relation_tracks_review_status_without_auto_approval() -> None:
    polymarket = InstrumentRef.new(
        venue_id=VenueId.POLYMARKET,
        venue_market_id="pm-market",
        venue_token_id="pm-token",
    )
    kalshi = InstrumentRef.new(venue_id=VenueId.KALSHI, venue_market_id="KXMARKET-26")

    candidate = MarketRelation(
        relation_type="equivalent_binary_contract",
        canonical_question="Will the test event resolve yes?",
        members=(polymarket, kalshi),
        confidence=0.92,
    )

    assert candidate.status == "candidate"
    assert not candidate.approved
