# Institutional Profitability Audit Implementation Plan

> **For Hermes:** Use trading-bot-validation for all validation runs. This is a planning artifact only: do not deploy live capital, do not set `execution.dry_run: false`, and do not add cosmetic features.

**Goal:** Determine whether the Polymarket bot can make money after realistic fills, latency, adverse selection, fees, gas, and operational constraints; if not, identify the shortest economic path to either fix it or abandon it.

**Architecture:** Treat the system as a trading experiment, not a software project. Build evidence from independent real-data collection, adversarial backtest audits, paper-trading reconciliation, and hard go/no-go gates. Optimize only for expected net profit after all costs.

**Tech Stack:** Python 3.11, existing Polymarket bot repo, Cloudflare Worker proxy, existing CLOB client, JSONL order-book snapshots, existing backtest/paper engines, markdown reports under `reports/`.

---

## Current Evidence Snapshot

This plan is grounded in current repo evidence inspected before writing:

- Repo: `C:\Users\Preethve\polymarket-bot`
- `config.yaml`: `execution.dry_run: true`; `post_only_default: true`; market making enabled; cross-arb/whale/AI disabled.
- Previous report: `reports/phase3_revised_go_no_go.md`
  - Backtest: starting `$1,000.00`, ending `$994.64`, net P&L `-$5.36`, quotes `1,078`, trades `0`, POST_ONLY rejection `0.0%`.
- Previous sweep: `reports/parameter_sweep_results.md`
  - Best offline fill-opportunity row: `2.08%`, roundtrips `0`, conservative net `-$1.67`.
- Previous live read-only snapshot: `reports/current_market_snapshot.md`
  - Valid books sampled: `34`; shallow passing markets: `4`; not proof of edge.
- Current system claims in user prompt differ slightly from repo evidence (`412/412` vs observed `422/422` tests, synthetic positive P&L vs real-data negative/flat). The audit must resolve these discrepancies with fresh tool output.

## Provisional Executive Summary

**Current deployment stance: NO-GO for real money.**

The bot has not yet demonstrated a durable executable edge on real Polymarket data. The most important blocker is not test coverage or architecture; it is missing evidence that realized maker fills plus rebates/spread capture exceed adverse selection, gas, inventory losses, and operational failures. Synthetic profit is not sufficient.

The highest expected-profit path is:

1. audit and repair the simulator until it pessimistically matches paper/live behavior,
2. collect targeted real order-book and quote-life data on candidate markets,
3. measure fill probability, queue position, adverse selection after fill, cancel latency, and gas/order costs,
4. only then tune market selection/spread/size.

If two weeks of targeted real-data experiments cannot produce positive expectancy before live capital, abandon active market making and pivot to either passive rewards or cross-venue arbitrage only if independently validated.

---

# Deliverable Outline to Produce After Execution

The final audit report must contain:

1. Executive Summary
2. Profitability Audit
3. Risk Register
4. Edge Analysis
5. Prioritized Fix List
6. Go/No-Go Framework
7. 30-Day Execution Plan
8. Final Probability of Profit (0–100%)
9. Capital Recommendation
10. Most Likely Failure Modes

Save final report to:

- `reports/institutional_profitability_audit.md`
- machine-readable risk table to `reports/risk_register_profit_impact.csv`
- metric thresholds to `reports/go_no_go_framework.yaml`

---

# Phase 1 — Find All Profitability Killers

## Task 1.1 — Freeze and document the baseline

**Objective:** Establish a clean, reproducible baseline so future changes can be attributed to profit impact.

**Files:**
- Read: `config.yaml`
- Read: `reports/*.md`
- Read: `data/backtest/results/*.json`
- Write: `reports/audit_baseline.md`

**Steps:**

1. Run read-only status checks:
   ```bash
   git status --short
   .venv/Scripts/python.exe -m pytest tests/ -q
   grep -n "dry_run\|post_only_default" config.yaml
   grep -R "clob.polymarket.com" . --include='*.py' --exclude-dir=.venv --exclude-dir=.git || true
   ```
