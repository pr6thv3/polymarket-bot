# Fee Model

Route economics must use fee metadata captured with the observation. Static category
tables, rebates, and incentive assumptions are not sufficient proof.

## Rules

- Use executable prices and depth, not midpoint or last trade.
- Require dynamic fee metadata for each accepted route.
- Apply venue rounding rules.
- Preserve observations with missing fee data as rejected rows.
- Count rewards, rebates, and liquidity programs as zero until independently verified
  from primary sources.

## Current posture

Reward farming remains `NO-GO`. The official reward payout formula is not fully
verified from this environment, and current paper EV is negative under tested pro-rata
assumptions.
