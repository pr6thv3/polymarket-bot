# Legacy Execution API Review Notes

This document tracks Gate B technical assumptions for the legacy live-capable runtime.
It is not live approval.

## Current SDK posture

- The locked package is `py_clob_client==0.34.6`.
- The legacy client now delegates order signing to the SDK builder instead of keeping a
  local nonce cache.
- The SDK `post_order` method accepts a `post_only` argument, and the legacy client now
  forwards the configured `post_only` value.
- Live writes are blocked before SDK initialization unless the live guard passes.

## RFQ and Combos awareness

RFQ and Combos flows can change what counts as executable liquidity, routing, and order
lifecycle behavior. They are not part of the current supported research runtime.

Before any live execution review, the maintainer must verify from current official
venue sources:

- whether normal CLOB order APIs remain the intended path for the canary order type;
- whether RFQ flow has different signing, matching, cancellation, or settlement rules;
- whether Combos introduce multi-leg atomicity or partial-fill semantics that the
  legacy order store cannot represent;
- whether fee, rebate, or reward treatment differs for RFQ or Combos;
- whether order-status polling surfaces distinguish normal CLOB orders from RFQ/Combo
  orders.

Until this review is complete, RFQ and Combos are excluded from the live canary scope.

## Authenticated read-only probe

`tools/polymarket_authenticated_readonly_probe.py` exists for a future Gate B run with
credentials. It is disabled unless `ALLOW_AUTH_READONLY_PROBE=TRUE` and only calls
read-only account metadata methods. It does not create, post, amend, cancel, or score
orders.
