"""Tests for reward economics modeling."""

import math

import pytest

from tools.reward_economics_model import RewardModelInput, calculate_reward_economics


def base_input(**overrides):
    data = dict(
        capital_usd=100.0,
        market_id="m1",
        yes_bid=0.49,
        yes_ask=0.50,
        no_bid=0.50,
        no_ask=0.51,
        spread_bps=100.0,
        min_order_size=5.0,
        max_reward_spread_bps=300.0,
        expected_reward_per_day=1.0,
        probability_of_fill=0.10,
        adverse_selection_loss_estimate=2.0,
        gas_cost_estimate=0.01,
        quote_refresh_interval_sec=3600.0,
        active_hours_per_day=10.0,
        holding_yield_apy=0.0,
        opportunity_cost_apy=0.0,
    )
    data.update(overrides)
    return RewardModelInput(**data)


def test_reward_ev_calculation_separates_income_and_costs():
    out = calculate_reward_economics(base_input())

    assert out.estimated_daily_reward == pytest.approx(1.0)
    assert out.estimated_daily_spread_income == pytest.approx(0.10 * 1.0)
    assert out.estimated_expected_adverse_loss == pytest.approx(0.20)
    assert out.estimated_daily_gas == pytest.approx(0.10)
    assert out.estimated_net_daily_ev == pytest.approx(0.80)


def test_gas_subtraction_scales_with_refreshes():
    out = calculate_reward_economics(base_input(gas_cost_estimate=0.02, quote_refresh_interval_sec=1800, active_hours_per_day=1))

    assert out.quotes_per_day == pytest.approx(2.0)
    assert out.estimated_daily_gas == pytest.approx(0.04)


def test_adverse_selection_subtraction():
    out = calculate_reward_economics(base_input(probability_of_fill=0.25, adverse_selection_loss_estimate=4.0))

    assert out.estimated_expected_adverse_loss == pytest.approx(1.0)


def test_breakeven_calculations():
    out = calculate_reward_economics(base_input(expected_reward_per_day=0.0, probability_of_fill=0.5, adverse_selection_loss_estimate=2.0))

    assert out.breakeven_reward_required == pytest.approx(0.6)  # gas 0.1 + adverse 1.0 - spread income 0.5
    assert out.breakeven_fill_loss_allowed == pytest.approx(0.8)  # (spread 0.5 - gas 0.1) / 0.5


def test_zero_reward_case_can_be_negative():
    out = calculate_reward_economics(base_input(expected_reward_per_day=0.0, probability_of_fill=0.0, gas_cost_estimate=0.01))

    assert out.estimated_daily_reward == 0
    assert out.estimated_net_daily_ev < 0


def test_negative_ev_case():
    out = calculate_reward_economics(base_input(expected_reward_per_day=0.05, probability_of_fill=0.5, adverse_selection_loss_estimate=5.0))

    assert out.estimated_net_daily_ev < 0
    assert out.annualized_return_estimate < 0


def test_small_capital_case_fails_min_order_size_gate():
    out = calculate_reward_economics(base_input(capital_usd=5.0, min_order_size=5.0))

    assert out.eligible_by_min_order_size is False


def test_zero_fill_probability_has_infinite_breakeven_loss_allowed():
    out = calculate_reward_economics(base_input(probability_of_fill=0.0))

    assert math.isinf(out.breakeven_fill_loss_allowed)
