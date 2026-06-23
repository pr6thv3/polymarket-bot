# Market Selection and Data Quality Audit

## Answer

Market selection is currently the highest-impact profitability killer. The current scanner can find tradable markets, but collected real data shows sticky markets with low fill opportunity and toxic markouts.

## Evidence

- `reports/current_market_snapshot.json`: 34 valid live books sampled, 4 passed shallow spread/liquidity gate.
- Latest real-data backtest: 1078 quotes and 0 trades.
- `config.yaml`: `scanner_use_activity_score: false`, `scanner_min_activity_score: 0.0`.
- `tools/collect_backtest_data.py` selects scanner top 3 markets, not explicit high-churn candidates.

## Top current passing candidates

|Rank|Market|Question|Bid/Ask|Spread bps|Min touch depth|Score|
|---:|---|---|---|---:|---:|---:|
|1|0x32b09f63…|Will Jesus Christ return before GTA VI?|0.490/0.500|100|$117778.34|51.25|
|2|0x84f8b703…|Trump out as President before GTA VI?|0.490/0.500|100|$230.78|45.16|
|3|0x7b49b9ba…|Will China invades Taiwan before GTA VI?|0.500/0.510|100|$1669.20|45.00|
|4|0x1fad72fa…|New Rihanna Album before GTA VI?|0.510/0.520|100|$27.56|37.77|

## Required market gates

1. top-of-book changes above threshold,
2. fill opportunity >5%,
3. 60s adverse markout <30% of gross edge,
4. touch depth >$25 for tiny capital and >$100 before scaling,
5. not near resolution unless event-driven,
6. rewards/rebates verified or excluded.

## Conclusion

Collect explicit targeted candidates; do not rely on broad scanner score. If no market passes gates, pause active market making.
