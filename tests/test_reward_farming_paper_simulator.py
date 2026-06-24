"""Tests for reward farming paper simulator."""

import pytest

from tools.reward_farming_paper_simulator import (
    FORMULA_WARNING,
    ReliabilityContext,
    evaluate_market,
    estimate_gas_usd_per_day,
)


def candidate(**overrides):
    data = {
        "market_id": "m1",
        "question": "Will test happen?",
        "yes_bid": 0.49,
        "yes_ask": 0.50,
        "no_bid": 0.50,
        "no_ask": 0.51,
        "spread_bps": 10.0,
        "touch_depth": 1000.0,
        "liquidity": 1000.0,
        "volume": 10000,
        "minimum_order_size": 5.0,
        "reward_min_size": 20.0,
        "reward_max_spread_raw": 4.5,
        "reward_max_spread_bps_model": 450.0,
        "reward_daily_rate_sum": 100.0,
        "reward_assets": ["0x2791bca1f2de4661ed88a30c99a7a9449aa84174"],
        "estimated_capital_required": 40.0,
    }
    data.update(overrides)
    return data


def reliable():
    return ReliabilityContext(error_rate_pct=2.0, p95_latency_ms=500, simulator_results_reliable=True, source="test")


def unreliable():
    return ReliabilityContext(error_rate_pct=46.5, p95_latency_ms=3000, simulator_results_reliable=False, source="test")


def test_pro_rata_reward_scenarios_do_not_assume_full_capture():
    sim = evaluate_market(candidate(reward_daily_rate_sum=1000), 100, 24, 300, reliable())

    assert sim.scenarios["pessimistic"].pro_rata_reward_usd_day == pytest.approx(0.1)
    assert sim.scenarios["base"].pro_rata_reward_usd_day == pytest.approx(0.5)
    assert sim.scenarios["optimistic"].pro_rata_reward_usd_day == pytest.approx(1.0)


def test_adverse_loss_subtraction_can_make_ev_negative():
    sim = evaluate_market(candidate(reward_daily_rate_sum=1), 5000, 24, 300, reliable())

    assert sim.scenarios["pessimistic"].adverse_loss_usd_day > sim.scenarios["pessimistic"].pro_rata_reward_usd_day
    assert sim.scenarios["pessimistic"].expected_net_ev_usd_day < 0


def test_gas_subtraction_is_positive():
    assert estimate_gas_usd_per_day(duration_hours=24, interval_seconds=3600) > 0


def test_capital_too_small_case_rejected():
    sim = evaluate_market(candidate(reward_min_size=200, estimated_capital_required=400), 50, 24, 300, reliable())

    assert sim.capital_sufficient is False
    assert any("capital" in reason for reason in sim.rejected_reasons)


def test_incomplete_reward_metadata_rejection():
    sim = evaluate_market(candidate(reward_daily_rate_sum=0), 1000, 24, 300, reliable())

    assert any("reward metadata" in reason for reason in sim.rejected_reasons)


def test_negative_ev_case():
    sim = evaluate_market(candidate(reward_daily_rate_sum=1, touch_depth=20), 1000, 24, 300, reliable())

    assert sim.scenarios["pessimistic"].expected_net_ev_usd_day < 0


def test_positive_ev_case_under_pessimistic_scenario():
    sim = evaluate_market(candidate(reward_daily_rate_sum=100000, estimated_capital_required=40), 1000, 24, 3600, reliable())

    assert sim.scenarios["pessimistic"].expected_net_ev_usd_day > 0


def test_unreliable_data_marks_low_confidence_and_rejected():
    sim = evaluate_market(candidate(reward_daily_rate_sum=100000), 1000, 24, 300, unreliable())

    assert sim.scenarios["base"].confidence == "low"
    assert any("data reliability" in reason for reason in sim.rejected_reasons)


def test_unknown_formula_warning_constant():
    assert "partially unverified" in FORMULA_WARNING
