# Audit Baseline

Generated: 2026-06-23T16:xxZ

## Safety / status commands

### `git status --short`

```text
M config.yaml
M data/backtest/0x1fad72fae204143ff1c3035e99e7c0f65ea8d5cd9bd1070987bd1a3316f772be.jsonl
M data/backtest/0x50ddb9cd80d5c271664a2ebb7fcaed1d0a148d82c8e8d314d830f75a944c3dcc.jsonl
M data/backtest/0x84f8b70331323c2fba97d7ceaa9a35fb645a0770d0dbff169d07f24f376766e9.jsonl
M data/market_scanner.py
M tests/test_market_scanner.py
?? .hermes/
?? data/backtest/results/MarketMaking_20260623_141329.json
?? data/backtest/results/MarketMaking_20260623_154404.json
?? data/market_activity.py
?? reports/
?? task.md
?? tests/test_market_activity.py
?? tools/__init__.py
?? tools/current_market_snapshot.py
?? tools/phase3b_diagnostics.py
?? walkthrough.md
```

### `.venv/Scripts/python.exe -m pytest tests/ -q`

```text
422 passed in 3.72s
```

### Safety grep

```text
139:  dry_run: true
140:  post_only_default: true
```

Direct Python references to `clob.polymarket.com`: none found by grep.

## Latest official backtest result

Path: `data/backtest/results/MarketMaking_20260623_154404.json`

|Metric|Value|
|---|---|
|starting_capital|1000.0|
|ending_capital|994.64|
|net_pnl|-5.360000000000014|
|gross_spread_captured_usd|0.0|
|rebates_earned_usd|0.0|
|holding_rewards_usd|0.0|
|estimated_gas_costs_usd|5.36|
|quotes_generated|1078|
|quotes_rejected|0|
|rejection_rate|0.0|
|total_trades|0|
|win_rate|0.0|
|profit_factor|0.0|
|max_drawdown_pct|0.0|

## Live read-only snapshot evidence

- Valid books sampled: 34
- Markets passing shallow spread/liquidity gate: 4
- Source: `reports/current_market_snapshot.json`

## Immediate conclusion

Baseline remains **NO-GO for live trading**: current real-data backtest is negative with zero trades, and current live snapshot is candidate discovery only.
