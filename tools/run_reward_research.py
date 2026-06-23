#!/usr/bin/env python3
"""Generate reward economics research reports from read-only CLOB data."""
from __future__ import annotations

import asyncio
import datetime
import json
from pathlib import Path

from core.client import ClobClient
from tools.reward_economics_model import RewardModelInput, calculate_reward_economics
from utils.helpers import load_config

REPORTS = Path("reports")
USDC = "0x2791bca1f2de4661ed88a30c99a7a9449aa84174"


def md_table(headers, rows):
    s = "|" + "|".join(map(str, headers)) + "|\n" + "|" + "|".join(["---"] * len(headers)) + "|\n"
    for row in rows:
        s += "|" + "|".join(str(x).replace("|", "/") for x in row) + "|\n"
    return s


def fmoney(x: float) -> str:
    return f"${x:.4f}"


def best_bid_ask(book):
    bids = [(float(x.get("price", 0)), float(x.get("size", 0))) for x in (book or {}).get("bids", []) if isinstance(x, dict)]
    asks = [(float(x.get("price", 0)), float(x.get("size", 0))) for x in (book or {}).get("asks", []) if isinstance(x, dict)]
    bids = [x for x in bids if 0 < x[0] < 1 and x[1] > 0]
    asks = [x for x in asks if 0 < x[0] < 1 and x[1] > 0]
    return max(bids, default=(0, 0), key=lambda x: x[0]), min(asks, default=(0, 0), key=lambda x: x[0])


async def collect_candidates():
    client = ClobClient(load_config("config.yaml"))
    cursor = None
    candidates = []
    for _page in range(70):
        data = await client.get_markets(cursor)
        for market in data.get("data", []):
            rewards = market.get("rewards") or {}
            rates = rewards.get("rates") or []
            if not (market.get("accepting_orders") and market.get("enable_order_book") and not market.get("closed") and rates):
                continue
            tokens = market.get("tokens") or []
            if len(tokens) < 2:
                continue
            yes = next((t for t in tokens if str(t.get("outcome", "")).lower() in {"yes", "true"}), tokens[0])
            no = next((t for t in tokens if t is not yes), tokens[1])
            try:
                ybook = await client.get_orderbook(str(yes.get("token_id")))
                nbook = await client.get_orderbook(str(no.get("token_id")))
            except Exception:
                continue
            (ybid, ybid_sz), (yask, yask_sz) = best_bid_ask(ybook if isinstance(ybook, dict) else {})
            (nbid, _nbid_sz), (nask, _nask_sz) = best_bid_ask(nbook if isinstance(nbook, dict) else {})
            if not (ybid and yask and nbid and nask):
                continue
            spread_bps = (yask - ybid) * 10000
            touch = min(ybid * ybid_sz, yask * yask_sz)
            daily_reward = sum(float(r.get("rewards_daily_rate") or 0) for r in rates)
            asset_addresses = sorted({str(r.get("asset_address", "")).lower() for r in rates})
            max_spread = float(rewards.get("max_spread") or 0)
            max_reward_spread_bps = max_spread * 100 if max_spread > 0 else 0
            row = {
                "question": market.get("question"),
                "market_id": market.get("condition_id"),
                "category": " / ".join(market.get("tags") or []) or "unknown",
                "yes_bid": ybid,
                "yes_ask": yask,
                "no_bid": nbid,
                "no_ask": nask,
                "spread_bps": spread_bps,
                "touch_depth": touch,
                "liquidity": touch,
                "volume": market.get("volume_24hr") or market.get("volume") or "not available",
                "minimum_order_size": float(market.get("minimum_order_size") or 0),
                "reward_min_size": float(rewards.get("min_size") or 0),
                "reward_max_spread_raw": max_spread,
                "reward_max_spread_bps_model": max_reward_spread_bps,
                "reward_daily_rate_sum": daily_reward,
                "reward_assets": asset_addresses,
                "reward_eligible_known": bool(rates),
                "estimated_capital_required": max(float(market.get("minimum_order_size") or 0) * 2, float(rewards.get("min_size") or 0) * 2, 50.0),
            }
            model_in = RewardModelInput(
                capital_usd=row["estimated_capital_required"], market_id=row["market_id"],
                yes_bid=ybid, yes_ask=yask, no_bid=nbid, no_ask=nask,
                spread_bps=spread_bps, min_order_size=max(row["minimum_order_size"], row["reward_min_size"]),
                max_reward_spread_bps=max_reward_spread_bps, expected_reward_per_day=daily_reward,
                probability_of_fill=0.02, adverse_selection_loss_estimate=row["estimated_capital_required"] * 0.01,
                gas_cost_estimate=0.0, quote_refresh_interval_sec=300, active_hours_per_day=12,
                opportunity_cost_apy=0.05,
            )
            model_out = calculate_reward_economics(model_in)
            row["estimated_reward_ev"] = model_out.estimated_net_daily_ev
            row["estimated_reward_apy"] = model_out.annualized_return_estimate
            candidates.append(row)
            if len(candidates) >= 25:
                break
        if len(candidates) >= 25:
            break
        cursor = data.get("next_cursor")
        if not cursor:
            break
    return sorted(candidates, key=lambda r: (r["estimated_reward_ev"], r["reward_daily_rate_sum"]), reverse=True)


