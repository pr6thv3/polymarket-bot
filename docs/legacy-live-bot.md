# Legacy Live-Capable Bot

The repository still contains an older execution-capable bot runtime:

- `main.py`;
- `core/`;
- `data/`;
- `strategies/`;
- `utils/`.

This code is kept for auditability, tests, and future refactoring. It is not the
supported public entrypoint and is not live-ready.

## Current policy

- live trading remains `NO-GO`;
- passive market making is paused;
- reward farming is `NO-GO`;
- execution-capable strategies remain disabled in `config.yaml`;
- `execution.dry_run` must remain `true`.

Do not enable live trading from this code without a separate legal/compliance review,
strategy evidence pack, canary plan, and explicit user approval.
