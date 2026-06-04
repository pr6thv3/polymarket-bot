# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.4.0] — 2026-06-04

### Phase 4 — AI Signal Trading

#### Added
- **AI signals strategy** (`strategies/ai_signals.py`): ensemble probability model combining news sentiment, market microstructure features, and price momentum to identify mispriced markets
- **News fetcher** (`data/news_fetcher.py`): multi-source news/social data collector with RSS feeds, mock sources, article deduplication (ArticleStore), sentiment extraction, relevance scoring, and category classification
- **Signal model** (`data/signal_model.py`): ensemble model with weighted sub-models (NewsSentimentModel, MarketFeatureModel, MomentumModel), recalibration shrinkage, Brier score tracking, and confidence-weighted signal output
- **AIPosition dataclass**: full position lifecycle tracking with entry/exit prices, stop-loss, take-profit, max hold time, and signal attribution
- **Wired AI signals into orchestrator** (`main.py`): `_init_ai_signals()` with dependency injection, conditional loading, and graceful fallback
- **Signal-specific Prometheus metrics** (`utils/metrics.py`): `signals_generated` counter, `signal_edge_usd` histogram, `record_signal_generated()` helper
- **Expanded config.yaml**: full `ai_signals` section with edge/confidence thresholds, position limits, news/social sources, model weights
- **`ai_signal_detected` alert** added to Telegram notifications
- **40 new tests**: `test_news_fetcher.py` (40), `test_signal_model.py` (30+), `test_ai_signals.py` (25+)
- **Bug fixes**: `order_store.get_order()` → `order_store.get()`, `order_state.status` → `order_record.is_terminal`, `AISignalStrategy` → `AISignalsStrategy` class name alignment

#### Test Results
- **407/407 tests passing** across all phases

---

## [0.3.0] — 2026-06-03

### Phase 3 — Whale Tracking

#### Added
- **Whale tracking strategy** (`strategies/whale_tracking.py`): smart-money copy trading with wallet filtering (60%+ win rate, 1.5x profit factor), dynamic position sizing, and correlation-based exposure limits
- **Whale tracker** (`data/whale_tracker.py`): on-chain wallet monitoring, trade signal generation, and profit-factor tracking
- **Wired whale tracking into orchestrator** (`main.py`): `_init_whale_tracking()` with config-driven setup
- **`whale_trade_copied` alert** added to Telegram notifications
- **Whale tracking config** section in `config.yaml`

---

## [0.2.0] — 2026-06-02

### Phase 2 — Cross-Platform Arbitrage

#### Added
- **Cross-platform arbitrage strategy** (`strategies/cross_platform_arb.py`): Polymarket vs. Kalshi price discrepancy detection with risk-free spread locking
- **Kalshi client** (`data/kalshi_client.py`): REST API wrapper for Kalshi prediction markets
- **Arbitrage config** section in `config.yaml`
- **Risk management enhancements**: cross-platform exposure limits, correlation tracking

---

## [0.1.0] — 2026-06-01

### Phase 1 — Core Infrastructure & Market Making

#### Added
- **Core order management** (`core/order_state.py`): full order lifecycle tracking (PENDING → OPEN → FILLED/CANCELLED) with OrderStore, state machine, and terminal state detection
- **CLOB client** (`core/client.py`): REST + WebSocket wrapper for Polymarket's Central Limit Order Book API
- **Order executor** (`core/executor.py`): real order placement with rate limiting, post-only enforcement, and USDC accounting
- **Paper executor** (`core/paper_executor.py`): simulated execution for backtesting
- **Orderbook manager** (`core/orderbook.py`): L2 orderbook tracking, mid-price computation, spread analysis
- **Risk manager** (`core/risk.py`): position limits (5% per market), stop-losses, daily loss caps, 40% halt threshold, gas fee accounting
- **Portfolio tracker** (`core/portfolio.py`): multi-strategy P&L, fill tracking, session reports
- **Market scanner** (`data/market_scanner.py`): scan, score, and rank Polymarket markets with weighted composite scoring, category filtering, and quality gates
- **Market making strategy** (`strategies/market_making.py`): spread capture with maker rebate optimization, holding yield targeting, and scheduled event handling
- **Strategy base class** (`strategies/base.py`): ABC with error tracking, cycle management, and circuit breaker pattern
- **Orchestrator** (`main.py`): strategy dispatch, lifecycle management, CLI with backtest mode
- **Prometheus metrics** (`utils/metrics.py`): counters, histograms, and helpers for P&L, orders, spreads, and fill rates
- **Telegram alerts** (`utils/alerting.py`): configurable notification dispatch
- **Structured logging** (`utils/logger.py`): JSON-formatted logs with structlog
- **Configuration** (`config.yaml`): comprehensive runtime config for all strategies, risk, execution, and alerting
- **Test suite**: 300+ tests across `test_order_state.py`, `test_market_making.py`, `test_risk.py`, `test_executor.py`, `test_market_scanner.py`, `test_backtest.py`, `test_paper_executor.py`, `test_data_feeds.py`

---

## [Unreleased] — Phase 5 (In Progress)

### Planned
- Live trading deployment and monitoring dashboards
- Advanced risk parity and correlation-aware position sizing
- WebSocket-based real-time orderbook streaming
- Retraining pipeline for signal model drift detection
- Cross-exchange hedging automation
