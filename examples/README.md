# Examples

The examples are fixture-first and safe for new contributors.

## Verify contracts

```bash
.venv\Scripts\python.exe tools/cross_venue_research.py verify-contracts
```

## Generate software health report

```bash
.venv\Scripts\python.exe tools/software_health_report.py
```

## Generate candidates without writing output

```bash
.venv\Scripts\python.exe tools/generate_candidates.py --dry-run
```

## What examples do not do

- no live orders;
- no deposits;
- no authenticated trading endpoints;
- no profitability claim.
