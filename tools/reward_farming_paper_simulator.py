#!/usr/bin/env python3
"""Read-only reward farming paper simulator.

The simulator never places, amends, cancels, or submits orders. It estimates
hypothetical reward-farming economics under pro-rata competition scenarios.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.run_reward_research import collect_candidates

SCENARIOS = {
    "pessimistic": 0.0001,  # 0.01%
    "base": 0.0005,         # 0.05%
    "optimistic": 0.001,    # 0.10%
}
DEFAULT_CAPITAL_LEVELS = [50, 100, 250, 500, 1000, 5000]
FORMULA_WARNING = "Reward formula remains partially unverified; live reward farming remains NO-GO."


@dataclass(frozen=True)
class ReliabilityContext:
    error_rate_pct: float | None
    p95_latency_ms: float | None
    simulator_results_reliable: bool
    source: str


@dataclass(frozen=True)
class ScenarioResult:
    scenario: str
    share_fraction: float
    gross_reward_pool_usd_day: float
    pro_rata_reward_usd_day: float
    adverse_loss_usd_day: float
    worst_case_loss_usd: float
    gas_usd_day: float
    opportunity_cost_usd_day: float
    expected_net_ev_usd_day: float
    expected_monthly_ev_usd: float
    ev_per_dollar_locked: float
    annualized_return_estimate: float
    confidence: str
    small_account_viable: bool


@dataclass(frozen=True)
class MarketSimulation:
    market_id: str
    question: str
    capital_usd: float
    capital_required_usd: float
    capital_sufficient: bool
    eligible: bool
    rejected_reasons: list[str]
    min_size: float
    max_spread: float
    spread_bps: float
    touch_depth: float
    liquidity: float
    volume: Any
    rewards_daily_rate: float
    asset_address: list[str]
    probability_of_fill: float
    expected_adverse_move_pct: float
    quote_staleness_risk: str
    adverse_risk_confidence: str
    scenarios: dict[str, ScenarioResult]


def money(value: float) -> str:
    return f"${value:,.4f}"


def md_table(headers: list[str], rows: list[list[Any]]) -> str:
    out = "|" + "|".join(headers) + "|\n" + "|" + "|".join(["---"] * len(headers)) + "|\n"
    for row in rows:
        out += "|" + "|".join(str(item).replace("|", "/") for item in row) + "|\n"
    return out


def load_reliability_context(path: str | Path | None) -> ReliabilityContext:
    if not path:
        return ReliabilityContext(None, None, False, "missing")
    p = Path(path)
    if not p.exists():
        return ReliabilityContext(None, None, False, str(p))
    data = json.loads(p.read_text(encoding="utf-8"))
    gates = data.get("gates") or {}
    return ReliabilityContext(
        error_rate_pct=data.get("error_rate_pct"),
        p95_latency_ms=data.get("p95_latency_ms"),
        simulator_results_reliable=bool(gates.get("simulator_results_reliable")),
        source=str(p),
    )


def estimate_fill_probability(market: dict[str, Any], reliability: ReliabilityContext) -> tuple[float, str, str]:
    """Conservative paper fill/adverse-risk estimate from static book metadata."""
    spread_bps = float(market.get("spread_bps") or 0)
    touch_depth = float(market.get("touch_depth") or 0)
    error_rate = reliability.error_rate_pct if reliability.error_rate_pct is not None else 46.5

    probability = 0.01
    if spread_bps <= 20:
        probability += 0.015
    elif spread_bps >= 100:
        probability += 0.005
    if touch_depth < 100:
        probability += 0.02
    elif touch_depth > 1000:
        probability += 0.005
    if error_rate > 20:
        probability += 0.03
    elif error_rate > 5:
        probability += 0.01
    probability = min(0.25, probability)

    if reliability.simulator_results_reliable:
        staleness = "medium" if (reliability.p95_latency_ms or 0) > 1000 else "low"
        confidence = "medium"
    else:
        staleness = "high"
        confidence = "low"
    return probability, staleness, confidence


def estimate_gas_usd_per_day(duration_hours: float, interval_seconds: float, polygon_gas_per_action_usd: float = 0.01) -> float:
    """Estimate Polygon/order ops costs for hypothetical refresh/cancel/fill actions."""
    refreshes = max(1.0, duration_hours * 3600.0 / max(1.0, interval_seconds))
    # Order placement + cancel/refresh. CLOB orders are off-chain, but include conservative settlement/ops proxy.
    return refreshes * polygon_gas_per_action_usd * 2.0 / max(1.0, duration_hours / 24.0)


def normalize_reward_pool(market: dict[str, Any]) -> float:
    return max(0.0, float(market.get("reward_daily_rate_sum") or market.get("rewards_daily_rate") or 0.0))


def evaluate_market(
    market: dict[str, Any],
    capital_usd: float,
    duration_hours: float,
    interval_seconds: float,
    reliability: ReliabilityContext,
    scenario_shares: dict[str, float] | None = None,
) -> MarketSimulation:
    scenario_shares = scenario_shares or SCENARIOS
    reward_min_size = float(market.get("reward_min_size") or market.get("min_size") or 0.0)
    minimum_order_size = float(market.get("minimum_order_size") or 0.0)
    min_size = max(reward_min_size, minimum_order_size)
    max_spread = float(market.get("reward_max_spread_raw") or market.get("max_spread") or 0.0)
    max_spread_bps = float(market.get("reward_max_spread_bps_model") or (max_spread * 100 if max_spread else 0.0))
    spread_bps = float(market.get("spread_bps") or 0.0)
    touch_depth = float(market.get("touch_depth") or 0.0)
    liquidity = float(market.get("liquidity") or touch_depth or 0.0)
    reward_pool = normalize_reward_pool(market)
    capital_required = max(2.0 * min_size, float(market.get("estimated_capital_required") or 0.0), 2.0 * reward_min_size)

    reasons: list[str] = []
    if reward_pool <= 0:
        reasons.append("reward metadata incomplete or zero reward pool")
    if capital_usd < capital_required:
        reasons.append(f"capital ${capital_usd:.2f} below required ${capital_required:.2f}")
    if max_spread_bps > 0 and spread_bps > max_spread_bps:
        reasons.append(f"spread {spread_bps:.0f} bps exceeds max reward spread {max_spread_bps:.0f} bps")
    if touch_depth < max(10.0, min_size):
        reasons.append("touch depth too thin")
    if not reliability.simulator_results_reliable:
        reasons.append("data reliability too poor or unverified")

    probability_fill, staleness, risk_confidence = estimate_fill_probability(market, reliability)
    adverse_move_pct = 0.015 if risk_confidence == "low" else 0.01
    adverse_loss = probability_fill * capital_usd * adverse_move_pct
    worst_case_loss = capital_usd * max(0.03, adverse_move_pct * 3.0)
    gas_day = estimate_gas_usd_per_day(duration_hours, interval_seconds)
    opportunity_cost_day = capital_usd * 0.05 / 365.0

    scenarios: dict[str, ScenarioResult] = {}
    for name, share in scenario_shares.items():
        pro_rata = reward_pool * share
        net = pro_rata - adverse_loss - gas_day - opportunity_cost_day
        annualized = net * 365.0 / capital_usd if capital_usd > 0 else 0.0
        confidence = "low" if risk_confidence == "low" or not reliability.simulator_results_reliable else "medium"
        if FORMULA_WARNING:
            confidence = "low" if name != "pessimistic" else "low"
        scenarios[name] = ScenarioResult(
            scenario=name,
            share_fraction=share,
            gross_reward_pool_usd_day=reward_pool,
            pro_rata_reward_usd_day=pro_rata,
            adverse_loss_usd_day=adverse_loss,
            worst_case_loss_usd=worst_case_loss,
            gas_usd_day=gas_day,
            opportunity_cost_usd_day=opportunity_cost_day,
            expected_net_ev_usd_day=net,
            expected_monthly_ev_usd=net * 30.0,
            ev_per_dollar_locked=net / capital_usd if capital_usd else 0.0,
            annualized_return_estimate=annualized,
            confidence=confidence,
            small_account_viable=(capital_usd <= 250 and capital_usd >= capital_required and net > 0 and name == "pessimistic"),
        )

    # Rejection if adverse/gas dominate pessimistic reward.
    pess = scenarios["pessimistic"]
    if pess.pro_rata_reward_usd_day <= (pess.adverse_loss_usd_day + pess.gas_usd_day):
        reasons.append("adverse/gas cost dominates pessimistic reward")
    if FORMULA_WARNING:
        reasons.append("docs/formula unknown makes result speculative")

    return MarketSimulation(
        market_id=str(market.get("market_id") or market.get("condition_id") or "unknown"),
        question=str(market.get("question") or "unknown"),
        capital_usd=capital_usd,
        capital_required_usd=capital_required,
        capital_sufficient=capital_usd >= capital_required,
        eligible=not reasons,
        rejected_reasons=reasons,
        min_size=min_size,
        max_spread=max_spread,
        spread_bps=spread_bps,
        touch_depth=touch_depth,
        liquidity=liquidity,
        volume=market.get("volume", "not available"),
        rewards_daily_rate=reward_pool,
        asset_address=list(market.get("reward_assets") or market.get("asset_address") or []),
        probability_of_fill=probability_fill,
        expected_adverse_move_pct=adverse_move_pct,
        quote_staleness_risk=staleness,
        adverse_risk_confidence=risk_confidence,
        scenarios=scenarios,
    )


def rank_markets(simulations: list[MarketSimulation], scenario: str) -> list[MarketSimulation]:
    return sorted(simulations, key=lambda sim: sim.scenarios[scenario].expected_net_ev_usd_day, reverse=True)


def load_candidates(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _sim_to_dict(sim: MarketSimulation) -> dict[str, Any]:
    data = asdict(sim)
    data["scenarios"] = {k: asdict(v) for k, v in sim.scenarios.items()}
    return data


def write_capital_sweep(output_dir: Path, sweep: dict[str, list[MarketSimulation]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    payload: dict[str, Any] = {}
    for capital, sims in sweep.items():
        payload[capital] = [_sim_to_dict(sim) for sim in sims]
        for scenario in SCENARIOS:
            best = rank_markets(sims, scenario)[0] if sims else None
            if best is None:
                continue
            s = best.scenarios[scenario]
            rows.append([
                capital,
                scenario,
                best.question[:52],
                money(s.gross_reward_pool_usd_day),
                money(s.pro_rata_reward_usd_day),
                money(s.adverse_loss_usd_day),
                money(s.gas_usd_day),
                money(s.expected_net_ev_usd_day),
                f"{s.ev_per_dollar_locked:.6f}",
                f"{s.annualized_return_estimate*100:.2f}%",
                s.confidence,
                "yes" if best.capital_sufficient else "no",
                "yes" if s.small_account_viable else "no",
            ])
    (output_dir / "capital_sweep.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md = "# Reward Farming Paper Simulator — Capital Sweep\n\n"
    md += FORMULA_WARNING + "\n\n"
    md += md_table([
        "Capital", "Scenario", "Best market", "Gross reward pool/day", "Pro-rata reward/day", "Adverse loss/day", "Gas/day", "Net EV/day", "EV/$", "Annualized", "Confidence", "Meets min size", "Small account viable",
    ], rows)
    (output_dir / "capital_sweep.md").write_text(md, encoding="utf-8")


def write_market_ranking(output_dir: Path, sims: list[MarketSimulation]) -> None:
    payload = {"rankings": {}, "rejected": []}
    md = "# Reward Farming Paper Simulator — Market Ranking\n\n"
    md += "Markets are ranked by realistic pro-rata EV, not raw reward rate.\n\n"
    for scenario in SCENARIOS:
        ranked = rank_markets(sims, scenario)
        payload["rankings"][scenario] = [_sim_to_dict(sim) for sim in ranked[:10]]
        rows = []
        for sim in ranked[:10]:
            s = sim.scenarios[scenario]
            rows.append([sim.question[:58], money(s.pro_rata_reward_usd_day), money(s.adverse_loss_usd_day), money(s.gas_usd_day), money(s.opportunity_cost_usd_day), money(s.expected_net_ev_usd_day), s.confidence, "; ".join(sim.rejected_reasons[:2]) or "none"])
        md += f"## Top 10 by {scenario} EV\n\n"
        md += md_table(["Market", "Pro-rata reward", "Adverse loss", "Gas", "Opportunity", "Reward score / EV", "Confidence", "Reject reason"], rows) + "\n"
    rejected = [sim for sim in sims if sim.rejected_reasons]
    payload["rejected"] = [{"market_id": sim.market_id, "question": sim.question, "reasons": sim.rejected_reasons} for sim in rejected]
    md += "## Rejected markets\n\n"
    md += md_table(["Market", "Reasons"], [[sim.question[:70], "; ".join(sim.rejected_reasons)] for sim in rejected[:50]])
    (output_dir / "market_ranking.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (output_dir / "market_ranking.md").write_text(md, encoding="utf-8")


def write_go_no_go(output_dir: Path, reliability: ReliabilityContext, sims: list[MarketSimulation]) -> str:
    best_pess = rank_markets(sims, "pessimistic")[0] if sims else None
    formula_verified = False
    reward_candidates_available = bool(sims)
    data_ok = reliability.simulator_results_reliable
    pessimistic_positive = bool(best_pess and best_pess.scenarios["pessimistic"].expected_net_ev_usd_day > 0)
    adverse_ok = bool(best_pess and best_pess.scenarios["pessimistic"].adverse_loss_usd_day < best_pess.scenarios["pessimistic"].pro_rata_reward_usd_day)
    gas_ok = bool(best_pess and best_pess.scenarios["pessimistic"].gas_usd_day < best_pess.scenarios["pessimistic"].pro_rata_reward_usd_day)
    small_cap_ok = any(sim.scenarios["pessimistic"].small_account_viable for sim in sims)
    confidence_ok = any(sim.scenarios["pessimistic"].confidence in {"medium", "high"} for sim in sims)

    if not formula_verified:
        decision = "VERIFY FORMULA FIRST"
    elif data_ok and reward_candidates_available and pessimistic_positive and adverse_ok and gas_ok and small_cap_ok and confidence_ok:
        decision = "CONTINUE REWARD PAPER SIMULATION"
    else:
        decision = "PIVOT TO CROSS-VENUE PRICING RESEARCH"

    gates = [
        ["official reward formula verified", "PASS" if formula_verified else "FAIL"],
        ["data-path error rate acceptable", "PASS" if data_ok else "FAIL"],
        ["reward candidates available", "PASS" if reward_candidates_available else "FAIL"],
        ["pessimistic scenario positive EV", "PASS" if pessimistic_positive else "FAIL"],
        ["adverse fill risk does not dominate reward", "PASS" if adverse_ok else "FAIL"],
        ["gas does not dominate reward", "PASS" if gas_ok else "FAIL"],
        ["small-account capital sufficient", "PASS" if small_cap_ok else "FAIL"],
        ["simulator confidence medium/high", "PASS" if confidence_ok else "FAIL"],
        ["no live-order assumptions untested", "FAIL"],
    ]
    md = f"# Reward Farming Paper Go/No-Go\n\n## Final decision\n\n**{decision}**\n\n"
    md += "Live reward farming remains **NO-GO**. Passive market-making remains paused.\n\n"
    md += "## Hard gates\n\n" + md_table(["Gate", "Status"], gates) + "\n"
    if best_pess:
        s = best_pess.scenarios["pessimistic"]
        md += "## Best pessimistic market\n\n"
        md += md_table(["Field", "Value"], [["Market", best_pess.question], ["Pro-rata reward/day", money(s.pro_rata_reward_usd_day)], ["Adverse loss/day", money(s.adverse_loss_usd_day)], ["Gas/day", money(s.gas_usd_day)], ["Net EV/day", money(s.expected_net_ev_usd_day)], ["Confidence", s.confidence]])
    md += "\n## Formula status\n\n" + FORMULA_WARNING + "\n\n"
    md += "## Exact next action\n\nVerify the official reward scoring/payout formula before any further live-deployment discussion. If docs remain inaccessible, keep reward farming in paper-only mode or pivot to cross-venue pricing research.\n"
    (output_dir / "reward_farming_paper_go_no_go.md").write_text(md, encoding="utf-8")
    return decision


def write_formula_verification(output_dir: Path, source_notes: list[str]) -> None:
    md = "# Reward Formula Verification Retry\n\n"
    md += FORMULA_WARNING + "\n\n"
    md += "## Sources attempted\n\n"
    for note in source_notes:
        md += f"- {note}\n"
    md += "\n## Current verified status\n\n"
    md += md_table(["Question", "Status"], [
        ["Is rewards_daily_rate a total pool or per-user payout?", "Unverified; simulator treats it as total pool and applies pro-rata shares."],
        ["Is payout pro-rata?", "Unverified; modeled with pessimistic/base/optimistic pro-rata scenarios."],
        ["Both-side quoting required?", "Unverified."],
        ["Actual fills required?", "Unverified; simulator assumes resting orders and does not rely on fills."],
        ["Resting orders only?", "Unverified; order-scoring endpoint exists but not called with live orders."],
        ["Minimum order size?", "Observed in CLOB fields: minimum_order_size and rewards.min_size."],
        ["Max spread?", "Observed in CLOB field rewards.max_spread; exact unit/formula unverified."],
        ["Payout timing?", "Unverified."],
        ["Payout asset?", "Observed in CLOB rewards.rates.asset_address."],
        ["Rewards active now?", "Yes, live CLOB market payloads include non-empty rewards.rates."],
    ])
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "formula_verification.md").write_text(md, encoding="utf-8")


async def maybe_fresh_candidates(use_fresh: bool, candidate_path: Path) -> list[dict[str, Any]]:
    if use_fresh:
        candidates = await collect_candidates()
        candidate_path.write_text(json.dumps(candidates, indent=2), encoding="utf-8")
        return candidates
    return load_candidates(candidate_path)


async def run_simulator(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    candidates = await maybe_fresh_candidates(args.from_current_snapshot, Path("reports/reward_candidate_markets.json"))
    if args.markets and args.markets > 0:
        candidates = candidates[: args.markets]
    reliability = load_reliability_context(args.reliability_report)

    capital_levels = [args.capital_usd] if args.capital_usd else DEFAULT_CAPITAL_LEVELS
    sweep: dict[str, list[MarketSimulation]] = {}
    all_sims_for_ranking: list[MarketSimulation] = []
    for cap in capital_levels:
        sims = [evaluate_market(c, cap, args.duration_hours, args.interval_seconds, reliability) for c in candidates]
        sweep[f"${cap:,.0f}"] = sims
        if cap == capital_levels[0]:
            all_sims_for_ranking = sims

    write_capital_sweep(output_dir, sweep)
    write_market_ranking(output_dir, all_sims_for_ranking)
    source_notes = [
        "docs.polymarket.com and Polymarket rewards pages should be retried externally if this host cannot reach them.",
        "CLOB API response fields used: rewards.rates, rewards_daily_rate, rewards.min_size, rewards.max_spread, minimum_order_size.",
        "Official SDK endpoint surface includes order-scoring endpoints, but no live orders were submitted for scoring.",
    ]
    write_formula_verification(output_dir, source_notes)
    decision = write_go_no_go(output_dir, reliability, all_sims_for_ranking)
    summary = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "decision": decision,
        "candidate_count": len(candidates),
        "capital_levels": capital_levels,
        "reliability": asdict(reliability),
        "formula_warning": FORMULA_WARNING,
    }
    (output_dir / "simulation_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--capital-usd", type=float, default=0.0, help="Single capital level; omit/0 for default sweep")
    p.add_argument("--duration-hours", type=float, default=24.0)
    p.add_argument("--interval-seconds", type=float, default=300.0)
    p.add_argument("--markets", type=int, default=25)
    p.add_argument("--from-current-snapshot", action="store_true")
    p.add_argument("--reliability-report", default="reports/data_path_reliability_report.json")
    p.add_argument("--output-dir", default="reports/reward_simulator/")
    return p.parse_args()


def main() -> None:
    summary = asyncio.run(run_simulator(parse_args()))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
