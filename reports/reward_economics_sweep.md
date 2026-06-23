# Reward Economics Sweep

Generated: 2026-06-23T19:35:23Z

Assumptions used for this read-only model:

- API `rewards_daily_rate` is treated optimistically as daily reward captured by the account. If rewards are pro-rata against other makers, these estimates are too high.
- Gas/quote-refresh cost set to `$0` because CLOB orders are off-chain; settlement/withdrawal costs are not included.
- Probability of adverse fill event: `2%/day`.
- Adverse-selection loss if filled: `1%` of deployed capital.
- Opportunity cost: `5% APY`.
- Spread income is modeled separately, but reward farming should not rely on frequent fills.

|Capital|Best candidate|Expected daily reward|Expected daily loss|Expected net EV|Annualized return|Min meaningful capital|Small account viable|
|---|---|---|---|---|---|---|---|
|$50|Will France win the 2026 FIFA World Cup?|3333.000000|$0.0168|$3332.9842|2433078.43%|$400|yes|
|$100|Will France win the 2026 FIFA World Cup?|3333.000000|$0.0337|$3332.9683|1216533.43%|$400|yes|
|$250|Will France win the 2026 FIFA World Cup?|3333.000000|$0.0842|$3332.9208|486606.43%|$400|yes|
|$500|Will France win the 2026 FIFA World Cup?|3333.000000|$0.1685|$3332.8415|243297.43%|$400|no|
|$1000|Will France win the 2026 FIFA World Cup?|3333.000000|$0.3370|$3332.6830|121642.93%|$400|no|
|$5000|Will France win the 2026 FIFA World Cup?|3333.000000|$1.6849|$3331.4151|24319.33%|$400|no|


Conclusion: some API-visible daily reward rates are large enough to justify further paper/simulator work if the units and pro-rata scoring formula are confirmed. These numbers are **not live-trading approval** because the model currently assumes full daily reward capture and docs/payout formula remain unresolved.
