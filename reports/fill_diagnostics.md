# Fill Diagnostics — Phase 3B

Generated: 2026-06-23T16:57:59Z

## Answer

The long paper run was stopped because it was producing weak signal: many quotes, zero fills, and intermittent network degradation. The collected order-book data is still useful for offline diagnostics.

## Live run summary before stop

|Metric|Value|
|---|---|
|Paper orders logged|390|
|Paper fills logged|0|
|Error/exception lines|318|
|Latest MM summary|`{"total_markets": 5, "active_markets": 5, "paused_markets": 0, "cycles_completed": 10748, "total_errors": 0, "orders_placed": 390, "orders_filled": 0, "strategy_enabled": true, "ev…`|
|Latest paper stats|`{"mode": "PAPER_TRADING", "orders_placed": 390, "fills": 0, "cancelled": 380, "rejected": 0, "open_orders": 10, "slippage_bps": 3.0, "fill_probability": "85%", "starting_capital": …`|


## Backtest on collected data

|Metric|Value|
|---|---|
|Starting capital|$1,000.00|
|Ending capital|$994.64|
|Net P&L|$-5.36|
|Gross spread captured|$0.00|
|Rebates|$0.00|
|Holding rewards|$0.00|
|Estimated gas|$5.36|
|Quotes generated|1078|
|Quotes rejected|0|
|POST_ONLY rejection rate|0.0%|
|Total trades|0|


## Market movement diagnostics

|Market|Snapshots|Activity|Unique top|Top changes|Fill opp rate|First top|Last top|Mid range|
|---|---|---|---|---|---|---|---|---|
|0x1fad72fa…|15,192|41.1|6|598|1.44%|(0.5, 0.52)|(0.51, 0.52)|0.0200|
|0x32b09f63…|6|0.0|1|0|0.00%|(0.49, 0.5)|(0.49, 0.5)|0.0000|
|0x50ddb9cd…|15,187|38.3|12|271|2.00%|(0.52, 0.53)|(0.54, 0.57)|0.0350|
|0x84f8b703…|15,192|13.5|2|1|1.71%|(0.5, 0.51)|(0.49, 0.5)|0.0100|


## Interpretation

- The selected markets were extremely sticky and produced no official backtest trades.
- The loss was entirely simulated gas (`$4.53`) with no spread capture or rebates.
- This is a market-selection / quote-competitiveness problem, not a POST_ONLY rejection problem (`0.0%` rejection rate).

## Confidence

High that Phase 3 should use offline market diagnostics before more live waiting.
