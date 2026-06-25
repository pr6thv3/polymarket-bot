# Phase 3B Market Selection Diagnostics Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Replace slow, low-signal passive paper validation with fast market-selection diagnostics that identify active, fillable Polymarket books before paper trading or Phase 4 SOR work.

**Architecture:** Add a reusable diagnostics layer that computes top-of-book movement, fill-through opportunity, spread stability, and quote-density metrics from collected JSONL snapshots and optionally from live scanner/book refreshes. Feed those diagnostics into reports first, then into `MarketScanner` scoring once validated. Keep trading behavior unchanged until tests and offline reports prove the new ranking selects better markets.

**Tech Stack:** Python 3.11, pytest, existing JSONL backtest format, existing `data.market_scanner.MarketScanner`, `core.backtest.BacktestEngine`, `tools/phase3b_diagnostics.py`, markdown reports.

---

## Current Context

Phase 3 long paper run was stopped intentionally after ~17 hours because it produced:

- 340 paper orders, 0 fills.
- Official backtest on collected data: 912 quotes, 0 trades, net P&L `-$4.53` from simulated gas only.
- POST_ONLY rejection rate `0.0%`, so quote rejection is not the blocker.
- Selected markets were very sticky: only 2–12 unique top-of-book states across ~12k snapshots each.

Existing files of interest:

- `tools/phase3b_diagnostics.py` — ad-hoc offline diagnostics script created during investigation.
- `reports/fill_diagnostics.md` — current diagnostic report.
- `reports/parameter_sweep_results.md` — current approximate sweep report.
- `reports/phase3_revised_go_no_go.md` — current no-go decision.
- `data/market_scanner.py` — current scanner scores volume/spread/rebate/holding/risk, but not top-of-book movement.
- `tests/test_market_scanner.py` — scanner unit tests.
- `tests/test_backtest.py` — backtest unit tests.

Hard constraints:

- Do not set `execution.dry_run: false`.
- Do not modify live trading strategy logic until diagnostics prove the change.
- Do not tune blindly.
- Do not use long passive paper runs as the first validation tool.
- Keep Cloudflare proxy URL unchanged.

---

## Proposed Approach

1. Promote the useful parts of `tools/phase3b_diagnostics.py` into tested, reusable functions.
2. Add a formal market activity diagnostic model that can score a snapshot series.
3. Add tests with tiny synthetic books that prove sticky markets score poorly and active markets score highly.
4. Extend the offline diagnostic report to rank markets by activity/fillability.
5. Only after offline tests pass, add optional activity-aware scanner scoring behind config flags.
6. Add reports documenting Phase 3B results and recommending a short, targeted paper validation on selected active markets.

---

## Task 1: Add Activity Metric Dataclass and Pure Functions

**Objective:** Create reusable pure functions for top-of-book movement and fill-opportunity metrics without touching live scanner behavior.

**Files:**
- Create: `data/market_activity.py`
- Test: `tests/test_market_activity.py`

**Step 1: Write failing tests**

Create `tests/test_market_activity.py`:

