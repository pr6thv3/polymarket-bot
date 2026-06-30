from decimal import Decimal

import pytest

from libs.sizing.buckets import CapitalBucket, reserve_from_bucket


def test_bucket_reservation_fully_fills_when_capacity_exists() -> None:
    reservation = reserve_from_bucket(
        CapitalBucket(name="cross_venue", limit_usd=Decimal("100"), reserved_usd=Decimal("20")),
        Decimal("30"),
    )

    assert reservation.approved_usd == Decimal("30")
    assert reservation.reason is None
    assert reservation.fully_filled


def test_bucket_reservation_resizes_when_capacity_is_limited() -> None:
    reservation = reserve_from_bucket(
        CapitalBucket(name="cross_venue", limit_usd=Decimal("100"), reserved_usd=Decimal("95")),
        Decimal("30"),
    )

    assert reservation.approved_usd == Decimal("5")
    assert reservation.reason == "bucket_capacity_limit"
    assert not reservation.fully_filled


def test_bucket_reservation_rejects_non_positive_requests() -> None:
    with pytest.raises(ValueError, match="positive"):
        reserve_from_bucket(
            CapitalBucket(name="cross_venue", limit_usd=Decimal("100")), Decimal("0")
        )