2. Parse latest backtest JSON:
   ```bash
   python - <<'PY'
   import json, glob, os
   paths=sorted(glob.glob('data/backtest/results/MarketMaking_*.json'), key=os.path.getmtime)
   p=paths[-1]
   d=json.load(open(p))
   keys=['starting_capital','ending_capital','net_pnl','gross_spread_captured_usd','rebates_earned_usd','holding_rewards_usd','estimated_gas_costs_usd','quotes_generated','quotes_rejected','rejection_rate','total_trades']
   print(p)
   for k in keys: print(k, d.get(k))
   PY
   ```
3. Write `reports/audit_baseline.md` with exact command outputs and hashes/paths of data used.

**Verification:** No live trading actions occurred; baseline contains exact command output.

**Stop condition:** If `dry_run` is false, stop immediately and restore paper mode before any other action.

---

## Task 1.2 — Audit market-making quote economics

**Objective:** Determine whether quoted spreads can mathematically cover expected costs and toxicity.

**Files:**
- Read: `strategies/market_making.py`
- Read: `core/backtest.py`
- Read: `core/paper_executor.py`
- Read: `core/executor.py`
- Write: `reports/market_making_economics_audit.md`

**Profitability killers to inspect:**

- spread too narrow for tick size and gas/order count,
- spread too wide causing zero fills,
- inventory skew too weak/strong,
- re-quote thresholds causing gas bleed or stale quotes,
- adverse-selection pause too permissive,
- no queue-position model,
- no post-fill markout measurement.

**Steps:**

1. Extract quote formula from `MarketMakingStrategy`.
2. For each quote, compute expected value:
   ```text
   EV = fill_prob * (half_spread + rebate - adverse_selection_markout - inventory_cost)
        - quote_gas_cost
        - cancel_replace_cost
   ```
3. Identify every variable currently hardcoded, guessed, or missing.
4. Add report table: variable, source, current assumption, why it may be wrong, required measurement.

**Verification:** Report identifies whether current market-making has a defensible EV equation.

**Stop condition:** If EV cannot be computed from current data, mark market making as `unproven edge`, not profitable.

---

## Task 1.3 — Audit fill model and adverse selection

**Objective:** Prove or disprove that simulated/paper fills resemble executable maker fills.

**Files:**
- Read: `core/backtest.py`
- Read: `core/paper_executor.py`
- Read: `data/market_activity.py`
- Read: `tools/phase3b_diagnostics.py`
- Write: `reports/fill_model_audit.md`

**Required measurements:**

- fill rate by market,
- buy vs sell fill imbalance,
- markout after fill at +5s, +30s, +60s, +300s,
- queue-through vs touch-through distinction,
- roundtrip rate,
- quote lifetime before fill/cancel,
- adverse selection as `% of gross spread`.

**Steps:**

1. Compare `BacktestExecutor` fill conditions to real CLOB maker execution reality.
2. Check whether simulator assumes fills when price touches quote even if queue size ahead is large.
3. Check whether simulator gives fills without sufficient opposite-side traded volume.
4. Check whether paper executor uses fixed `fill_probability` from config (`0.85`) in a way that can fabricate profits.
5. Write a gap table and minimum realistic fill-model requirements.

**Verification:** Report states exactly which fill assumptions are invalid/unproven.

**Stop condition:** If paper fills are not causally tied to trade-through/queue depletion, do not use paper P&L as evidence.

---

## Task 1.4 — Audit execution/order-state risk

**Objective:** Find bugs that can convert a profitable model into live losses.

**Files:**
- Read: `core/executor.py`
- Read: `core/order_state.py`
- Read: `core/client.py`
- Read: `core/risk.py`
- Read: `strategies/market_making.py`
- Write: `reports/execution_risk_audit.md`

**Risks:**

