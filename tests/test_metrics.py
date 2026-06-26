"""Regression tests for Prometheus metric wrapper signatures."""

from utils import metrics


class FakeLabeledCounter:
    def __init__(self):
        self.calls = []

    def labels(self, **labels):
        self.calls.append(("labels", labels))
        return self

    def inc(self, amount=1):
        self.calls.append(("inc", amount))


class FakeCounter:
    def __init__(self):
        self.calls = []

    def inc(self, amount=1):
        self.calls.append(("inc", amount))


class FakeGauge:
    def __init__(self):
        self.calls = []

    def set(self, value):
        self.calls.append(("set", value))

    def inc(self, amount=1):
        self.calls.append(("inc", amount))

    def dec(self, amount=1):
        self.calls.append(("dec", amount))


def test_record_signal_generated_uses_declared_labels(monkeypatch):
    signal_counter = FakeLabeledCounter()
    edge_counter = FakeCounter()
    monkeypatch.setattr(metrics, "signals_generated", signal_counter)
    monkeypatch.setattr(metrics, "signal_edge_usd", edge_counter)

    metrics.record_signal_generated("m1", "YES", 0.25)

    assert signal_counter.calls == [
        ("labels", {"market_id": "m1", "direction": "YES"}),
        ("inc", 1),
    ]
    assert edge_counter.calls == [("inc", 0.25)]


def test_update_arb_opportunities_found_sets_gauge(monkeypatch):
    gauge = FakeGauge()
    monkeypatch.setattr(metrics, "arb_opportunities_found", gauge)

    metrics.update_arb_opportunities_found(3)

    assert gauge.calls == [("set", 3)]


def test_record_arb_pnl_increments_and_decrements_gauge(monkeypatch):
    gauge = FakeGauge()
    monkeypatch.setattr(metrics, "arb_pnl_usd_total", gauge)

    metrics.record_arb_pnl(2.5)
    metrics.record_arb_pnl(-1.0)

    assert gauge.calls == [("inc", 2.5), ("dec", 1.0)]
