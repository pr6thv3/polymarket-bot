"""Pure fee helpers for read-only route economics.

The helpers intentionally model only verified direct trading fees. Rewards, rebates,
and liquidity programs are zero-credit until independently verified from primary
sources and attached to an observation.
"""

from __future__ import annotations

from decimal import Decimal

from research.quotes import FeeRule

ZERO = Decimal("0")


def c_p_one_minus_p_fee_rule(
    *,
    venue: str,
    rate: Decimal,
    schedule_reference: str,
    source_contract_version: str,
    rounding_increment_usd: Decimal | None = None,
) -> FeeRule:
    """Build a verified ``C * rate * p * (1-p)`` fee rule for one observation."""
    return FeeRule(
        venue=venue,
        formula="c_p_one_minus_p",
        rate=rate,
        schedule_reference=schedule_reference,
        source_contract_version=source_contract_version,
        verified=True,
        rounding_increment_usd=rounding_increment_usd,
    )


def zero_credit_for_unverified_programs() -> Decimal:
    """Return the only allowed value for unverified rewards/rebates/incentives."""
    return ZERO
