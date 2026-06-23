# Economic Assumptions Audit

|Assumption|Current source|Classification|Action|
|---|---|---|---|
|Maker fee = 0|`core/backtest.py:327`; paper portfolio assumes maker|Plausible but verify current Polymarket rules|Never allow taker unless explicitly modeled|
|Taker fee schedule|`core/client.py:20-27`; `config.yaml:8-15`|Unverified in this audit|Do not use stale hardcoded fees for live P&L|
|Rebate rates|`core/client.py:29-36`; `config.yaml:16-22`|Unverified / conditional|Exclude until reward eligibility is proven|
|Holding rewards 4% APY|`config.yaml:40-43`; risk loop logs estimates|Unverified|Treat as zero until reconciled|
|Gas per quote|Backtest uses $5.36 / 1078 quotes|Model parameter, not exchange bill|Separate off-chain ops from settlement/redemption costs|
|Capital efficiency|$15 order size, 5 max active markets, 5% max position|Small capital may be dominated by fixed costs/no-fill time|Compute return on locked capital|

## Conclusion

A positive synthetic P&L that depends on rebates/holding rewards is not deployable unless those revenues are independently verified. Latest real-data result has zero rebates and zero spread capture.
