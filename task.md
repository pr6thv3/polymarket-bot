# Task Status — Polymarket Bot Phase 3C Clean Targeted Validation

Updated: 2026-06-23T18:50Z

## Mission constraints

- Repo: `C:\Users\Preethve\polymarket-bot`
- Live trading remains **NO-GO**.
- `execution.dry_run: true` verified.
- `execution.post_only_default: true` verified.
- No live orders, no real funds, no deposits.
- Phase 3C diagnostics used only the clean folder, not `data/backtest/`.

## Step 1 — stopped old processes

Stopped old validation processes found before this run:

- PID `96`: old shell wrapper for `main.py`
- PID `116`: old `C:\Users\Preethve\polymarket-bot\.venv\Scripts\python.exe main.py`
- PID `169`: old shell wrapper for `tools/collect_backtest_data.py --duration-minutes 1440`
- PID `189`: old `tools/collect_backtest_data.py --duration-minutes 1440`

After stopping, `ps -efW | grep ...` showed no remaining `polymarket-bot` validation Python processes.

## Step 2 — clean run folder

Clean dataset folder:

`data/backtest_runs/phase3c_targeted_20260623_2310`

All new Phase 3C JSONL snapshots were written there. The old shared `data/backtest/` folder was not used for Phase 3C diagnostics.

## Step 3 — fresh live read-only market snapshot

Command:

```bash
PYTHONPATH=. .venv/Scripts/python.exe tools/current_market_snapshot.py --max-pages 70 --max-markets 40
```

Output:

```text
Wrote reports/current_market_snapshot.md with 35 valid books; 4 passed shallow gate
```

Top 5 candidates:

|Rank|Market|Question|Category|Bid/Ask|Spread bps|Touch depth|
|---:|---|---|---|---|---:|---:|
|1|0x50ddb9cd...|New Playboi Carti Album before GTA VI?|politics|0.540/0.570|300|$26.92|
|2|0x32b09f63...|Will Jesus Christ return before GTA VI?|politics|0.490/0.500|100|$117778.34|
|3|0x84f8b703...|Trump out as President before GTA VI?|politics|0.490/0.500|100|$230.78|
|4|0x7b49b9ba...|Will China invades Taiwan before GTA VI?|geopolitics|0.500/0.510|100|$1669.20|
|5|0xbb57ccf5...|Will bitcoin hit $1m before GTA VI?|crypto|0.495/0.496|10|$4900.99|

## Step 4 — clean targeted collection

Command:

```bash
PYTHONPATH=. .venv/Scripts/python.exe tools/collect_backtest_data.py --from-current-snapshot --markets 4 --duration-minutes 60 --interval-seconds 10 --output-dir data/backtest_runs/phase3c_targeted_20260623_2310
```

Collection completed successfully.

- Total iterations: `346`
- Error count: `161`
- Circuit-breaker log lines: `122`
- Average request latency: `1.608s`

Selected markets:

|Market|Question|Category|Snapshots|
|---|---|---|---:|
|0x50ddb9cd...|New Playboi Carti Album before GTA VI?|politics|305|
|0x32b09f63...|Will Jesus Christ return before GTA VI?|politics|304|
|0x84f8b703...|Trump out as President before GTA VI?|politics|307|
|0x7b49b9ba...|Will China invades Taiwan before GTA VI?|geopolitics|307|

All markets exceeded the `250` snapshot completeness threshold.

## Step 5/6/7/8 — clean diagnostics and sweep

Command:

```bash
.venv/Scripts/python.exe tools/phase3b_diagnostics.py --data-dir data/backtest_runs/phase3c_targeted_20260623_2310
```

Output:

```text
Dataset: data\backtest_runs\phase3c_targeted_20260623_2310
Markets: 4 snapshots: 1223
Decision PAUSE MARKET-MAKING AND PIVOT
```

Current-like parameters: spread `200 bps`, quote interval `300s`, TTL `1800s`.

|Metric|Value|
|---|---:|
|Total quotes|96|
|Fills|0|
|Buy fills|0|
|Sell fills|0|
|Roundtrips|0|
|Fill rate|0.00%|
|Gross spread captured|$0.00|
|Estimated gas|$0.48|
|Rebates|$0.00|
|Holding rewards|$0.00|
|Adverse selection loss|$0.00|
|60s toxicity|0.00% / not measurable because no fills|
|Net P&L|-$0.48|
|POST_ONLY rejection rate|0.00%|

Best sweep row was also negative:

|Spread|Quote interval|TTL|Quotes|Fills|Roundtrips|Net P&L|
|---:|---:|---:|---:|---:|---:|---:|
|25|900|900|32|0|0|-$0.16|

## Reports

- `reports/phase3c_clean_targeted_validation.md`
- `reports/phase3c_parameter_sweep.md`
- `reports/phase3c_go_no_go.md`

## Decision

**PAUSE MARKET-MAKING AND PIVOT**

Why:

- Fill rate was `0.00%`, below the `<2%` kill/pause gate.
- Roundtrips were `0`.
- Net P&L after gas was negative.
- Gas as % of gross spread was infinite because gross spread captured was `$0.00`.
- Best result only reduced quote count; it did not produce fills or positive P&L.

## Exact next action

Pause active market-making validation on this strategy/market-selection assumption. Pivot to either:

1. holding/reward economics verification, or
2. cross-venue pricing research / arbitrage mapping.

## Phase 4 — Holding/Reward Economics Verification

Started: 2026-06-23T19:05Z

Status freeze:

- Phase 3C completed.
- Passive market-making is paused.
- Reason: 0 fills, 0 roundtrips, 0.00% fill rate, negative net P&L after gas.
- Live trading remains **NO-GO**.
- Next research track: holding/reward economics.
- This is an economics verification task only: no live orders, no deposits, and `dry_run` stays true.

Reward research result:

- Official docs/rewards pages were unreachable from this host, so the full payout/scoring formula is not verified.
- Live CLOB market payloads do expose reward metadata: `rewards.rates`, `rewards.min_size`, `rewards.max_spread`, and `minimum_order_size`.
- Fresh read-only scan found 25 reward markets with valid YES/NO books.
- Best observed API reward-rate candidate: France 2026 FIFA World Cup market, API daily reward rate `3333.0`, USDC asset address, minimum reward size `200`, max spread raw `4.5`.
- The optimistic model is positive only if full daily reward capture is possible; this is unverified and not enough for live trading.
- Final recommendation: **BUILD REWARD FARMING PAPER SIMULATOR**; live reward farming remains NO-GO.