- duplicate orders on retry,
- stale orders after process restart,
- cancellation not confirmed,
- race between cancel and replace,
- POST_ONLY not actually sent/enforced by API type,
- partial fills mishandled,
- local order store diverging from CLOB,
- pending timeout too short/long,
- API retries causing repeated signed orders.

**Steps:**

1. Trace order lifecycle: create → pending → open → partial → filled/cancelled/rejected.
2. Verify idempotency around retries and exceptions.
3. Verify cancel confirmation and startup reconciliation exist.
4. Verify POST_ONLY semantics are real for Polymarket API, not merely logged.
5. Produce risk table with code line references.

**Verification:** Every order-state transition has a source of truth and recovery behavior.

**Stop condition:** If restart recovery cannot reconcile open orders, live trading remains no-go regardless of backtest profit.

---

## Task 1.5 — Audit market selection and data quality

**Objective:** Determine whether the scanner selects markets where maker edge can exist.

**Files:**
- Read: `data/market_scanner.py`
- Read: `tools/current_market_snapshot.py`
- Read: `tools/collect_backtest_data.py`
- Read: `reports/current_market_snapshot.md`
- Write: `reports/market_selection_audit.md`

**Risks:**

- bad category classification,
- selecting sticky/low-fill markets,
- selecting manipulated/deceptive books,
- ignoring volume/trade count because CLOB API volume fields are missing,
- using spread as opportunity without fill probability,
- ignoring market resolution/event risk,
- targeting only politics/geopolitics/finance while sports/crypto may have tighter but more real flow.

**Steps:**

1. Compare scanner scoring factors to observed fill outcomes.
2. Evaluate whether `scanner_use_activity_score: false` is still defensible.
3. Identify required market filters:
   - trade count over last N minutes,
   - top-of-book change frequency,
   - spread stability,
   - touch depth,
   - not near resolution,
   - not one-sided impossible-tail markets.
4. Produce top candidate classes to collect next.

**Verification:** Report says which markets to exclude and why.

**Stop condition:** If market selection cannot find >5% fill opportunity in real data, stop market-making expansion.

---

## Task 1.6 — Audit economics: fees, rebates, gas, capital efficiency

**Objective:** Confirm all P&L inputs are real and conservative.

**Files:**
- Read: `config.yaml`
- Read: `core/backtest.py`
- Read: `core/portfolio.py`
- Read: `core/risk.py`
- Write: `reports/economic_assumptions_audit.md`

**Checks:**

- Are maker/taker fee assumptions correct for Polymarket current rules?
- Are rebates actually earned for quoted markets, sizes, spread widths, and holding time?
- Are holding rewards real, accessible, and not double-counted?
- Is gas per quote/cancel realistic or should on-chain gas be zero for off-chain CLOB placement but nonzero for settlement/withdrawal/redeem?
- Does position sizing produce enough dollars per fill to overcome fixed costs?
- Is capital locked by resting quotes accounted for?

**Verification:** Each economic assumption must be tagged: `verified`, `conservative estimate`, or `invalid/unproven`.

**Stop condition:** Any unverified rebate/holding reward must be excluded from go-live P&L.

---

## Task 1.7 — Audit operational/proxy risk

**Objective:** Determine whether India proxy dependence creates unacceptable latency/failure risk.

**Files:**
- Read: `core/client.py`
- Read: `utils/alerting.py`
- Read: `utils/logger.py`
- Read: `main.py`
- Write: `reports/operational_risk_audit.md`

**Checks:**

- Cloudflare Worker timeout/rate limits,
- proxy adds latency and stale-book risk,
- circuit breaker behavior,
- crash/restart recovery,
- log persistence,
- state corruption risks,
- alert delivery evidence vs device receipt,
- health checks tied to trading halt.

**Verification:** Report includes measured/past observed latency/error evidence where available, and required measurement scripts where missing.

**Stop condition:** If proxy latency cannot be measured and bounded, live market making remains no-go.

---

# Phase 2 — Rank Issues by Expected Profit Impact

