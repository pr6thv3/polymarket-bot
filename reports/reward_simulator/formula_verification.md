# Reward Formula Verification Retry

Generated: 2026-06-24T18:26Z

## Bottom line

**Reward formula remains partially unverified; live reward farming remains NO-GO.**

## Sources attempted

Primary/high-quality sources attempted from this host:

- `https://docs.polymarket.com/developers/rewards/overview` via Python `urllib`: timed out after ~20s.
- `https://docs.polymarket.com/llms.txt` via Python `urllib`: timed out after ~20s.
- `https://polymarket.com/rewards` via Python `urllib`: timed out after ~20s.
- `https://docs.polymarket.com/developers/rewards/overview` via agent-browser MCP: timed out after 120s.
- Official GitHub source `https://raw.githubusercontent.com/Polymarket/py-clob-client/main/py_clob_client/endpoints.py`: HTTP 200 and reachable.
- Live CLOB API response fields via configured client/proxy: reachable and used in `reports/reward_candidate_markets.json`.

## Verified snippets

Official SDK endpoint surface from Polymarket `py-clob-client`:

```text
IS_ORDER_SCORING = "/order-scoring"
ARE_ORDERS_SCORING = "/orders-scoring"
GET_MARKETS = "/markets"
GET_MARKET = "/markets/"
```

Live CLOB market reward metadata fields observed in candidate JSON:

```json
{
  "reward_daily_rate_sum": 3333.0,
  "reward_min_size": 200.0,
  "reward_max_spread_raw": 4.5,
  "reward_assets": ["0x2791bca1f2de4661ed88a30c99a7a9449aa84174"],
  "minimum_order_size": 5.0
}
```

## Verification table

| Question | Status |
|---|---|
| Is `rewards_daily_rate` a total pool or per-user possible payout? | **Unverified**. Simulator treats it as a total pool and applies pro-rata shares; it never assumes full capture. |
| Is payout pro-rata? | **Unverified**. Modeled with pessimistic/base/optimistic pro-rata shares: 0.01%, 0.05%, 0.10%. |
| Does earning require both-side quoting? | **Unverified** from official docs. Simulator assumes capital for two-sided hypothetical quoting when sizing min capital. |
| Does earning require actual fills? | **Unverified**. Simulator assumes resting orders and models fills only as adverse risk, not required income. |
| Does earning require resting orders only? | **Unverified**. Official SDK exposes order-scoring endpoints, but no live order was placed/scored. |
| How is scoring calculated? | **Unverified**; blocked on docs/UI access or official formula source. |
| Minimum order size | Observed from live CLOB fields: `minimum_order_size`, `rewards.min_size`. |
| Max spread | Observed from live CLOB field `rewards.max_spread`; exact unit/formula remains unverified. |
| Payout timing | **Unverified**. |
| Payout asset | Observed from `rewards.rates[].asset_address`; USDC address observed in top candidates. |
| Are rewards active now? | **Yes at metadata level**: live CLOB market payloads include non-empty `rewards.rates`. |

## Action required before live reward farming

Verify the official scoring and payout formula from a network path that can load Polymarket docs/UI, or from an official source code/API reference that explicitly defines reward scoring. Until then, the only acceptable next step is paper simulation or a pivot away from reward farming.
