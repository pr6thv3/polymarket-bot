# Market-Making Economics Audit

## EV equation required before live trading

```text
EV_per_quote = P(fill) * (half_spread + verified_rebate - adverse_markout - inventory_cost)
               - operational_cost_per_quote - cancel_replace_cost
```

## Current evidence

|Input|Current evidence|Status|
|---|---|---|
|P(fill)|Backtest trades=0; best prior opportunity ≈2.08%; markout diagnostic fills 18 / 1018|Fails proceed gate|
|Spread capture|gross_spread_captured_usd=0.0|No realized evidence|
|Rebates|rebates_earned_usd=0.0; config assumes category rates|Unverified for live eligibility|
|Holding rewards|holding_rewards_usd=0.0; config target APY 4%|Unverified / exclude until proven|
|Gas/operational cost|estimated_gas_costs_usd=5.36 over 1078 quotes|Dominates because fills are zero|
|Adverse selection|0x1fad=200%, 0x50dd=111%, 0x84f8=100% of gross edge at 60s|High|
|Inventory cost|No realized roundtrips; no inventory decay/hedge evidence|Unproven|

## Profitability conclusion

Current market making does **not** have a defensible positive EV equation on real data. The bot can quote, but it has not shown it can get filled profitably. Wide spreads are mostly no-flow traps; tighter spreads increase toxicity risk.

## Highest-ROI economic fix

Do not tune spreads blindly. First collect targeted data on markets with top-of-book churn and measure fill markout. Only tune spread/TTL/size after fill rate and toxicity pass gates.
