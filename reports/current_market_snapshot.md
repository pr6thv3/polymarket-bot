# Current Live Market Snapshot — Read-only

Generated: 2026-06-23T19:24:21Z

## Method

Read-only CLOB/proxy scan. Fetched accepting CLOB markets, sampled YES-token order books, and ranked by executable spread, touch depth, rebate yield, and time-to-resolution. No orders were placed/cancelled/amended.

Parameters: `max_pages=70`, `max_markets=80`.

## Top candidates by profitability-readiness score

|Rank|Market|Question|Cat|Days|Bid/Ask|Spread bps|Touch depth|Rebate yield|Score|
|---|---|---|---|---|---|---|---|---|---|
|1|0x32b09f63…|Will Jesus Christ return before GTA VI?|politics|37|0.490/0.500|100|$114529.24|0.0025|51.25|
|2|0x84f8b703…|Trump out as President before GTA VI?|politics|37|0.490/0.500|100|$230.28|0.0025|45.15|
|3|0x7b49b9ba…|Will China invades Taiwan before GTA VI?|geopolitics|37|0.500/0.510|100|$1640.88|0.0000|45.00|
|4|0xbb57ccf5…|Will bitcoin hit $1m before GTA VI?|crypto|37|0.495/0.496|10|$4897.07|0.0036|45.00|
|5|0x1595b481…|Will Germany win the 2026 FIFA World Cup?|sports|26|0.054/0.055|10|$3513.56|0.0019|40.69|
|6|0x9b6fef24…|Will France win the 2026 FIFA World Cup?|sports|26|0.192/0.193|10|$9817.76|0.0019|40.69|
|7|0x375409bc…|Will England win the 2026 FIFA World Cup?|sports|26|0.124/0.125|10|$2437.17|0.0019|40.69|
|8|0x7976b8db…|Will Spain win the 2026 FIFA World Cup?|sports|26|0.138/0.139|10|$31604.75|0.0019|40.69|
|9|0x1fad72fa…|New Rihanna Album before GTA VI?|politics|37|0.510/0.520|100|$22.25|0.0025|37.03|
|10|0x50ddb9cd…|New Playboi Carti Album before GTA VI?|politics|37|0.540/0.560|200|$0.14|0.0025|36.25|
|11|0x4f3421fb…|Will Portugal win the 2026 FIFA World Cup?|sports|26|0.074/0.075|10|$308.10|0.0019|35.60|
|12|0xe6bcc2f1…|Will Alexandria Ocasio-Cortez win the 2028 Democratic presidenti|politics|867|0.095/0.096|10|$114.93|0.0025|33.73|
|13|0x9be56371…|Will Netherlands win the 2026 FIFA World Cup?|sports|26|0.051/0.053|20|$119.25|0.0019|33.30|
|14|0x74dba1ce…|Will Jon Ossoff win the 2028 Democratic presidential nomination?|politics|867|0.092/0.093|10|$96.28|0.0025|33.12|
|15|0xf398b0e5…|Will Harvey Weinstein be sentenced to no prison time?|politics|0|0.856/0.869|130|$32.15|0.0025|31.31|
|16|0xdee5db54…|Will Harvey Weinstein be sentenced to between 20 and 30 years in|politics|0|0.051/0.076|250|$1.01|0.0025|31.28|
|17|0x2499928f…|Will Harvey Weinstein be sentenced to more than 30 years in pris|politics|0|0.005/0.047|420|$0.12|0.0025|31.25|
|18|0x30d55d81…|Will Brazil win the 2026 FIFA World Cup?|sports|26|0.046/0.050|40|$1434.03|0.0019|28.69|
|19|0x450810ae…|Will Andrew Yang win the 2028 Democratic presidential nomination|politics|867|0.006/0.007|10|$16627.68|0.0025|27.25|
|20|0x3cd6e526…|Will Jasmine Crockett win the 2028 Democratic presidential nomin|politics|867|0.006/0.007|10|$16783.65|0.0025|27.25|


## Gate interpretation

Candidate gate for next **paper-only** test: spread 100–800 bps, min touch depth >= $25, days_to_resolution >= 3.

- Markets sampled with valid books: 67
- Markets passing this shallow liquidity/spread gate: 3
- This report does **not** prove edge or expected return. It only identifies where a short paper/backtest collection is less likely to waste time than the previous sticky markets.

## Recommended next validation

Collect 30–60 minutes of JSONL snapshots for the top 3 passing markets, then run the same fill-opportunity/backtest sweep before enabling any live trading.
