"""Execution gateway skeleton.

The gateway converts approved risk decisions into non-transmitting order intents.
It deliberately contains no venue client and cannot place an order.
"""

from __future__ import annotations

from decimal import Decimal

from libs.domain.enums import ExecutionMode, OrderSide, ProposalSide, VenueId
from libs.domain.events import OrderIntent, RiskDecision, SignalProposal


class ExecutionPlanError(ValueError):
    """Raised when a proposal cannot become a safe order intent."""


class ExecutionGateway:
    """Planner-only execution gateway.

    A future transmitting gateway must live in a separate process with credentials,
    live canary gates, and venue-specific reconciliation. This class is intentionally
    paper/canary intent generation only.
    """

    def plan_single_leg_intent(
        self,
        *,
        proposal: SignalProposal,
        decision: RiskDecision,
        venue_id: VenueId,
        instrument_id: str,
        limit_price: Decimal,
        post_only: bool = True,
    ) -> OrderIntent:
        if not decision.approved_for_order_intent:
            raise ExecutionPlanError("risk decision is not approved for order intent")
        if decision.execution_mode is None:
            raise ExecutionPlanError("risk decision has no execution mode")
        if decision.resized_notional_usd is None or decision.resized_notional_usd <= 0:
            raise ExecutionPlanError("risk decision has no positive notional")
        if proposal.side not in {ProposalSide.BUY_YES, ProposalSide.BUY_NO}:
            raise ExecutionPlanError("single-leg skeleton supports buy proposals only")
        if decision.execution_mode == ExecutionMode.CANARY and not post_only:
            raise ExecutionPlanError("canary order intents must be post_only")

        quantity = decision.resized_notional_usd / limit_price
        return OrderIntent(
            proposal_id=proposal.proposal_id,
            venue_id=venue_id,
            instrument_id=instrument_id,
            side=OrderSide.BUY,
            price=limit_price,
            quantity=quantity,
            post_only=post_only,
            execution_mode=decision.execution_mode,
            payload={
                "strategy_name": proposal.strategy_name,
                "proposal_type": proposal.proposal_type.value,
                "transmission": "disabled",
            },
        )
