"""Offline Polymarket market-making diagnostics.

Reads JSONL order-book snapshots from an explicit data directory and writes
validation reports. No network calls and no order placement.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any, Sequence

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from data.market_activity import (  # noqa: E402
    BookSnapshot,
    compute_market_activity,
    quote_fill_markouts,
    quote_fill_opportunities,
)
from utils.helpers import load_config  # noqa: E402

DEFAULT_DATA_DIR = REPO / "data/backtest"
RESULTS_DIR = REPO / "data/backtest/results"
REPORTS = REPO / "reports"


def latest_backtest_result() -> Path | None:
    """Return the newest MarketMaking backtest result if one exists."""
    results = sorted(
        RESULTS_DIR.glob("MarketMaking_*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return results[0] if results else None


def md_table(headers: Sequence[Any], rows: Sequence[Sequence[Any]]) -> str:
    out = "|" + "|".join(str(h) for h in headers) + "|\n"
    out += "|" + "|".join(["---"] * len(headers)) + "|\n"
    for row in rows:
        out += "|" + "|".join(str(x).replace("|", "/") for x in row) + "|\n"
    return out


def load_jsonl_snapshots(path: Path) -> list[BookSnapshot]:
    """Load valid top-of-book snapshots from one JSONL file."""
    snapshots: list[BookSnapshot] = []
    with path.open(errors="ignore") as f:
        for line in f:
            try:
                d = json.loads(line)
                bids = d.get("bids") or []
                asks = d.get("asks") or []
                if not bids or not asks:
                    continue
                best_bid = float(bids[0][0])
                best_ask = float(asks[0][0])
                mid = float(d.get("mid") or ((best_bid + best_ask) / 2))
                timestamp = float(d.get("timestamp") or 0)
                snapshots.append(
                    BookSnapshot(
                        timestamp=timestamp,
                        best_bid=best_bid,
                        best_ask=best_ask,
                        mid=mid,
                    )
                )
            except Exception:
                continue
    return snapshots


def rank_market_candidates(candidates: list[dict]) -> list[dict]:
    """Rank market candidates by fill opportunity first, then activity."""
    def key(candidate: dict) -> tuple[float, float, float]:
        return (
            float(candidate.get("fill_opportunity_rate_pct", 0.0)),
            float(candidate.get("activity_score", 0.0)),
            float(candidate.get("top_change_count", 0.0)),
        )

    return sorted(candidates, key=key, reverse=True)


def _latest_gas_per_quote(default: float = 0.00497) -> float:
    result_path = latest_backtest_result()
    if not result_path:
        return default
    try:
        result = json.loads(result_path.read_text())
        quotes = float(result.get("quotes_generated") or 0)
        gas = float(result.get("estimated_gas_costs_usd") or 0)
        return gas / quotes if quotes > 0 else default
    except Exception:
        return default


def load_rows(data_dir: Path = DEFAULT_DATA_DIR) -> tuple[dict[str, list[BookSnapshot]], list[dict]]:
    """Load JSONL data and compute per-market activity summaries."""
    all_rows: dict[str, list[BookSnapshot]] = {}
    markets: list[dict] = []
    for path in sorted(data_dir.glob("*.jsonl")):
        snapshots = load_jsonl_snapshots(path)
        if not snapshots:
            continue
        all_rows[path.name] = snapshots
        activity = compute_market_activity(snapshots)
        fill = quote_fill_opportunities(
            snapshots,
            spread_bps=200,
            quote_interval_sec=300,
            ttl_sec=1800,
        )
        markout = quote_fill_markouts(
            snapshots,
            spread_bps=200,
            quote_interval_sec=300,
            ttl_sec=1800,
        )
        toxicity_60 = markout.adverse_markout_pct_of_gross.get(60, 0.0)
        markets.append({
            "file": path.name,
            "market_id": path.stem,
            "snapshots": activity.snapshot_count,
            "size": path.stat().st_size,
            "unique_top": activity.unique_top_of_book,
            "top_changes": activity.top_change_count,
            "first_top": (snapshots[0].best_bid, snapshots[0].best_ask),
            "last_top": (snapshots[-1].best_bid, snapshots[-1].best_ask),
            "mid_range": activity.mid_range,
            "avg_spread_cents": activity.average_spread_cents,
            "activity_score": activity.activity_score,
            "fill_opportunity_rate_pct": fill.fill_opportunity_rate_pct,
            "buy_fill_opportunities": fill.buy_fill_opportunities,
            "sell_fill_opportunities": fill.sell_fill_opportunities,
            "roundtrip_opportunities": fill.roundtrip_opportunities,
            "markout_fills": markout.fills,
            "markout_fill_rate_pct": markout.fill_rate_pct,
            "avg_gross_edge": markout.average_gross_edge,
            "avg_adverse_markout_60s": markout.average_adverse_markout.get(60, 0.0),
            "toxicity_60_pct_gross": toxicity_60,
            "passes_toxicity_gate": toxicity_60 <= 40.0 and markout.fills > 0,
        })
    return all_rows, markets


def _summarize_combo(
    all_rows: dict[str, list[BookSnapshot]],
    spread: int,
    quote_interval: int,
    ttl: int,
    gas_per_quote: float,
    shares_per_fill: float,
) -> dict[str, Any]:
    quotes = buy_fills = sell_fills = roundtrips = fills = 0
    gross_edge_sum = 0.0
    adverse_edge_sum_60 = 0.0
    for snapshots in all_rows.values():
        fill = quote_fill_opportunities(snapshots, spread, quote_interval, ttl)
        markout = quote_fill_markouts(snapshots, spread, quote_interval, ttl)
        quotes += fill.quotes_generated
        buy_fills += fill.buy_fill_opportunities
        sell_fills += fill.sell_fill_opportunities
        roundtrips += fill.roundtrip_opportunities
        fills += markout.fills
        gross_edge_sum += markout.average_gross_edge * markout.fills
        adverse_edge_sum_60 += markout.average_adverse_markout.get(60, 0.0) * markout.fills

    gross_spread = gross_edge_sum * shares_per_fill
    adverse_loss = adverse_edge_sum_60 * shares_per_fill
    gas = quotes * gas_per_quote
    net = gross_spread - adverse_loss - gas
    fill_rate = (fills / quotes * 100.0) if quotes else 0.0
    toxicity = (adverse_edge_sum_60 / gross_edge_sum * 100.0) if gross_edge_sum > 0 else 0.0
    gas_pct_gross = (gas / gross_spread * 100.0) if gross_spread > 0 else float("inf")
    return {
        "spread_bps": spread,
        "quote_interval_sec": quote_interval,
        "ttl_sec": ttl,
        "quotes": quotes,
        "fills": fills,
        "buy_fills": buy_fills,
        "sell_fills": sell_fills,
        "roundtrips": roundtrips,
        "fill_rate_pct": fill_rate,
        "gross_spread_captured_usd": gross_spread,
        "estimated_gas_usd": gas,
        "rebates_usd": 0.0,
        "holding_rewards_usd": 0.0,
        "adverse_selection_loss_usd": adverse_loss,
        "toxicity_60_pct_gross": toxicity,
        "gas_pct_of_gross_spread": gas_pct_gross,
        "net_pnl_usd": net,
        "post_only_rejection_rate_pct": 0.0,
    }


def sweep(
    all_rows: dict[str, list[BookSnapshot]],
    spreads: Sequence[int],
    gas_per_quote: float,
    quote_intervals: Sequence[int] = (60, 300, 900),
    ttls: Sequence[int] = (300, 900, 1800),
    shares_per_fill: float = 30.0,
) -> list[dict[str, Any]]:
    """Run fill/markout parameter sweep over loaded snapshots."""
    out = []
    for spread in spreads:
        for quote_interval in quote_intervals:
            for ttl in ttls:
                out.append(_summarize_combo(all_rows, spread, quote_interval, ttl, gas_per_quote, shares_per_fill))
    return sorted(out, key=lambda r: (r["net_pnl_usd"], r["fill_rate_pct"]), reverse=True)


def _safe_money(value: float) -> str:
    return f"${value:,.2f}"


def _safe_pct(value: float) -> str:
    if value == float("inf"):
        return "∞"
    return f"{value:.2f}%"


def write_phase3c_reports(data_dir: Path, all_rows: dict[str, list[BookSnapshot]], markets: list[dict], sweep_rows: list[dict], current_like: dict, summary: dict[str, Any] | None) -> str:
    REPORTS.mkdir(exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ranked = rank_market_candidates(markets)
    total_snapshots = sum(len(v) for v in all_rows.values())
    incomplete = [m for m in markets if m["snapshots"] < 250]
    best = sweep_rows[0] if sweep_rows else current_like

    gates = {
        "fill_rate_lt_2": current_like["fill_rate_pct"] < 2.0,
        "no_roundtrips": current_like["roundtrips"] < 1,
        "net_pnl_lte_0": current_like["net_pnl_usd"] <= 0.0,
        "toxicity_gt_40": current_like["toxicity_60_pct_gross"] > 40.0,
        "gas_gt_30_gross": current_like["gas_pct_of_gross_spread"] > 30.0,
        "best_unrealistic": best["quotes"] > 5000 or best["roundtrips"] < 1,
    }
    if gates["fill_rate_lt_2"] or gates["no_roundtrips"] or gates["net_pnl_lte_0"]:
        decision = "PAUSE MARKET-MAKING AND PIVOT"
    elif any(gates.values()):
        decision = "KILL MARKET-MAKING FOR NOW"
    else:
        decision = "CONTINUE MARKET-MAKING VALIDATION"

    market_rows = [[
        i + 1,
        m["market_id"][:10] + "…",
        m["snapshots"],
        "INCOMPLETE" if m["snapshots"] < 250 else "complete",
        f"{m['activity_score']:.1f}",
        f"{m['fill_opportunity_rate_pct']:.2f}%",
        m["buy_fill_opportunities"],
        m["sell_fill_opportunities"],
        m["roundtrip_opportunities"],
        f"{m['toxicity_60_pct_gross']:.2f}%",
    ] for i, m in enumerate(ranked)]

    metric_rows = [
        ["Dataset folder", str(data_dir.relative_to(REPO))],
        ["Markets/files", len(all_rows)],
        ["Total snapshots", total_snapshots],
        ["Incomplete markets (<250 snapshots)", len(incomplete)],
        ["Total quotes", current_like["quotes"]],
        ["Fills", current_like["fills"]],
        ["Buy fills", current_like["buy_fills"]],
        ["Sell fills", current_like["sell_fills"]],
        ["Roundtrips", current_like["roundtrips"]],
        ["Fill rate", f"{current_like['fill_rate_pct']:.2f}%"],
        ["Current-like fill rate", f"{current_like['fill_rate_pct']:.2f}%"],
        ["Gross spread captured", _safe_money(current_like["gross_spread_captured_usd"])],
        ["Estimated gas", _safe_money(current_like["estimated_gas_usd"])],
        ["Rebates", _safe_money(current_like["rebates_usd"])],
        ["Holding rewards", _safe_money(current_like["holding_rewards_usd"])],
        ["Adverse selection loss", _safe_money(current_like["adverse_selection_loss_usd"])],
        ["60s toxicity %", f"{current_like['toxicity_60_pct_gross']:.2f}%"],
        ["Net P&L", _safe_money(current_like["net_pnl_usd"])],
        ["POST_ONLY rejection rate", f"{current_like['post_only_rejection_rate_pct']:.2f}%"],
        ["Quote interval used", current_like["quote_interval_sec"]],
        ["Spread bps used", current_like["spread_bps"]],
        ["TTL used", current_like["ttl_sec"]],
    ]

    sweep_table_rows = [[
        r["spread_bps"],
        r["quote_interval_sec"],
        r["ttl_sec"],
        r["quotes"],
        r["fills"],
        f"{r['fill_rate_pct']:.2f}%",
        r["roundtrips"],
        f"{r['toxicity_60_pct_gross']:.2f}%",
        _safe_pct(r["gas_pct_of_gross_spread"]),
        _safe_money(r["gross_spread_captured_usd"]),
        _safe_money(r["estimated_gas_usd"]),
        _safe_money(r["adverse_selection_loss_usd"]),
        _safe_money(r["net_pnl_usd"]),
    ] for r in sweep_rows]

    summary_rows = []
    if summary:
        for m in summary.get("selected_markets", []):
            summary_rows.append([
                m.get("market_id", "")[:10] + "…",
                m.get("question", "")[:72],
                m.get("category", ""),
                summary.get("snapshots_written", {}).get(m.get("market_id", ""), 0),
            ])

    validation = f"""# Phase 3C Clean Targeted Validation

