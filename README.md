# polymarket-bot

Safety-first prediction-market research tooling for reproducible Polymarket/Kalshi
mapping, capture, replay, and paper evidence.

This repository is being rebuilt as a split project. The supported public surface is
the read-only research kernel. The older execution-capable bot code remains in the
repo for auditability and tests, but it is not advertised as live-ready and is not
the default path for contributors.

## Current status

| Area | Status | Evidence / next gate |
|---|---:|---|
| Software health | Passing locally | Source-contract fixtures and full tests pass |
| Cross-venue research | Paper-only | Awaiting manually approved mappings |
| Market making | Paused | Requires latency/fill/Block 0 proof before strategy work resumes |
| Reward farming | NO-GO | Official formula incomplete and current paper EV is negative |
| AI/news and whale tracking | Deferred | Research ideas only, not profit-proven strategies |
| Live trading | NO-GO | Requires legal/compliance review, paper evidence, and explicit approval |

The honest claim today is: **the research/paper infrastructure is working**. This
repository does not currently prove that any strategy makes money.

## What this project does

- Validates pinned source contracts for Polymarket and Kalshi read-only surfaces.
- Generates cross-venue mapping candidates without making them replay-eligible.
- Requires manual mapping review before any replay or capture claim.
- Captures append-only raw records and normalized paired snapshots.
- Replays evidence deterministically from manifests and approved mappings.
- Preserves rejected observations with explicit rejection reasons.
- Keeps live-capable execution paths out of the research runtime by architecture and tests.

## Architecture

```text
research/                     supported read-only kernel
  adapters.py                  venue normalization and executable quote parsing
  contracts.py                 versioned source-contract validation
  event_log.py                 append-only research records
  mapping.py                   manually reviewed mapping catalog
  replay.py                    deterministic paper replay and route economics
  safety.py                    fail-closed config and credential checks
  transport.py                 GET/HEAD-only public REST transport

tools/
  cross_venue_research.py      verify-contracts, capture, replay
  generate_candidates.py       candidates-only mapping discovery
  software_health_report.py    read-only software proof artifact

research_contracts/            official source-contract artifacts and fixtures
research_mappings/             candidate and approved mapping catalogs
reports/                       generated evidence, audits, and go/no-go reports

libs/, services/                proposal/risk/order-intent contracts for a future
                                platform; non-transmitting and paper-only by default
sql/                            schema sketches for future Postgres/ClickHouse split

main.py, core/, data/, strategies/
                                legacy execution-capable bot code; not live-ready
```

## Safe quickstart

These commands do not need wallet keys, exchange credentials, deposits, or live
orders.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

.venv\Scripts\python.exe tools/cross_venue_research.py verify-contracts
.venv\Scripts\python.exe -m pytest tests/ -q
.venv\Scripts\python.exe tools/software_health_report.py
```

Generated proof artifacts:

- `reports/software_health_report.md`
- `reports/software_health_report.json`

## Proof standard

The project uses three gates:

1. **Software working** — tests, source-contract fixtures, safety checks, and
   import-policy checks pass.
2. **Strategy economically working** — at least 14 calendar days of forward paper
   evidence over at least 10 approved mappings, realistic executable quotes, dynamic
   fees, rejection accounting, and a positive conservative lower confidence bound.
3. **Live readiness** — legal/compliance clearance, explicit user approval, isolated
   credentials, canary limits, kill switch, and rollback plan.

See [docs/proof_standard.md](docs/proof_standard.md) for the full standard.

## Documentation

- [Architecture](docs/architecture.md)
- [Safety model](docs/safety-model.md)
- [Proof standard](docs/proof_standard.md)
- [Proposal-driven strategy platform](docs/strategy-platform.md)
- [Mapping review](docs/mapping-review.md)
- [Source contracts](docs/source-contracts.md)
- [Fee model](docs/fee-model.md)
- [Legacy live-capable bot](docs/legacy-live-bot.md)
- [Demo walkthrough](docs/demo-walkthrough.md)
- [Launch strategy](docs/launch-strategy.md)

## Development

```bash
.venv\Scripts\python.exe -m pytest tests/ -q
.venv\Scripts\python.exe tools/cross_venue_research.py verify-contracts
.venv\Scripts\python.exe tools/software_health_report.py
```

Normal pull-request CI must pass without secrets. The live source-contract probe is
manual/scheduled only and is not required for forked PRs.

## Contributing

Contributions are welcome when they improve reproducibility, safety, documentation,
fixtures, mappings, or paper-replay evidence. Strategy or execution changes must pass
the proof gates before they are described as profitable or live-ready.

Start with [CONTRIBUTING.md](CONTRIBUTING.md), [GOVERNANCE.md](GOVERNANCE.md), and
[ROADMAP.md](ROADMAP.md).

## Security

Do not add private keys, wallet credentials, exchange trading credentials, or
authenticated trading endpoints to the research path. See [SECURITY.md](SECURITY.md).

## License

Licensed under the terms in [LICENSE](LICENSE).
