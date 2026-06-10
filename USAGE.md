# Polymarket Bot — Usage Guide

A practical guide to setting up, running, and operating the Polymarket trading bot.

---

## Table of Contents

1. [First Time Setup](#1-first-time-setup)
2. [Running the Bot](#2-running-the-bot)
3. [Config Controls](#3-config-controls-configyaml)
4. [Telegram Alerts](#4-telegram-alerts)
5. [Monitoring](#5-monitoring)
6. [Common Problems & Fixes](#6-common-problems--fixes)
7. [Scaling Up](#7-scaling-up)

---

## 1. First Time Setup

### 1.1 Clone and Install

```bash
git clone https://github.com/pr6thv3/polymarket-bot.git
cd polymarket-bot

# Create virtual environment
python -m venv .venv

# Activate it
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 1.2 Environment Variables (.env)

Copy the example file and fill in your values:

```bash
cp .env.example .env
```

Open `.env` in a text editor. Here's what each variable does and where to get it:

| Variable | Required? | Where to Get It |
|---|---|---|
| `POLYGON_PRIVATE_KEY` | **Yes** | Your Polygon wallet private key. Export from MetaMask: Account → Details → Export Private Key. This signs your on-chain orders. **Never share this.** |
| `POLY_API_KEY` | **Yes** | Go to [polymarket.com](https://polymarket.com), connect your wallet, then generate API credentials via the py-clob-client SDK (`python -c "from py_clob_client.client import ClobClient; c = ClobClient('https://clob.polymarket.com', key='YOUR_PRIVATE_KEY', chain_id=137); print(c.create_api_key())"`) |
| `POLY_API_SECRET` | **Yes** | Generated alongside `POLY_API_KEY` (same command above). |
| `POLY_PASSPHRASE` | **Yes** | Generated alongside `POLY_API_KEY` (same command above). |
| `POLYGON_RPC_URL` | No | Custom Polygon RPC endpoint. Leave blank to use the public default. For better performance, get a free endpoint from [Alchemy](https://alchemy.com) or [Infura](https://infura.io). |
| `STARTING_CAPITAL` | No | Starting capital in USD. Default: `1000`. Only affects paper trading portfolio tracking. |
| `OPENAI_API_KEY` | No | Only needed if you enable the `ai_signals` strategy. Get one at [platform.openai.com](https://platform.openai.com). |
| `TELEGRAM_BOT_TOKEN` | No | For Telegram alerts. Create a bot via [@BotFather](https://t.me/BotFather) on Telegram → `/newbot` → copy the token. |
| `TELEGRAM_CHAT_ID` | No | Send any message to your bot, then visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` → find `"chat":{"id": 123456}` → that number is your chat ID. |

Example `.env` file:

```env
POLYGON_PRIVATE_KEY=0xabc123...
POLY_API_KEY=your-api-key
POLY_API_SECRET=your-api-secret
POLY_PASSPHRASE=your-passphrase
STARTING_CAPITAL=1000
TELEGRAM_BOT_TOKEN=7123456789:AAH...
TELEGRAM_CHAT_ID=123456789
```

### 1.3 Verify Setup

Run the test suite to confirm everything is installed correctly:

```bash
.venv\Scripts\python.exe -m pytest tests/ -q
```

Expected output:

```
407 passed in 2.83s
```

If all 407 tests pass, your environment is ready.

---

## 2. Running the Bot

### 2.1 Paper Trading Mode (Recommended First)

Paper trading simulates real trading without placing real orders or risking real money. **Always start here.**

```bash
.venv\Scripts\python.exe main.py --paper
```

This is also the default if `execution.dry_run: true` is set in `config.yaml` (which it is by default).

### 2.2 Live Trading Mode

> ⚠️ **Warning:** This places real orders with real money. Only do this after you've confirmed paper trading works correctly.

```bash
.venv\Scripts\python.exe main.py
```

Make sure `execution.dry_run: false` in `config.yaml` first (see [Section 3.1](#31-switch-between-paper-and-live-trading)).

### 2.3 Backtest Mode

Test a strategy against historical or synthetic data:

```bash
# Synthetic data (quick test)
.venv\Scripts\python.exe main.py --backtest

# With your own data
.venv\Scripts\python.exe main.py --backtest --backtest-data ./data/backtest/

# Custom capital
.venv\Scripts\python.exe main.py --backtest --backtest-capital 5000
```

### 2.4 How to Stop the Bot

Press `Ctrl+C` in the terminal. The bot handles this gracefully:

1. Stops all strategies
2. Cancels all open orders
3. Saves portfolio state to disk
4. Prints a paper trading summary (if in paper mode)
5. Sends a daily summary alert to Telegram
6. Closes all connections

**Do not kill the process forcefully** (e.g., closing the terminal window) — this skips the order cancellation step and may leave orphaned orders.

### 2.5 What Healthy Logs Look Like

When everything is working, you'll see output like this:

```
2026-06-11 00:15:08 [info] CLOB sync client initialized
2026-06-11 00:15:10 [info] CLOB health check                    status=ok latency_sec=1.234
2026-06-11 00:15:10 [info] Portfolio initialized                 starting_capital=1000 free_usdc=1000.0
2026-06-11 00:15:10 [info] Strategy started                      strategy=market_making
2026-06-11 00:15:10 [info] Bot main loop started (mode=PAPER)
2026-06-11 00:15:10 [info] Market-making initialized             markets=5 eligible=12
2026-06-11 00:15:10 [info] Market added to MM                    market_id=... category=politics
```

**Red flags** to watch for:
- `[critical]` messages → something is seriously wrong
- `Circuit breaker triggered` → too many API errors, bot is pausing
- `health check failed` repeatedly → connectivity issue

---

## 3. Config Controls (config.yaml)

All bot behavior is controlled by `config.yaml` in the project root. Here are the key settings.

### 3.1 Switch Between Paper and Live Trading

```yaml
execution:
  dry_run: true   # true = paper trading, false = live trading
```

You can also override this with the `--paper` CLI flag without editing the config.

### 3.2 Change Order Size

```yaml
strategies:
  market_making:
    order_size_usd: 15.0      # Size of each quote (in USD)
    min_order_size_usd: 5.0   # Minimum order size
```

Start small ($5–$15). Only increase after confirming the strategy is profitable.

### 3.3 Enable/Disable Strategies

Each strategy has an `enabled` flag:

```yaml
strategies:
  market_making:
    enabled: true       # Core strategy — leave enabled

  cross_arb:
    enabled: false      # Cross-platform arbitrage (needs Kalshi API keys)

  whale_tracking:
    enabled: false      # Copy-trade profitable wallets

  ai_signals:
    enabled: false      # AI/LLM-powered signal trading (needs OpenAI key)
```

Only enable strategies you've configured the credentials for.

### 3.4 Adjust Risk Limits

```yaml
risk:
  max_position_pct: 0.05       # Max 5% of capital in any single market
  daily_loss_cap_pct: 0.10     # Stop trading if daily loss exceeds 10%
  halt_total_loss_pct: 0.40    # Emergency halt at 40% total loss
  min_profit_threshold_usd: 0.30  # Minimum profit target per trade
  max_correlated_exposure_pct: 0.15  # Max 15% in correlated markets
```

**Explanation:**
- `max_position_pct: 0.05` → With $1000 capital, max $50 in any one market
- `daily_loss_cap_pct: 0.10` → Bot pauses after losing $100 in a single day
- `halt_total_loss_pct: 0.40` → Bot halts entirely if total losses reach $400

### 3.5 Add/Remove Target Market Categories

The bot only trades in categories you specify:

```yaml
strategies:
  market_making:
    target_categories:
      - geopolitics    # 0% taker fees — best for market making
      - finance        # 50% maker rebate — second best
      - politics       # 25% maker rebate
      # - crypto       # High fees — usually not profitable for MM
      # - sports       # Fast-moving — high adverse selection risk
```

Available categories: `crypto`, `sports`, `finance`, `politics`, `economics`, `geopolitics`.

**Tip:** `geopolitics` has **0% taker fees** and `finance` has the highest rebate rate (50%). These are the best categories for market making.

### 3.6 Spread and Quoting Controls

```yaml
strategies:
  market_making:
    min_spread_bps: 100        # Minimum spread: 1% (100 basis points)
    max_spread_bps: 400        # Maximum spread: 4%
    base_spread_bps: 200       # Starting spread: 2% (widens with volatility)
    midpoint_move_threshold_bps: 50   # Re-quote when midpoint moves >0.5%
    cancel_stale_sec: 120      # Cancel quotes older than 2 minutes
```

---

## 4. Telegram Alerts

### 4.1 Alert Types

| Alert | Emoji | What It Means | Action Needed? |
|---|---|---|---|
| `halt_triggered` | 🚨 | Risk manager halted the bot (daily loss cap or total loss cap hit) | **Yes** — investigate immediately. Bot has stopped trading. |
| `daily_loss_cap_hit` | ⚠️ | Daily loss limit reached | **Yes** — bot pauses for the day. Check what went wrong. |
| `connection_lost` | 🔌 | API health check failed after multiple retries | **Maybe** — could be temporary. If repeated, check internet/proxy. |
| `large_fill` | 💰 | A large order was filled | **No** — informational. Good to know. |
| `rebate_earned` | 🏦 | Maker rebate earned on a trade | **No** — informational. This is good news. |

### 4.2 Which Alerts Need Immediate Action

**Drop everything:**
- 🚨 `halt_triggered` — the bot has stopped. Something is seriously wrong with P&L.

**Check within the hour:**
- ⚠️ `daily_loss_cap_hit` — you're losing money today. Review recent trades.
- 🔌 `connection_lost` (if repeated) — the bot can't reach the API.

**No action needed:**
- 💰 `large_fill` — just letting you know a trade happened.
- 🏦 `rebate_earned` — money in your pocket.

### 4.3 Alert Rate Limiting

Alerts are rate-limited to **one per 30 seconds** (`min_interval_sec: 30` in config). The health monitor also requires **2 consecutive failures** before sending a `connection_lost` alert, preventing false alarms from transient network blips.

---

## 5. Monitoring

### 5.1 Check if the Bot is Actively Quoting

Look at the logs for these messages:

```bash
# Windows — show the last 20 lines of the log file
Get-Content logs\bot.log -Tail 20

# Or search for quote placement
Select-String "Order created" logs\bot.log | Select-Object -Last 10
Select-String "Quote" logs\bot.log | Select-Object -Last 10
```

Healthy output shows regular `Order created` or `place_quote_pair` entries.

### 5.2 Check P&L

The bot logs a risk summary every 5 minutes:

```bash
Select-String "Risk summary" logs\bot.log | Select-Object -Last 5
```

For paper trading stats:

```bash
Select-String "Paper trading stats" logs\bot.log | Select-Object -Last 5
```

### 5.3 Check Rebates

```bash
Select-String "rebate" logs\bot.log | Select-Object -Last 10
Select-String "Holding rewards" logs\bot.log | Select-Object -Last 5
```

### 5.4 Prometheus Metrics

The bot exposes Prometheus metrics on port 9090 (configurable in `config.yaml`):

```bash
# Quick check
curl http://localhost:9090/metrics
```

Or open `http://localhost:9090/metrics` in your browser.

### 5.5 Reading the Log File

The log file is at `logs/bot.log` (JSON format by default).

```bash
# Follow logs in real-time (Windows PowerShell)
Get-Content logs\bot.log -Wait -Tail 50

# Search for errors
Select-String "error" logs\bot.log | Select-Object -Last 20

# Search for specific market
Select-String "market_id=YOUR_MARKET_ID" logs\bot.log | Select-Object -Last 10
```

---

## 6. Common Problems & Fixes

### 6.1 Bot Starts But Finds 0 Markets

**Symptom:** Log shows `markets=0 eligible=0`

**Causes and fixes:**

1. **Wrong target categories** — Check `strategies.market_making.target_categories` in `config.yaml`. Make sure at least one category is listed.

2. **API not returning data** — Run a manual connectivity test:
   ```bash
   .venv\Scripts\python.exe -c "import asyncio; from dotenv import load_dotenv; load_dotenv(); from utils.helpers import load_config; from core.client import ClobClient; c = ClobClient(load_config()); print(asyncio.run(c.health_check()))"
   ```

3. **Market scanner filtering too aggressively** — The scanner ranks markets by spread, volume, and days to resolution. If all markets have very wide spreads or very low volume, none may qualify.

### 6.2 Connection Lost Alerts

**Symptom:** Telegram sends 🔌 `Connection Lost` alerts

**Causes and fixes:**

1. **Internet connectivity** — Check your internet connection.

2. **Cloudflare proxy down** — The bot routes through `polymarket-proxy.nameispreeth.workers.dev`. Test it:
   ```bash
   curl https://polymarket-proxy.nameispreeth.workers.dev/markets?limit=1
   ```

3. **Polymarket API outage** — Check [Polymarket's status](https://polymarket.com). Nothing you can do but wait.

4. **Rate limiting** — The bot is limited to 55 requests/minute. If you're running multiple instances, you'll hit the rate limit. The circuit breaker pauses after 10 errors in 60 seconds.

**Note:** The health check retries 3 times with exponential backoff before reporting failure, and the monitor requires 2 consecutive failures before alerting. So if you're getting alerts, it's a real problem, not a transient blip.

### 6.3 Order Rejected

**Symptom:** Log shows `Quote rejected by risk`

**This is normal and expected.** The risk manager blocks orders that would:
- Exceed `max_position_pct` (too much in one market)
- Exceed `max_correlated_exposure_pct` (too many correlated bets)
- Violate the daily loss cap

**Fix:** Either reduce order sizes or increase risk limits in `config.yaml`. But think carefully before increasing risk limits.

### 6.4 Health Check Errors

**Symptom:** Log shows `CLOB health check failed` with `status=error`

The health check calls `get_markets()` through the proxy. If it fails 3 times in a row, it reports an error.

**Troubleshooting steps:**
1. Run the connectivity test from [Section 6.1](#61-bot-starts-but-finds-0-markets)
2. Check if the proxy is reachable (see [Section 6.2](#62-connection-lost-alerts))
3. Check if your API keys are valid (expired keys can cause auth errors)
4. Check the circuit breaker — if it's open, the bot is auto-pausing to protect you

### 6.5 Circuit Breaker Triggered

**Symptom:** Log shows `Circuit breaker triggered, pause_sec=300`

This means the bot had 10+ API errors within 60 seconds. The bot pauses for 5 minutes to prevent cascading failures.

**Common causes:**
- API is rate-limiting you (too many requests)
- API is temporarily down
- Network issues

**Fix:** Wait for the pause to expire. The bot will automatically resume. If it keeps triggering, investigate the root cause.

### 6.6 POST_ONLY Rejection

**Symptom:** Log shows `POST_ONLY rejection (expected)`

**This is normal and expected.** It means your limit order would have crossed the spread and executed as a taker (paying fees). The exchange correctly rejected it. The bot will place a new order at the correct price on the next cycle.

---

## 7. Scaling Up

### 7.1 Paper → Live Trading

Follow these steps **in order**:

1. **Run paper trading for at least 1 week.** Confirm:
   - The bot runs without crashes
   - Health checks pass consistently
   - P&L is positive (or at least not deeply negative)
   - No unexpected `halt_triggered` alerts

2. **Review your paper trading results:**
   ```bash
   Select-String "Paper trading stats" logs\bot.log | Select-Object -Last 5
   ```

3. **Fund your Polygon wallet** with USDC on Polygon network. Start with a small amount ($50–$100).

4. **Set `STARTING_CAPITAL` in `.env`** to match your actual USDC balance.

5. **Switch to live mode:**
   ```yaml
   # config.yaml
   execution:
     dry_run: false   # Change from true to false
   ```

6. **Start the bot without the `--paper` flag:**
   ```bash
   .venv\Scripts\python.exe main.py
   ```

7. **Watch the first 30 minutes closely.** Monitor logs and Telegram alerts for any issues.

### 7.2 Increase Order Size Safely

**The rule: increase slowly.** Never more than 2x at a time.

Recommended progression:

| Week | `order_size_usd` | Capital Needed |
|---|---|---|
| 1 | 5.0 | $100 |
| 2 | 10.0 | $200 |
| 3 | 15.0 | $300 |
| 4 | 25.0 | $500 |
| 5+ | 50.0 | $1000+ |

After each increase, monitor for 3–5 days before increasing again. If you see increased adverse selection (frequent `volatility_spike` pauses), reduce size.

### 7.3 Enable Additional Strategies

**Cross-Platform Arbitrage** (requires Kalshi account):
```yaml
strategies:
  cross_arb:
    enabled: true
    kalshi:
      api_key: "your-kalshi-api-key"
      api_secret: "your-kalshi-api-secret"
```

**Whale Tracking** (no extra credentials needed):
```yaml
strategies:
  whale_tracking:
    enabled: true
```

**AI Signals** (requires OpenAI API key):
```yaml
strategies:
  ai_signals:
    enabled: true
```
Also set `OPENAI_API_KEY` in your `.env` file.

**Important:** Enable one strategy at a time. Run for at least 3 days before enabling another. This makes it easy to identify which strategy is causing issues if something goes wrong.

---

## Quick Reference — All CLI Commands

```bash
# Paper trading (safe, no real money)
.venv\Scripts\python.exe main.py --paper

# Live trading
.venv\Scripts\python.exe main.py

# Backtest
.venv\Scripts\python.exe main.py --backtest
.venv\Scripts\python.exe main.py --backtest --backtest-data ./data/backtest/
.venv\Scripts\python.exe main.py --backtest --backtest-capital 5000

# Run tests
.venv\Scripts\python.exe -m pytest tests/ -q

# Follow logs
Get-Content logs\bot.log -Wait -Tail 50

# Check health
Select-String "health check" logs\bot.log | Select-Object -Last 5
```