Generated: {now}

## Safety

- Live trading: **NO-GO**.
- This diagnostic reads only `{data_dir.relative_to(REPO)}`.
- No live orders, deposits, cancellations, or strategy-logic changes are performed by this script.

## Collection summary

{md_table(['Market','Question','Category','Snapshots written'], summary_rows) if summary_rows else 'No collection_summary.json found.'}

- Errors/timeouts/retries observed by collector: `{summary.get('error_count', 'not available') if summary else 'not available'}`
- Average request latency: `{round(summary.get('average_request_latency_sec'), 3) if summary and summary.get('average_request_latency_sec') is not None else 'not available'}s`

## Clean dataset verification

{md_table(['Rank','Market','Snapshots','Completeness','Activity','Fill rate','Buy fills','Sell fills','Roundtrips','60s toxicity'], market_rows)}

## Required current-like diagnostics

Current-like parameters: spread `200 bps`, quote interval `300s`, TTL `1800s`.

{md_table(['Metric','Value'], metric_rows)}

## Notes on monetary estimates

Gross spread, adverse-selection loss, and net P&L are conservative replay estimates from top-of-book movement, using configured order size converted to an approximate share count. They are **not live realized P&L** and do not prove executable fills.
"""

    sweep_report = f"""# Phase 3C Parameter Sweep — Clean Dataset Only

