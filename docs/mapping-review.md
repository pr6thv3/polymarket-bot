# Mapping Review

Cross-venue comparisons are only valid when the contracts are semantically equivalent.
Title similarity is not enough.

## Candidate generation

`tools/generate_candidates.py` may create candidate pairs from public listing data. It
uses page-level source-contract validation before aggregating paginated results.

Candidates are not replay-eligible.

## Promotion requirements

An approved mapping must include:

- Polymarket condition and YES/NO token IDs;
- Kalshi event, market, and series tickers;
- canonical proposition;
- YES predicate;
- resolution source;
- UTC cutoff and timezone;
- payout convention;
- invalidation behavior;
- wording, timing, payout, and resolution-risk evidence;
- reviewer identity;
- reviewed timestamp;
- immutable version.

Only `status: approved` mappings in `research_mappings/catalog.yaml` enter replay.

## Current state

The catalog is intentionally empty until manual review is complete. Therefore no
profitability replay claim can be made yet.