```python
"""Tests for market activity / fill-opportunity diagnostics."""

from data.market_activity import (
    BookSnapshot,
    compute_market_activity,
    quote_fill_opportunities,
)


def test_sticky_book_has_low_activity_score():
    snapshots = [
        BookSnapshot(timestamp=i * 10.0, best_bid=0.50, best_ask=0.52, mid=0.51)
        for i in range(20)
    ]

    metrics = compute_market_activity(snapshots)

    assert metrics.snapshot_count == 20
    assert metrics.unique_top_of_book == 1
    assert metrics.top_change_count == 0
    assert metrics.activity_score < 10.0


def test_moving_book_has_higher_activity_score():
    snapshots = [
        BookSnapshot(timestamp=0.0, best_bid=0.50, best_ask=0.52, mid=0.51),
        BookSnapshot(timestamp=10.0, best_bid=0.51, best_ask=0.53, mid=0.52),
        BookSnapshot(timestamp=20.0, best_bid=0.52, best_ask=0.54, mid=0.53),
        BookSnapshot(timestamp=30.0, best_bid=0.51, best_ask=0.52, mid=0.515),
    ]

    metrics = compute_market_activity(snapshots)

    assert metrics.unique_top_of_book == 4
    assert metrics.top_change_count == 3
    assert metrics.mid_range == 0.02
    assert metrics.activity_score > 10.0


def test_quote_fill_opportunities_count_trade_throughs():
    snapshots = [
        BookSnapshot(timestamp=0.0, best_bid=0.50, best_ask=0.52, mid=0.51),
        BookSnapshot(timestamp=60.0, best_bid=0.50, best_ask=0.51, mid=0.505),
        BookSnapshot(timestamp=120.0, best_bid=0.53, best_ask=0.54, mid=0.535),
    ]

    result = quote_fill_opportunities(
        snapshots=snapshots,
        spread_bps=200,
        quote_interval_sec=60,
        ttl_sec=180,
        tick_size=0.005,
    )

    assert result.quotes_generated == 6
    assert result.buy_fill_opportunities >= 1
    assert result.sell_fill_opportunities >= 1
    assert result.fill_opportunity_rate_pct > 0
```

**Step 2: Run tests to verify failure**

Run:

```bash
cd /c/Users/Preethve/polymarket-bot
.venv/Scripts/python.exe -m pytest tests/test_market_activity.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'data.market_activity'`.

**Step 3: Implement minimal module**

Create `data/market_activity.py`:

```python
"""Market activity and fill-opportunity diagnostics.

Pure functions only. No network calls, no order placement, no strategy side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Iterable, Sequence


@dataclass(frozen=True)
class BookSnapshot:
    timestamp: float
    best_bid: float
    best_ask: float
    mid: float


@dataclass(frozen=True)
class MarketActivityMetrics:
    snapshot_count: int
    unique_top_of_book: int
    top_change_count: int
    mid_range: float
    average_spread_cents: float
    snapshots_per_hour: float
    activity_score: float


@dataclass(frozen=True)
class FillOpportunityMetrics:
    quotes_generated: int
    buy_fill_opportunities: int
    sell_fill_opportunities: int
    roundtrip_opportunities: int
    fill_opportunity_rate_pct: float


def _round_tick(value: float, tick_size: float) -> float:
    return round(value / tick_size) * tick_size


def compute_market_activity(snapshots: Sequence[BookSnapshot]) -> MarketActivityMetrics:
    if not snapshots:
        return MarketActivityMetrics(0, 0, 0, 0.0, 0.0, 0.0, 0.0)

    tops = [(s.best_bid, s.best_ask) for s in snapshots]
    mids = [s.mid for s in snapshots]
    spreads = [(s.best_ask - s.best_bid) * 100 for s in snapshots]
    duration_sec = max(0.0, snapshots[-1].timestamp - snapshots[0].timestamp)
    snapshots_per_hour = len(snapshots) / (duration_sec / 3600.0) if duration_sec > 0 else float(len(snapshots))
    top_change_count = sum(1 for i in range(1, len(tops)) if tops[i] != tops[i - 1])
    top_change_rate = top_change_count / max(1, len(snapshots) - 1)
    mid_range = max(mids) - min(mids)
    average_spread_cents = mean(spreads) if spreads else 0.0

    # 0-100 heuristic: movement matters most, then mid volatility, then update density.
    movement_component = min(1.0, top_change_rate * 10.0) * 55.0
    mid_component = min(1.0, mid_range / 0.05) * 30.0
    density_component = min(1.0, snapshots_per_hour / 120.0) * 15.0
    activity_score = movement_component + mid_component + density_component

    return MarketActivityMetrics(
        snapshot_count=len(snapshots),
        unique_top_of_book=len(set(tops)),
        top_change_count=top_change_count,
        mid_range=mid_range,
        average_spread_cents=average_spread_cents,
        snapshots_per_hour=snapshots_per_hour,
        activity_score=activity_score,
    )


def quote_fill_opportunities(
    snapshots: Sequence[BookSnapshot],
    spread_bps: float,
    quote_interval_sec: float,
    ttl_sec: float,
    tick_size: float = 0.005,
) -> FillOpportunityMetrics:
    quotes_generated = 0
    buy_fills = 0
    sell_fills = 0
    roundtrips = 0
    last_quote_ts = -1e30

    for i, snapshot in enumerate(snapshots):
        if snapshot.timestamp - last_quote_ts < quote_interval_sec:
            continue
        last_quote_ts = snapshot.timestamp

        half_spread = spread_bps / 20000.0
        bid = min(_round_tick(snapshot.mid * (1 - half_spread), tick_size), snapshot.best_bid)
        ask = max(_round_tick(snapshot.mid * (1 + half_spread), tick_size), snapshot.best_ask)
        quotes_generated += 2

        buy_fill = False
        sell_fill = False
        end_ts = snapshot.timestamp + ttl_sec

        for later in snapshots[i + 1:]:
            if later.timestamp > end_ts:
                break
            if not buy_fill and later.best_ask <= bid:
                buy_fill = True
            if not sell_fill and later.best_bid >= ask:
                sell_fill = True
            if buy_fill and sell_fill:
                break

        buy_fills += int(buy_fill)
        sell_fills += int(sell_fill)
        roundtrips += int(buy_fill and sell_fill)

    fill_rate = ((buy_fills + sell_fills) / quotes_generated * 100.0) if quotes_generated else 0.0
    return FillOpportunityMetrics(
        quotes_generated=quotes_generated,
        buy_fill_opportunities=buy_fills,
        sell_fill_opportunities=sell_fills,
        roundtrip_opportunities=roundtrips,
        fill_opportunity_rate_pct=fill_rate,
    )
```