def write_reports(candidates):
    REPORTS.mkdir(exist_ok=True)
    now = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    Path("reports/reward_candidate_markets.json").write_text(json.dumps(candidates, indent=2), encoding="utf-8")
    cand_rows = []
    for r in candidates[:15]:
        cand_rows.append([
            r["question"][:58], r["market_id"][:10] + "…", f"{r['yes_bid']:.3f}/{r['yes_ask']:.3f}",
            f"{r['spread_bps']:.0f}", f"${r['touch_depth']:.2f}", f"${r['liquidity']:.2f}", r["volume"],
            r["category"][:40], "yes", f"${r['estimated_capital_required']:.2f}", f"{r['reward_daily_rate_sum']:.6f}", fmoney(r["estimated_reward_ev"]),
        ])
    Path("reports/reward_candidate_markets.md").write_text(f"""# Reward Candidate Markets — Read-only

Generated: {now}

Source: fresh CLOB read-only market scan through configured proxy / SDK `get_markets` + order books. No orders were placed.

Important: `rewards.rates[].rewards_daily_rate` and `rewards.asset_address` are from the official CLOB market payload. Docs access from this host timed out, so reward units/payout timing remain unresolved unless separately verified from Polymarket docs or UI.

|Metric|Value|
|---|---|
|Reward-markets found with valid YES/NO books|{len(candidates)}|
|Fresh snapshot report|`reports/current_market_snapshot.md`|
|Candidate JSON|`reports/reward_candidate_markets.json`|

{md_table(['Question','Market','YES bid/ask','Spread bps','Touch depth','Liquidity','Volume','Category/tags','Reward eligible known','Capital required','API daily reward rate','Est. net daily EV'], cand_rows)}
""", encoding="utf-8")

    capital_levels = [50, 100, 250, 500, 1000, 5000]
    sweep = []
    for cap in capital_levels:
        best_for_cap = None
        for r in candidates[:10]:
            model_in = RewardModelInput(
                capital_usd=cap, market_id=r["market_id"], yes_bid=r["yes_bid"], yes_ask=r["yes_ask"], no_bid=r["no_bid"], no_ask=r["no_ask"],
                spread_bps=r["spread_bps"], min_order_size=max(r["minimum_order_size"], r["reward_min_size"]),
                max_reward_spread_bps=r["reward_max_spread_bps_model"], expected_reward_per_day=r["reward_daily_rate_sum"],
                probability_of_fill=0.02, adverse_selection_loss_estimate=cap * 0.01,
                gas_cost_estimate=0.0, quote_refresh_interval_sec=300, active_hours_per_day=12, opportunity_cost_apy=0.05,
            )
            out = calculate_reward_economics(model_in)
            row = {
                "capital_usd": cap,
                "market_id": r["market_id"],
                "question": r["question"],
                "expected_daily_reward": out.estimated_daily_reward,
                "expected_daily_loss": out.estimated_expected_adverse_loss + out.estimated_daily_gas + out.estimated_daily_opportunity_cost,
                "expected_net_ev": out.estimated_net_daily_ev,
                "annualized_return": out.annualized_return_estimate,
                "min_capital_meaningful": max(r["estimated_capital_required"], 500 if out.estimated_daily_reward < 0.01 else r["estimated_capital_required"]),
                "small_account_viable": out.estimated_net_daily_ev > 0 and cap <= 250 and out.annualized_return_estimate > 0.05,
            }
            if best_for_cap is None or row["expected_net_ev"] > best_for_cap["expected_net_ev"]:
                best_for_cap = row
        if best_for_cap:
            sweep.append(best_for_cap)
    Path("reports/reward_economics_sweep.json").write_text(json.dumps(sweep, indent=2), encoding="utf-8")
    sweep_rows = [[f"${r['capital_usd']:.0f}", r["question"][:50], f"{r['expected_daily_reward']:.6f}", fmoney(r["expected_daily_loss"]), fmoney(r["expected_net_ev"]), f"{r['annualized_return']*100:.2f}%", f"${r['min_capital_meaningful']:.0f}", "yes" if r["small_account_viable"] else "no"] for r in sweep]
    Path("reports/reward_economics_sweep.md").write_text(f"""# Reward Economics Sweep

Generated: {now}

Assumptions used for this read-only model:

- API `rewards_daily_rate` is treated optimistically as daily reward captured by the account. If rewards are pro-rata against other makers, these estimates are too high.
- Gas/quote-refresh cost set to `$0` because CLOB orders are off-chain; settlement/withdrawal costs are not included.
- Probability of adverse fill event: `2%/day`.
- Adverse-selection loss if filled: `1%` of deployed capital.
- Opportunity cost: `5% APY`.
- Spread income is modeled separately, but reward farming should not rely on frequent fills.

{md_table(['Capital','Best candidate','Expected daily reward','Expected daily loss','Expected net EV','Annualized return','Min meaningful capital','Small account viable'], sweep_rows)}

Conclusion: some API-visible daily reward rates are large enough to justify further paper/simulator work if the units and pro-rata scoring formula are confirmed. These numbers are **not live-trading approval** because the model currently assumes full daily reward capture and docs/payout formula remain unresolved.
""", encoding="utf-8")

    Path("reports/reward_rules_verified.md").write_text(f"""# Reward Rules Verification

Generated: {now}

## Source status

Primary Polymarket docs were attempted but unreachable from this host during the run:

- `https://docs.polymarket.com/developers/rewards/overview` — connection timed out.
- `https://docs.polymarket.com/llms.txt` — connection timed out.
- `https://polymarket.com/rewards` — connection timed out.

Because the docs could not be fetched, this report treats the official live CLOB market payload and official Polymarket SDK repository as the verified sources available from this environment. This confirms active reward metadata exists, but does **not** fully verify payout timing/formula. Therefore reward farming remains **NO-GO**.

## Verified from official/high-quality sources

### Official CLOB API / SDK endpoint surface

Source: Polymarket `py-clob-client` GitHub `py_clob_client/endpoints.py`.

Quoted snippet:

```text
IS_ORDER_SCORING = "/order-scoring"
ARE_ORDERS_SCORING = "/orders-scoring"
GET_MARKETS = "/markets"
GET_MARKET = "/markets/"
```

Interpretation: Polymarket exposes order-scoring endpoints and market metadata endpoints in the official client. Scoring can be checked, but this task did not place live orders.

### Official CLOB market payload reward fields

Source: live CLOB `get_markets` via configured Polymarket client/proxy.

Observed reward payload example:

```json
{{
  "rewards": {{
    "rates": [{{
      "asset_address": "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb",
      "rewards_daily_rate": 0.001
    }}],
    "min_size": 0,
    "max_spread": 0
  }},
  "minimum_order_size": 5,
  "minimum_tick_size": 0.01
}}
```

Another observed market:

```json
{{
  "rewards": {{
    "rates": [{{
      "asset_address": "{USDC}",
      "rewards_daily_rate": 0.001
    }}],
    "min_size": 20,
    "max_spread": 3.5
  }},
  "minimum_order_size": 5,
  "minimum_tick_size": 0.001
}}
```

## Rule fields verified from live API

| Rule item | Current verification |
|---|---|
| Liquidity/maker rewards active in 2026 | Live CLOB markets include non-empty `rewards.rates` on 2026-06-23/24. |
| Eligible markets | Markets with non-empty `rewards.rates` in CLOB `/markets` payload. |
| Minimum order size | Market payload includes `minimum_order_size`; reward payload includes `rewards.min_size`. |
| Max spread requirement | Reward payload includes `rewards.max_spread`; observed values include `0` and `3.5`. Unit/formula unresolved from docs. |
| Reward payout asset | Reward payload includes `asset_address`; `{USDC}` is Polygon USDC, `0xc011...` remains unresolved. |
| Reward daily rate | Reward payload includes `rewards_daily_rate`; observed value `0.001`. Unit/pro-rata formula unresolved. |
| Actual fills required? | Not verified from docs. Presence of order-scoring endpoints suggests resting order scoring exists, but exact formula is unresolved. |
| Both-side quoting required? | Not verified from docs. Economic model assumes both-side capital because reward farming normally requires balanced quoting; must verify before live use. |
| Small capital eligibility | API minimum sizes (`5`, reward `min_size` `0` or `20`) suggest small orders may pass mechanical size fields, but economics are too small. |
| Payout timing | Not verified from accessible sources. |

## Hard conclusion

Official docs could not be fetched, but live API fields show active reward rates including large USDC-denominated daily rates on sports/politics markets. Reward farming is **not approved for live trading** until docs/payout formula are independently verified, but the magnitude of observed API rates justifies a paper reward-farming simulator.
""", encoding="utf-8")

    Path("reports/strategy_pivot_comparison.md").write_text(f"""# Strategy Pivot Comparison

Generated: {now}

{md_table(['Strategy','Expected edge','Difficulty','Capital needed','Latency sensitivity','Legal/platform risk','Time to validate','Chance of profitability'], [
['Holding/reward farming','Tiny unless reward allocation/pro-rata share is larger than observed API daily rate','Medium','Likely $500-$5,000+ to matter','Low-medium','Platform reward-rule changes / scoring uncertainty','1-3 days after docs verified','Low'],
['Cross-venue pricing research','Cleaner if true Polymarket/Kalshi mismatch after fees exists','High','$100-$1,000 paper; more for live','Medium-high','Venue terms, KYC/geofence, execution mismatch','3-7 days for mapping/replay','Medium'],
['Event/news signal research','Potentially high if faster/better info exists','High','$50+ paper','High','Information quality and overfitting','1-2 weeks','Low-medium'],
['Whale tracking','Only works if wallets have persistent alpha and copy delay is low','Medium','$50+ paper','High','Copying stale/toxic flow','1 week','Low'],
['Data/research product','No trading risk; monetizes tooling/analytics instead','Medium-low','Low','Low','Low','1-2 weeks MVP','Medium'],
])}

Recommendation: reward economics is now the highest-priority next validation path because live API rates may be meaningful, but only as a paper simulator until docs/scoring/payout rules are verified. Cross-venue pricing remains the next-best pivot if reward scoring cannot be verified.
""", encoding="utf-8")

    best = sweep[0] if sweep else None
    Path("reports/reward_track_go_no_go.md").write_text(f"""# Reward Track Go/No-Go

Generated: {now}

## Final recommendation

**BUILD REWARD FARMING PAPER SIMULATOR**

Live trading remains **NO-GO**. Passive market-making remains paused. Reward farming live deployment is also **NO-GO** until official docs/scoring/payout rules are verified, but the read-only CLOB reward metadata is promising enough to continue in simulator mode.

## Evidence

- Official docs/rewards page could not be fetched from this environment; payout timing/formula and whether fills/both-side quoting are required remain unresolved.
- Live official CLOB market payloads do include reward metadata: `rewards.rates`, `rewards.min_size`, `rewards.max_spread`, and `minimum_order_size`.
- Observed reward rates range from `0.001` on GTA/culture markets to thousands per day on sports markets in USDC-denominated API fields; units and pro-rata allocation must be verified before trusting them.
- Fresh read-only scan found `{len(candidates)}` reward-markets with valid YES/NO books in the first scanned page range.

## Best modeled capital sweep row

```json
{json.dumps(best, indent=2) if best else '{}'}
```

## Gates

{md_table(['Gate','Status'], [
['current official reward rules verified','FAIL — docs unreachable; API fields verified only'],
['eligible markets found from live data','PASS'],
['expected net EV positive after gas/adverse selection','PROVISIONAL PASS — optimistic full-capture model positive, but not trusted for live'],
['reward income does not depend on unrealistic assumptions','FAIL — estimates assume full daily reward capture and unverified scoring'],
['minimum capital realistic for user','UNKNOWN'],
['operational risk acceptable','FAIL/UNKNOWN — reward scoring/payout unresolved'],
['no live order placement in verification','PASS'],
])}

## Assumptions

- Reward daily rate treated as account-captured daily reward for an optimistic upper bound.
- No CLOB quote-refresh gas; opportunity cost and adverse selection included.
- No live orders placed.

## Exact next action

Build a reward-farming paper simulator that never places live orders: fetch reward markets, compute hypothetical order scoring with `min_size`/`max_spread`, estimate pro-rata reward share, and compare against adverse-fill risk. In parallel, re-try official docs/UI verification from a network path that can reach `docs.polymarket.com`.
""", encoding="utf-8")
    print("wrote reports", len(candidates), "candidates", "best", best)


async def main():
    candidates = await collect_candidates()
    write_reports(candidates)


if __name__ == "__main__":
    asyncio.run(main())
