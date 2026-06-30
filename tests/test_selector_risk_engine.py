from decimal import Decimal

from libs.domain.enums import ProposalSide, ProposalType, RiskDecisionStatus, StrategyMode
from libs.domain.events import SignalProposal
from services.selector_risk.engine import PortfolioState, RiskPolicy, SelectorRiskEngine


def make_proposal(
    *,
    edge_bps: Decimal = Decimal("5"),
    confidence: Decimal = Decimal("0.80"),
    max_notional_usd: Decimal = Decimal("25"),
    mode: StrategyMode = StrategyMode.PAPER,
    relation_id: str | None = "approved-relation",
) -> SignalProposal:
    return SignalProposal(
        strategy_name="cross_venue_arb",
        proposal_type=ProposalType.CROSS_VENUE_ARB,
        side=ProposalSide.BUY_YES,
        edge_bps=edge_bps,
        confidence=confidence,
        max_notional_usd=max_notional_usd,
        fresh_until="2026-06-30T12:01:00Z",
        instrument_ids=("pm-token",) if relation_id is None else (),
        relation_id=relation_id,
        mode=mode,
    )


def test_shadow_strategy_never_reaches_execution_mode() -> None:
    decision = SelectorRiskEngine().evaluate(
        make_proposal(mode=StrategyMode.SHADOW),
        PortfolioState(available_cash_usd=Decimal("100")),
    )

    assert decision.decision == RiskDecisionStatus.SHADOW_ONLY
    assert decision.execution_mode is None
    assert decision.reason_codes == ("shadow_mode",)


def test_good_paper_proposal_is_approved_for_paper_only() -> None:
    decision = SelectorRiskEngine().evaluate(
        make_proposal(),
        PortfolioState(available_cash_usd=Decimal("100")),
    )

    assert decision.decision == RiskDecisionStatus.APPROVED
    assert decision.execution_mode is not None
    assert decision.execution_mode.value == "paper"
    assert decision.resized_notional_usd == Decimal("25")


def test_selector_rejects_low_quality_or_unmapped_proposals() -> None:
    engine = SelectorRiskEngine()

    low_confidence = engine.evaluate(
        make_proposal(confidence=Decimal("0.49")),
        PortfolioState(available_cash_usd=Decimal("100")),
    )
    missing_mapping = engine.evaluate(
        make_proposal(relation_id=None, max_notional_usd=Decimal("15"), mode=StrategyMode.PAPER),
        PortfolioState(available_cash_usd=Decimal("100")),
    )

    assert low_confidence.decision == RiskDecisionStatus.REJECTED
    assert "confidence_below_threshold" in low_confidence.reason_codes
    assert missing_mapping.decision == RiskDecisionStatus.REJECTED
    assert "missing_approved_relation" in missing_mapping.reason_codes


def test_selector_resizes_to_policy_or_cash_limit() -> None:
    engine = SelectorRiskEngine(policy=RiskPolicy(max_proposal_notional_usd=Decimal("20")))

    policy_limited = engine.evaluate(
        make_proposal(max_notional_usd=Decimal("50")),
        PortfolioState(available_cash_usd=Decimal("100")),
    )
    cash_limited = engine.evaluate(
        make_proposal(max_notional_usd=Decimal("50")),
        PortfolioState(available_cash_usd=Decimal("12")),
    )

    assert policy_limited.decision == RiskDecisionStatus.RESIZED
    assert policy_limited.resized_notional_usd == Decimal("20")
    assert cash_limited.decision == RiskDecisionStatus.RESIZED
    assert cash_limited.resized_notional_usd == Decimal("12")
