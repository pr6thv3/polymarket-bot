# Walkthrough — Phase 3C Clean Targeted Polymarket Validation

## Safety invariants

1. Keep `execution.dry_run: true`.
2. Keep `execution.post_only_default: true`.
3. Do not enable live trading or real funds until `reports/go_no_go_framework.yaml` gates pass.
4. Do not mix clean validation data with `data/backtest/`.
5. Treat replay diagnostics as evidence about opportunity/fill probability, not live realized P&L.

## Stop old validation processes

Use Git Bash-compatible process checks on this Windows host:

```bash
ps -efW | grep -E 'C:\\Users\\Preethve\\polymarket-bot|main.py|collect_backtest_data.py|phase3b_diagnostics.py|current_market_snapshot.py' | grep -v grep || true
kill -9 <msys-pid> 2>/dev/null || true
```

Only stop bot/collector/diagnostic processes from `C:\Users\Preethve\polymarket-bot`; do not stop Hermes agent Python processes.

## Create clean run folder

```bash
RUN_ID=$(date +%Y%m%d_%H%M)
RUN_DIR="data/backtest_runs/phase3c_targeted_${RUN_ID}"
mkdir -p "$RUN_DIR"
printf '%s\n' "$RUN_DIR" > .phase3c_run_dir
```

## Refresh read-only market candidates

```bash
PYTHONPATH=. .venv/Scripts/python.exe tools/current_market_snapshot.py --max-pages 70 --max-markets 40
```

Expected artifacts:

- `reports/current_market_snapshot.md`
- `reports/current_market_snapshot.json`

## Run clean targeted collection

```bash
RUN_DIR=$(cat .phase3c_run_dir)
PYTHONPATH=. .venv/Scripts/python.exe tools/collect_backtest_data.py \
  --from-current-snapshot \
  --markets 4 \
  --duration-minutes 60 \
  --interval-seconds 10 \
  --output-dir "$RUN_DIR" \
  2>&1 | tee "$RUN_DIR/collector.log"
```

The collector writes:

- one JSONL per selected market,
- `collection_summary.json`, including selected markets, snapshot counts, error count, and average request latency,
- `collector.log` if launched with `tee` as above.

## Verify clean dataset only

Use bash, not PowerShell, in Hermes terminal:

```bash
RUN_DIR=$(cat .phase3c_run_dir)
find "$RUN_DIR" -maxdepth 1 -type f -name '*.jsonl' -print0 | while IFS= read -r -d '' f; do
  lines=$(wc -l < "$f")
  name=$(basename "$f")
  if [ "$lines" -lt 250 ]; then flag=' INCOMPLETE'; else flag=' complete'; fi
  echo "$name: $lines snapshots$flag"
done
```

## Run clean-folder-only diagnostics

```bash
RUN_DIR=$(cat .phase3c_run_dir)
.venv/Scripts/python.exe tools/phase3b_diagnostics.py --data-dir "$RUN_DIR"
```

Required outputs:

- `reports/phase3c_clean_targeted_validation.md`
- `reports/phase3c_parameter_sweep.md`
- `reports/phase3c_go_no_go.md`

## Phase 3C actual result

Dataset:

`data/backtest_runs/phase3c_targeted_20260623_2310`

Collection:

- 4 markets
- 1,223 total snapshots
- 304–307 snapshots per market
- 161 collector errors
- 122 circuit-breaker log lines
- 1.608s average request latency

Current-like diagnostic:

- spread: 200 bps
- quote interval: 300s
- TTL: 1800s
- quotes: 96
- fills: 0
- roundtrips: 0
- fill rate: 0.00%
- gross spread captured: $0.00
- estimated gas: $0.48
- net P&L: -$0.48

Final decision:

**PAUSE MARKET-MAKING AND PIVOT**

## Pivot options

1. Verify holding/reward economics with read-only reward eligibility and capital lockup analysis.
2. Run cross-venue pricing research: market mapping, fee model, latency/fill assumptions, and paper-only arbitrage replay.

## Phase 4 reward-economics pivot

Current frozen state:

- Phase 3C completed.
- Passive market-making is paused.
- Reason: 0 fills, 0 roundtrips, 0.00% fill rate, negative net P&L.
- Live trading remains **NO-GO**.
- Next research track: holding/reward economics.

Reward-economics workflow:

1. Verify current official Polymarket reward rules from primary/high-quality sources.
2. Build `tools/reward_economics_model.py` to separate reward income, spread income, holding yield, gas cost, adverse-selection cost, and opportunity cost.
3. Use fresh read-only market data only.
4. Run capital sweeps without placing orders.
5. Keep reward farming **NO-GO** unless rules, eligible markets, net EV, capital requirements, and operational risks all pass.

Current reward-track conclusion:

- Build a paper reward-farming simulator next.
- Do not live trade: docs/payout/scoring formula remain unresolved.
- Treat the Phase 3C collector error rate (`161/346`, `46.5%`) as an operational blocker for any latency-sensitive strategy until proxy/local reliability is fixed and remeasured.
- Use `tools/reward_economics_model.py` and `tools/run_reward_research.py` for read-only modeling.
- Key reports: `reports/reward_rules_verified.md`, `reports/reward_candidate_markets.md`, `reports/reward_economics_sweep.md`, `reports/reward_track_go_no_go.md`.
