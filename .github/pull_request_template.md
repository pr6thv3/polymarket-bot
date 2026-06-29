## Summary

Describe the change and why it is needed.

## Safety checklist

- [ ] I did not add live order placement, deposits, or authenticated trading endpoints.
- [ ] I did not call `core/client.py create_order` or live paths in `core/executor.py`.
- [ ] Research code remains isolated from legacy execution-capable modules.
- [ ] I did not add unsupported profitability, reward, or live-readiness claims.
- [ ] I updated docs/tests for public behavior changes.

## Required checks

- [ ] `python tools/cross_venue_research.py verify-contracts`
- [ ] `python -m pytest tests/ -q`
- [ ] `python tools/software_health_report.py`
