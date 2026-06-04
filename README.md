# polymarket-bot

Automated market-making bot for Polymarket prediction markets.

---

## Overview

polymarket-bot is a multi-strategy algorithmic trading bot for [Polymarket](https://polymarket.com), the on-chain prediction market platform on Polygon. It trades via the Central Limit Order Book (CLOB) API using `py-clob-client`, targeting consistent income through market making, cross-platform arbitrage, AI/News signal trading, and whale tracking strategies.

**Status:** Phase 1–4 complete (407/407 tests passing), Phase 5 in progress.

## Architecture

```
polymarket-bot/
├── main.py                  # Orchestrator — strategy dispatch, lifecycle, CLI
├── config.yaml              # All strategy, risk, execution, and alert config
├── core/
│   ├── order_state.py       # Order lifecycle tracking (OrderStore, OrderState)
│   └── risk_manager.py      # Position limits, stop-loss, daily loss caps
├── data/
│   ├── market_scanner.py    # Scan, score, and rank Polymarket markets
│   ├── news_fetcher.py      # Multi-source news/social data collector
│   └── signal_model.py      # Ensemble probability model (news + features + momentum)
├── strategies/
│   ├── base.py              # Strategy ABC with error tracking and cycle management
│   ├── market_making.py     # Spread capture with maker rebates + holding yield
│   ├── ai_signals.py        # AI/News signal trading with position management
│   └── whale_tracking.py    # Smart-money copy trading with dynamic sizing
├── execution/
│   ├── orderbook.py         # L2 orderbook management and mid-price computation
│   └── clob_client.py       # CLOB REST + WebSocket API wrapper
├── utils/
│   ├── metrics.py           # Prometheus counters, histograms, and helpers
│   ├── alerts.py            # Telegram alert dispatch
│   └── logger.py            # Structured logging
├── tests/
│   ├── conftest.py          # Shared pytest fixtures
│   ├── test_market_making.py
│   ├── test_news_fetcher.py
│   ├── test_signal_model.py
│   └── test_ai_signals.py
├── .env                     # API credentials (NEVER commit)
├── .gitignore
└── requirements.txt
```

## Strategies

| Strategy | Description | Risk Profile |
|----------|-------------|-------------|
| **Market Making** | Place limit orders on both sides, earn the spread + maker rebates + holding yield | Low directional risk |
| **AI Signals** | Ensemble model (news sentiment, market features, momentum) identifies mispriced markets | Medium — directional positions with stop-losses |
| **Whale Tracking** | Monitor large profitable wallets, copy-trade milliseconds after execution | Medium — follows smart money with size limits |

### Fee Awareness

- **Maker fees:** 0% on all markets — limit orders are free
- **Taker fees:** Vary by category (Crypto 1.80%, Sports 0.75%, Finance 1.00%, Politics 1.00%, Economics 1.50%, Geopolitics 0%)
- **Maker rebates:** 20–50% of taker fees returned daily in USDC
- **Key insight:** Run as a maker (limit orders) to pay zero fees AND earn rebates

## Setup

### Prerequisites

- Python 3.11+
- A Polygon-compatible wallet funded with USDC
- Polymarket API credentials (generate via the Polymarket interface or SDK)

### Install

```bash
git clone https://github.com/pr6thv3/polymarket-bot.git
cd polymarket-bot
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows
pip install -r requirements.txt
```

### Environment

Create a `.env` file in the project root with your credentials:

```env
POLYMARKET_API_KEY=your_api_key
POLYMARKET_API_SECRET=your_api_secret
POLYMARKET_WALLET_PRIVATE_KEY=your_wallet_private_key
TELEGRAM_BOT_TOKEN=your_telegram_bot_token   # optional, for alerts
TELEGRAM_CHAT_ID=your_telegram_chat_id        # optional, for alerts
```

**Never commit `.env` to version control.** It is listed in `.gitignore`.

## Configuration

All strategy parameters, risk limits, and execution settings live in `config.yaml`. Key sections:

- **`strategies.market_making`** — spread targets, quote sizes, rebate optimization
- **`strategies.ai_signals`** — min edge, confidence thresholds, news sources, model weights
- **`strategies.whale_tracking`** — smart-money filters, win-rate thresholds, max copy size
- **`risk`** — position limits (5% per market), stop-losses, daily loss caps, 40% halt
- **`execution`** — rate limits (60 orders/min), post-only defaults, pending timeouts
- **`taker_fees`** — per-category fee schedule for profit calculations
- **`alerts`** — Telegram notification triggers

## Running

### Live Trading

```bash
python main.py
```

### Backtesting

```bash
python main.py --backtest --backtest-strategy market_making
python main.py --backtest --backtest-strategy ai_signals
python main.py --backtest --backtest-strategy whale_tracking
```

## Testing

```bash
# Full suite
python -m pytest tests/ -v

# Individual modules
python -m pytest tests/test_market_making.py -v
python -m pytest tests/test_news_fetcher.py -v
python -m pytest tests/test_signal_model.py -v
python -m pytest tests/test_ai_signals.py -v
```

**407/407 tests passing** across all four phases.

## Tech Stack

- **Python 3.11** — primary language
- **py-clob-client** — official Polymarket CLOB SDK
- **Polygon / USDC** — on-chain settlement
- **Prometheus** — real-time metrics and monitoring
- **Telegram** — alert notifications

---

> **Legal note:** Polymarket is geo-restricted in the US. Ensure it is accessible and legal in your jurisdiction before trading.
