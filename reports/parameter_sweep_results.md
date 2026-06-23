# Parameter Sweep Results — Phase 3B

Generated: 2026-06-23T16:57:59Z

## Method

This is a fast offline approximation over collected JSONL order-book snapshots. It does **not** modify strategy logic. It counts a fill opportunity if a later snapshot within TTL trades through/touches the quote.

Assumptions:

- Tick size approximation: `0.005`
- Maker fill opportunity: BUY if later `best_ask <= bid`; SELL if later `best_bid >= ask`
- Gas approximation from latest official backtest: `$5.36 / 1078 quotes = $0.00497 / quote`
- Conservative net treats opportunity counts as diagnostics, not realized P&L.

## Top sweep rows

|Rank|Spread bps|Quote interval|TTL|Quotes|Buy fills|Sell fills|Fill rate|Roundtrips|Gas|Conservative net|
|---|---|---|---|---|---|---|---|---|---|---|
|1|25|900|1800|368|5|2|1.90%|0|$1.83|$-1.83|
|2|50|900|1800|368|5|2|1.90%|0|$1.83|$-1.83|
|3|75|900|1800|368|5|2|1.90%|0|$1.83|$-1.83|
|4|100|900|1800|368|5|2|1.90%|0|$1.83|$-1.83|
|5|150|900|1800|368|5|2|1.90%|0|$1.83|$-1.83|
|6|200|900|1800|368|5|2|1.90%|0|$1.83|$-1.83|
|7|25|60|1800|4904|65|21|1.75%|0|$24.38|$-24.38|
|8|50|60|1800|4904|65|21|1.75%|0|$24.38|$-24.38|
|9|75|60|1800|4904|65|21|1.75%|0|$24.38|$-24.38|
|10|100|60|1800|4904|65|21|1.75%|0|$24.38|$-24.38|
|11|150|60|1800|4904|65|21|1.75%|0|$24.38|$-24.38|
|12|200|60|1800|4904|65|21|1.75%|0|$24.38|$-24.38|
|13|25|300|1800|1050|13|5|1.71%|0|$5.22|$-5.22|
|14|50|300|1800|1050|13|5|1.71%|0|$5.22|$-5.22|
|15|75|300|1800|1050|13|5|1.71%|0|$5.22|$-5.22|
|16|100|300|1800|1050|13|5|1.71%|0|$5.22|$-5.22|
|17|150|300|1800|1050|13|5|1.71%|0|$5.22|$-5.22|
|18|200|300|1800|1050|13|5|1.71%|0|$5.22|$-5.22|
|19|25|900|900|368|3|1|1.09%|0|$1.83|$-1.83|
|20|50|900|900|368|3|1|1.09%|0|$1.83|$-1.83|


## Current-like diagnostic row

```json
{
  "spread_bps": 200,
  "quote_interval_sec": 300,
  "ttl_sec": 1800,
  "quotes": 1050,
  "buy_fills": 13,
  "sell_fills": 5,
  "roundtrips": 0,
  "fill_rate_pct": 1.7142857142857144,
  "optimistic_gross_usd": 0.0,
  "gas_usd": 5.220779220779221,
  "optimistic_net_usd": -5.220779220779221
}
```

## Recommendation

Do not blindly lower/widen spreads in live mode. First rank markets by recent top-of-book movement and fill opportunity density, then rerun sweeps only on the most active markets.
