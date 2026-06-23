"""Read-only live Polymarket market snapshot diagnostics.

Fetches currently accepting CLOB markets via the configured proxy, samples YES-side
order books, and writes a ranked profitability-readiness report. It never places,
amends, or cancels orders.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import math
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.client import REBATE_RATES, TAKER_FEES, ClobClient
from data.market_scanner import MarketScanner
from utils.helpers import load_config

REPORTS = REPO / "reports"


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _best_bid(book: dict[str, Any]) -> tuple[float, float]:
    bids = book.get("bids") or []
    levels = [(_as_float(x.get("price")), _as_float(x.get("size"))) for x in bids if isinstance(x, dict)]
    levels = [(p, s) for p, s in levels if 0 < p < 1 and s > 0]
    return max(levels, key=lambda x: x[0], default=(0.0, 0.0))


def _best_ask(book: dict[str, Any]) -> tuple[float, float]:
    asks = book.get("asks") or []
    levels = [(_as_float(x.get("price")), _as_float(x.get("size"))) for x in asks if isinstance(x, dict)]
    levels = [(p, s) for p, s in levels if 0 < p < 1 and s > 0]
    return min(levels, key=lambda x: x[0], default=(0.0, 0.0))


def _yes_token(market: dict[str, Any]) -> str:
    for tok in market.get("tokens") or []:
        if isinstance(tok, dict) and str(tok.get("outcome", "")).lower() in {"yes", "true"}:
            return str(tok.get("token_id") or "")
    toks = market.get("tokens") or []
    return str(toks[0].get("token_id") or "") if toks and isinstance(toks[0], dict) else ""


def _days_to_resolution(end_date: str) -> int:
    if not end_date:
        return 30
    try:
        end = dt.datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        now = dt.datetime.now(dt.timezone.utc)
        return max(0, int((end - now).total_seconds() / 86400))
    except Exception:
        return 30


def rank_row(row: dict[str, Any]) -> float:
    """Profitability-readiness score: executable spread + touch depth + rebate + horizon.

    This is a discovery score, not an expected-return estimate.
    """
    if row["best_bid"] <= 0 or row["best_ask"] <= 0 or row["best_ask"] <= row["best_bid"]:
        return 0.0
    spread_cents = row["best_ask"] - row["best_bid"]
    spread_score = min(40.0, spread_cents * 1000.0)  # 4c => 40
    depth_usd = min(row["bid_touch_usd"], row["ask_touch_usd"])
    depth_score = min(25.0, math.log10(max(1.0, depth_usd)) * 8.0)
    rebate_score = min(15.0, row["rebate_yield"] * 2500.0)
    horizon_score = 10.0 if row["days_to_resolution"] >= 14 else max(0.0, row["days_to_resolution"] / 14.0 * 10.0)
    mid_penalty = 0.0 if 0.05 <= row["mid"] <= 0.95 else 15.0
    wide_penalty = 10.0 if row["spread_bps"] > 800 else 0.0
    return round(max(0.0, spread_score + depth_score + rebate_score + horizon_score - mid_penalty - wide_penalty), 2)


def md_table(headers: list[str], rows: list[list[Any]]) -> str:
    out = "|" + "|".join(headers) + "|\n"
    out += "|" + "|".join(["---"] * len(headers)) + "|\n"
    for row in rows:
        out += "|" + "|".join(str(x).replace("|", "/") for x in row) + "|\n"
    return out


async def discover_markets(client: ClobClient, max_pages: int, max_markets: int) -> tuple[list[dict[str, Any]], int]:
    cursor = None
    markets: list[dict[str, Any]] = []
    pages = 0
    while pages < max_pages and len(markets) < max_markets:
        data = await client.get_markets(cursor)
        pages += 1
        for market in data.get("data", data.get("markets", [])) if isinstance(data, dict) else []:
            if (
                market.get("accepting_orders")
                and market.get("enable_order_book")
                and not market.get("closed", False)
                and _yes_token(market)
            ):
                markets.append(market)
                if len(markets) >= max_markets:
                    break
        cursor = data.get("next_cursor") if isinstance(data, dict) else None
        if not cursor:
            break
    return markets, pages


async def snapshot_books(config: dict[str, Any], max_pages: int, max_markets: int) -> list[dict[str, Any]]:
    client = ClobClient(config)
    # Use scanner only for category inference; no trading side effects.
    scanner = MarketScanner(client=client, orderbook=None, config=config)  # type: ignore[arg-type]
    markets, pages = await discover_markets(client, max_pages=max_pages, max_markets=max_markets)
    rows = []
    for idx, market in enumerate(markets, start=1):
        token_id = _yes_token(market)
        book = await client.get_orderbook(token_id)
        bid, bid_size = _best_bid(book if isinstance(book, dict) else {})
        ask, ask_size = _best_ask(book if isinstance(book, dict) else {})
        if not bid or not ask or ask <= bid:
            continue
        mid = (bid + ask) / 2.0
        spread_bps = (ask - bid) * 10_000
        category = scanner._infer_category(market)
        taker_fee = TAKER_FEES.get(category, 0.01)
        rebate_rate = REBATE_RATES.get(category, 0.25)
        row = {
            "condition_id": market.get("condition_id", ""),
            "question": market.get("question", ""),
            "category": category,
            "days_to_resolution": _days_to_resolution(market.get("end_date_iso", "")),
            "token_id": token_id,
            "best_bid": bid,
            "best_ask": ask,
            "mid": mid,
            "spread_bps": spread_bps,
            "bid_size": bid_size,
            "ask_size": ask_size,
            "bid_touch_usd": bid * bid_size,
            "ask_touch_usd": ask * ask_size,
            "rebate_yield": taker_fee * rebate_rate,
            "minimum_order_size": _as_float(book.get("min_order_size") if isinstance(book, dict) else None),
            "source_index": idx,
            "pages_scanned": pages,
        }
        row["readiness_score"] = rank_row(row)
        rows.append(row)
    return sorted(rows, key=lambda r: r["readiness_score"], reverse=True)


def write_report(rows: list[dict[str, Any]], args: argparse.Namespace) -> None:
    REPORTS.mkdir(exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (REPORTS / "current_market_snapshot.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    table_rows = []
    for i, row in enumerate(rows[:20], start=1):
        table_rows.append([
            i,
            row["condition_id"][:10] + "…",
            row["question"][:64],
            row["category"],
            row["days_to_resolution"],
            f"{row['best_bid']:.3f}/{row['best_ask']:.3f}",
            f"{row['spread_bps']:.0f}",
            f"${min(row['bid_touch_usd'], row['ask_touch_usd']):.2f}",
            f"{row['rebate_yield']:.4f}",
            f"{row['readiness_score']:.2f}",
        ])
    proceed = [r for r in rows if 100 <= r["spread_bps"] <= 800 and min(r["bid_touch_usd"], r["ask_touch_usd"]) >= 25 and r["days_to_resolution"] >= 3]
    report = f"""# Current Live Market Snapshot — Read-only

