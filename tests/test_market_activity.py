"""Tests for market activity / fill-opportunity diagnostics."""

import json

from data.market_activity import (
    BookSnapshot,
    compute_market_activity,
    quote_fill_markouts,
    quote_fill_opportunities,
    quote_fill_pnl_by_adverse_selection,
)
from tools.phase3b_diagnostics import load_jsonl_snapshots, rank_market_candidates


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
        BookSnapshot(timestamp=60.0, best_bid=0.49, best_ask=0.50, mid=0.495),
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


def test_quote_fill_markouts_measure_adverse_selection_after_fill():
    snapshots = [
        BookSnapshot(timestamp=0.0, best_bid=0.50, best_ask=0.52, mid=0.51),
        # BUY quote from t=0 fills when ask trades through/touches the bid.
        BookSnapshot(timestamp=10.0, best_bid=0.48, best_ask=0.50, mid=0.49),
        # After the fill, midpoint moves further against the bought inventory.
        BookSnapshot(timestamp=70.0, best_bid=0.46, best_ask=0.48, mid=0.47),
    ]

    result = quote_fill_markouts(
        snapshots=snapshots,
        spread_bps=200,
        quote_interval_sec=999,
        ttl_sec=120,
        horizons_sec=(60,),
        tick_size=0.005,
    )

    assert result.quotes_generated == 2
    assert result.fills == 1
    assert result.fill_rate_pct == 50.0
    assert result.average_adverse_markout[60] > 0
    assert result.adverse_markout_pct_of_gross[60] > 100.0


def test_quote_fill_pnl_breakdown_classifies_adverse_buy_fill():
    snapshots = [
        BookSnapshot(timestamp=0.0, best_bid=0.50, best_ask=0.52, mid=0.51),
        BookSnapshot(timestamp=10.0, best_bid=0.48, best_ask=0.50, mid=0.49),
        BookSnapshot(timestamp=70.0, best_bid=0.46, best_ask=0.48, mid=0.47),
    ]

    result = quote_fill_pnl_by_adverse_selection(
        snapshots=snapshots,
        spread_bps=200,
        quote_interval_sec=999,
        ttl_sec=120,
        horizon_sec=60,
        size=10.0,
        tick_size=0.005,
    )

    assert result.quotes_generated == 2
    assert result.observed_fills == 1
    assert result.classified_fills == 1
    assert result.unclassified_fills == 0
    assert result.adverse_fills == 1
    assert result.non_adverse_fills == 0
    assert result.adverse_pnl < 0
    assert result.total_pnl == result.adverse_pnl
    assert result.adverse_fill_rate_pct == 100.0


def test_quote_fill_pnl_breakdown_classifies_favorable_sell_fill():
    snapshots = [
        BookSnapshot(timestamp=0.0, best_bid=0.50, best_ask=0.52, mid=0.51),
        BookSnapshot(timestamp=10.0, best_bid=0.53, best_ask=0.55, mid=0.54),
        BookSnapshot(timestamp=70.0, best_bid=0.47, best_ask=0.51, mid=0.49),
    ]

    result = quote_fill_pnl_by_adverse_selection(
        snapshots=snapshots,
        spread_bps=200,
        quote_interval_sec=999,
        ttl_sec=120,
        horizon_sec=60,
        size=10.0,
        tick_size=0.005,
    )

    assert result.observed_fills == 1
    assert result.classified_fills == 1
    assert result.adverse_fills == 0
    assert result.non_adverse_fills == 1
    assert result.non_adverse_pnl > 0
    assert result.total_pnl == result.non_adverse_pnl
    assert result.adverse_fill_rate_pct == 0.0


def test_quote_fill_pnl_breakdown_leaves_missing_horizon_unclassified():
    snapshots = [
        BookSnapshot(timestamp=0.0, best_bid=0.50, best_ask=0.52, mid=0.51),
        BookSnapshot(timestamp=10.0, best_bid=0.48, best_ask=0.50, mid=0.49),
    ]

    result = quote_fill_pnl_by_adverse_selection(
        snapshots=snapshots,
        spread_bps=200,
        quote_interval_sec=999,
        ttl_sec=120,
        horizon_sec=60,
        size=10.0,
        tick_size=0.005,
    )

    assert result.observed_fills == 1
    assert result.classified_fills == 0
    assert result.unclassified_fills == 1
    assert result.total_pnl == 0.0
    assert result.adverse_fill_rate_pct == 0.0


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


def test_rank_market_candidates_orders_by_activity_and_fill_rate():
    candidates = [
        {"market_id": "sticky", "activity_score": 1.0, "fill_opportunity_rate_pct": 0.0},
        {"market_id": "active", "activity_score": 50.0, "fill_opportunity_rate_pct": 4.0},
    ]

    ranked = rank_market_candidates(candidates)

    assert ranked[0]["market_id"] == "active"
