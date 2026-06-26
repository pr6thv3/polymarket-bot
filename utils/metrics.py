"""Prometheus metrics for the Polymarket trading bot."""

import logging
import threading
from typing import Optional

from prometheus_client import Counter, Gauge, start_http_server

logger = logging.getLogger(__name__)

# --- Counters ---

spread_captured_usd = Counter(
    "polymarket_spread_captured_usd_daily",
    "Total spread captured in USD (daily cumulative)",
)

rebate_earned_usd = Counter(
    "polymarket_rebate_earned_usd_daily",
    "Total maker rebates earned in USD (daily cumulative)",
)

holding_reward_usd = Counter(
    "polymarket_holding_reward_usd_daily",
    "Total holding rewards earned in USD (daily cumulative)",
)

adverse_selection_losses_usd = Counter(
    "polymarket_adverse_selection_losses_usd",
    "Total losses from adverse selection in USD",
)

circuit_breaker_triggers = Counter(
    "polymarket_circuit_breaker_triggers_total",
    "Number of times the circuit breaker has triggered",
)

post_only_rejections = Counter(
    "polymarket_post_only_rejections_total",
    "Number of POST_ONLY order rejections (expected, not errors)",
)

signals_generated = Counter(
    "polymarket_signals_generated_total",
    "Total AI signals generated",
    ["market_id", "direction"],
)

signal_edge_usd = Counter(
    "polymarket_signal_edge_usd_total",
    "Total signal edge in USD",
)

orders_placed = Counter(
    "polymarket_orders_placed_total",
    "Total number of orders placed",
    ["market_id", "side"],
)

orders_filled = Counter(
    "polymarket_orders_filled_total",
    "Total number of orders filled",
    ["market_id", "side"],
)

# --- Gauges ---

fill_rate_pct = Gauge(
    "polymarket_fill_rate_pct",
    "Percentage of placed orders that were filled",
)

pnl_usd_total = Gauge(
    "polymarket_pnl_usd_total",
    "Current total P&L in USD",
)

arb_opportunities_found = Gauge(
    "polymarket_arb_opportunities_found",
    "Current number of cross-platform arbitrage opportunities found",
)

arb_pnl_usd_total = Gauge(
    "polymarket_arb_pnl_usd_total",
    "Cumulative cross-platform arbitrage P&L in USD",
)


_metrics_server_started = False
_metrics_lock = threading.Lock()


def start_metrics_server(port: int = 9090) -> None:
    """Start the Prometheus metrics HTTP server.

    Safe to call multiple times — only starts once.

    Args:
        port: Port to serve metrics on.
    """
    global _metrics_server_started

    with _metrics_lock:
        if _metrics_server_started:
            logger.info("Metrics server already running on port %d", port)
            return

        try:
            start_http_server(port)
            _metrics_server_started = True
            logger.info("Prometheus metrics server started on port %d", port)
        except OSError as e:
            logger.error("Failed to start metrics server on port %d: %s", port, e)


def record_order_placed(market_id: str, side: str) -> None:
    """Record a placed order."""
    orders_placed.labels(market_id=market_id, side=side).inc()


def record_order_filled(market_id: str, side: str) -> None:
    """Record a filled order."""
    orders_filled.labels(market_id=market_id, side=side).inc()


def record_spread_captured(amount_usd: float) -> None:
    """Record spread captured."""
    spread_captured_usd.inc(amount_usd)


def record_rebate_earned(amount_usd: float) -> None:
    """Record maker rebate earned."""
    rebate_earned_usd.inc(amount_usd)


def record_holding_reward(amount_usd: float) -> None:
    """Record holding reward earned."""
    holding_reward_usd.inc(amount_usd)


def record_adverse_selection_loss(amount_usd: float) -> None:
    """Record loss from adverse selection."""
    adverse_selection_losses_usd.inc(amount_usd)


def record_circuit_breaker_trigger() -> None:
    """Record a circuit breaker trigger."""
    circuit_breaker_triggers.inc()


def record_post_only_rejection() -> None:
    """Record a POST_ONLY order rejection."""
    post_only_rejections.inc()


def update_fill_rate(rate_pct: float) -> None:
    """Update the current fill rate gauge."""
    fill_rate_pct.set(rate_pct)


def update_pnl(amount_usd: float) -> None:
    """Update the total P&L gauge."""
    pnl_usd_total.set(amount_usd)


def update_arb_opportunities_found(count: int) -> None:
    """Update current cross-platform arbitrage opportunity count."""
    arb_opportunities_found.set(count)


def record_arb_pnl(amount_usd: float) -> None:
    """Record realized cross-platform arbitrage P&L.

    Uses a gauge because realized P&L can be positive or negative.
    """
    if amount_usd >= 0:
        arb_pnl_usd_total.inc(amount_usd)
    else:
        arb_pnl_usd_total.dec(abs(amount_usd))



def record_signal_generated(market_id: str, direction: str, edge_usd: float = 0.0) -> None:
    """Record an AI signal generated.

    Args:
        market_id: Market the signal was generated for.
        direction: Signal direction ("BUY" or "SELL").
        edge_usd: Estimated edge in USD.
    """
    signals_generated.labels(market_id=market_id, direction=direction).inc()
    if edge_usd > 0:
        signal_edge_usd.inc(edge_usd)
