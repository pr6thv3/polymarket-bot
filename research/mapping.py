"""Manual, versioned contract mappings for cross-venue research."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class MappingValidationError(ValueError):
    """Raised when a mapping is not sufficiently reviewed for replay."""


APPROVED_REQUIRED_FIELDS = (
    "mapping_id",
    "version",
    "canonical_proposition",
    "yes_predicate",
    "resolution_source",
    "cutoff_utc",
    "timezone",
    "payout_convention",
    "invalidation_behavior",
    "review_evidence",
    "reviewer",
    "reviewed_at",
)


@dataclass(frozen=True)
class ContractMapping:
    mapping_id: str
    version: int
    status: str
    polymarket_condition_id: str
    polymarket_yes_token_id: str
    polymarket_no_token_id: str
    kalshi_event_ticker: str
    kalshi_market_ticker: str
    kalshi_series_ticker: str
    canonical_proposition: str
    yes_predicate: str
    resolution_source: str
    cutoff_utc: str
    timezone: str
    payout_convention: str
    invalidation_behavior: str
    review_evidence: tuple[str, ...]
    reviewer: str
    reviewed_at: str

    @property
    def digest(self) -> str:
        encoded = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "mapping_id": self.mapping_id,
            "version": self.version,
            "status": self.status,
            "polymarket": {
                "condition_id": self.polymarket_condition_id,
                "yes_token_id": self.polymarket_yes_token_id,
                "no_token_id": self.polymarket_no_token_id,
            },
            "kalshi": {
                "event_ticker": self.kalshi_event_ticker,
                "market_ticker": self.kalshi_market_ticker,
                "series_ticker": self.kalshi_series_ticker,
            },
            "canonical_proposition": self.canonical_proposition,
            "yes_predicate": self.yes_predicate,
            "resolution_source": self.resolution_source,
            "cutoff_utc": self.cutoff_utc,
            "timezone": self.timezone,
            "payout_convention": self.payout_convention,
            "invalidation_behavior": self.invalidation_behavior,
            "review_evidence": list(self.review_evidence),
            "reviewer": self.reviewer,
            "reviewed_at": self.reviewed_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContractMapping":
        if data.get("status") != "approved":
            raise MappingValidationError("only manually approved mappings are replay eligible")
        missing = [field for field in APPROVED_REQUIRED_FIELDS if not data.get(field)]
        if missing:
            raise MappingValidationError("approved mapping missing: " + ", ".join(missing))
        poly = data.get("polymarket") or {}
        kalshi = data.get("kalshi") or {}
        nested = {
            "polymarket.condition_id": poly.get("condition_id"),
            "polymarket.yes_token_id": poly.get("yes_token_id"),
            "polymarket.no_token_id": poly.get("no_token_id"),
            "kalshi.event_ticker": kalshi.get("event_ticker"),
            "kalshi.market_ticker": kalshi.get("market_ticker"),
            "kalshi.series_ticker": kalshi.get("series_ticker"),
        }
        absent = [key for key, value in nested.items() if not value]
        if absent:
            raise MappingValidationError("approved mapping missing: " + ", ".join(absent))
        evidence = data["review_evidence"]
        if not isinstance(evidence, list) or not evidence:
            raise MappingValidationError("review_evidence must be a non-empty list")
        return cls(
            mapping_id=str(data["mapping_id"]),
            version=int(data["version"]),
            status="approved",
            polymarket_condition_id=str(poly["condition_id"]),
            polymarket_yes_token_id=str(poly["yes_token_id"]),
            polymarket_no_token_id=str(poly["no_token_id"]),
            kalshi_event_ticker=str(kalshi["event_ticker"]),
            kalshi_market_ticker=str(kalshi["market_ticker"]),
            kalshi_series_ticker=str(kalshi["series_ticker"]),
            canonical_proposition=str(data["canonical_proposition"]),
            yes_predicate=str(data["yes_predicate"]),
            resolution_source=str(data["resolution_source"]),
            cutoff_utc=str(data["cutoff_utc"]),
            timezone=str(data["timezone"]),
            payout_convention=str(data["payout_convention"]),
            invalidation_behavior=str(data["invalidation_behavior"]),
            review_evidence=tuple(str(item) for item in evidence),
            reviewer=str(data["reviewer"]),
            reviewed_at=str(data["reviewed_at"]),
        )


@dataclass(frozen=True)
class MappingCatalog:
    version: int
    mappings: tuple[ContractMapping, ...]

    @classmethod
    def load(cls, path: str | Path) -> "MappingCatalog":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        entries = raw.get("mappings", [])
        if not isinstance(entries, list):
            raise MappingValidationError("catalog mappings must be a list")
        approved: list[ContractMapping] = []
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("status") != "approved":
                continue
            mapping = ContractMapping.from_dict(entry)
            if mapping.mapping_id in seen:
                raise MappingValidationError(f"duplicate mapping_id: {mapping.mapping_id}")
            seen.add(mapping.mapping_id)
            approved.append(mapping)
        return cls(version=int(raw.get("version", 1)), mappings=tuple(approved))