**Step 4: Run test to verify pass**

Run:

```bash
.venv/Scripts/python.exe -m pytest tests/test_market_activity.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add data/market_activity.py tests/test_market_activity.py
git commit -m "feat: add market activity diagnostics"
```

---

## Task 2: Refactor Phase 3B Script to Use Shared Diagnostics

**Objective:** Remove duplicated ad-hoc activity/fill logic from `tools/phase3b_diagnostics.py` and call `data.market_activity` functions instead.

**Files:**
- Modify: `tools/phase3b_diagnostics.py`
- Test: `tests/test_market_activity.py`

**Step 1: Write failing integration-ish test for JSONL loader helper**

Add to `tests/test_market_activity.py`:

```python
import json

from tools.phase3b_diagnostics import load_jsonl_snapshots


def test_load_jsonl_snapshots_skips_invalid_rows(tmp_path):
    path = tmp_path / "market.jsonl"
    path.write_text(
        "\n".join([
            json.dumps({"timestamp": 1.0, "bids": [[0.50, 10]], "asks": [[0.52, 10]], "mid": 0.51}),
            "not-json",
            json.dumps({"timestamp": 2.0, "bids": [], "asks": [[0.53, 10]], "mid": 0.52}),
        ])
    )

    snapshots = load_jsonl_snapshots(path)

    assert len(snapshots) == 1
    assert snapshots[0].best_bid == 0.50
    assert snapshots[0].best_ask == 0.52
```

**Step 2: Run test to verify failure**

```bash
.venv/Scripts/python.exe -m pytest tests/test_market_activity.py::test_load_jsonl_snapshots_skips_invalid_rows -q
```

Expected: FAIL — `load_jsonl_snapshots` does not exist.

**Step 3: Refactor script**

Modify `tools/phase3b_diagnostics.py`:

