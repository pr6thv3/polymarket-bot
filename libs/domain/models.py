"""Control-plane domain models for instruments and market relations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from libs.domain.enums import VenueId


@dataclass(frozen=True)
class InstrumentRef:
    instrument_id: UUID
    venue_id: VenueId
    venue_market_id: str
    venue_token_id: str | None = None

    @classmethod
    def new(
        cls,
        *,
        venue_id: VenueId,
        venue_market_id: str,
        venue_token_id: str | None = None,
    ) -> InstrumentRef:
        return cls(
            instrument_id=uuid4(),
            venue_id=venue_id,
            venue_market_id=venue_market_id,
            venue_token_id=venue_token_id,
        )


@dataclass(frozen=True)
class MarketRelation:
    relation_type: str
    canonical_question: str
    members: tuple[InstrumentRef, ...]
    status: str = "candidate"
    confidence: float = 0.0
    relation_id: UUID = field(default_factory=uuid4)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def approved(self) -> bool:
        return self.status == "approved"
