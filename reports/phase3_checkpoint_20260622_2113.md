# Phase 3 Checkpoint — 2026-06-22T21:13Z

## Process status

| Component | Session | PID | Status | Uptime at poll |
|---|---|---:|---|---:|
| Paper trading bot | `proc_fe4f276218f4` | 21076 | running | ~1082 sec |
| Data collector | `proc_6780f88c0f29` | 17000 | running | ~996 sec |

## Portfolio snapshot from `state/portfolio.json`

```json
{
  "free_usdc": 1000.0,
  "locked_usdc": 0.0,
  "initial_capital": 1000.0,
  "current_day": "2026-06-22",
  "positions": {},
  "daily_pnl": {
    "2026-06-12": {
      "realized_pnl": 0.0,
      "unrealized_pnl_start": 0,
      "unrealized_pnl_end": 0.0,
      "spread_captured": 0.0,
      "rebates_earned": 0.0,
      "holding_rewards_earned": 0.0
    },
    "2026-06-22": {
      "realized_pnl": 0.0,
      "unrealized_pnl_start": 0,
      "unrealized_pnl_end": 0.0,
      "spread_captured": 0.0,
      "rebates_earned": 0.0,
      "holding_rewards_earned": 0.0
    }
  },
  "saved_at": "2026-06-22T21:13:24.896227+00:00"
}
```

## State files

Only `state/portfolio.json` exists. No `state/paper_orders.json` found.

## Paper order tracking finding

`state/portfolio.json` is the real `Portfolio` state, not the in-memory `PaperPortfolio` state. It reports `locked_usdc: 0.0` even while the paper executor stats log reports open orders and locked virtual capital.

Latest paper stats log evidence:

```json
{
  "mode": "PAPER_TRADING",
  "orders_placed": 10,
  "fills": 0,
  "cancelled": 0,
  "rejected": 0,
  "open_orders": 10,
  "locked_usdc": 144.47,
  "free_usdc": 855.53,
  "net_pnl": 0.0,
  "event": "Paper trading stats",
  "timestamp": "2026-06-22T21:11:24.727346Z"
}
```

Source evidence:

- `PaperExecutor` stores virtual orders in memory at `self._orders`.
- `PaperExecutor.get_stats()` reports open orders from `self._orders` and locked USDC from `PaperPortfolio`.
- `main._portfolio_save_loop()` saves only `self.portfolio.save_state()`, i.e. the real portfolio object, not `self.paper_portfolio`.

Conclusion: while the process is alive, paper order tracking appears active in memory and fills can still occur. However, paper orders / paper portfolio are not persisted to `state/`, so `state/portfolio.json` is misleading for paper-mode open-order capital and restart recovery would lose open paper orders.

## Log counts so far

| Metric | Count / value |
|---|---:|
| Market scans | 4 |
| Latest eligible markets | 5 |
| MM summaries | 4 |
| Cycles completed | 150 |
| Paper orders placed | 10 |
| Open paper orders | 10 |
| Paper fills | 0 |
| Rejected | 0 |
| Real error-like lines | 0 |
| Health OK | 1 |
| Adverse mentions/pauses | 0 |
| Telegram/alert mentions | 0 |

Latest scan:

```json
{"total": 46413, "eligible": 5, "top": 5, "errors": 0, "event": "Market scan complete", "timestamp": "2026-06-22T21:11:22.080678Z"}
```

Latest MM summary:

```json
{"total_markets": 5, "active_markets": 5, "paused_markets": 0, "cycles_completed": 150, "total_errors": 0, "orders_placed": 10, "orders_filled": 0, "strategy_enabled": true, "event": "MM summary", "timestamp": "2026-06-22T21:11:24.725331Z"}
```

## Backtest data collection

| File | Snapshots | Size |
|---|---:|---:|
| `0x1fad72fae204143ff1c3035e99e7c0f65ea8d5cd9bd1070987bd1a3316f772be.jsonl` | 379 | 461,256 bytes |
| `0x50ddb9cd80d5c271664a2ebb7fcaed1d0a148d82c8e8d314d830f75a944c3dcc.jsonl` | 379 | 387,758 bytes |
| `0x84f8b70331323c2fba97d7ceaa9a35fb645a0770d0dbff169d07f24f376766e9.jsonl` | 379 | 426,044 bytes |

## Flags

- Processes alive: OK.
- Backtest JSONL files non-empty: OK.
- Error count growing: no evidence.
- Locked USDC: **state file shows $0, but live paper executor logs show $144.47 locked.** This is not blocking current live fills, but it is a paper-state persistence/reporting gap to fix after the current validation or with explicit permission.
