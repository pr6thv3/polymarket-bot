# Block 0 Decision Input Template

Updated: 2026-06-27

This template exists because the current roadmap explicitly says Codex implements, never designs. Do not treat any unchecked placeholder below as a decision. Fill this file manually before asking Codex to implement Tasks 3.2, 4.2, 6.x, or 7.x.

Live trading remains **NO-GO**. This document does not approve live orders, deposits, authenticated endpoints, WebSockets, or any call to `core/client.py create_order`.

## 1. Fill-probability calibration spec for Task 3.2

Required before creating `research/calibrate_fill_probability.py`.

- [ ] Dataset source URL or local path:
- [ ] Dataset license/usage note:
- [ ] Dataset file format:
- [ ] One row represents:
- [ ] Required columns and dtypes:
  - [ ] market identifier:
  - [ ] timestamp / event time:
  - [ ] side:
  - [ ] quote price:
  - [ ] midpoint at quote time:
  - [ ] distance from mid in cents:
  - [ ] visible depth at best / queue proxy:
  - [ ] arrival latency in milliseconds:
  - [ ] fill outcome label:
  - [ ] fill horizon / TTL:
- [ ] Label definition for `filled = 1`:
- [ ] Label definition for `filled = 0`:
- [ ] Treatment of partial fills:
- [ ] Treatment of cancelled/expired quotes:
- [ ] Train/test split rule:
- [ ] Calibration algorithm:
- [ ] Metrics to report:
- [ ] Minimum sample size:
- [ ] Acceptance threshold:
- [ ] Output artifact path and schema:

Do not implement calibration until these fields are specified.

## 2. Binary-outcome market-making replacement theory for Task 6.1

Required before creating any `market_making_v2.py` implementation.

- [ ] Chosen theory/framework:
- [ ] State variables:
- [ ] Probability/prior definition:
- [ ] Order-flow update rule:
- [ ] Inventory penalty term:
- [ ] Adverse-selection penalty term:
- [ ] Latency/queue-position adjustment term:
- [ ] Fee/cost term:
- [ ] Quote bid formula:
- [ ] Quote ask formula:
- [ ] Bounds/clamps for binary outcome prices:
- [ ] Time-to-resolution behavior:
- [ ] Exact pure function signature Codex should implement:
- [ ] Known-input test cases:
- [ ] Kill condition if model output is nonsensical:

Do not ask Codex to choose the theory or formula.

## 3. Latency-viability calculation inputs

Required before any maker-side viability claim.

- [ ] Target market universe:
- [ ] Observed queue-depth source:
- [ ] Order-arrival-rate source:
- [ ] Quote update interval assumption:
- [ ] Current local/proxy latency metric to use:
- [ ] Comparison latency target, e.g. sub-200ms:
- [ ] Fill-rate calculation formula:
- [ ] Adverse-selection penalty assumption:
- [ ] Minimum viable expected fill rate:
- [ ] Maximum acceptable adverse-fill rate:
- [ ] Output report path:
- [ ] Decision rule:

Do not use the placeholder fill-probability model as latency-viability proof.

## 4. Empirical validation parameters for Task 7.1

Required before writing a validation runner or interpreting results.

- [ ] Evaluation unit, e.g. opportunity episode vs polling snapshot:
- [ ] Minimum simulated trades or episodes:
- [ ] Minimum mappings or markets:
- [ ] Minimum calendar duration:
- [ ] In-sample/out-of-sample split:
- [ ] Walk-forward schedule:
- [ ] Confidence interval method:
- [ ] Clustering/blocking method:
- [ ] Fee/cost model source:
- [ ] Required report fields:
- [ ] Proceed gate:
- [ ] Pause gate:
- [ ] Kill gate:

Do not let Codex infer these values from existing backtests or reports.

## 5. Cross-venue mapping review inputs for Task 4.1

Required before capture/replay can use a mapping.

For each mapping candidate:

- [ ] Candidate ID:
- [ ] Polymarket condition ID:
- [ ] Polymarket YES token ID:
- [ ] Polymarket NO token ID:
- [ ] Kalshi market ticker:
- [ ] Kalshi event ticker:
- [ ] Kalshi series ticker:
- [ ] Canonical proposition:
- [ ] YES predicate:
- [ ] Resolution source comparison:
- [ ] UTC cutoff comparison:
- [ ] Timezone handling:
- [ ] Payout convention comparison:
- [ ] Invalidation/void behavior comparison:
- [ ] Wording-equivalence evidence:
- [ ] Timing-divergence evidence:
- [ ] Payout-divergence evidence:
- [ ] Reviewer:
- [ ] Reviewed timestamp:
- [ ] Decision: reject / approve

Only approved mappings with full fields may be promoted to `research_mappings/catalog.yaml`.

## 6. Fee/reward verification inputs

Required before crediting rebates, rewards, or incentive programs in economics.

- [ ] Official source URL:
- [ ] Retrieved at timestamp:
- [ ] Venue:
- [ ] Market or series scope:
- [ ] Fee formula:
- [ ] Rounding rule:
- [ ] Maker/taker distinction:
- [ ] Product-specific exceptions:
- [ ] Incentive/reward formula:
- [ ] Whether reward amount is pool-level or participant entitlement:
- [ ] Required API fields:
- [ ] Sanitized fixture path:
- [ ] Verification status:

Until verified, route economics should credit rewards/rebates as zero.