```python
from data.market_activity import (
    BookSnapshot,
    compute_market_activity,
    quote_fill_opportunities,
)


def load_jsonl_snapshots(path: Path) -> list[BookSnapshot]:
    snapshots: list[BookSnapshot] = []
    with path.open(errors="ignore") as f:
        for line in f:
            try:
                d = json.loads(line)
                bids = d.get("bids") or []
                asks = d.get("asks") or []
                if not bids or not asks:
                    continue
                bb = float(bids[0][0])
                ba = float(asks[0][0])
                mid = float(d.get("mid") or ((bb + ba) / 2))
                ts = float(d.get("timestamp") or 0)
                snapshots.append(BookSnapshot(timestamp=ts, best_bid=bb, best_ask=ba, mid=mid))
            except Exception:
                continue
    return snapshots
```

Then update `load_rows()` to:

```python
def load_rows():
    all_rows = {}
    markets = []
    for p in sorted(DATA_DIR.glob("*.jsonl")):
        snapshots = load_jsonl_snapshots(p)
        if not snapshots:
            continue
        all_rows[p.name] = snapshots
        metrics = compute_market_activity(snapshots)
        markets.append({
            "file": p.name,
            "market_id": p.stem,
            "snapshots": metrics.snapshot_count,
            "size": p.stat().st_size,
            "unique_top": metrics.unique_top_of_book,
            "top_changes": metrics.top_change_count,
            "first_top": (snapshots[0].best_bid, snapshots[0].best_ask),
            "last_top": (snapshots[-1].best_bid, snapshots[-1].best_ask),
            "mid_range": metrics.mid_range,
            "avg_spread_cents": metrics.average_spread_cents,
            "activity_score": metrics.activity_score,
        })
    return all_rows, markets
```

Update the script's `sweep()` implementation to call `quote_fill_opportunities()` for the core opportunity counts. Keep gas and optimistic net calculations in the script.

**Step 4: Run tests**

```bash
.venv/Scripts/python.exe -m pytest tests/test_market_activity.py -q
```

Expected: PASS.

**Step 5: Regenerate reports**

```bash
.venv/Scripts/python.exe tools/phase3b_diagnostics.py
```

Expected output includes:

```text
Wrote reports/fill_diagnostics.md
Wrote reports/parameter_sweep_results.md
Wrote reports/phase3_revised_go_no_go.md
```

**Step 6: Commit**

```bash
git add tools/phase3b_diagnostics.py reports/fill_diagnostics.md reports/parameter_sweep_results.md reports/phase3_revised_go_no_go.md tests/test_market_activity.py
git commit -m "refactor: reuse market activity diagnostics in phase3b reports"
```

---

## Task 3: Add Activity-Aware Scanner Fields Without Changing Eligibility

**Objective:** Extend `MarketInfo` with optional activity diagnostics so market selection can report activity without changing current scanner ranking yet.

**Files:**
- Modify: `data/market_scanner.py`
- Test: `tests/test_market_scanner.py`

**Step 1: Write failing test**

Add to `tests/test_market_scanner.py`:

```python
def test_market_info_has_activity_fields():
    info = MarketInfo(market_id="m1", token_id="t1")

    assert info.activity_score == 0.0
    assert info.top_change_count == 0
    assert info.unique_top_of_book == 0
    assert info.fill_opportunity_rate_pct == 0.0
```

**Step 2: Run failure**

```bash
.venv/Scripts/python.exe -m pytest tests/test_market_scanner.py::test_market_info_has_activity_fields -q
```

Expected: FAIL — missing attributes.

**Step 3: Implement fields**

Modify `MarketInfo` in `data/market_scanner.py` around lines 65–69:

```python
    # Activity diagnostics (optional, populated by offline/live diagnostics)
    activity_score: float = 0.0
    top_change_count: int = 0
    unique_top_of_book: int = 0
    fill_opportunity_rate_pct: float = 0.0
```

**Step 4: Run targeted test**