Generated: {now}

## Method

Read-only CLOB/proxy scan. Fetched accepting CLOB markets, sampled YES-token order books, and ranked by executable spread, touch depth, rebate yield, and time-to-resolution. No orders were placed/cancelled/amended.

Parameters: `max_pages={args.max_pages}`, `max_markets={args.max_markets}`.

## Top candidates by profitability-readiness score

{md_table(['Rank','Market','Question','Cat','Days','Bid/Ask','Spread bps','Touch depth','Rebate yield','Score'], table_rows)}

## Gate interpretation

Candidate gate for next **paper-only** test: spread 100–800 bps, min touch depth >= $25, days_to_resolution >= 3.

- Markets sampled with valid books: {len(rows)}
- Markets passing this shallow liquidity/spread gate: {len(proceed)}
- This report does **not** prove edge or expected return. It only identifies where a short paper/backtest collection is less likely to waste time than the previous sticky markets.

## Recommended next validation

Collect 30–60 minutes of JSONL snapshots for the top 3 passing markets, then run the same fill-opportunity/backtest sweep before enabling any live trading.
"""
    (REPORTS / "current_market_snapshot.md").write_text(report, encoding="utf-8")
    print(f"Wrote reports/current_market_snapshot.md with {len(rows)} valid books; {len(proceed)} passed shallow gate")
    if rows:
        print("Top row", json.dumps(rows[0], indent=2)[:1200])


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--max-pages", type=int, default=70)
    p.add_argument("--max-markets", type=int, default=40)
    return p.parse_args()


async def async_main() -> None:
    args = parse_args()
    config = load_config(REPO / "config.yaml")
    if not config.get("execution", {}).get("dry_run", False):
        raise SystemExit("Refusing to run diagnostics unless execution.dry_run is true")
    rows = await snapshot_books(config, max_pages=args.max_pages, max_markets=args.max_markets)
    write_report(rows, args)


if __name__ == "__main__":
    asyncio.run(async_main())
