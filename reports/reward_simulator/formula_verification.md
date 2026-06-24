# Reward Formula Verification — Primary-Source Retry

Generated: 2026-06-25T00:12Z

## Decision

**Current Polymarket reward scoring and payout formula is not verified. Reward farming remains NO-GO; pivot to cross-venue pricing research.**

This retry used only Polymarket-controlled sources and read-only API requests. It did not submit, score, amend, or cancel an order; it did not query account rewards; it did not deposit funds.

## Primary sources examined

|Source|Evidence|What it establishes|Limit|
|---|---|---|---|
|[Current official Python CLOB SDK v2](https://github.com/Polymarket/py-clob-client-v2/blob/ff23d678ae6753e9d18e0be0d9854cb8eb2dfe21/py_clob_client_v2/endpoints.py)|Official source, commit `ff23d678ae6753e9d18e0be0d9854cb8eb2dfe21` (2026-05-25). Defines `/rewards/markets/current`, `/rewards/markets/{condition_id}`, `/rewards/user`, `/rewards/user/total`, `/rewards/user/percentages`, `/rewards/user/markets`, and the order-scoring endpoints.|A current rewards API and account-level reward-percentage endpoint exist.|It contains endpoint names, not the scoring or payout equation.|
|Current official SDK v2 client implementation|`get_current_rewards()` and `get_raw_rewards_for_market()` are unauthenticated reads. User earnings and reward-percentage methods require Level 2 authentication.|Market reward configuration can be collected safely without orders; user-specific percentages are account-private reads.|No method describes how a percentage or payout is computed.|
|Current CLOB rewards API, read-only via the configured proxy|`GET /rewards/markets/current` returned HTTP 200 with 500 records. Records contained `total_daily_rate`, `native_daily_rate`, `rewards_config[].rate_per_day`, `rewards_min_size`, and `rewards_max_spread`. `GET /rewards/markets/{condition_id}` returned matching market configuration plus `market_competitiveness`.|The live API presently publishes a daily-rate field and eligibility configuration such as minimum size and maximum spread.|Field names and values do not define whether the rate is a total pool, a per-maker ceiling, or the payout formula. `market_competitiveness` has no published calculation here.|
|[Official historical liquidity-mining code](https://github.com/Polymarket/polymarket-liq-mining/blob/57d2271285e1421a40cd1bd21a1c6a6beb268e05/snapshots/src/clob-liq.ts)|Official source, commit `57d2271285e1421a40cd1bd21a1c6a6beb268e05` (2023-12-07). Its snapshot code computes a historical maker score as `qfinal * allocationForMarket`.|The earlier liquidity-mining implementation was score/allocation-based, rather than a guaranteed full reward for each maker.|This repository predates the current CLOB rewards API by years. It is not evidence that today's `qfinal`, allocation, payout timing, or qualification rules are identical.|
|`https://docs.polymarket.com/developers/rewards/overview` and `https://polymarket.com/rewards`|Both official documentation/UI URLs were retried directly from this host on 2026-06-25 and timed out. The direct `clob.polymarket.com` host also timed out; the configured read-only proxy remained available.|The blocker is this host's network path, not a claim that Polymarket lacks documentation.|The authoritative prose formula could not be read or validated here.|

## Observed current API shape

The public current-market endpoint returned entries of this form (values vary by market):

```json
{
  "condition_id": "0x...",
  "rewards_config": [{
    "asset_address": "0x...",
    "start_date": "2026-06-24",
    "end_date": "2500-12-31",
    "rate_per_day": 162,
    "total_rewards": 0,
    "id": 0
  }],
  "rewards_max_spread": 4.5,
  "rewards_min_size": 20,
  "native_daily_rate": 162,
  "total_daily_rate": 162
}
```

This establishes available metadata only. It does **not** establish that `total_daily_rate` is a pool shared pro rata, that `rate_per_day` is a guaranteed payout, or that a maker can capture all of either amount.

## Verification matrix

|Question|Status|Decision-use consequence|
|---|---|---|
|What does the live daily-rate field represent economically?|**Unverified.**|Do not treat any advertised rate as attainable revenue.|
|Exact maker score equation|**Unverified for the current program.**|Do not estimate a production share from quote size, spread, or time at touch.|
|Payout allocation among makers|**Unverified for the current program.** Historical code was score/allocation-based, but that is not a current-rule assertion.|The simulator's 0.01%/0.05%/0.10% shares remain sensitivity cases, not a verified Polymarket formula.|
|Both-outcome quoting requirement|**Unverified.**|Do not infer required capital from a live program rule.|
|Fill requirement and treatment of filled orders|**Unverified.**|Do not infer earnings from resting-order behavior.|
|Minimum size and maximum spread metadata|**Observed, but exact scoring boundary/units are unverified.**|Use only as a coarse research filter.|
|Payout cadence, settlement, and asset mechanics|**Unverified.**|Do not annualize or compound prospective rewards.|
|Order scoring exists|**Verified as an official API surface.**|No order was created to test it; its boolean result would not reveal the formula anyway.|

## Resulting action

The formula gate fails. Combined with negative paper-simulation EV at every tested capital level and a p95 read latency of 1861 ms, there is no justified reward-farming continuation path from this host.

The next research track is **paper-only cross-venue pricing**: map equivalent Polymarket/Kalshi contracts, normalize fees and settlement rules, measure quote-age/availability, and estimate executable edge without submitting orders. Keep `execution.dry_run: true`, passive market-making paused, and all live trading NO-GO.