```bash
.venv/Scripts/python.exe -m pytest tests/test_market_scanner.py::test_market_info_has_activity_fields -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add data/market_scanner.py tests/test_market_scanner.py
git commit -m "feat: add market activity fields to scanner model"
```

---

## Task 4: Add Activity Score Component Behind Config Flag

**Objective:** Let scanner scoring include activity when explicitly enabled, but preserve current behavior by default.

**Files:**
- Modify: `data/market_scanner.py`
- Modify: `config.yaml`
- Test: `tests/test_market_scanner.py`

**Step 1: Write tests**

Add to `tests/test_market_scanner.py`:

```python
def test_activity_score_does_not_affect_score_by_default(scanner):
    low = MarketInfo(market_id="low", token_id="t", daily_volume_usd=50000, activity_score=0.0)
    high = MarketInfo(market_id="high", token_id="t", daily_volume_usd=50000, activity_score=100.0)

    scanner._compute_score(low)
    scanner._compute_score(high)

    assert low.score == high.score


def test_activity_score_affects_score_when_enabled(mock_client, mock_orderbook, scanner_config):
    scanner_config["strategies"]["market_making"]["scanner_use_activity_score"] = True
    scanner_config["strategies"]["market_making"]["scanner_weights"] = {
        "volume": 0.0,
        "spread_width": 0.0,
        "rebate_yield": 0.0,
        "holding_yield": 0.0,
        "resolution_risk": 0.0,
        "activity": 1.0,
    }
    scanner = MarketScanner(mock_client, mock_orderbook, scanner_config)
    low = MarketInfo(market_id="low", token_id="t", activity_score=0.0)
    high = MarketInfo(market_id="high", token_id="t", activity_score=80.0)

    scanner._compute_score(low)
    scanner._compute_score(high)

    assert high.score == 80.0
    assert low.score == 0.0
```

**Step 2: Run failure**

```bash
.venv/Scripts/python.exe -m pytest tests/test_market_scanner.py::test_activity_score_affects_score_when_enabled -q
```

Expected: FAIL — activity not included.

**Step 3: Implement config flag**

In `MarketScanner.__init__`, add:

```python
        self.use_activity_score = mm_cfg.get("scanner_use_activity_score", False)
```

In `_compute_score()`, add before composite score:

```python
        activity_norm = min(1.0, max(0.0, info.activity_score / 100.0)) if self.use_activity_score else 0.0
```

Then update score formula:

```python
        info.score = (
            w.get("volume", 0.25) * volume_norm
            + w.get("spread_width", 0.20) * spread_norm
            + w.get("rebate_yield", 0.25) * rebate_norm
            + w.get("holding_yield", 0.15) * holding_norm
            + w.get("resolution_risk", 0.15) * risk_factor
            + w.get("activity", 0.0) * activity_norm
        ) * 100.0
```

**Step 4: Add config defaults**

In `config.yaml` under `strategies.market_making`, add but keep disabled:

```yaml
    scanner_use_activity_score: false
    scanner_min_activity_score: 0.0
```

Do **not** change live behavior yet.

**Step 5: Run tests**

```bash
.venv/Scripts/python.exe -m pytest tests/test_market_scanner.py -q
```

Expected: PASS.

**Step 6: Commit**

```bash
git add data/market_scanner.py config.yaml tests/test_market_scanner.py
git commit -m "feat: gate scanner activity scoring behind config"
```

---

## Task 5: Add Optional Activity Eligibility Gate

**Objective:** Allow scanner to filter out sticky markets when explicitly configured.

**Files:**
- Modify: `data/market_scanner.py`
- Test: `tests/test_market_scanner.py`

**Step 1: Write tests**

Add to `tests/test_market_scanner.py`:

