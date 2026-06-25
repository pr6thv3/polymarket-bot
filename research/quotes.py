"""Quote, fee, and executable-route primitives for read-only research."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from typing import Any


ONE = Decimal("1")
ZERO = Decimal("0")


class QuoteValidationError(ValueError):
    """Raised when a fixture or captured quote cannot be interpreted safely."""


def decimal_or_none(value: Any) -> Decimal | None:
    """Parse venue numeric fields without accepting booleans or empty strings."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        normalized = value.strip().replace("$", "")
        if not normalized:
            return None
    else:
        normalized = str(value)
    try:
        parsed = Decimal(normalized)
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite():
        return None
    return parsed


def decimal_to_json(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


def normalize_probability(value: Any) -> Decimal | None:
    """Parse a probability/price and convert cent-style values to dollars."""
    parsed = decimal_or_none(value)
    if parsed is None:
        return None
    if parsed > ONE and parsed <= Decimal("100"):
        parsed = parsed / Decimal("100")
    if parsed < ZERO or parsed > ONE:
        return None
    return parsed


@dataclass(frozen=True)
class BookLevel:
    price: Decimal
    size: Decimal

    def __post_init__(self) -> None:
        if self.price < ZERO or self.price > ONE:
            raise QuoteValidationError(f"price outside [0, 1]: {self.price}")
        if self.size <= ZERO:
            raise QuoteValidationError(f"book level size must be positive: {self.size}")

    def to_dict(self) -> dict[str, str]:
        return {
            "price": decimal_to_json(self.price) or "0",
            "size": decimal_to_json(self.size) or "0",
        }


@dataclass(frozen=True)
class OutcomeQuote:
    bid_price: Decimal | None
    bid_size: Decimal | None
    ask_price: Decimal | None
    ask_size: Decimal | None
    ask_source: str
    missing_depth: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "bid_price": decimal_to_json(self.bid_price),
            "bid_size": decimal_to_json(self.bid_size),
            "ask_price": decimal_to_json(self.ask_price),
            "ask_size": decimal_to_json(self.ask_size),
            "ask_source": self.ask_source,
            "missing_depth": self.missing_depth,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OutcomeQuote":
        return cls(
            bid_price=decimal_or_none(data.get("bid_price")),
            bid_size=decimal_or_none(data.get("bid_size")),
            ask_price=decimal_or_none(data.get("ask_price")),
            ask_size=decimal_or_none(data.get("ask_size")),
            ask_source=str(data.get("ask_source") or "unknown"),
            missing_depth=bool(data.get("missing_depth")),
        )


@dataclass(frozen=True)
class FeeRule:
    """A verified dynamic fee formula attached to an observation.

    Supported formula:
    - ``c_p_one_minus_p``: rate * contracts * price * (1 - price)

    ``rounding_increment_usd`` applies ceiling rounding to the next increment,
    e.g. Kalshi's next-cent rounding is ``0.01``.
    """

    venue: str
    formula: str
    rate: Decimal
    schedule_reference: str
    source_contract_version: str
    verified: bool
    rounding_increment_usd: Decimal | None = None

    def cost(self, contracts: Decimal, price: Decimal) -> Decimal:
        if not self.verified:
            raise QuoteValidationError(f"unverified fee rule for {self.venue}")
        if contracts <= ZERO:
            raise QuoteValidationError("fee contracts must be positive")
        if price < ZERO or price > ONE:
            raise QuoteValidationError("fee price must be within [0, 1]")
        if self.formula != "c_p_one_minus_p":
            raise QuoteValidationError(f"unsupported fee formula: {self.formula}")
        fee = self.rate * contracts * price * (ONE - price)
        if self.rounding_increment_usd is not None:
            increment = self.rounding_increment_usd
            if increment <= ZERO:
                raise QuoteValidationError("rounding increment must be positive")
            fee = (fee / increment).to_integral_value(rounding=ROUND_CEILING) * increment
        return fee

    def to_dict(self) -> dict[str, Any]:
        return {
            "venue": self.venue,
            "formula": self.formula,
            "rate": decimal_to_json(self.rate),
            "schedule_reference": self.schedule_reference,
            "source_contract_version": self.source_contract_version,
            "verified": self.verified,
            "rounding_increment_usd": decimal_to_json(self.rounding_increment_usd),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "FeeRule | None":
        if not data:
            return None
        rate = decimal_or_none(data.get("rate"))
        if rate is None:
            return None
        rounding = decimal_or_none(data.get("rounding_increment_usd"))
        return cls(
            venue=str(data.get("venue") or ""),
            formula=str(data.get("formula") or ""),
            rate=rate,
            schedule_reference=str(data.get("schedule_reference") or ""),
            source_contract_version=str(data.get("source_contract_version") or ""),
            verified=bool(data.get("verified")),
            rounding_increment_usd=rounding,
        )


@dataclass(frozen=True)
class VenueSnapshot:
    venue: str
    market_id: str
    yes: OutcomeQuote
    no: OutcomeQuote
    receipt_timestamp: str
    source_timestamp: str | None
    raw_payload_hash: str
    source_contract_version: str
    fee_rule: FeeRule | None
    fee_schedule_reference: str | None
    min_order_size: Decimal | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "venue": self.venue,
            "market_id": self.market_id,
            "yes": self.yes.to_dict(),
            "no": self.no.to_dict(),
            "receipt_timestamp": self.receipt_timestamp,
            "source_timestamp": self.source_timestamp,
            "raw_payload_hash": self.raw_payload_hash,
            "source_contract_version": self.source_contract_version,
            "fee_rule": self.fee_rule.to_dict() if self.fee_rule else None,
            "fee_schedule_reference": self.fee_schedule_reference,
            "min_order_size": decimal_to_json(self.min_order_size),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VenueSnapshot":
        return cls(
            venue=str(data["venue"]),
            market_id=str(data["market_id"]),
            yes=OutcomeQuote.from_dict(data["yes"]),
            no=OutcomeQuote.from_dict(data["no"]),
            receipt_timestamp=str(data["receipt_timestamp"]),
            source_timestamp=(
                str(data["source_timestamp"]) if data.get("source_timestamp") else None
            ),
            raw_payload_hash=str(data["raw_payload_hash"]),
            source_contract_version=str(data["source_contract_version"]),
            fee_rule=FeeRule.from_dict(data.get("fee_rule")),
            fee_schedule_reference=(
                str(data["fee_schedule_reference"])
                if data.get("fee_schedule_reference")
                else None
            ),
            min_order_size=decimal_or_none(data.get("min_order_size")),
        )


@dataclass(frozen=True)
class PairedSnapshot:
    mapping_id: str
    mapping_version: int
    mapping_digest: str
    captured_at: str
    pair_skew_ms: int | None
    polymarket: VenueSnapshot
    kalshi: VenueSnapshot
    rejection_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_type": "paired_snapshot",
            "mapping_id": self.mapping_id,
            "mapping_version": self.mapping_version,
            "mapping_digest": self.mapping_digest,
            "captured_at": self.captured_at,
            "pair_skew_ms": self.pair_skew_ms,
            "polymarket": self.polymarket.to_dict(),
            "kalshi": self.kalshi.to_dict(),
            "rejection_reason": self.rejection_reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PairedSnapshot":
        return cls(
            mapping_id=str(data["mapping_id"]),
            mapping_version=int(data["mapping_version"]),
            mapping_digest=str(data["mapping_digest"]),
            captured_at=str(data["captured_at"]),
            pair_skew_ms=(
                int(data["pair_skew_ms"]) if data.get("pair_skew_ms") is not None else None
            ),
            polymarket=VenueSnapshot.from_dict(data["polymarket"]),
            kalshi=VenueSnapshot.from_dict(data["kalshi"]),
            rejection_reason=(
                str(data["rejection_reason"]) if data.get("rejection_reason") else None
            ),
        )
