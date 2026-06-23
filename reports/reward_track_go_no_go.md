# Reward Track Go/No-Go

Generated: 2026-06-23T19:35:23Z

## Final recommendation

**BUILD REWARD FARMING PAPER SIMULATOR**

Live trading remains **NO-GO**. Passive market-making remains paused. Reward farming live deployment is also **NO-GO** until official docs/scoring/payout rules are verified, but the read-only CLOB reward metadata is promising enough to continue in simulator mode.

## Evidence

- Official docs/rewards page could not be fetched from this environment; payout timing/formula and whether fills/both-side quoting are required remain unresolved.
- Live official CLOB market payloads do include reward metadata: `rewards.rates`, `rewards.min_size`, `rewards.max_spread`, and `minimum_order_size`.
- Observed reward rates range from `0.001` on GTA/culture markets to thousands per day on sports markets in USDC-denominated API fields; units and pro-rata allocation must be verified before trusting them.
- Fresh read-only scan found `25` reward-markets with valid YES/NO books in the first scanned page range.
- Prior Phase 3C collector reliability was weak: `161` errors over `346` iterations (`46.5%`). This is an operational blocker for latency-sensitive strategies and a reason to keep reward validation read-only/paper until the data path is reliable.

## Best modeled capital sweep row

```json
{
  "capital_usd": 50,
  "market_id": "0x9b6fef249040fd17e9c107955b37ac2c3e923509b6b0ff01cc463a331ddeb894",
  "question": "Will France win the 2026 FIFA World Cup?",
  "expected_daily_reward": 3333.0,
  "expected_daily_loss": 0.016849315068493152,
  "expected_net_ev": 3332.9841506849316,
  "annualized_return": 24330.784300000003,
  "min_capital_meaningful": 400.0,
  "small_account_viable": true
}
```

## Gates

|Gate|Status|
|---|---|
|current official reward rules verified|FAIL — docs unreachable; API fields verified only|
|eligible markets found from live data|PASS|
|expected net EV positive after gas/adverse selection|PROVISIONAL PASS — optimistic full-capture model positive, but not trusted for live|
|reward income does not depend on unrealistic assumptions|FAIL — estimates assume full daily reward capture and unverified scoring|
|minimum capital realistic for user|UNKNOWN|
|operational risk acceptable|FAIL/UNKNOWN — reward scoring/payout unresolved|
|no live order placement in verification|PASS|


## Assumptions

- Reward daily rate treated as account-captured daily reward for an optimistic upper bound.
- No CLOB quote-refresh gas; opportunity cost and adverse selection included.
- No live orders placed.

## Exact next action

Build a reward-farming paper simulator that never places live orders: fetch reward markets, compute hypothetical order scoring with `min_size`/`max_spread`, estimate pro-rata reward share, and compare against adverse-fill risk. In parallel, re-try official docs/UI verification from a network path that can reach `docs.polymarket.com`.
