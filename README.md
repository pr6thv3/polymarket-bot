# polymarket-bot

Automated market-making bot for Polymarket prediction markets.

## Overview

polymarket-bot is a multi-strategy trading system for Polymarket prediction markets.
It provides automated market making, cross-platform arbitrage, whale tracking, and
AI-driven signal trading — all with risk management, paper trading, and backtesting
built in.

**Status:** Phase 1–4 complete (407/407 tests passing), Phase 5 in progress.

## Architecture

```
polymarket-bot/
├── main.py                  # Entry point — strategy orchestrator
├── config.yaml              # All runtime configuration
├── core/                    # Infrastructure layer
│   ├── client.py            # Polymarket CLOB client wrapper
│   ├── executor.py          # Order execution + fill processing
│   ├── order_state.py       # Order state machine (pending→open→filled/cancelled)
│   ├── orderbook.py         # Order book snapshot + quoting
│   ├── portfolio.py         # Position tracking + USDC accounting
│   ├── risk.py              # Risk manager (position limits, halt, correlation)
│   ├── paper_executor.py    # Paper trading engine (simulated fills)
│   └── backtest.py          # Backtesting engine (historical replay)
├── data/                    # Data + signal layer
│   ├── market_scanner.py    # Market discovery, scoring, eligibility
│   ├── news_fetcher.py      # RSS/webhook news ingestion + sentiment
│   ├── signal_model.py      # Ensemble signal model (news, features, momentum)
│   ├── whale_tracker.py     # Whale profiling + signal aggregation
│   └── kalshi_client.py     # Kalshi API client (cross-arb)
├── strategies/              # Strategy layer
│   ├── base.py              # Strategy interface + lifecycle
│   ├── market_making.py     # Market making with inventory skew
│   ├── cross_platform_arb.py # Cross-platform arbitrage (Polymarket↔Kalshi)
│   ├── whale_tracking.py    # Whale copy-trading strategy
│   └── ai_signals.py        # AI signal-driven position strategy
├── utils/                   # Shared utilities
│   ├── alerting.py          # Telegram alerting
│   ├── metrics.py           # Prometheus metrics
│   ├── logger.py            # Structured logging (structlog)
│   └── helpers.py           # Common helpers
└── tests/                   # 407 tests across 12 test files
```

## Strategies

| Strategy | Description | Config Key |
|----------|-------------|------------|
| **Market Making** | Liquidity provision with inventory skew, adverse selection detection, scheduled event blackouts, and holding reward optimization | `strategies.market_making` |
| **Cross-Platform Arb** | Detects and executes price discrepancies between Polymarket and Kalshi | `strategies.cross_arb` |
| **Whale Tracking** | Profiles high-win-rate traders and copy-trades their positions with configurable scaling and stop-loss | `strategies.whale_tracking` |
| **AI Signals** | LLM-augmented news sentiment + market features → ensemble signal model → directional positions with stop-loss/take-profit | `strategies.ai_signals` |

## Tech Stack

- **Python 3.11** — runtime
- **py-clob-client** — Polymarket CLOB API
- **Polygon/USDC** — settlement layer
- **Prometheus** — metrics exposition (port 9090)
- **Telegram** — real-time alerts
- **structlog** — structured JSON logging
- **pytest** — testing (strict asyncio mode)

## Setup

```bash
# Clone the repository
git clone https://github.com/pr6thv3/polymarket-bot.git
cd polymarket-bot

# Create virtual environment
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows

# Install dependencies
pip install -r requirements.txt

# Copy and fill environment variables
cp .env.example .env
# Edit .env with your credentials — NEVER commit this file
```

## Configuration

All runtime configuration lives in `config.yaml`. Key sections:

| Section | Purpose |
|---------|---------|
| `risk` | Position limits, loss caps, halt thresholds |
| `taker_fees` / `rebate_rates` | Per-category fee schedules |
| `strategies.*` | Per-strategy toggles, thresholds, sizing |
| `execution` | Rate limits, retries, circuit breaker, dry-run mode |
| `paper_trading` | Slippage + fill probability simulation params |
| `backtesting` | Historical replay configuration |
| `alerting` | Telegram alert routing |
| `logging` / `metrics` / `monitoring` | Observability stack |

Secrets are loaded from `.env` — never stored in config.yaml or committed to git.

## Running

```bash
# Live trading (production)
python main.py

# Paper trading (simulated execution)
python main.py                    # with execution.dry_run: true in config.yaml

# Backtesting
python main.py --backtest data/backtest/sample.jsonl

# Custom config path
python main.py --config path/to/config.yaml
```

The bot handles Windows asyncio (ProactorEventLoop), graceful shutdown on
SIGINT/SIGTERM, and auto-recovery from consecutive strategy errors.

## Testing

```bash
# Full suite (407 tests)
python -m pytest tests/ -v

# Single module
python -m pytest tests/test_market_making.py -v

# With coverage
python -m pytest tests/ --cov=. --cov-report=term-missing
```

All tests use `asyncio_mode = strict` — async tests require `@pytest.mark.asyncio`.
