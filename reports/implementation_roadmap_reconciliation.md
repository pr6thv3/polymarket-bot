# Codex Implementation Roadmap Reconciliation

Updated: 2026-06-27

## Safety posture

- Live trading remains **NO-GO**.
- `config.yaml` keeps `execution.dry_run: true`.
- All strategy enable flags in `config.yaml` remain false.
- This reconciliation is a repo-state artifact only. It does not approve live orders, deposits, authenticated WebSockets, or any use of `core/client.py create_order`.

## Why this artifact exists

The active roadmap warns that stale phase ordering can make Codex duplicate completed work or implement unspecified research decisions. This file records the current implementation status from the local worktree so future tasks can start from evidence rather than redoing or inventing work.

## Current evidence-backed status

| Roadmap item | Current status | Evidence |
| --- | --- | --- |
| Dependency pinning | Done | `requirements.lock` generated from the current `.venv` with exact pins. |
| Task 1.1: candidate-generation read-only endpoint unblocker | Done | `tools/generate_candidates.py` uses `ALLOWED_HOSTS = {gamma-api.polymarket.com, external-api.kalshi.com}` and validates listing pages before aggregation. |
| Page-level listing contract validation | Done | `fetch_polymarket(...)` and `fetch_kalshi(...)` call `validate_payload(...)` inside each pagination loop before extending market arrays. |
| Task 1.3: `POLY_TIMESTAMP` call-site audit | Stale in this checkout | `rg` finds only the read-only denied header name in `research/safety.py`; no trading timestamp call sites are present under `core/`, `data/`, `strategies/`, `tools/`, `research/`, or `tests/`. |
| Section 14/15 stale fee-model reconciliation | Stale in this checkout | No `polymarket_fee_model.py` or stale “build fee/rebate module” checklist exists in the current worktree. Current fee/reward formula remains unverified for live reward farming. |
| Task 2.1: `OrderBookManager` `_books` / `_markets` mismatch | Done | Legacy strategy token lookup now uses `OrderBookManager.get_snapshot(...)` and no longer reads a private `_markets` attribute; tests cover cross-platform arb and whale-tracking lookups. |
| Task 2.2: `OrderStore.get_recently_filled()` | Done | `core/order_state.py` implements `get_recently_filled(since: Optional[float] = None)` and tests cover one-shot polling plus since-filter behavior. |
| Task 2.3: `amend_order()` replacement token ID | Done | `tests/test_executor.py` covers cancel-replace using the stored record token ID and failing closed when token ID is missing. |
| Task 2.4: metrics/signature mismatches | Done | Metrics call-path tests pass, and `RiskManager.calculate_rebate_value(...)` now exists as a compatibility wrapper for the legacy fill-processing metric call. |
| Task 2.5: paper executor false-P&L bug | Done | Paper SELL without inventory is rejected; inventory reservation tests cover sell-order locking and release. |
| AI strategy constructor/config drift | Done | `AISignalsStrategy` accepts the `signal_model` injected by `main.py` and reads both legacy test keys and current `config.yaml` aliases for edge, confidence, and order sizing. |
| Cross-arb/Kalshi config alias drift | Done | Legacy cross-arb runtime now reads both `strategies.cross_arb` and `strategies.cross_platform_arb`; `KalshiClient` reads current `strategies.cross_arb.kalshi` aliases while preserving legacy `data_feeds.kalshi` precedence. |
| Task 3.1: placeholder fill-probability model | Done | `research/fill_probability.py` exposes `estimate_fill_prob(distance_from_mid_cents, depth_at_best, arrival_latency_ms) -> float` with placeholder coefficients and monotonic tests. |
| Adverse-selection P&L split diagnostic | Done | `data/market_activity.py` exposes `quote_fill_pnl_by_adverse_selection(...)` and tests classify adverse, non-adverse, and unclassified fills. |
| Cross-venue resolution-risk checklist | Done | `research/mapping.py` requires non-empty `resolution_risk_checklist` for approved mappings; candidate output leaves it null for manual review. |
| Research mapping eligibility | Blocked by manual review | `research_mappings/catalog.yaml` intentionally has `mappings: []`; no capture/replay profitability claim can start from candidates alone. |

## Human-owned decisions still blocking later phases

Do not ask Codex to implement the following until the missing spec is supplied. Use `reports/block0_decision_inputs.md` as the manual input template:

1. Fill-probability calibration methodology and Jon Becker dataset schema for `research/calibrate_fill_probability.py`.
2. Replacement binary-outcome market-making theory, including the exact spread/inventory formula for any `market_making_v2.py` implementation.
3. Latency-viability calculation inputs: observed queue depths, target market order-arrival rates, and the comparison method for 1.8s vs sub-200ms latency.
4. Precommitted empirical validation parameters: minimum trades/episodes, walk-forward split, confidence-interval method, and kill criteria.
5. Manual promotion of Polymarket/Kalshi mapping candidates into approved catalog entries.
6. Current primary-source fee/reward formula verification before reward/rebate economics can be credited.

## Current gates

- Data-path reliability is acceptable for read-only research, but not latency-sensitive trading: `reports/data_path_reliability_report.json` shows `40/40` successful read-only requests and p95 latency `1861ms`; latency-sensitive gate is false.
- Live-trading gates remain failed/no-go in `reports/go_no_go_framework.yaml`.
- Cross-venue replay remains blocked until approved mappings exist.

## Next safe Codex actions

The next Codex task should be chosen only from implementation work with a supplied interface and testable success condition. Safe examples:

- add tests around a supplied calibration CSV schema, if the schema is provided;
- implement a supplied latency-viability calculation formula as a pure function;
- implement a supplied `market_making_v2.py` mathematical function in a new file;
- implement a supplied capture schema after mappings are manually approved.

Do not infer any of those missing formulas, schemas, thresholds, or approval decisions from existing placeholder code.
