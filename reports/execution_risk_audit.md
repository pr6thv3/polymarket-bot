# Execution and Order-State Risk Audit

## Answer

Execution is safer than before but still not live-capital ready because restart reconciliation and edge-case semantics are unproven.

|Issue|Evidence|Profit impact|Required fix/gate|
|---|---|---|---|
|POST_ONLY intent exists|`config.yaml:140`; `Executor.place_order(... post_only=True)` for quotes|Protects against taker fees|Verify actual CLOB OrderType semantics before capital|
|Cancel+replace fallback token_id bug risk|`core/executor.py:292-298` calls `client.create_order(token_id=record.market_id, ...)`|Invalid replacement/failure during live amendment fallback|Fix before using amend fallback live|
|Partial quote allowed|`place_quote_pair` can place one side if other fails|One-sided exposure/inventory risk|Partial quote rate <1%, alert/cancel lonely quotes|
|Pending timeout assumes OPEN|OrderStore promotes old PENDING to OPEN without exchange reconciliation|Ghost/open state mismatch|Exchange reconciliation before live|
|Restart reconciliation not proven|Startup initializes portfolio/strategies; no inspected CLOB open-order reconciliation|Stale live orders after crash|Zero unreconciled orders after restart drill|
|Emergency cancel local-store dependent|`emergency_cancel_all` cancels markets from local open orders|Useful only if local store matches exchange|Reconcile local vs exchange open orders|

## Live trading implication

No live capital until restart/open-order reconciliation is demonstrated against the real CLOB/proxy path.
