# Proof Standard

The project separates “working software” from “profitable strategy” and “live
readiness.” A claim is only allowed at the highest gate it has actually passed.

## Gate 1: software working

This gate proves the research/paper infrastructure runs safely.

Required evidence:

- full test suite passes;
- source-contract fixture validation passes;
- `config.yaml` has `execution.dry_run: true`;
- execution-capable strategies are disabled;
- research tools do not import `core`, `strategies`, `data`, or `main.py`;
- injected trading credentials are rejected or ignored by read-only research paths;
- software health artifacts exist:
  - `reports/software_health_report.md`;
  - `reports/software_health_report.json`.

Allowed claim: “the research/paper infrastructure is working.”

Disallowed claim: “the bot makes money.”

## Gate 2: strategy economically working

This gate proves a paper strategy has conservative positive evidence.

Required evidence:

- at least 10 manually approved Polymarket/Kalshi mappings;
- at least 14 calendar days of forward paper capture;
- executable asks and depth used for both YES and NO routes;
- dynamic fee metadata and venue rounding used in route economics;
- stale quotes, excessive pair skew, missing depth, missing fees, and non-positive edge
  preserved as rejections;
- evaluation unit is opportunity episode, not raw polling snapshot;
- mapping-clustered or moving-block bootstrap 95% lower confidence bound is positive;
- rewards, rebates, and incentive programs are credited as zero unless independently
  verified from primary sources.

Required artifact:

- `reports/profitability_evidence_pack.md`

Allowed claim: “this paper strategy passed the economic proof gate.”

Disallowed claim: “this is live-ready.”

## Gate 3: live readiness

This gate is intentionally separate and currently closed.

Required evidence:

- legal/compliance review cleared for the user’s jurisdiction and venue use;
- explicit user approval for a live canary;
- isolated live credentials that are never loaded by the research runtime;
- canary size, max daily loss, kill switch, and rollback plan;
- live execution code reviewed against current official venue APIs;
- prior Gate 1 and Gate 2 artifacts passed.

Allowed claim after approval: “live canary approved under defined limits.”

Disallowed claim before approval: “production trading is ready.”
