"""Canonical event contracts for proposals, risk decisions, and order intents."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from libs.domain.enums import (
    ExecutionMode,
    OrderSide,
    ProposalSide,
    ProposalType,
    RiskDecisionStatus,
    StrategyMode,
    VenueId,
)


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def decimal_to_json(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def decimal_from_json(value: str | int | float | Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


@dataclass(frozen=True)
class SignalProposal:
    """A strategy proposal that cannot place an order by itself."""

    strategy_name: str
    proposal_type: ProposalType
    side: ProposalSide
    edge_bps: Decimal
    confidence: Decimal
    max_notional_usd: Decimal
    fresh_until: str
    instrument_ids: tuple[str, ...] = ()
    relation_id: str | None = None
    expected_holding_sec: int | None = None
    latency_budget_ms: int | None = None
    regime_fit: Decimal = Decimal("1")
    mode: StrategyMode = StrategyMode.SHADOW
    proposal_id: UUID = field(default_factory=uuid4)
    created_at: str = field(default_factory=utc_now_iso)
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.edge_bps <= 0:
            raise ValueError("signal proposal edge_bps must be positive after costs")
        if not Decimal("0") <= self.confidence <= Decimal("1"):
            raise ValueError("signal proposal confidence must be within [0, 1]")
        if not Decimal("0") <= self.regime_fit <= Decimal("1"):
            raise ValueError("signal proposal regime_fit must be within [0, 1]")
        if self.max_notional_usd <= 0:
            raise ValueError("signal proposal max_notional_usd must be positive")
        if not self.instrument_ids and not self.relation_id:
            raise ValueError("signal proposal requires instrument_ids or relation_id")

    @property
    def audit_key(self) -> str:
        return f"{self.strategy_name}:{self.proposal_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": str(self.proposal_id),
            "strategy_name": self.strategy_name,
            "proposal_type": self.proposal_type.value,
            "side": self.side.value,
            "edge_bps": decimal_to_json(self.edge_bps),
            "confidence": decimal_to_json(self.confidence),
            "max_notional_usd": decimal_to_json(self.max_notional_usd),
            "fresh_until": self.fresh_until,
            "instrument_ids": list(self.instrument_ids),
            "relation_id": self.relation_id,
            "expected_holding_sec": self.expected_holding_sec,
            "latency_budget_ms": self.latency_budget_ms,
            "regime_fit": decimal_to_json(self.regime_fit),
            "mode": self.mode.value,
            "created_at": self.created_at,
            "payload": self.payload,
        }


@dataclass(frozen=True)
class RiskDecision:
    """Risk layer response to a proposal."""

    proposal_id: UUID
    decision: RiskDecisionStatus
    reason_codes: tuple[str, ...]
    resized_notional_usd: Decimal | None
    execution_mode: ExecutionMode | None
    created_at: str = field(default_factory=utc_now_iso)
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def approved_for_order_intent(self) -> bool:
        return self.decision in {RiskDecisionStatus.APPROVED, RiskDecisionStatus.RESIZED}

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": str(self.proposal_id),
            "decision": self.decision.value,
            "reason_codes": list(self.reason_codes),
            "resized_notional_usd": decimal_to_json(self.resized_notional_usd),
            "execution_mode": self.execution_mode.value if self.execution_mode else None,
            "created_at": self.created_at,
            "details": self.details,
        }


@dataclass(frozen=True)
class OrderIntent:
    """Non-transmitting order intent emitted after risk approval."""

    proposal_id: UUID
    venue_id: VenueId
    instrument_id: str
    side: OrderSide
    price: Decimal
    quantity: Decimal
    post_only: bool
    execution_mode: ExecutionMode
    client_order_id: str = field(default_factory=lambda: f"intent-{uuid4()}")
    created_at: str = field(default_factory=utc_now_iso)
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.price <= 0 or self.price >= 1:
            raise ValueError("order intent price must be inside (0, 1)")
        if self.quantity <= 0:
            raise ValueError("order intent quantity must be positive")
        if self.execution_mode == ExecutionMode.CANARY and not self.post_only:
            raise ValueError("canary order intents must be post_only")

    @property
    def notional_usd(self) -> Decimal:
        return self.price * self.quantity

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": str(self.proposal_id),
            "venue_id": self.venue_id.value,
            "instrument_id": self.instrument_id,
            "side": self.side.value,
            "price": decimal_to_json(self.price),
            "quantity": decimal_to_json(self.quantity),
            "notional_usd": decimal_to_json(self.notional_usd),
            "post_only": self.post_only,
            "execution_mode": self.execution_mode.value,
            "client_order_id": self.client_order_id,
            "created_at": self.created_at,
            "payload": self.payload,
        }
