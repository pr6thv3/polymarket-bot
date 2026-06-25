# Walkthrough — Read-Only Cross-Venue Research Kernel

## v1 safety invariants

1. Keep `execution.dry_run: true`.
2. Keep every `strategies.*.enabled` flag false.
3. Use `tools/cross_venue_research.py` for research capture/replay only.
4. Do not import or call `core.executor`, `core.client`, `main.py`, paper/live executors, or strategy classes from research code.
5. Use only public REST `GET`/`HEAD` through `ReadOnlyTransport`.
6. Do not include request bodies, signing headers, wallet keys, API keys, or trading credentials in research processes.
7. Treat missing fee data, stale quotes, excessive pair skew, missing depth, mapping mismatch, and non-positive edge as recorded rejections.
8. Count rebates, maker programs, and incentives as zero until their current official rules are independently verified.

## Validate pinned source contracts

Fixture-only deterministic check:

```powershell
.venv/Scripts/python.exe tools/cross_venue_research.py verify-contracts
```

Manual/scheduled live read-only check:

```powershell
.venv/Scripts/python.exe tools/cross_venue_research.py verify-contracts --live `
  --polymarket-token-id <TOKEN_ID> `
  --kalshi-ticker <MARKET_TICKER> `
  --kalshi-series-ticker <SERIES_TICKER>
```

Live contract promotion requires manual review of source URLs, consumed fields, and sanitized fixtures.

## Mapping catalog

Mappings live in `research_mappings/catalog.yaml`.

Only `status: approved` entries are replay eligible. Each approved mapping must include Polymarket condition/token IDs, Kalshi event/market/series tickers, canonical proposition, YES predicate, resolution source, UTC cutoff, timezone, payout convention, invalidation behavior, review evidence, reviewer, and review time.

An empty catalog is intentional until semantic equivalence is reviewed manually.

Candidate generation is separate from the approved catalog:

```powershell
.venv/Scripts/python.exe tools/generate_candidates.py --limit 50 --threshold 0.25
```

Preview without writing:

```powershell
.venv/Scripts/python.exe tools/generate_candidates.py --dry-run --fetch-limit 50
```

The generator writes `research_mappings/candidates.yaml`. These rows remain `status: candidate`, use stable hash-based IDs, and keep every semantic review field null. Candidates are not replay eligible.

## Capture baseline

Capture is public REST only and writes append-only logs under `data/research_runs/`:

```powershell
.venv/Scripts/python.exe tools/cross_venue_research.py capture `
  --config config.yaml `
  --mapping-catalog research_mappings/catalog.yaml `
  --duration-hours 24 `
  --interval-seconds 60
```

The first 24-hour run is only a data-quality baseline. It measures quote age, pair skew, missing-depth rate, rejection stability, and concentration. It does not assert profitability.

## Replay evidence pack

```powershell
.venv/Scripts/python.exe tools/cross_venue_research.py replay `
  --run-dir data/research_runs/<RUN_ID> `
  --mapping-catalog research_mappings/catalog.yaml `
  --output reports/cross_venue_research/<RUN_ID>_evidence_pack.json
```

Replay evaluates both routes from executable asks:

- Polymarket YES + Kalshi NO;
- Kalshi YES + Polymarket NO.

The engine applies depth-limited quantity, venue minimums, verified dynamic fee rules, fee rounding, and separate capital lockup. Missing or unverified fee data rejects the route.

---

# Previous Walkthrough — Phase 3C Clean Targeted Polymarket Validation

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

- Paper reward-farming simulator is built: `tools/reward_farming_paper_simulator.py`.
- Data-path gate is built: `tools/data_path_reliability_check.py`.
- Do not live trade: docs/payout/scoring formula remain unresolved.
- Treat the Phase 3C collector error rate (`161/346`, `46.5%`) as an operational blocker for latency-sensitive strategies.
- Latest read-only reliability probe improved vs collector: `0.00%` error rate over 40 requests, but p95 latency `1861ms` still fails latency-sensitive gate.
- Reward simulator conclusion: small account reward farming is not realistically positive EV under 0.01%/0.05%/0.10% pro-rata share assumptions after gas/ops, adverse risk, and opportunity cost.
- Formula verification retry (2026-06-25): current official SDK/API evidence verifies reward-market metadata and private reward-percentage endpoints, but not the current scoring/payout equation. The official 2023 liquidity-mining implementation was score/allocation based, but is historical and cannot be used as the current formula.
- Current final recommendation: **PIVOT TO CROSS-VENUE PRICING RESEARCH**. Keep reward farming paper-only and do not infer full reward capture from advertised daily-rate fields.
- Key reports: `reports/data_path_reliability_report.md`, `reports/reward_simulator/capital_sweep.md`, `reports/reward_simulator/market_ranking.md`, `reports/reward_simulator/formula_verification.md`, `reports/reward_simulator/reward_farming_paper_go_no_go.md`.