```python
def test_activity_gate_disabled_by_default(scanner):
    info = MarketInfo(
        market_id="m1",
        token_id="t1",
        category="politics",
        daily_volume_usd=10000,
        days_to_resolution=30,
        accepting_orders=True,
        enable_order_book=True,
        activity_score=0.0,
    )
    scanner._compute_score(info)

    assert scanner._is_eligible(info) is True


def test_activity_gate_filters_sticky_market_when_enabled(mock_client, mock_orderbook, scanner_config):
    scanner_config["strategies"]["market_making"]["scanner_min_activity_score"] = 20.0
    scanner = MarketScanner(mock_client, mock_orderbook, scanner_config)
    info = MarketInfo(
        market_id="m1",
        token_id="t1",
        category="politics",
        daily_volume_usd=10000,
        days_to_resolution=30,
        accepting_orders=True,
        enable_order_book=True,
        activity_score=5.0,
    )
    scanner._compute_score(info)

    assert scanner._is_eligible(info) is False
```

**Step 2: Run failure**

```bash
.venv/Scripts/python.exe -m pytest tests/test_market_scanner.py::test_activity_gate_filters_sticky_market_when_enabled -q
```

Expected: FAIL — gate not implemented.

**Step 3: Implement gate**

In `MarketScanner.__init__`, add:

```python
        self.min_activity_score = mm_cfg.get("scanner_min_activity_score", 0.0)
```

In `_is_eligible()` before minimum score threshold:

```python
        if self.min_activity_score > 0 and info.activity_score < self.min_activity_score:
            return False
```

**Step 4: Run tests**

```bash
.venv/Scripts/python.exe -m pytest tests/test_market_scanner.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add data/market_scanner.py tests/test_market_scanner.py
git commit -m "feat: add optional scanner activity gate"
```

---

## Task 6: Add Offline Candidate Ranking Report

**Objective:** Produce a concrete list of candidate markets ranked by activity and fill opportunities from collected datasets.

**Files:**
- Modify: `tools/phase3b_diagnostics.py`
- Create/Update: `reports/market_activity_ranking.md`
- Test: `tests/test_market_activity.py`

**Step 1: Add pure ranking helper test**

Add to `tests/test_market_activity.py`:

```python
from tools.phase3b_diagnostics import rank_market_candidates


def test_rank_market_candidates_orders_by_activity_and_fill_rate():
    candidates = [
        {"market_id": "sticky", "activity_score": 1.0, "fill_opportunity_rate_pct": 0.0},
        {"market_id": "active", "activity_score": 50.0, "fill_opportunity_rate_pct": 4.0},
    ]

    ranked = rank_market_candidates(candidates)

    assert ranked[0]["market_id"] == "active"
```

**Step 2: Run failure**

```bash
.venv/Scripts/python.exe -m pytest tests/test_market_activity.py::test_rank_market_candidates_orders_by_activity_and_fill_rate -q
```

Expected: FAIL — helper missing.

**Step 3: Implement helper**

In `tools/phase3b_diagnostics.py`:

```python
def rank_market_candidates(candidates: list[dict]) -> list[dict]:
    def key(c: dict) -> tuple[float, float, float]:
        return (
            float(c.get("fill_opportunity_rate_pct", 0.0)),
            float(c.get("activity_score", 0.0)),
            float(c.get("top_change_count", 0.0)),
        )
    return sorted(candidates, key=key, reverse=True)
```

Then in `main()`, build candidate rows for each JSONL file using:

```python
fill_metrics = quote_fill_opportunities(snapshots, spread_bps=200, quote_interval_sec=300, ttl_sec=1800)
```

Generate `reports/market_activity_ranking.md` with table columns:

- Market ID
- Snapshots
- Activity score
- Top changes
- Unique top states
- Fill opportunity rate
- Buy opportunities
- Sell opportunities
- Recommendation

**Step 4: Run tests and script**

```bash
.venv/Scripts/python.exe -m pytest tests/test_market_activity.py -q
.venv/Scripts/python.exe tools/phase3b_diagnostics.py
```

Expected:

