# Current Live Market Snapshot — Read-only

Generated: 2026-06-23T17:45:37Z

## Method

Read-only CLOB/proxy scan. Fetched accepting CLOB markets, sampled YES-token order books, and ranked by executable spread, touch depth, rebate yield, and time-to-resolution. No orders were placed/cancelled/amended.

Parameters: `max_pages=70`, `max_markets=40`.

## Top candidates by profitability-readiness score

|Rank|Market|Question|Cat|Days|Bid/Ask|Spread bps|Touch depth|Rebate yield|Score|
|---|---|---|---|---|---|---|---|---|---|
|1|0x50ddb9cd…|New Playboi Carti Album before GTA VI?|politics|37|0.540/0.570|300|$26.92|0.0025|57.69|
|2|0x32b09f63…|Will Jesus Christ return before GTA VI?|politics|37|0.490/0.500|100|$117778.34|0.0025|51.25|
|3|0x84f8b703…|Trump out as President before GTA VI?|politics|37|0.490/0.500|100|$230.78|0.0025|45.16|
|4|0x7b49b9ba…|Will China invades Taiwan before GTA VI?|geopolitics|37|0.500/0.510|100|$1669.20|0.0000|45.00|
|5|0xbb57ccf5…|Will bitcoin hit $1m before GTA VI?|crypto|37|0.495/0.496|10|$4900.99|0.0036|45.00|
|6|0x9b6fef24…|Will France win the 2026 FIFA World Cup?|sports|26|0.192/0.193|10|$18917.80|0.0019|40.69|
|7|0x1fad72fa…|New Rihanna Album before GTA VI?|politics|37|0.510/0.520|100|$22.25|0.0025|37.03|
|8|0x1595b481…|Will Germany win the 2026 FIFA World Cup?|sports|26|0.055/0.056|10|$434.04|0.0019|36.79|
|9|0x2499928f…|Will Harvey Weinstein be sentenced to more than 30 years in pris|politics|0|0.006/0.047|410|$0.07|0.0025|31.25|
|10|0xdee5db54…|Will Harvey Weinstein be sentenced to between 20 and 30 years in|politics|0|0.052/0.076|240|$0.38|0.0025|30.25|
|11|0x450810ae…|Will Andrew Yang win the 2028 Democratic presidential nomination|politics|867|0.006/0.007|10|$16636.50|0.0025|27.25|
|12|0x3cd6e526…|Will Jasmine Crockett win the 2028 Democratic presidential nomin|politics|867|0.006/0.007|10|$16788.69|0.0025|27.25|
|13|0x9d4f94f8…|Will Mark Cuban win the 2028 Democratic presidential nomination?|politics|867|0.009/0.010|10|$6649.91|0.0025|27.25|
|14|0x46dbd48d…|Will Liz Cheney win the 2028 Democratic presidential nomination?|politics|867|0.007/0.008|10|$7694.68|0.0025|27.25|
|15|0x663b88d3…|Will Hillary Clinton win the 2028 Democratic presidential nomina|politics|867|0.007/0.008|10|$3715.25|0.0025|27.25|
|16|0x98933c78…|Will Ruben Gallego win the 2028 Democratic presidential nominati|politics|867|0.007/0.008|10|$4766.89|0.0025|27.25|
|17|0x8fbcb151…|Will Jared Polis win the 2028 Democratic presidential nomination|politics|867|0.007/0.008|10|$5392.08|0.0025|27.25|
|18|0x3535fb2f…|Will Zohran Mamdani win the 2028 Democratic presidential nominat|politics|867|0.007/0.008|10|$8754.07|0.0025|27.25|
|19|0xc44edcfd…|Will MrBeast win the 2028 Democratic presidential nomination?|politics|867|0.007/0.008|10|$12159.21|0.0025|27.25|
|20|0xf2e51acf…|Will Chelsea Clinton win the 2028 Democratic presidential nomina|politics|867|0.009/0.010|10|$1259.62|0.0025|27.05|


## Gate interpretation

Candidate gate for next **paper-only** test: spread 100–800 bps, min touch depth >= $25, days_to_resolution >= 3.

- Markets sampled with valid books: 35
- Markets passing this shallow liquidity/spread gate: 4
- This report does **not** prove edge or expected return. It only identifies where a short paper/backtest collection is less likely to waste time than the previous sticky markets.

## Recommended next validation

Collect 30–60 minutes of JSONL snapshots for the top 3 passing markets, then run the same fill-opportunity/backtest sweep before enabling any live trading.
