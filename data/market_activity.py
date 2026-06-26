"""Market activity and fill-opportunity diagnostics.

Pure functions only. No network calls, no order placement, no strategy side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Sequence


@dataclass(frozen=True)
class BookSnapshot:
    """Top-of-book snapshot for activity diagnostics."""

    timestamp: float
    best_bid: float
    best_ask: float
    mid: float


@dataclass(frozen=True)
class MarketActivityMetrics:
    """Summary metrics describing how active a market book is."""

    snapshot_count: int
    unique_top_of_book: int
    top_change_count: int
    mid_range: float
    average_spread_cents: float
    snapshots_per_hour: float
    activity_score: float


@dataclass(frozen=True)
class FillOpportunityMetrics:
    """Counts of maker fill opportunities for hypothetical quotes."""

    quotes_generated: int
    buy_fill_opportunities: int
    sell_fill_opportunities: int
    roundtrip_opportunities: int
    fill_opportunity_rate_pct: float


@dataclass(frozen=True)
class FillMarkoutMetrics:
    """Adverse-selection markouts for hypothetical maker fills.

    Markout is measured from the maker fill price to a future midpoint.
    For BUY fills, adverse markout is `fill_price - future_mid` when positive.
    For SELL fills, adverse markout is `future_mid - fill_price` when positive.
    """

    quotes_generated: int
    fills: int
    fill_rate_pct: float
    average_gross_edge: float
    average_adverse_markout: dict[int, float]
    adverse_markout_pct_of_gross: dict[int, float]


@dataclass(frozen=True)
class AdverseSelectionPnLBreakdown:
    """P&L split by whether a maker fill was adverse at a future horizon.

    `observed_fills` counts hypothetical maker fills whose quote was
    touched/traded-through inside TTL. `classified_fills` counts the subset
    with a future midpoint at `fill_ts + horizon_sec`; only classified fills
    contribute to P&L buckets.
    """

    quotes_generated: int
    observed_fills: int
    classified_fills: int
    unclassified_fills: int
    adverse_fills: int
    non_adverse_fills: int
    adverse_pnl: float
    non_adverse_pnl: float
    total_pnl: float
    adverse_fill_rate_pct: float
    average_adverse_pnl: float
    average_non_adverse_pnl: float


def _first_snapshot_at_or_after(
    snapshots: Sequence[BookSnapshot],
    start_index: int,
    target_ts: float,
) -> BookSnapshot | None:
    for snapshot in snapshots[start_index:]:
        if snapshot.timestamp >= target_ts:
            return snapshot
    return None


def _round_tick(value: float, tick_size: float) -> float:
    return round(value / tick_size) * tick_size


def compute_market_activity(snapshots: Sequence[BookSnapshot]) -> MarketActivityMetrics:
    """Compute top-of-book movement metrics for a market.

    Args:
        snapshots: Ordered top-of-book snapshots.

    Returns:
        MarketActivityMetrics with a 0-100 heuristic activity score.
    """
    if not snapshots:
        return MarketActivityMetrics(0, 0, 0, 0.0, 0.0, 0.0, 0.0)

    tops = [(s.best_bid, s.best_ask) for s in snapshots]
    mids = [s.mid for s in snapshots]
    spreads = [(s.best_ask - s.best_bid) * 100 for s in snapshots]
    duration_sec = max(0.0, snapshots[-1].timestamp - snapshots[0].timestamp)
    snapshots_per_hour = len(snapshots) / (duration_sec / 3600.0) if duration_sec > 0 else float(len(snapshots))
    top_change_count = sum(1 for i in range(1, len(tops)) if tops[i] != tops[i - 1])
    top_change_rate = top_change_count / max(1, len(snapshots) - 1)
    mid_range = round(max(mids) - min(mids), 10)
    average_spread_cents = mean(spreads) if spreads else 0.0

    # 0-100 heuristic: movement matters most, then mid volatility, then update density.
    movement_component = min(1.0, top_change_rate * 10.0) * 55.0
    mid_component = min(1.0, mid_range / 0.05) * 30.0
    density_component = min(1.0, snapshots_per_hour / 120.0) * 15.0 if top_change_count > 0 else 0.0
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
    """Count hypothetical maker fill opportunities in a snapshot series.

    BUY quote fills if a later best ask trades through/touches our bid.
    SELL quote fills if a later best bid trades through/touches our ask.
    """
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


def quote_fill_markouts(
    snapshots: Sequence[BookSnapshot],
    spread_bps: float,
    quote_interval_sec: float,
    ttl_sec: float,
    horizons_sec: Sequence[int] = (5, 30, 60, 300),
    tick_size: float = 0.005,
) -> FillMarkoutMetrics:
    """Measure adverse-selection markouts for hypothetical maker fills.

    This diagnostic is intentionally conservative: a fill is counted only after a
    subsequent snapshot trades through/touches the maker quote, and toxicity is
    measured against later midpoint movement.
    """
    quotes_generated = 0
    fills: list[tuple[str, float, float, int]] = []  # side, fill_price, gross_edge, fill_index
    adverse_by_horizon: dict[int, list[float]] = {int(h): [] for h in horizons_sec}
    last_quote_ts = -1e30

    for i, snapshot in enumerate(snapshots):
        if snapshot.timestamp - last_quote_ts < quote_interval_sec:
            continue
        last_quote_ts = snapshot.timestamp

        half_spread = spread_bps / 20000.0
        bid = min(_round_tick(snapshot.mid * (1 - half_spread), tick_size), snapshot.best_bid)
        ask = max(_round_tick(snapshot.mid * (1 + half_spread), tick_size), snapshot.best_ask)
        quotes_generated += 2
        end_ts = snapshot.timestamp + ttl_sec

        quote_fills: list[tuple[str, float, float, int]] = []
        buy_filled = False
        sell_filled = False
        for later_index, later in enumerate(snapshots[i + 1:], start=i + 1):
            if later.timestamp > end_ts:
                break
            if not buy_filled and later.best_ask <= bid:
                quote_fills.append(("BUY", bid, max(0.0, snapshot.mid - bid), later_index))
                buy_filled = True
            if not sell_filled and later.best_bid >= ask:
                quote_fills.append(("SELL", ask, max(0.0, ask - snapshot.mid), later_index))
                sell_filled = True
            if buy_filled and sell_filled:
                break

        for side, fill_price, gross_edge, fill_index in quote_fills:
            fills.append((side, fill_price, gross_edge, fill_index))
            fill_ts = snapshots[fill_index].timestamp
            for horizon in adverse_by_horizon:
                future = _first_snapshot_at_or_after(snapshots, fill_index, fill_ts + horizon)
                if future is None:
                    continue
                if side == "BUY":
                    adverse = max(0.0, fill_price - future.mid)
                else:
                    adverse = max(0.0, future.mid - fill_price)
                adverse_by_horizon[horizon].append(adverse)

    fill_count = len(fills)
    fill_rate = (fill_count / quotes_generated * 100.0) if quotes_generated else 0.0
    avg_gross = sum(fill[2] for fill in fills) / fill_count if fill_count else 0.0
    avg_adverse = {
        horizon: (sum(values) / len(values) if values else 0.0)
        for horizon, values in adverse_by_horizon.items()
    }
    adverse_pct = {
        horizon: ((avg / avg_gross * 100.0) if avg_gross > 0 else 0.0)
        for horizon, avg in avg_adverse.items()
    }
    return FillMarkoutMetrics(
        quotes_generated=quotes_generated,
        fills=fill_count,
        fill_rate_pct=fill_rate,
        average_gross_edge=avg_gross,
        average_adverse_markout=avg_adverse,
        adverse_markout_pct_of_gross=adverse_pct,
    )

def quote_fill_pnl_by_adverse_selection(
    snapshots: Sequence[BookSnapshot],
    spread_bps: float,
    quote_interval_sec: float,
    ttl_sec: float,
    horizon_sec: int = 60,
    size: float = 1.0,
    tick_size: float = 0.005,
) -> AdverseSelectionPnLBreakdown:
    """Split hypothetical maker-fill P&L by adverse vs non-adverse fills.

    The fill detector intentionally matches `quote_fill_markouts(...)`: a BUY
    quote fills when a later best ask touches/trades through the bid, and a SELL
    quote fills when a later best bid touches/trades through the ask.

    P&L is marked to the first midpoint at or after `fill_ts + horizon_sec`.
    BUY P&L is `(future_mid - fill_price) * size`; SELL P&L is
    `(fill_price - future_mid) * size`. Negative P&L is classified adverse.
    """
    if size < 0:
        raise ValueError("size must be non-negative")

    quotes_generated = 0
    observed_fills = 0
    unclassified_fills = 0
    adverse_fills = 0
    non_adverse_fills = 0
    adverse_pnl = 0.0
    non_adverse_pnl = 0.0
    last_quote_ts = -1e30

    for i, snapshot in enumerate(snapshots):
        if snapshot.timestamp - last_quote_ts < quote_interval_sec:
            continue
        last_quote_ts = snapshot.timestamp

        half_spread = spread_bps / 20000.0
        bid = min(_round_tick(snapshot.mid * (1 - half_spread), tick_size), snapshot.best_bid)
        ask = max(_round_tick(snapshot.mid * (1 + half_spread), tick_size), snapshot.best_ask)
        quotes_generated += 2
        end_ts = snapshot.timestamp + ttl_sec

        quote_fills: list[tuple[str, float, int]] = []
        buy_filled = False
        sell_filled = False
        for later_index, later in enumerate(snapshots[i + 1:], start=i + 1):
            if later.timestamp > end_ts:
                break
            if not buy_filled and later.best_ask <= bid:
                quote_fills.append(("BUY", bid, later_index))
                buy_filled = True
            if not sell_filled and later.best_bid >= ask:
                quote_fills.append(("SELL", ask, later_index))
                sell_filled = True
            if buy_filled and sell_filled:
                break

        for side, fill_price, fill_index in quote_fills:
            observed_fills += 1
            fill_ts = snapshots[fill_index].timestamp
            future = _first_snapshot_at_or_after(
                snapshots,
                fill_index,
                fill_ts + horizon_sec,
            )
            if future is None:
                unclassified_fills += 1
                continue

            if side == "BUY":
                pnl = (future.mid - fill_price) * size
            else:
                pnl = (fill_price - future.mid) * size

            if pnl < 0:
                adverse_fills += 1
                adverse_pnl += pnl
            else:
                non_adverse_fills += 1
                non_adverse_pnl += pnl

    classified_fills = adverse_fills + non_adverse_fills
    total_pnl = adverse_pnl + non_adverse_pnl
    adverse_fill_rate = (
        adverse_fills / classified_fills * 100.0 if classified_fills else 0.0
    )
    average_adverse = adverse_pnl / adverse_fills if adverse_fills else 0.0
    average_non_adverse = (
        non_adverse_pnl / non_adverse_fills if non_adverse_fills else 0.0
    )

    return AdverseSelectionPnLBreakdown(
        quotes_generated=quotes_generated,
        observed_fills=observed_fills,
        classified_fills=classified_fills,
        unclassified_fills=unclassified_fills,
        adverse_fills=adverse_fills,
        non_adverse_fills=non_adverse_fills,
        adverse_pnl=adverse_pnl,
        non_adverse_pnl=non_adverse_pnl,
        total_pnl=total_pnl,
        adverse_fill_rate_pct=adverse_fill_rate,
        average_adverse_pnl=average_adverse,
        average_non_adverse_pnl=average_non_adverse,
    )

