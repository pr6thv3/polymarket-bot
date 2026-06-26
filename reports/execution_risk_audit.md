# Execution and Order-State Risk Audit

## Answer

Execution is safer than before: the local amend fallback token-ID bug is fixed and tested. It is still not live-capital ready because exchange restart reconciliation and live amend/cancel semantics are unproven.

|Issue|Evidence|Profit impact|Required fix/gate|
|---|---|---|---|
|POST_ONLY intent exists|`config.yaml:140`; `Executor.place_order(... post_only=True)` for quotes|Protects against taker fees|Verify actual CLOB OrderType semantics before capital|
|Cancel+replace fallback token_id bug|Fixed in current code; tests cover cancel-replace with stored `record.token_id` and fail-closed behavior when token ID is missing|Material bug risk reduced, but live amend semantics still unproven against exchange|Keep live amendment disabled until exchange reconciliation/drill passes|
|Partial quote allowed|`place_quote_pair` can place one side if other fails|One-sided exposure/inventory risk|Partial quote rate <1%, alert/cancel lonely quotes|
|Pending timeout assumes OPEN|OrderStore promotes old PENDING to OPEN without exchange reconciliation|Ghost/open state mismatch|Exchange reconciliation before live|
|Restart reconciliation not proven|Startup initializes portfolio/strategies; no inspected CLOB open-order reconciliation|Stale live orders after crash|Zero unreconciled orders after restart drill|
|Emergency cancel local-store dependent|`emergency_cancel_all` cancels markets from local open orders|Useful only if local store matches exchange|Reconcile local vs exchange open orders|

## Live trading implication

No live capital until restart/open-order reconciliation is demonstrated against the real CLOB/proxy path.