```text
reports/market_activity_ranking.md
```

exists and ranks current collected markets.

**Step 5: Commit**

```bash
git add tools/phase3b_diagnostics.py tests/test_market_activity.py reports/market_activity_ranking.md
git commit -m "feat: report activity-ranked market candidates"
```

---

## Task 7: Add Paper State Persistence Plan/Test Stub Before Implementation

**Objective:** Document and test the persistence gap found during Phase 3 without changing live execution behavior yet.

**Files:**
- Modify: `tests/test_paper_executor.py`
- Later modify: `core/paper_executor.py`, `main.py`

**Step 1: Write failing serialization test**

Add to `tests/test_paper_executor.py`:

```python
def test_paper_executor_stats_expose_serializable_open_orders(paper_executor):
    stats = paper_executor.get_stats()

    assert "open_order_details" in stats
    assert isinstance(stats["open_order_details"], list)
```

If no `paper_executor` fixture exists, create one using existing test patterns in `tests/test_paper_executor.py`.

**Step 2: Run failure**

```bash
.venv/Scripts/python.exe -m pytest tests/test_paper_executor.py::test_paper_executor_stats_expose_serializable_open_orders -q
```

Expected: FAIL — missing `open_order_details`.

**Step 3: Implement only serializable stats, not disk persistence yet**

In `core/paper_executor.py`, update `get_stats()` to include:

```python
            "open_order_details": [
                {
                    "order_id": o.order_id,
                    "market_id": o.market_id,
                    "token_id": o.token_id,
                    "side": o.side,
                    "price": o.price,
                    "size": o.size,
                    "status": o.status,
                    "category": o.category,
                    "placed_at": o.placed_at,
                    "placed_at_snapshot_time": o.placed_at_snapshot_time,
                }
                for o in self._orders.values()
                if o.is_open
            ],
```

**Step 4: Run tests**

```bash
.venv/Scripts/python.exe -m pytest tests/test_paper_executor.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add core/paper_executor.py tests/test_paper_executor.py
git commit -m "feat: expose serializable paper open orders"
```

---

## Task 8: Persist Paper State to Disk in Paper Mode

**Objective:** Make future paper runs inspectable via files instead of relying only on logs.

**Files:**
- Modify: `core/paper_executor.py`
- Modify: `main.py`
- Test: `tests/test_paper_executor.py`

**Step 1: Write failing test for `save_state()`**

Add to `tests/test_paper_executor.py`:

```python
import json


@pytest.mark.asyncio
async def test_paper_executor_save_state_writes_json(tmp_path, paper_executor):
    output = tmp_path / "paper_orders.json"

    await paper_executor.save_state(output)

    data = json.loads(output.read_text())
    assert "stats" in data
    assert "open_orders" in data
```

**Step 2: Run failure**

```bash
.venv/Scripts/python.exe -m pytest tests/test_paper_executor.py::test_paper_executor_save_state_writes_json -q
```

Expected: FAIL — no `save_state()`.

**Step 3: Implement `save_state()`**

In `core/paper_executor.py`:

```python
    async def save_state(self, path) -> None:
        """Persist paper executor state for inspection/debugging."""
        import json
        from pathlib import Path
        from datetime import datetime, timezone

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        stats = self.get_stats()
        payload = {
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "stats": {k: v for k, v in stats.items() if k != "open_order_details"},
            "open_orders": stats.get("open_order_details", []),
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
```

**Step 4: Wire save loop in `main.py`**

In `_portfolio_save_loop()`, after saving real portfolio, add:

```python
                if self.paper_mode and hasattr(self.executor, "save_state"):
                    await self.executor.save_state("state/paper_orders.json")
```

This is paper-mode only and does not affect live trading.

**Step 5: Run tests**

```bash
.venv/Scripts/python.exe -m pytest tests/test_paper_executor.py -q
.venv/Scripts/python.exe -m pytest tests/ -q
```