Generated: {now}

Dataset: `{data_dir.relative_to(REPO)}`

Grid:

- `spread_bps`: 25, 50, 100, 150, 200, 300
- `quote_interval_sec`: 60, 180, 300, 600, 900
- `ttl_sec`: 900, 1800, 3600

{md_table(['Spread bps','Quote interval','TTL','Quote count','Fills','Fill rate','Roundtrips','60s toxicity','Gas % gross','Gross spread','Gas','Adverse loss','Net P&L'], sweep_table_rows)}
"""

    gate_rows = [
        ["fill rate < 2%", f"{current_like['fill_rate_pct']:.2f}%", "FAIL" if gates["fill_rate_lt_2"] else "PASS"],
        ["no roundtrips", current_like["roundtrips"], "FAIL" if gates["no_roundtrips"] else "PASS"],
        ["net P&L <= 0 after gas", _safe_money(current_like["net_pnl_usd"]), "FAIL" if gates["net_pnl_lte_0"] else "PASS"],
        ["60s toxicity > 40% gross", f"{current_like['toxicity_60_pct_gross']:.2f}%", "FAIL" if gates["toxicity_gt_40"] else "PASS"],
        ["gas > 30% gross spread", _safe_pct(current_like["gas_pct_of_gross_spread"]), "FAIL" if gates["gas_gt_30_gross"] else "PASS"],
        ["best result unrealistic/stale", f"quotes={best['quotes']}, roundtrips={best['roundtrips']}", "FAIL" if gates["best_unrealistic"] else "PASS"],
    ]
    go_report = f"""# Phase 3C Go/No-Go — Clean Targeted Dataset

