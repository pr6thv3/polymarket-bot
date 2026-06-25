# Minimal Read-Only Cross-Venue Research Kernel

Updated: 2026-06-25T13:10:38Z

## Scope

This repo now has a v1 research-only kernel for Polymarket/Kalshi capture and deterministic replay. It is not a trading runtime and it does not produce a live-readiness decision.

Tracks 2–4 remain deferred:

- market making remains paused;
- reward farming remains paper-only/no-go;
- whale tracking and AI/news receive no v1 adapters or strategy work.

## Safety boundary

The research entrypoint is `tools/cross_venue_research.py`. It imports the isolated `research` package only and is covered by static import-policy tests. It must not import `core.client`, `core.executor`, `main.py`, paper/live executors, or strategy classes.

Network access is constrained by `ReadOnlyTransport`:

- public allowlisted hosts only;
- HTTPS `GET`/`HEAD` only;
- no request bodies;
- no signing/auth headers;
- no process inherited trading credentials.

`execution.dry_run: true` remains configured, but the research safety boundary is architectural rather than relying on dry-run alone.

## Source contracts

Committed source-contract artifacts:

- `research_contracts/polymarket_clob_v1.json`
- `research_contracts/kalshi_trade_api_v1.json`

The contracts pin the official source URLs, retrieval timestamp, consumed JSON paths, and sanitized response fixtures. Fixture validation is deterministic. Live verification is available through:

```powershell
.venv/Scripts/python.exe tools/cross_venue_research.py verify-contracts --live `
  --polymarket-token-id <TOKEN_ID> `
  --kalshi-ticker <MARKET_TICKER> `
  --kalshi-series-ticker <SERIES_TICKER>
```

A GitHub Actions workflow also exists at `.github/workflows/research-contract-live.yml` for scheduled/manual live source-contract probes.

## Mapping policy

The mapping catalog is `research_mappings/catalog.yaml`. It is intentionally empty until manually reviewed mappings are added.

Only `status: approved` mappings enter replay. Each approved mapping must include:

- Polymarket condition and YES/NO token IDs;
- Kalshi event, market, and series tickers;
- canonical proposition and YES predicate;
- resolution source;
- UTC cutoff and timezone;
- payout convention;
- invalidation behavior;
- review evidence, reviewer, and review time.

Title similarity and auto-discovery are not replay-eligible.

## Quote and fee policy

Polymarket quotes use token-book asks and sizes directly. Kalshi quotes use `yes_ask_dollars`/`no_ask_dollars` when present. If those ask fields are absent, the Kalshi adapter derives the ask only from the opposite-side bid in the same orderbook snapshot.

Replay never uses midpoint, last trade, or convenience complements.

Dynamic fee data is required for executable edge acceptance. Rebates, maker programs, and incentives are zero-credit. If current match-time fee inputs cannot be resolved for an observation, the observation is preserved with `missing_fee_data` and route economics reject it.

## Evidence pack

Replay writes one JSON evidence pack containing:

- source-contract versions;
- mapping versions;
- raw-record manifest linkage;
- route rejection reasons;
- executable-edge distribution;
- mapping concentration;
- mapping-clustered 95% lower bound when enough mapping clusters exist.

Initial capture is a data-quality baseline only. A validation claim still requires at least 14 calendar days and 10 approved mappings, with opportunity episodes treated as the evaluation unit.
