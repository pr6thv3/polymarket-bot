# Reward Rules Verification

Generated: 2026-06-23T19:35:23Z

## Source status

Primary Polymarket docs were attempted but unreachable from this host during the run:

- `https://docs.polymarket.com/developers/rewards/overview` — connection timed out.
- `https://docs.polymarket.com/llms.txt` — connection timed out.
- `https://polymarket.com/rewards` — connection timed out.

Because the docs could not be fetched, this report treats the official live CLOB market payload and official Polymarket SDK repository as the verified sources available from this environment. This confirms active reward metadata exists, but does **not** fully verify payout timing/formula. Therefore reward farming remains **NO-GO**.

## Verified from official/high-quality sources

### Official CLOB API / SDK endpoint surface

Source: Polymarket `py-clob-client` GitHub `py_clob_client/endpoints.py`.

Quoted snippet:

```text
IS_ORDER_SCORING = "/order-scoring"
ARE_ORDERS_SCORING = "/orders-scoring"
GET_MARKETS = "/markets"
GET_MARKET = "/markets/"
```

Interpretation: Polymarket exposes order-scoring endpoints and market metadata endpoints in the official client. Scoring can be checked, but this task did not place live orders.

### Official CLOB market payload reward fields

Source: live CLOB `get_markets` via configured Polymarket client/proxy.

Observed reward payload example:

```json
{
  "rewards": {
    "rates": [{
      "asset_address": "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb",
      "rewards_daily_rate": 0.001
    }],
    "min_size": 0,
    "max_spread": 0
  },
  "minimum_order_size": 5,
  "minimum_tick_size": 0.01
}
```

Another observed market:

```json
{
  "rewards": {
    "rates": [{
      "asset_address": "0x2791bca1f2de4661ed88a30c99a7a9449aa84174",
      "rewards_daily_rate": 0.001
    }],
    "min_size": 20,
    "max_spread": 3.5
  },
  "minimum_order_size": 5,
  "minimum_tick_size": 0.001
}
```

## Rule fields verified from live API

| Rule item | Current verification |
|---|---|
| Liquidity/maker rewards active in 2026 | Live CLOB markets include non-empty `rewards.rates` on 2026-06-23/24. |
| Eligible markets | Markets with non-empty `rewards.rates` in CLOB `/markets` payload. |
| Minimum order size | Market payload includes `minimum_order_size`; reward payload includes `rewards.min_size`. |
| Max spread requirement | Reward payload includes `rewards.max_spread`; observed values include `0` and `3.5`. Unit/formula unresolved from docs. |
| Reward payout asset | Reward payload includes `asset_address`; `0x2791bca1f2de4661ed88a30c99a7a9449aa84174` is Polygon USDC, `0xc011...` remains unresolved. |
| Reward daily rate | Reward payload includes `rewards_daily_rate`; observed value `0.001`. Unit/pro-rata formula unresolved. |
| Actual fills required? | Not verified from docs. Presence of order-scoring endpoints suggests resting order scoring exists, but exact formula is unresolved. |
| Both-side quoting required? | Not verified from docs. Economic model assumes both-side capital because reward farming normally requires balanced quoting; must verify before live use. |
| Small capital eligibility | API minimum sizes (`5`, reward `min_size` `0` or `20`) suggest small orders may pass mechanical size fields, but economics are too small. |
| Payout timing | Not verified from accessible sources. |

## Hard conclusion

Official docs could not be fetched, but live API fields show active reward rates including large USDC-denominated daily rates on sports/politics markets. Reward farming is **not approved for live trading** until docs/payout formula are independently verified, but the magnitude of observed API rates justifies a paper reward-farming simulator.
