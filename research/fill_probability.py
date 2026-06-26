"""Placeholder fill-probability model for prediction-market CLOB research.

This module is intentionally standalone and calibration-ready.  The default
coefficients below are placeholders, not empirical evidence.  They exist only so
backtest/replay plumbing can depend on a deterministic interface while the real
model is later calibrated from trade/depth data.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class FillProbabilityCoefficients:
    """Coefficients for the placeholder logistic fill-probability model.

    Formula:
        z = intercept
            - distance_cents_weight * distance_from_mid_cents
            - depth_log_weight * log1p(depth_at_best)
            - latency_seconds_weight * (arrival_latency_ms / 1000)
        fill_probability = sigmoid(z)

    Interpretation:
    - ``distance_from_mid_cents`` is absolute quote distance from mid in cents.
    - ``depth_at_best`` is treated as visible queue/depth ahead at the quote.
    - ``arrival_latency_ms`` is the estimated latency before the order can join
      or react to the book.

    These coefficients are deliberately conservative placeholders and must be
    replaced by calibrated values before any profitability or live-readiness
    claim can rely on this model.
    """

    intercept: float = 1.50
    distance_cents_weight: float = 0.45
    depth_log_weight: float = 0.20
    latency_seconds_weight: float = 1.00


PLACEHOLDER_COEFFICIENTS = FillProbabilityCoefficients()


def _require_non_negative(name: str, value: float) -> float:
    numeric = float(value)
    if numeric < 0:
        raise ValueError(f"{name} must be non-negative")
    return numeric


def _sigmoid(value: float) -> float:
    # Clamp to avoid overflow while preserving practical probability bounds.
    bounded = max(-60.0, min(60.0, value))
    return 1.0 / (1.0 + math.exp(-bounded))


def estimate_fill_prob(
    distance_from_mid_cents: float,
    depth_at_best: float,
    arrival_latency_ms: float,
) -> float:
    """Estimate maker-fill probability using a placeholder logistic model.

    Args:
        distance_from_mid_cents: Absolute quote distance from mid in cents.
        depth_at_best: Visible depth/queue ahead at the best quote.
        arrival_latency_ms: Estimated order-arrival or reaction latency.

    Returns:
        Probability in ``[0.0, 1.0]``.

    Notes:
        This is not a calibrated model.  It is a deterministic, monotone
        placeholder for Block 3.1.  Any replay, backtest, or paper result using
        these coefficients must be labeled as placeholder-model output until
        calibration data replaces ``PLACEHOLDER_COEFFICIENTS``.
    """
    distance = _require_non_negative("distance_from_mid_cents", distance_from_mid_cents)
    depth = _require_non_negative("depth_at_best", depth_at_best)
    latency_ms = _require_non_negative("arrival_latency_ms", arrival_latency_ms)

    c = PLACEHOLDER_COEFFICIENTS
    score = (
        c.intercept
        - c.distance_cents_weight * distance
        - c.depth_log_weight * math.log1p(depth)
        - c.latency_seconds_weight * (latency_ms / 1000.0)
    )
    return _sigmoid(score)
