"""Strategy module interface for proposal-producing strategies."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from libs.domain.events import SignalProposal


@dataclass(frozen=True)
class StrategyContext:
    now: str
    features: dict[str, Any] = field(default_factory=dict)
    market_state: dict[str, Any] = field(default_factory=dict)
    operator_overrides: dict[str, Any] = field(default_factory=dict)


class StrategyModule(Protocol):
    """A strategy emits proposals; it never places orders."""

    name: str

    def generate_proposals(self, context: StrategyContext) -> tuple[SignalProposal, ...]: ...
