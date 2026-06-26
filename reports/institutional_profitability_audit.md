# Institutional Profitability Audit — Polymarket Bot

## Executive Summary

**Decision: NO-GO for live trading.** I would not deploy my own money into this system today. The bot can run, tests pass, and several mechanical bugs have improved, but it has not demonstrated a real executable edge after fills, latency, adverse selection, fees/rebates, gas/operational costs, and restart risk.

Latest real-data backtest: `1078` quotes, `0` trades, net P&L `-$5.36`. The best prior offline fill-opportunity row remains below the >5% proceed threshold, and the new markout diagnostic shows fill toxicity around 100–200% of gross edge in collected markets.

## Profitability Audit

### Market Making

Current market making is **unproven**. It has no demonstrated positive EV equation on real data.

- Spread capture: `$0.00`
- Rebates: `$0.00`
- Holding rewards: `$0.00`
- Estimated gas/operational costs: `$5.36`
- Trades: `0`

### Execution

POST_ONLY intent exists, and the local amend cancel+replace token-ID bug is fixed in current code with regression tests. Live execution remains no-go until exchange reconciliation and live amend/cancel edge cases are tested against the actual venue path.

### Economics

Rebates and holding rewards are not validated revenue. Exclude them from deployment P&L until independently proven.

### Data and Simulation

Paper trading remains suspect because random fill probability still exists after a touch-through condition. Backtests/paper runs should be assumed optimistic until they model queue position, traded volume, delayed fills, and markouts.

### Operations

The Cloudflare Worker proxy is a latency/staleness risk. Market making cannot deploy until proxy p95 latency and stale quote rate are measured and pass gates.

## Risk Register

Full CSV: `reports/risk_register_profit_impact.csv`.

Top issues by expected profit impact:

|Issue|Category|Priority|Why it matters|
|---|---|---|---|
|No proven real-data maker edge / zero fills|Market making|P0|Current real-data backtest: 1078 quotes, 0 trades, -$5.36|
|Unrealistic/random paper fill model|Simulation|P0|Paper executor still uses placeholder/random `fill_probability` after touch-through; this is not calibrated live evidence|
|Market scanner selects sticky/no-flow books|Data|P0|Collected markets show <2.1% opportunity and toxic markouts|
|Adverse selection markout high/unmeasured|Market making|P0|Markout diagnostic shows 100–200% toxicity vs gross edge|
|No queue-position/traded-volume fill model|Simulation|P0|Current snapshots infer touch-through, not queue depletion|

## Edge Analysis

|Opportunity|Why it might make money|Current evidence|Decision|
|---|---|---|---|
|Targeted market making|Rebates + spread could exceed toxicity on selected high-churn markets|Current real data: zero trades, negative P&L, low fill opportunity, high toxicity|NO-GO; continue only as targeted experiment|
|Holding/rewards farming|May earn passive rewards with lower turnover|Reward eligibility/revenue unverified|Research after verification; exclude from P&L now|
|Cross-arbitrage|Locked cross-venue mispricings can be cleaner than passive MM|Disabled, no credentials/mapping/execution evidence|Blocked; possible future spike|
|Whale tracking|Persistent smart-money copying could work in theory|No timestamped whale alpha database; copy latency risk|Abandon for now|
|AI signals|External info could beat market if faster than prices|No out-of-sample timestamped edge|Abandon for now|

## Prioritized Fix List

1. **P0:** Replace random/fixed paper fill model with evidence-based replay fill model.
2. **P0:** Collect targeted real data for markets passing liquidity/spread gates.
3. **P0:** Add markout/toxicity gates to market selection.
4. **P1:** Verify or exclude rebates and holding rewards.
5. **P1:** Measure proxy latency/stale quote rate.
6. **P1:** Implement and drill restart/open-order reconciliation.
7. **P1:** Rehearse amend/cancel and restart reconciliation against the real venue path before any live amendment usage.
8. **P2:** Only after MM is falsified or validated, run cross-arb research spike.

