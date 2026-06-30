"""Proposal selector and risk checks for the strategy platform skeleton."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from libs.domain.enums import ExecutionMode, RiskDecisionStatus, StrategyMode
from libs.domain.events import RiskDecision, SignalProposal


@dataclass(frozen=True)
class RiskPolicy:
    min_edge_bps: Decimal = Decimal("1")
    min_confidence: Decimal = Decimal("0.50")
    min_regime_fit: Decimal = Decimal("0.50")
    max_proposal_notional_usd: Decimal = Decimal("150")
    require_relation_for_cross_venue: bool = True
    allowed_live_modes: frozenset[StrategyMode] = frozenset({StrategyMode.PAPER})


@dataclass(frozen=True)
class PortfolioState:
    available_cash_usd: Decimal
    reserved_cash_usd: Decimal = Decimal("0")
    per_strategy_reserved_usd: dict[str, Decimal] = field(default_factory=dict)

    @property
    def deployable_cash_usd(self) -> Decimal:
        return max(Decimal("0"), self.available_cash_usd - self.reserved_cash_usd)


class SelectorRiskEngine:
    """Pure proposal gate; it emits decisions and never transmits orders."""

    def __init__(self, policy: RiskPolicy | None = None) -> None:
        self.policy = policy or RiskPolicy()

    def evaluate(self, proposal: SignalProposal, portfolio: PortfolioState) -> RiskDecision:
        reasons: list[str] = []

        if proposal.mode == StrategyMode.DISABLED:
            reasons.append("strategy_disabled")
        if proposal.mode == StrategyMode.SHADOW:
            return RiskDecision(
                proposal_id=proposal.proposal_id,
                decision=RiskDecisionStatus.SHADOW_ONLY,
                reason_codes=("shadow_mode",),
                resized_notional_usd=None,
                execution_mode=None,
            )
        if proposal.mode not in self.policy.allowed_live_modes:
            reasons.append("strategy_mode_not_allowed")
        if proposal.edge_bps < self.policy.min_edge_bps:
            reasons.append("edge_below_threshold")
        if proposal.confidence < self.policy.min_confidence:
            reasons.append("confidence_below_threshold")
        if proposal.regime_fit < self.policy.min_regime_fit:
            reasons.append("regime_fit_below_threshold")
        if self.policy.require_relation_for_cross_venue and not proposal.relation_id:
            reasons.append("missing_approved_relation")

        if reasons:
            return RiskDecision(
                proposal_id=proposal.proposal_id,
                decision=RiskDecisionStatus.REJECTED,
                reason_codes=tuple(reasons),
                resized_notional_usd=None,
                execution_mode=None,
            )

        requested = min(proposal.max_notional_usd, self.policy.max_proposal_notional_usd)
        approved = min(requested, portfolio.deployable_cash_usd)
        if approved <= 0:
            return RiskDecision(
                proposal_id=proposal.proposal_id,
                decision=RiskDecisionStatus.REJECTED,
                reason_codes=("insufficient_cash",),
                resized_notional_usd=None,
                execution_mode=None,
            )

        decision = (
            RiskDecisionStatus.APPROVED
            if approved == proposal.max_notional_usd
            else RiskDecisionStatus.RESIZED
        )
        return RiskDecision(
            proposal_id=proposal.proposal_id,
            decision=decision,
            reason_codes=() if decision == RiskDecisionStatus.APPROVED else ("resized_to_limit",),
            resized_notional_usd=approved,
            execution_mode=ExecutionMode.PAPER,
            details={"requested_notional_usd": str(proposal.max_notional_usd)},
        )
