# Usage Guide

This guide covers the supported read-only research workflow. The legacy live-capable
bot is documented separately in `docs/legacy-live-bot.md` and remains `NO-GO` for live
trading.

## Install

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

No wallet, exchange API key, deposit, or trading credential is required for the
supported workflow.

## Verify source contracts

```bash
.venv\Scripts\python.exe tools/cross_venue_research.py verify-contracts
```

This validates committed sanitized fixtures against the pinned source-contract files.

## Run tests

```bash
.venv\Scripts\python.exe -m pytest tests/ -q
```

All tests must pass before a change is considered healthy.

## Generate the software health report

```bash
.venv\Scripts\python.exe tools/software_health_report.py
```

Outputs:

- `reports/software_health_report.md`;
- `reports/software_health_report.json`.

The report proves the software-health gate only. It does not prove profitability.

## Generate mapping candidates

```bash
.venv\Scripts\python.exe tools/generate_candidates.py --dry-run
```

Candidate generation validates every paginated listing response before aggregation.
Candidates are written separately from the approved catalog and are not replay-eligible.

## Approve mappings

Manual review is required before a mapping enters replay. See
`docs/mapping-review.md`.

Approved mappings must live in `research_mappings/catalog.yaml` with full semantic
review fields.

## Capture and replay

Capture requires at least one approved mapping:

```bash
.venv\Scripts\python.exe tools/cross_venue_research.py capture `
  --duration-hours 24 `
  --interval-seconds 60
```

Replay a completed run:

```bash
.venv\Scripts\python.exe tools/cross_venue_research.py replay `
  --run-dir data/research_runs/<run-id> `
  --mapping-catalog research_mappings/catalog.yaml
```

The first 24-hour capture is a data-quality baseline. It measures quote age, pair
skew, missing-depth rate, rejection stability, and market concentration. It does not
assert profitability.

## Profitability evidence

Do not call a strategy profitable unless it passes `docs/proof_standard.md` Gate 2:

- at least 10 approved mappings;
- at least 14 calendar days of forward paper capture;
- realistic executable quotes, depth, fees, rounding, and rejections;
- positive conservative lower confidence bound after all costs;
- rewards/rebates counted as zero unless independently verified.

## Live trading

Live trading remains `NO-GO`.

Do not enable live orders, deposits, authenticated trading endpoints, WebSockets, or
executor/client order paths without a separate legal/compliance review, strategy
evidence pack, canary plan, and explicit user approval.