Generated: {now}

## Decision

**{decision}**

Live trading remains **NO-GO**.

## Gate evaluation

{md_table(['Gate','Observed','Result'], gate_rows)}

## Best sweep row

```json
{json.dumps(best, indent=2).replace('Infinity', '"Infinity"')}
```

## Current-like row

```json
{json.dumps(current_like, indent=2).replace('Infinity', '"Infinity"')}
```

## Exact next action

If decision is `PAUSE MARKET-MAKING AND PIVOT` or `KILL MARKET-MAKING FOR NOW`, do not run another passive market-making validation on the same assumptions. Pivot to slower holding/reward economics verification or cross-venue pricing research.
"""

    (REPORTS / "phase3c_clean_targeted_validation.md").write_text(validation, encoding="utf-8")
    (REPORTS / "phase3c_parameter_sweep.md").write_text(sweep_report, encoding="utf-8")
    (REPORTS / "phase3c_go_no_go.md").write_text(go_report, encoding="utf-8")
    return decision


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data_dir = args.data_dir if args.data_dir.is_absolute() else REPO / args.data_dir
    config = load_config(REPO / "config.yaml")
    order_size_usd = float(config.get("strategies", {}).get("market_making", {}).get("order_size_usd", 15.0))
    shares_per_fill = order_size_usd / 0.5
    gas_per_quote = _latest_gas_per_quote()

    all_rows, markets = load_rows(data_dir)
    if not all_rows:
        raise SystemExit(f"No JSONL snapshots found in {data_dir}")

    sweep_rows = sweep(
        all_rows,
        spreads=[25, 50, 100, 150, 200, 300],
        quote_intervals=[60, 180, 300, 600, 900],
        ttls=[900, 1800, 3600],
        gas_per_quote=gas_per_quote,
        shares_per_fill=shares_per_fill,
    )
    current_like = _summarize_combo(
        all_rows,
        spread=200,
        quote_interval=300,
        ttl=1800,
        gas_per_quote=gas_per_quote,
        shares_per_fill=shares_per_fill,
    )
    summary_path = data_dir / "collection_summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else None
    decision = write_phase3c_reports(data_dir, all_rows, markets, sweep_rows, current_like, summary)

    print(f"Dataset: {data_dir.relative_to(REPO)}")
    print(f"Markets: {len(all_rows)} snapshots: {sum(len(v) for v in all_rows.values())}")
    print("Current-like", json.dumps(current_like, sort_keys=True))
    print("Best sweep", json.dumps(sweep_rows[0], sort_keys=True))
    print("Decision", decision)


if __name__ == "__main__":
    main()
