# Strategy Ranking and Go/No-Go — 2026-06-23

## Answer

Current live trading remains **NO-GO**. The highest-ROI path is not enabling more strategies; it is fixing market selection for the existing market-making strategy and validating only the best current candidates in paper/backtest mode.

## Strategy ranking

| Rank | Path | Evidence | Decision |
|---:|---|---|---|
| 1 | Market-making + better market selection | Existing implementation is tested; backtest on collected real JSONL generated 1,078 quotes, 0 trades, net P&L -$5.36; read-only live CLOB snapshot found 4 markets passing a shallow spread/liquidity gate for the next paper-only data collection. | **Proceed only with targeted paper/backtest collection on top candidates** |
| 2 | Cross-platform arbitrage | Code exists but config has `cross_arb.enabled: false`; Kalshi API key/secret are empty in config. | **Blocked until credentials + mapping + paper arb replay exist** |
| 3 | AI signals/news | Code exists but config has `ai_signals.enabled: false`; no current signal backtest evidence in this run. | **No-go until labeled signal history/backtest exists** |
| 4 | Whale tracking/copy trading | Code exists but config has `whale_tracking.enabled: false`; copy trading has adverse-selection/latency risk and no validated fill/P&L evidence. | **Kill for now** |

## Real metrics used

| Source | Metric | Value |
|---|---|---:|
| `pytest tests/ -q` before/after | Tests | 422 passed |
| `main.py --backtest --backtest-data data/backtest/ --backtest-capital 1000` | Net P&L | -$5.36 |
| same backtest | Quotes generated | 1,078 |
| same backtest | Total trades | 0 |
| same backtest | POST_ONLY rejection rate | 0.0% |
| `tools/phase3b_diagnostics.py` | Best offline fill-opportunity row | 2.08% fill opportunity, 0 roundtrips, conservative net -$1.67 |
| `tools/current_market_snapshot.py --max-pages 70 --max-markets 40` | Valid live books sampled | 34 |
| same live snapshot | Markets passing shallow spread/liquidity gate | 4 |

## Top live candidates for the next paper-only collection

Gate: spread 100–800 bps, min touch depth >= $25, days_to_resolution >= 3.

| Rank | Market | Question | Bid/Ask | Spread bps | Min touch depth |
|---:|---|---|---|---:|---:|
| 1 | `0x32b09f63…` | Will Jesus Christ return before GTA VI? | 0.490 / 0.500 | 100 | $117,778.34 |
| 2 | `0x84f8b703…` | Trump out as President before GTA VI? | 0.490 / 0.500 | 100 | $230.78 |
| 3 | `0x7b49b9ba…` | Will China invades Taiwan before GTA VI? | 0.500 / 0.510 | 100 | $1,669.21 |
| 4 | `0x1fad72fa…` | New Rihanna Album before GTA VI? | 0.510 / 0.520 | 100 | $27.56 |

## Go/no-go

**NO-GO for live trading.** Gates failed:

- Net P&L after gas is negative: -$5.36.
- Real/backtest fills are zero: 0 trades from 1,078 quotes.
- Best offline fill-opportunity sweep is only 2.08%, below the >5% proceed gate.
- No roundtrip opportunities were observed in the collected dataset.

## Exact next action

Run a **30–60 minute paper-only targeted data collection** for the top 3 live candidates above, then rerun backtest/fill diagnostics. Do not enable live trading unless that targeted run shows:

1. net P&L after gas > 2%,
2. fill opportunity / paper fill rate > 5%,
3. adverse selection losses < 20–40% of gross,
4. POST_ONLY rejection rate < 10–20%,
5. no health/circuit-breaker failures.
