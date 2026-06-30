from decimal import Decimal

import pytest

from libs.domain.enums import (
    ExecutionMode,
    ProposalSide,
    ProposalType,
    RiskDecisionStatus,
    StrategyMode,
    VenueId,
)
from libs.domain.events import RiskDecision, SignalProposal
from services.execution_gateway.gateway import ExecutionGateway, ExecutionPlanError


def make_proposal() -> SignalProposal:
    return SignalProposal(
        strategy_name="cross_venue_arb",
        proposal_type=ProposalType.CROSS_VENUE_ARB,
        side=ProposalSide.BUY_YES,
        edge_bps=Decimal("8"),
        confidence=Decimal("0.80"),
        max_notional_usd=Decimal("40"),
        fresh_until="2026-06-30T12:01:00Z",
        relation_id="approved-relation",
        mode=StrategyMode.PAPER,
    )


def test_gateway_creates_non_transmitting_intent_from_approved_risk_decision() -> None:
    proposal = make_proposal()
    decision = RiskDecision(
        proposal_id=proposal.proposal_id,
        decision=RiskDecisionStatus.APPROVED,
        reason_codes=(),
        resized_notional_usd=Decimal("40"),
        execution_mode=ExecutionMode.PAPER,
    )

    intent = ExecutionGateway().plan_single_leg_intent(
        proposal=proposal,
        decision=decision,
        venue_id=VenueId.POLYMARKET,
        instrument_id="token-yes",
        limit_price=Decimal("0.50"),
    )

    assert intent.quantity == Decimal("8E+1")
    assert intent.payload["transmission"] == "disabled"
    assert intent.execution_mode == ExecutionMode.PAPER


def test_gateway_rejects_non_approved_risk_decisions() -> None:
    proposal = make_proposal()
    decision = RiskDecision(
        proposal_id=proposal.proposal_id,
        decision=RiskDecisionStatus.REJECTED,
        reason_codes=("missing_approved_relation",),
        resized_notional_usd=None,
        execution_mode=None,
    )

    with pytest.raises(ExecutionPlanError, match="not approved"):
        ExecutionGateway().plan_single_leg_intent(
            proposal=proposal,
            decision=decision,
            venue_id=VenueId.KALSHI,
            instrument_id="KXTEST-26",
            limit_price=Decimal("0.48"),
        )


def test_gateway_keeps_canary_intents_post_only() -> None:
    proposal = make_proposal()
    decision = RiskDecision(
        proposal_id=proposal.proposal_id,
        decision=RiskDecisionStatus.APPROVED,
        reason_codes=(),
        resized_notional_usd=Decimal("5"),
        execution_mode=ExecutionMode.CANARY,
    )

    with pytest.raises(ExecutionPlanError, match="post_only"):
        ExecutionGateway().plan_single_leg_intent(
            proposal=proposal,
            decision=decision,
            venue_id=VenueId.POLYMARKET,
            instrument_id="token-yes",
            limit_price=Decimal("0.25"),
            post_only=False,
        )
