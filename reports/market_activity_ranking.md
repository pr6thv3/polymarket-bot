# Market Activity Ranking — Phase 3B

Generated: 2026-06-23T16:57:59Z

## Candidate ranking

|Rank|Market|Snapshots|Activity|Fill opp rate|60s toxicity|Toxicity gate|Buy opp|Sell opp|Roundtrips|Recommendation|
|---|---|---|---|---|---|---|---|---|---|---|
|1|0x50ddb9cd…|15,187|38.3|2.00%|111.1%|fail|2|5|0|skip/sticky/toxic|
|2|0x84f8b703…|15,192|13.5|1.71%|100.0%|fail|6|0|0|skip/sticky/toxic|
|3|0x1fad72fa…|15,192|41.1|1.44%|200.0%|fail|5|0|0|skip/sticky/toxic|
|4|0x32b09f63…|6|0.0|0.00%|0.0%|fail|0|0|0|skip/sticky/toxic|


## Rule of thumb

Only consider a short paper run when a market has both:

- `activity_score >= 20`
- `fill_opportunity_rate_pct >= 5%`

Current collected markets do not meet that bar, so they should be skipped for the next validation run.
