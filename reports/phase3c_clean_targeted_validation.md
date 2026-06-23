# Phase 3C Clean Targeted Validation

Generated: 2026-06-23T18:51:01Z

## Safety

- Live trading: **NO-GO**.
- This diagnostic reads only `data\backtest_runs\phase3c_targeted_20260623_2310`.
- No live orders, deposits, cancellations, or strategy-logic changes are performed by this script.

## Collection summary

|Market|Question|Category|Snapshots written|
|---|---|---|---|
|0x50ddb9cd…|New Playboi Carti Album before GTA VI?|politics|305|
|0x32b09f63…|Will Jesus Christ return before GTA VI?|politics|304|
|0x84f8b703…|Trump out as President before GTA VI?|politics|307|
|0x7b49b9ba…|Will China invades Taiwan before GTA VI?|geopolitics|307|


- Errors/timeouts/retries observed by collector: `161`
- Average request latency: `1.608s`

## Clean dataset verification

|Rank|Market|Snapshots|Completeness|Activity|Fill rate|Buy fills|Sell fills|Roundtrips|60s toxicity|
|---|---|---|---|---|---|---|---|---|---|
|1|0x50ddb9cd…|305|complete|21.6|0.00%|0|0|0|0.00%|
|2|0x32b09f63…|304|complete|0.0|0.00%|0|0|0|0.00%|
|3|0x7b49b9ba…|307|complete|0.0|0.00%|0|0|0|0.00%|
|4|0x84f8b703…|307|complete|0.0|0.00%|0|0|0|0.00%|


## Required current-like diagnostics

Current-like parameters: spread `200 bps`, quote interval `300s`, TTL `1800s`.

|Metric|Value|
|---|---|
|Dataset folder|data\backtest_runs\phase3c_targeted_20260623_2310|
|Markets/files|4|
|Total snapshots|1223|
|Incomplete markets (<250 snapshots)|0|
|Total quotes|96|
|Fills|0|
|Buy fills|0|
|Sell fills|0|
|Roundtrips|0|
|Fill rate|0.00%|
|Current-like fill rate|0.00%|
|Gross spread captured|$0.00|
|Estimated gas|$0.48|
|Rebates|$0.00|
|Holding rewards|$0.00|
|Adverse selection loss|$0.00|
|60s toxicity %|0.00%|
|Net P&L|$-0.48|
|POST_ONLY rejection rate|0.00%|
|Quote interval used|300|
|Spread bps used|200|
|TTL used|1800|


## Notes on monetary estimates

Gross spread, adverse-selection loss, and net P&L are conservative replay estimates from top-of-book movement, using configured order size converted to an approximate share count. They are **not live realized P&L** and do not prove executable fills.
