"""Capital bucket primitives for proposal selection."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class CapitalBucket:
    name: str
    limit_usd: Decimal
    reserved_usd: Decimal = Decimal("0")

    @property
    def available_usd(self) -> Decimal:
        return max(Decimal("0"), self.limit_usd - self.reserved_usd)


@dataclass(frozen=True)
class BucketReservation:
    bucket: CapitalBucket
    requested_usd: Decimal
    approved_usd: Decimal
    reason: str | None = None

    @property
    def fully_filled(self) -> bool:
        return self.approved_usd == self.requested_usd and self.reason is None


def reserve_from_bucket(bucket: CapitalBucket, requested_usd: Decimal) -> BucketReservation:
    if requested_usd <= 0:
        raise ValueError("requested_usd must be positive")
    approved = min(requested_usd, bucket.available_usd)
    reason = None if approved == requested_usd else "bucket_capacity_limit"
    return BucketReservation(
        bucket=bucket,
        requested_usd=requested_usd,
        approved_usd=approved,
        reason=reason,
    )
