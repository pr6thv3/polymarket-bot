# Fill Model and Adverse Selection Audit

## Answer

The current fill evidence is **not sufficient to deploy real capital**. The real-data backtest produced zero official trades. The offline opportunity/markout diagnostic finds low fill opportunity and toxic markouts in the collected markets.

## Code evidence

- `core/paper_executor.py:284-288` loads `fill_probability`, `partial_fill_probability`, and `min_fill_pct` from config.
- `core/paper_executor.py:473-482` applies random fill probability and random partial-fill sizing after a touch/trade-through condition.
- `core/backtest.py:374-391` only fills in immediate placement if quote crosses current best bid/ask; with POST_ONLY enabled this generally rejects rather than models resting queue fills.
- `data/market_activity.py` now includes `quote_fill_markouts(...)`, a conservative diagnostic that counts fills only after later snapshots touch/trade through and measures midpoint markout after fill.
- `data/market_activity.py` also includes `quote_fill_pnl_by_adverse_selection(...)`, which splits hypothetical maker-fill P&L into adverse and non-adverse buckets using future midpoint markout at a specified horizon.

## Current real-data markout diagnostics

Tool output from `quote_fill_markouts(spread_bps=200, quote_interval_sec=300, ttl_sec=1800)`:

|Market|Quotes|Fills|Fill rate|Adverse 5s|Adverse 30s|Adverse 60s|Adverse 300s|Toxicity 60s % gross|
|---|---:|---:|---:|---:|---:|---:|---:|---:|
|0x1fad72fa…|338|5|1.48%|0.0100|0.0100|0.0100|0.0100|200.0%|
|0x50ddb9cd…|340|7|2.06%|0.0086|0.0071|0.0071|0.0071|111.1%|
|0x84f8b703…|340|6|1.76%|0.0050|0.0050|0.0050|0.0050|100.0%|

## Interpretation

- Fill rates in current collected markets are below the >5% proceed gate.
- 60s adverse markout is 100–200% of the average gross quote edge in these diagnostics.
- No queue-position or traded-volume depletion model exists yet, so even these fills may be optimistic.
- Paper P&L must not be treated as evidence until random fill probability is replaced by observable book/trade evidence.

## Required fix before profit claims

Replace fixed/random paper fills with a replay/live fill model requiring actual trade-through, queue depletion, or a conservative delayed fill after the price moves through by at least one tick.
