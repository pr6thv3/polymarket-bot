"""Tests for the placeholder fill-probability model."""

import pytest

from research.fill_probability import PLACEHOLDER_COEFFICIENTS, estimate_fill_prob


def test_estimate_fill_prob_is_bounded():
    assert 0.0 <= estimate_fill_prob(0.0, 0.0, 0.0) <= 1.0
    assert 0.0 <= estimate_fill_prob(25.0, 10_000.0, 10_000.0) <= 1.0


def test_estimate_fill_prob_decreases_with_distance_from_mid():
    near_mid = estimate_fill_prob(0.5, 100.0, 500.0)
    far_from_mid = estimate_fill_prob(5.0, 100.0, 500.0)

    assert near_mid > far_from_mid


def test_estimate_fill_prob_decreases_with_arrival_latency():
    low_latency = estimate_fill_prob(1.0, 100.0, 100.0)
    high_latency = estimate_fill_prob(1.0, 100.0, 1800.0)

    assert low_latency > high_latency


def test_estimate_fill_prob_decreases_with_depth_ahead():
    shallow_queue = estimate_fill_prob(1.0, 10.0, 500.0)
    deep_queue = estimate_fill_prob(1.0, 1_000.0, 500.0)

    assert shallow_queue > deep_queue


def test_estimate_fill_prob_rejects_negative_inputs():
    with pytest.raises(ValueError, match="distance_from_mid_cents"):
        estimate_fill_prob(-0.1, 100.0, 500.0)
    with pytest.raises(ValueError, match="depth_at_best"):
        estimate_fill_prob(1.0, -1.0, 500.0)
    with pytest.raises(ValueError, match="arrival_latency_ms"):
        estimate_fill_prob(1.0, 100.0, -1.0)


def test_placeholder_coefficients_are_explicitly_not_zeroed():
    """Guard the deterministic placeholder shape until calibration replaces it."""
    assert PLACEHOLDER_COEFFICIENTS.distance_cents_weight > 0
    assert PLACEHOLDER_COEFFICIENTS.depth_log_weight > 0
    assert PLACEHOLDER_COEFFICIENTS.latency_seconds_weight > 0
