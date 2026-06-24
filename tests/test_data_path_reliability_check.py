"""Tests for data-path reliability gate calculations."""

from tools.data_path_reliability_check import evaluate_reliability_gate, percentile


def test_error_rate_gate_passes_for_research_but_fails_latency_sensitive():
    gates = evaluate_reliability_gate(error_rate_pct=10.0, p95_latency_ms=500, consecutive_failure_max=1)

    assert gates.latency_sensitive_pass is False
    assert gates.research_pass is True
    assert gates.simulator_results_reliable is True


def test_error_rate_gate_fails_research_above_20_percent():
    gates = evaluate_reliability_gate(error_rate_pct=21.0, p95_latency_ms=500, consecutive_failure_max=1)

    assert gates.research_pass is False
    assert gates.simulator_results_reliable is False
    assert any("reward research" in reason for reason in gates.reasons)


def test_latency_percentile_calculation():
    values = [100, 200, 300, 400, 500]

    assert percentile(values, 50) == 300
    assert percentile(values, 95) == 480
    assert percentile([], 95) is None


def test_latency_sensitive_gate_fails_on_slow_p95():
    gates = evaluate_reliability_gate(error_rate_pct=0.0, p95_latency_ms=1200, consecutive_failure_max=0)

    assert gates.latency_sensitive_pass is False
    assert gates.research_pass is True


def test_consecutive_failure_streak_fails_latency_sensitive():
    gates = evaluate_reliability_gate(error_rate_pct=0.0, p95_latency_ms=500, consecutive_failure_max=3)

    assert gates.latency_sensitive_pass is False
    assert any("consecutive" in reason for reason in gates.reasons)
