# Operational and Proxy Risk Audit

## Answer

The Cloudflare proxy path is workable for data access but is an unpriced trading risk until latency, timeout, and stale-quote rates are measured continuously.

|Risk|Evidence|Profit impact|Required gate|
|---|---|---|---|
|Proxy dependency|`core/client.py:122-124` host is Cloudflare Worker proxy|Latency/staleness can turn maker quotes toxic|p95 orderbook/order latency <750ms|
|Rate limit|`config.yaml:136 rate_limit_per_min: 55`|May prevent timely cancels across multiple markets|No missed cancels from rate limit in 72h paper|
|Circuit breaker|`config.yaml:143-146`; opens after 10 errors/60s for 300s|Protects from repeated failures but can pause trading|0 circuit breaker events during paper validation|
|Health monitor interval|main enforces min 60s health checks|Too slow for sub-minute toxicity|Add latency histogram to data collector|
|Portfolio persistence|main saves every 60s and shutdown|Does not prove exchange-order reconciliation|Controlled restart drill required|

## Conclusion

No live market making until proxy latency and restart reconciliation pass gates.