## Go/No-Go Framework

Hard gates are in `reports/go_no_go_framework.yaml`. Key gates: 24h real data, 10 markets, 1,000 quotes/orders, net P&L >2%, lower 95% CI >$0, fill rate >5%, adverse selection <30% gross, cost <20% gross, stale quote <2%, unreconciled open orders 0, proxy p95 latency <750ms.

## 30-Day Execution Plan

### Week 1 — Prove or kill market-making assumptions

|Action|Expected outcome|Verification|Stop condition|
|---|---|---|---|
|Baseline audit|Claims reconciled to actual repo output|`reports/audit_baseline.md`|Unsafe config or direct endpoint bypass|
|Fill model audit|Paper/backtest optimism identified|`reports/fill_model_audit.md`|Paper fills not evidence-based|
|Targeted collection list|Top 3–10 candidate markets selected|`reports/current_market_snapshot.json`|No market passes shallow gates|

### Week 2 — Collect real data and measure toxicity

|Action|Expected outcome|Verification|Stop condition|
|---|---|---|---|
|24h targeted book collection|Robust snapshots + latency metadata|Snapshot counts and gap report|Proxy/rate limits make data stale|
|Markout analysis|Toxicity by market and horizon|`reports/toxicity_markout_report.md`|Toxicity >40% gross on best markets|
|Economic verification|Rewards/fees classified|`reports/economic_assumptions_audit.md`|P&L depends on unverified revenue|

### Week 3 — Fix only profit-critical gaps

|Action|Expected outcome|Verification|Stop condition|
|---|---|---|---|
|Replace fill model|Paper fills tied to observable evidence|Paper/backtest reconciliation|Realistic fill rate <2%|
|Add scanner gates|Sticky/toxic books excluded|Scanner candidate report|No candidates pass|
|Sweep passing markets only|Conservative EV table|`reports/profitability_sweep_real_data.md`|Lower 95% EV <=0|

### Week 4 — Paper validation and capital decision

|Action|Expected outcome|Verification|Stop condition|
|---|---|---|---|
|48–72h paper-only run|Realistic paper metrics|`reports/paper_trading_72h_profitability_report.md`|Any gate fails|
|Restart drill|No stale/duplicate/unreconciled orders|`reports/restart_reconciliation_drill.md`|Unreconciled orders >0|
|Capital decision|Deploy/abandon/rerun recommendation|Final report update|Ambiguous evidence => no capital|

## Final Probability of Profit

**Current probability of profitable live deployment today: 15/100.** If all 30-day gates pass, probability may rise to 45–60/100 for tiny capital only. If gates fail, probability drops to 0–10/100 and active market making should be abandoned.

## Capital Recommendation

- Current live capital: **$0**.
- Continue paper/data collection only.
- If every gate passes for 7 consecutive days: maximum live capital **$50**.
- If 14 additional days pass with positive net after all costs and no operational failures: maximum **$250**.
- Never scale on synthetic backtest profit.

## Most Likely Failure Modes

1. Paper/backtest fills overstate executable maker fills.
2. Selected markets remain sticky/no-flow.
3. Real fills are toxic and erase spread.
4. Rebates/holding rewards are unavailable or overestimated.
5. Proxy latency creates stale quotes.
6. Scanner mistakes wide spreads for opportunity.
7. Restart/cancel failures leave stale live exposure.
8. Tiny samples overfit transient market states.
9. Capital is too small for meaningful edge but large enough for tail loss.
10. Cross-arb/AI/whale features distract from proving one edge.

## Final Recommendation

Do not trade real money. Implement the P0 validation fixes and run targeted real-data collection. If targeted markets cannot show >5% fill rate, positive conservative EV, and acceptable markout within two weeks, abandon active market making and only revisit cross-arbitrage or verified passive rewards.
