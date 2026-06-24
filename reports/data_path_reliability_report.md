# Data-Path Reliability Report

Generated: `2026-06-24T18:26:15+00:00`

This is read-only. It does not place, amend, cancel, or submit orders.

## Metrics

|Metric|Value|
|---|---:|
|Endpoint tested|CLOB get_markets + sampled get_orderbook (read-only)|
|Total requests|40|
|Successful requests|40|
|Failed requests|0|
|Error rate|0.00%|
|Average latency|959 ms|
|p50 latency|811 ms|
|p95 latency|1861 ms|
|p99 latency|2384 ms|
|Timeout count|0|
|Retry count available|0|
|Max consecutive failures|0|

## Gate results

|Gate|Result|
|---|---|
|Latency-sensitive strategies|FAIL|
|Reward simulator/read-only research|PASS|
|Simulator results reliable|YES|

## Prior blocker

Previous collector: 161 errors / 346 iterations = 46.5% error rate.

## Reasons

- latency-sensitive p95 latency 1861ms >= 1000ms

## Recent errors

- `none`