Expected: full suite still `412+` passing. Count may increase due to new tests.

**Step 6: Commit**

```bash
git add core/paper_executor.py main.py tests/test_paper_executor.py
git commit -m "feat: persist paper trading state snapshots"
```

---

## Task 9: Update Walkthrough and Phase 3 Reports

**Objective:** Make project artifacts reflect the pivot from passive paper validation to Phase 3B diagnostics.

**Files:**
- Modify: `walkthrough.md`
- Modify: `task.md`
- Modify: `reports/phase3_revised_go_no_go.md`

**Step 1: Update `task.md`**

Add a section:

```markdown
## Phase 3 status — revised

Long passive paper validation was stopped after zero fills and negative backtest net P&L. Current priority is Phase 3B: market-selection diagnostics.

Next implementation target:
1. Add tested `data/market_activity.py` diagnostics.
2. Refactor `tools/phase3b_diagnostics.py` to reuse them.
3. Add activity-aware scanner scoring behind config flags.
4. Persist paper executor state for future short paper runs.
```

**Step 2: Update `walkthrough.md`**

Add:

```markdown
## Phase 3B workflow

Run offline diagnostics first:

```bash
.venv/Scripts/python.exe tools/phase3b_diagnostics.py
```

Only run paper mode after the diagnostic reports identify active markets with sufficient fill opportunity.
```

**Step 3: Update `reports/phase3_revised_go_no_go.md`**

Add an explicit implementation checklist linking to the new plan.

**Step 4: Commit**

```bash
git add task.md walkthrough.md reports/phase3_revised_go_no_go.md
git commit -m "docs: document phase3b diagnostic pivot"
```

---

## Task 10: Final Verification and Push

**Objective:** Verify the full codebase and push meaningful checkpoints.

**Files:**
- All changed files.

**Step 1: Run full tests**

```bash
cd /c/Users/Preethve/polymarket-bot
.venv/Scripts/python.exe -m pytest tests/ -q
```

Expected: all tests pass. Previously baseline was `412 passed`; new tests should increase count.

**Step 2: Run diagnostics script**

```bash
.venv/Scripts/python.exe tools/phase3b_diagnostics.py
```

Expected: reports regenerate successfully.

**Step 3: Check dry run still true**

```bash
grep "dry_run" config.yaml
```

Expected:

```yaml
  dry_run: true
```

**Step 4: Check no direct CLOB references were introduced**

```bash
grep -r "clob.polymarket.com" . --include="*.py"
```

Expected: no output.

**Step 5: Push**

```bash
git status --short
git push origin master
```

Expected: push succeeds.

---

## Risks and Tradeoffs

| Risk | Mitigation |
|---|---|
| Activity scoring overfits the tiny collected dataset | Keep scanner behavior unchanged by default; use offline diagnostics first. |
| Fill-opportunity approximation differs from production backtester | Label sweep as optimistic; use official backtest as authority for P&L. |
| Adding activity fields changes old tests unexpectedly | Defaults preserve existing behavior. |
| Paper persistence accidentally affects live trading | Gate persistence under `self.paper_mode`. |
| Reports include large JSONL data in git | Commit reports and scripts; decide separately whether raw `data/backtest/*.jsonl` belongs in repo. |

---

## Open Questions

1. Should raw JSONL backtest data be committed, or should reports/results only be committed?
2. Should activity scoring eventually fetch live top-of-book history, or only use collector/backtest datasets?
3. What minimum activity threshold should trigger a short paper run? Initial candidate: `activity_score >= 20` and `fill_opportunity_rate_pct >= 5%`.
4. Should scanner temporarily include crypto/sports for diagnostics even if live strategy remains politics/geopolitics/finance?

---

## Execution Handoff

Plan complete. Ready to execute using subagent-driven-development — dispatch a fresh subagent per task with two-stage review: spec compliance, then code quality. Proceed only when both reviews approve each task.
