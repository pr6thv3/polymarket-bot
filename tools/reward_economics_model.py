#!/usr/bin/env python3
"""Reward economics model for Polymarket reward/holding verification.

This module is read-only: it does not place, amend, or cancel orders. It models
whether reward income can cover gas/ops, adverse selection, and opportunity cost.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RewardModelInput:
    capital_usd: float
    market_id: str
    yes_bid: float
    yes_ask: float
    no_bid: float
    no_ask: float
    spread_bps: float
    min_order_size: float
    max_reward_spread_bps: float
    expected_reward_per_day: float
    probability_of_fill: float
    adverse_selection_loss_estimate: float
    gas_cost_estimate: float
    quote_refresh_interval_sec: float
    active_hours_per_day: float
    holding_yield_apy: float = 0.0
    opportunity_cost_apy: float = 0.0
    expected_spread_capture_per_fill: float | None = None


@dataclass(frozen=True)
class RewardModelOutput:
    estimated_daily_reward: float
    estimated_daily_spread_income: float
    estimated_daily_holding_yield: float
    estimated_daily_gas: float
    estimated_expected_adverse_loss: float
    estimated_daily_opportunity_cost: float
    estimated_net_daily_ev: float
    annualized_return_estimate: float
    capital_efficiency: float
    breakeven_reward_required: float
    breakeven_fill_loss_allowed: float
    quotes_per_day: float
    eligible_by_min_order_size: bool
    eligible_by_spread: bool


def _clamp_probability(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def calculate_reward_economics(inp: RewardModelInput) -> RewardModelOutput:
    """Calculate daily reward-farming EV with separated economics buckets.

    Interpretations:
    - expected_reward_per_day: user's estimated reward allocation captured per day.
    - gas_cost_estimate: estimated gas/ops cost per quote refresh.
    - adverse_selection_loss_estimate: dollar loss if a quote is filled adversely.
    - probability_of_fill: probability of an adverse/filled event per day.
    """
    if inp.capital_usd <= 0:
        raise ValueError("capital_usd must be positive")
    if inp.quote_refresh_interval_sec <= 0:
        raise ValueError("quote_refresh_interval_sec must be positive")
    if inp.active_hours_per_day < 0:
        raise ValueError("active_hours_per_day cannot be negative")

    fill_probability = _clamp_probability(inp.probability_of_fill)
    quotes_per_day = inp.active_hours_per_day * 3600.0 / inp.quote_refresh_interval_sec

    estimated_daily_reward = max(0.0, inp.expected_reward_per_day)
    spread_capture_per_fill = (
        inp.expected_spread_capture_per_fill
        if inp.expected_spread_capture_per_fill is not None
        else inp.capital_usd * max(0.0, inp.spread_bps) / 10_000.0
    )
    estimated_daily_spread_income = fill_probability * max(0.0, spread_capture_per_fill)
    estimated_daily_holding_yield = inp.capital_usd * max(0.0, inp.holding_yield_apy) / 365.0
    estimated_daily_gas = quotes_per_day * max(0.0, inp.gas_cost_estimate)
    estimated_expected_adverse_loss = fill_probability * max(0.0, inp.adverse_selection_loss_estimate)
    estimated_daily_opportunity_cost = inp.capital_usd * max(0.0, inp.opportunity_cost_apy) / 365.0

    estimated_net_daily_ev = (
        estimated_daily_reward
        + estimated_daily_spread_income
        + estimated_daily_holding_yield
        - estimated_daily_gas
        - estimated_expected_adverse_loss
        - estimated_daily_opportunity_cost
    )
    annualized_return_estimate = estimated_net_daily_ev * 365.0 / inp.capital_usd
    capital_efficiency = estimated_net_daily_ev / inp.capital_usd
    breakeven_reward_required = max(
        0.0,
        estimated_daily_gas
        + estimated_expected_adverse_loss
        + estimated_daily_opportunity_cost
        - estimated_daily_spread_income
        - estimated_daily_holding_yield,
    )
    breakeven_fill_loss_allowed = (
        max(
            0.0,
            estimated_daily_reward
            + estimated_daily_spread_income
            + estimated_daily_holding_yield
            - estimated_daily_gas
            - estimated_daily_opportunity_cost,
        )
        / fill_probability
        if fill_probability > 0 else float("inf")
    )

    return RewardModelOutput(
        estimated_daily_reward=estimated_daily_reward,
        estimated_daily_spread_income=estimated_daily_spread_income,
        estimated_daily_holding_yield=estimated_daily_holding_yield,
        estimated_daily_gas=estimated_daily_gas,
        estimated_expected_adverse_loss=estimated_expected_adverse_loss,
        estimated_daily_opportunity_cost=estimated_daily_opportunity_cost,
        estimated_net_daily_ev=estimated_net_daily_ev,
        annualized_return_estimate=annualized_return_estimate,
        capital_efficiency=capital_efficiency,
        breakeven_reward_required=breakeven_reward_required,
        breakeven_fill_loss_allowed=breakeven_fill_loss_allowed,
        quotes_per_day=quotes_per_day,
        eligible_by_min_order_size=inp.capital_usd >= max(0.0, inp.min_order_size) * 2.0,
        eligible_by_spread=(inp.max_reward_spread_bps <= 0 or inp.spread_bps <= inp.max_reward_spread_bps),
    )


def model_from_dict(data: dict[str, Any]) -> dict[str, Any]:
    inp = RewardModelInput(**data)
    return asdict(calculate_reward_economics(inp))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--json", type=str, help="JSON object containing RewardModelInput fields")
    p.add_argument("--json-file", type=Path, help="Path to JSON object or list of objects")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if args.json:
        payload = json.loads(args.json)
    elif args.json_file:
        payload = json.loads(args.json_file.read_text())
    else:
        raise SystemExit("Provide --json or --json-file")

    if isinstance(payload, list):
        result = [model_from_dict(item) for item in payload]
    else:
        result = model_from_dict(payload)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