## Task 2.1 — Build profit-impact risk register

**Objective:** Rank all issues by expected profit impact, not engineering convenience.

**Files:**
- Create: `reports/risk_register_profit_impact.csv`
- Include in: `reports/institutional_profitability_audit.md`

**Required columns:**

```csv
Issue,Category,Severity,Probability,ImpactUsdPerMonth,FixCostDays,Priority,WhyItMatters,Verification,StopCondition
```

**Scoring rules:**

- Severity: 1–5
- Probability: 1–5
- ImpactUsdPerMonth: estimate from capital, expected turnover, and loss mechanism; use ranges if uncertain.
- Priority score:
  ```text
  Priority = Severity * Probability * abs(ImpactUsdPerMonth) / max(0.5, FixCostDays)
  ```

**Initial expected top issues to validate:**

| Issue | Severity | Probability | Expected Impact | Fix Cost | Priority |
|---|---:|---:|---:|---:|---:|
| No proven real-data maker edge / zero fills | 5 | 5 | Very high | 2–4d | P0 |
| Unrealistic/paper fill model | 5 | 4 | Very high | 2–3d | P0 |
| No queue-position / traded-volume fill model | 5 | 4 | High | 3–5d | P0 |
| Market selection chooses sticky books | 5 | 4 | High | 1–3d | P0 |
| Adverse-selection markout not measured | 5 | 4 | High | 2–4d | P0 |
| Unverified rebates/holding rewards | 4 | 3 | Medium-high | 1–2d | P1 |
| Proxy latency/staleness unmeasured | 4 | 3 | Medium-high | 1–2d | P1 |
| Restart/open-order reconciliation gap | 4 | 2 | High tail loss | 2–4d | P1 |
| Disabled strategies with no evidence | 2 | 4 | Opportunity cost | 0.5d | P2 |

**Verification:** CSV sorted descending by priority score.

---

# Phase 3 — Find the Real Edge

## Task 3.1 — State the edge hypothesis explicitly

**Objective:** Answer “why should this bot make money?” in one falsifiable sentence per strategy.

**Files:**
- Write: `reports/edge_hypotheses.md`

**Market-making hypothesis to test:**

> On selected Polymarket markets with sufficient top-of-book churn but low toxicity, maker rebates plus captured spread exceed adverse-selection markout, inventory losses, and operational costs.

**If this cannot be supported by data, market making has no proven edge.**

**Cross-arb hypothesis:**

> Cross-venue pricing discrepancies between Polymarket and Kalshi/PredictIt persist long enough after latency and fees to lock risk-controlled profit.

Currently blocked by disabled config and missing credentials/mapping evidence.

**Whale-tracking hypothesis:**

> Certain addresses have persistent predictive skill that remains profitable after copy latency, market impact, and selection bias.

Likely weak without robust identity/outcome database; high risk of overfitting.

**AI-signals hypothesis:**

> External news/model signals update probabilities faster than market prices.

Likely hard; requires timestamped news and execution before price move, not LLM opinions.

**Holding rewards hypothesis:**

> Passive qualifying liquidity/rewards produce positive return with lower toxicity than active spread capture.

Potentially more plausible than active MM if rewards are verified and inventory risk hedged.

---

## Task 3.2 — Rank opportunity classes by evidence and expected ROI

**Objective:** Decide what to pursue and what to abandon.

**Files:**
- Write section in `reports/institutional_profitability_audit.md`

**Initial ranking to validate:**

1. **Targeted market-making / rewards farming** — highest near-term because code exists, but edge unproven.
2. **Holding reward farming with strict inventory-neutral rules** — potentially lower turnover and lower gas; must verify rewards eligibility.
3. **Cross-arbitrage** — potentially stronger edge but blocked by venue access, mapping, latency, and execution complexity.
4. **AI signals** — high research burden; no live evidence.
5. **Whale tracking** — likely abandon unless a real historical whale database proves persistent alpha.

**Verification:** Each opportunity receives: data required, expected ROI range, time to validate, and abandon criteria.

