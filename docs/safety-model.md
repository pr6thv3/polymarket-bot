# Safety Model

The safety boundary is architectural. `execution.dry_run: true` is required, but it is
not treated as sufficient.

## Primary controls

- Research tools use `ReadOnlyTransport`.
- The transport rejects write methods, request bodies, credentialed URLs, signing
  headers, and known trading credentials in the process environment.
- The research package is import-isolated from legacy execution-capable modules.
- Replay is deterministic and offline.
- Approved mappings are manual-only; auto-discovery can only create candidates.

## What is intentionally not allowed

- no deposits;
- no live orders;
- no authenticated trading endpoints;
- no live WebSockets;
- no calls to `core/client.py create_order`;
- no calls through `core/executor.py` live order paths;
- no rewards/rebates credited without primary-source verification.

## Verification

Run:

```bash
.venv\Scripts\python.exe tools/software_health_report.py
```

The report proves the current software safety posture. It does not prove profitability.
