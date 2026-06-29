# Changelog

All notable changes to this project are documented here.

The repository is being rebuilt from a legacy live-capable bot into a safety-first
prediction-market research lab. Historical entries below describe legacy code presence,
not live-readiness.

## [Unreleased]

### Added

- Read-only software health report command:
  - `tools/software_health_report.py`;
  - `reports/software_health_report.md`;
  - `reports/software_health_report.json`.
- Public proof standard separating software health, economic proof, and live readiness.
- Open-source documentation for architecture, safety, mapping review, source contracts,
  fee model, demo workflow, legacy quarantine, and launch strategy.
- Research-safe `.env.example` plus warning-only `.env.live.example`.
- Contributor, governance, roadmap, issue-template, pull-request-template, CI, and
  pre-commit scaffolding.

### Changed

- README now presents the supported project as a read-only research/paper evidence
  kernel rather than a profit-proven trading bot.
- Usage and contribution docs now remove live-trading quickstarts from the supported
  path.
- Reward farming, AI/news, whale tracking, and latency-sensitive market making are
  documented as gated/deferred research ideas.

### Safety

- Live trading remains `NO-GO`.
- Rewards/rebates remain zero-credit unless independently verified from primary sources.
- Cross-venue profitability claims remain blocked until approved mappings and forward
  paper evidence exist.

## [0.4.0] — 2026-06-04

### Legacy phase: AI signal trading

Added AI/news strategy code, signal models, metrics, and tests. This historical phase
does not prove profitability and is not part of the supported live path.

## [0.3.0] — 2026-06-03

### Legacy phase: whale tracking

Added whale-tracking strategy code and related data structures. This historical phase
does not prove profitability and is currently deferred.

## [0.2.0] — 2026-06-02

### Legacy phase: cross-platform arbitrage

Added legacy cross-platform arbitrage code and Kalshi client scaffolding. Current
cross-venue research uses the newer read-only kernel instead.

## [0.1.0] — 2026-06-01

### Legacy phase: core infrastructure and market making

Added order management, execution, risk, portfolio, scanner, market-making, metrics,
alerting, configuration, and tests. This code remains live-capable legacy code and is
not live-ready.