---

# Phase 4 — Shortest Path to Profitability

## Task 4.1 — Build a targeted real-data experiment harness

**Objective:** Collect only data that can falsify or validate maker edge.

**Files likely to change:**
- Modify: `tools/collect_backtest_data.py`
- Create: `tools/collect_targeted_books.py` if current collector cannot accept explicit market IDs.
- Create: `reports/targeted_collection_plan.md`

**Requirements:**

- Accept explicit condition IDs/token IDs from `reports/current_market_snapshot.json`.
- Capture snapshots at fixed cadence for 30–60 minutes.
- Include best bid/ask, full top N depth, timestamps, last trade if available, proxy latency per call.
- Never place orders.

**Verification:** JSONL files contain timestamped book snapshots for top 3 candidate markets and latency metadata.

**Stop condition:** If proxy cannot collect stable snapshots under rate limits, active MM remains no-go.

---

## Task 4.2 — Add markout and toxicity diagnostics

**Objective:** Measure whether fills are toxic before optimizing spreads.

**Files likely to change:**
- Modify: `data/market_activity.py`
- Modify: `tools/phase3b_diagnostics.py`
- Test: `tests/test_market_activity.py`

**Metrics to compute:**

- hypothetical maker fills,
- markout at 5s/30s/60s/300s,
- realized spread after markout,
- buy/sell imbalance,
- roundtrip completion,
- toxicity = adverse markout / gross spread.

**Verification:** Report shows toxicity by market and parameter row.

**Stop condition:** If adverse markout >40% of gross spread for best candidates, abandon active MM on those markets.

---

## Task 4.3 — Replace fixed paper fill probability with data-derived fill model

**Objective:** Stop paper trading from fabricating profits.

**Files likely to change:**
- Modify: `core/paper_executor.py`
- Modify: `core/backtest.py`
- Test: `tests/test_paper_executor.py`
- Test: `tests/test_backtest.py`

**Implementation principle:** Paper fills must require observable market movement/queue depletion/trade-through evidence, not a fixed `fill_probability: 0.85`.

**Verification:** A paper order does not fill merely because random probability triggers; it fills only when replay/live book evidence supports a maker fill.

**Stop condition:** If realistic paper fill rate falls below 2% and net remains flat/negative, do not tune around it.

---

## Task 4.4 — Add candidate-market gating to scanner

**Objective:** Prevent the bot from quoting markets that historical diagnostics already identify as sticky/toxic.

**Files likely to change:**
- Modify: `data/market_scanner.py`
- Modify: `config.yaml`
- Test: `tests/test_market_scanner.py`

**Candidate gates:**

- minimum top-of-book change rate,
- minimum fill-opportunity rate,
- maximum adverse markout,
- minimum touch depth,
- exclude near-resolution markets unless explicitly event-driven,
- exclude markets where rewards/rebates are unavailable.

**Verification:** Scanner excludes prior zero-fill markets unless diagnostics improve.

**Stop condition:** If gate leaves no markets, do not trade; edge unavailable under current constraints.

---

# Phase 5 — Hard Go/No-Go Framework

Create `reports/go_no_go_framework.yaml` with exact gates:

```yaml
live_trading_go_gates:
  dry_run_must_be_true_until_manual_cutover: true
  minimum_real_data_duration_hours: 24
  minimum_markets_tested: 10
  minimum_orders_or_hypothetical_quotes: 1000
  net_pnl_after_all_costs_pct_min: 2.0
  lower_95_confidence_net_pnl_min_usd: 0.0
  maker_fill_rate_min_pct: 5.0
  roundtrip_rate_min_pct: 1.0
  adverse_selection_max_pct_of_gross: 30.0
  gas_or_operational_cost_max_pct_of_gross: 20.0
  post_only_rejection_rate_max_pct: 10.0
  stale_quote_rate_max_pct: 2.0
  cancel_success_rate_min_pct: 99.0
  duplicate_order_count_max: 0
  unreconciled_open_orders_max: 0
  max_drawdown_pct: 5.0
  daily_loss_cap_pct: 2.0
  proxy_p95_latency_ms_max: 750
  circuit_breaker_events_max: 0
  restart_reconciliation_required: true
capital_ramp:
  phase_0: paper_only
  phase_1_max_capital_usd: 50
  phase_1_required_days: 7
  phase_2_max_capital_usd: 250
  phase_2_required_days: 14
  stop_if_any_gate_fails: true
```

