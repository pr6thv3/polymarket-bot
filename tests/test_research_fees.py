from decimal import Decimal

from research.fees import c_p_one_minus_p_fee_rule, zero_credit_for_unverified_programs


def test_fee_helper_builds_verified_cpmm_rule_with_rounding():
    rule = c_p_one_minus_p_fee_rule(
        venue="kalshi",
        rate=Decimal("0.07"),
        schedule_reference="fixture",
        source_contract_version="kalshi_fixture",
        rounding_increment_usd=Decimal("0.01"),
    )

    assert rule.verified is True
    assert rule.cost(Decimal("1"), Decimal("0.50")) == Decimal("0.02")


def test_unverified_rewards_and_rebates_are_zero_credit():
    assert zero_credit_for_unverified_programs() == Decimal("0")