**Important:** These gates are intentionally strict. If they prevent deployment, that is a feature, not a bug.

---

# Phase 6 — 30-Day Execution Plan

## Week 1 — Prove or kill market-making assumptions

### Action 1: Baseline audit report

- **Expected outcome:** All current claims reconciled with repo output.
- **Verification:** `reports/audit_baseline.md` contains command outputs and latest result metrics.
- **Stop condition:** Any unsafe config or direct blocked endpoint bypass.

### Action 2: Fill-model audit

- **Expected outcome:** Clear list of unrealistic fill assumptions.
- **Verification:** `reports/fill_model_audit.md` identifies fixed/random fill assumptions and queue/trade-through gaps.
- **Stop condition:** If paper fills are not evidence-based, ignore paper P&L until fixed.

### Action 3: Targeted data collection plan

- **Expected outcome:** Top 3–5 markets selected for real-data collection.
- **Verification:** `reports/targeted_collection_plan.md` includes condition IDs/token IDs and collection commands.
- **Stop condition:** No markets satisfy shallow spread/liquidity gates.

## Week 2 — Collect real data and measure toxicity

### Action 1: 24h targeted order-book collection

- **Expected outcome:** Robust JSONL dataset across at least 10 candidate markets or all available candidates.
- **Verification:** Snapshot counts, latency distribution, no large gaps.
- **Stop condition:** Proxy/rate limits make data incomplete or stale.

### Action 2: Markout/toxicity analysis

- **Expected outcome:** Fill opportunity, roundtrip, and adverse markout metrics by market.
- **Verification:** `reports/toxicity_markout_report.md` with 5s/30s/60s/300s markouts.
- **Stop condition:** Best candidate adverse markout >40% of gross spread.

### Action 3: Economic assumption verification

- **Expected outcome:** Fees/rebates/rewards classified as verified or excluded.
- **Verification:** `reports/economic_assumptions_audit.md`.
- **Stop condition:** If rebates/rewards cannot be verified, exclude from go-live P&L.

## Week 3 — Fix only profit-critical simulation and scanner gaps

### Action 1: Replace unrealistic paper fill behavior

- **Expected outcome:** Paper/backtest fills tied to real book movement and queue/trade-through evidence.
- **Verification:** Tests plus backtest-paper reconciliation report.
- **Stop condition:** If realistic fill rate <2% on best markets, do not optimize spreads.

### Action 2: Add market-selection gates

- **Expected outcome:** Scanner avoids sticky/toxic markets.
- **Verification:** Scanner output overlaps with markets that passed Week 2 diagnostics.
- **Stop condition:** If no markets pass, stop active MM.

### Action 3: Run parameter sweeps on only passing markets

- **Expected outcome:** Conservative EV table by spread/TTL/size/market.
- **Verification:** `reports/profitability_sweep_real_data.md` sorted by lower-bound EV.
- **Stop condition:** Lower 95% confidence EV <= 0.

## Week 4 — Paper validation and capital decision

### Action 1: 48–72h paper-only run on validated candidates

- **Expected outcome:** Realistic paper/live-observed metrics, not synthetic P&L.
- **Verification:** `reports/paper_trading_72h_profitability_report.md`.
- **Stop condition:** Any go-live gate fails.

### Action 2: Restart/reconciliation drill

- **Expected outcome:** Bot can restart without duplicate/stale/unreconciled orders.
- **Verification:** `reports/restart_reconciliation_drill.md`.
- **Stop condition:** Any unreconciled open order.

### Action 3: Final capital recommendation

- **Expected outcome:** Clear deploy/abandon/rerun decision.
- **Verification:** `reports/institutional_profitability_audit.md` finalized with probability and capital recommendation.
- **Stop condition:** If evidence remains ambiguous, no live capital.

---

# Prioritized Fix List by Expected Profit Impact

1. **P0 — Realistic fill and markout model**
   - Expected ROI: prevents fake profit and live losses.
   - Success: paper/backtest fills require real book/trade-through evidence; markout measured.

2. **P0 — Targeted market selection using activity/toxicity gates**
   - Expected ROI: avoids zero-fill/sticky markets.
   - Success: >5% fill opportunity and positive conservative EV on real collected data.

3. **P0 — Economic assumption verification**
   - Expected ROI: prevents rebate/reward/gas hallucination.
   - Success: unverified rewards excluded; P&L remains positive without them or strategy is no-go.

4. **P1 — Proxy latency and stale quote measurement**
   - Expected ROI: avoids quoting stale markets from India/proxy path.
   - Success: p95 latency below threshold and stale quote rate <2%.

5. **P1 — Restart/open-order reconciliation**
   - Expected ROI: reduces tail loss from operational failure.
   - Success: zero unreconciled orders after controlled restart drill.

6. **P2 — Cross-arb research spike**
   - Expected ROI: potentially high, but blocked and more complex.
   - Success: independent cross-venue price database shows persistent executable edge.

7. **P3 — AI/whale signals**
   - Expected ROI: speculative; likely abandon unless historical alpha is proven.
   - Success: timestamped out-of-sample edge after costs.

---

# Final Probability of Profit — Provisional

Current probability that this bot is profitable with real money **today**: **15/100**.

Reasoning:

- Positive synthetic P&L is not enough.
- Real-data evidence is flat/negative and too small.
- Existing collected-data backtest produced zero trades and negative net P&L.
- Fill model, adverse selection, and market selection remain the main unknowns.
- There may be a narrow path via rewards/market selection, but it is not proven.

Target after 30-day plan if gates pass: **45–60/100** for very small capital only. If gates fail: **0–10/100**, abandon active MM.

---

# Capital Recommendation — Provisional

- Current live capital: **$0**.
- Paper/data collection only until gates pass.
- If all gates pass for 7 consecutive live-paper days: start with **$50 max capital**, not more.
- Increase to **$250** only after 14 additional days with positive net after all costs and no operational failures.
- Never scale capital based on synthetic backtest alone.

---

# Most Likely Failure Modes

1. Backtest/paper fills overstate actual maker fills due to no queue-position/trade-volume model.
2. Selected markets are sticky: many quotes, near-zero fills.
3. Fills occur only when the bot is adversely selected.
4. Rebates/holding rewards are unavailable, overestimated, or offset by inventory risk.
5. Proxy latency makes quotes stale before cancellation/requote.
6. Market scanner treats wide spreads as profit opportunity when they are actually no-flow traps.
7. Restart or cancellation failures leave stale live exposure.
8. Strategy overfits tiny data samples and fails when market regime changes.
9. Capital is too small for fixed operational costs but too large for unproven inventory risk.
10. Cross-arb/AI/whale features distract from proving one real edge.

---

# Definition of Done for the Audit

The audit is complete only when:

- `reports/institutional_profitability_audit.md` exists and includes all requested deliverables.
- `reports/risk_register_profit_impact.csv` is sorted by expected profit impact.
- `reports/go_no_go_framework.yaml` has hard deployment gates.
- All claims are backed by command output, logs, JSON result files, or explicitly labeled assumptions.
- Final recommendation is one of:
  - **NO-GO / abandon active MM**
  - **NO-GO / collect more data**
  - **PAPER-GO only**
  - **TINY-CAPITAL GO with strict kill switch**

No report may recommend live trading on synthetic profit alone.
