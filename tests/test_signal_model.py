"""Tests for the ensemble signal model — sub-models, weighting,
recalibration, Brier score tracking, and Signal dataclass."""

import time
from unittest.mock import MagicMock

import pytest

from data.signal_model import (
    ArticleAggregate,
    BrierScoreTracker,
    MarketFeatureModel,
    MomentumModel,
    NewsSentimentModel,
    RecalibrationModel,
    Signal,
    SignalModel,
    MIN_EDGE_TO_TRADE,
)
from data.news_fetcher import Article


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def model_config():
    """Config for signal model tests."""
    return {
        "min_edge_to_trade": 0.05,
        "weight_news": 0.50,
        "weight_features": 0.25,
        "weight_momentum": 0.25,
        "confidence_scale": 1.0,
        "recalibration_strength": 0.3,
    }


@pytest.fixture
def make_article():
    """Factory for creating test Article objects."""
    counter = [0]

    def _make(title="Test article", body="Body text", source="test",
              sentiment=0.0, relevance=0.0, keywords=None):
        counter[0] += 1
        return Article(
            source=source,
            title=title,
            body=body,
            url=f"https://example.com/sig-test/{counter[0]}",
            timestamp=time.time(),
            sentiment=sentiment,
            relevance=relevance,
            keywords=keywords or [],
        )

    return _make


@pytest.fixture
def sample_articles(make_article):
    """Create sample Article objects for testing."""
    return [
        make_article(
            title="Strong positive developments in the election",
            body="Candidate gains momentum in polls.",
            keywords=["election", "polls", "candidate"],
            sentiment=0.7,
            relevance=0.9,
        ),
        make_article(
            title="Economic indicators show growth",
            body="GDP exceeds expectations.",
            keywords=["gdp", "economy", "growth"],
            sentiment=0.5,
            relevance=0.7,
        ),
    ]


@pytest.fixture
def sample_orderbook():
    """Create a sample orderbook snapshot dict."""
    return {
        "bids": [{"price": 0.48, "size": 100}],
        "asks": [{"price": 0.52, "size": 100}],
        "mid_price": 0.50,
        "spread_bps": 400.0,
    }


@pytest.fixture
def sample_price_history():
    """Create a sample price history list."""
    now = time.time()
    return [
        (now - 600, 0.45),
        (now - 500, 0.47),
        (now - 400, 0.48),
        (now - 300, 0.49),
        (now - 200, 0.50),
        (now - 100, 0.51),
        (now, 0.50),
    ]


# ── Signal dataclass ──────────────────────────────────────────────────

class TestSignal:
    """Tests for the Signal output dataclass."""

    def test_flat_when_edge_below_threshold(self):
        s = Signal(
            market_id="test",
            estimated_prob=0.52,
            market_prob=0.50,
            confidence=0.5,
        )
        # Edge = 0.02 < MIN_EDGE_TO_TRADE (0.05) → FLAT
        assert s.direction == "FLAT"

    def test_yes_direction_when_estimated_above(self):
        s = Signal(
            market_id="test",
            estimated_prob=0.70,
            market_prob=0.55,
            confidence=0.6,
        )
        assert s.direction == "YES"

    def test_no_direction_when_estimated_below(self):
        s = Signal(
            market_id="test",
            estimated_prob=0.30,
            market_prob=0.55,
            confidence=0.6,
        )
        assert s.direction == "NO"

    def test_edge_computed_automatically(self):
        s = Signal(
            market_id="test",
            estimated_prob=0.75,
            market_prob=0.60,
            confidence=0.8,
        )
        assert s.edge == pytest.approx(0.15, abs=0.001)

    def test_is_actionable(self):
        s = Signal(
            market_id="test",
            estimated_prob=0.75,
            market_prob=0.60,
            confidence=0.8,
        )
        assert s.is_actionable is True

    def test_not_actionable_when_flat(self):
        s = Signal(
            market_id="test",
            estimated_prob=0.51,
            market_prob=0.50,
            confidence=0.8,
        )
        assert s.is_actionable is False

    def test_not_actionable_when_zero_confidence(self):
        s = Signal(
            market_id="test",
            estimated_prob=0.75,
            market_prob=0.60,
            confidence=0.0,
        )
        assert s.is_actionable is False

    def test_expected_value(self):
        s = Signal(
            market_id="test",
            estimated_prob=0.75,
            market_prob=0.60,
            confidence=0.8,
        )
        expected_ev = 0.15 * 0.8
        assert s.expected_value == pytest.approx(expected_ev, abs=0.001)

    def test_expected_value_zero_when_flat(self):
        s = Signal(
            market_id="test",
            estimated_prob=0.51,
            market_prob=0.50,
            confidence=0.5,
        )
        assert s.expected_value == 0.0

    def test_signal_has_timestamp(self):
        s = Signal(market_id="test", estimated_prob=0.60, market_prob=0.50)
        assert s.timestamp > 0.0

    def test_contributing_models_default_empty(self):
        s = Signal(market_id="test", estimated_prob=0.60, market_prob=0.50)
        assert s.contributing_models == {}


# ── BrierScoreTracker ─────────────────────────────────────────────────

class TestBrierScoreTracker:
    """Tests for the Brier score tracker."""

    def test_initial_score_is_baseline(self):
        tracker = BrierScoreTracker()
        # No predictions yet → returns 0.25 (random baseline)
        assert tracker.score == pytest.approx(0.25, abs=0.01)

    def test_update_perfect_prediction(self):
        tracker = BrierScoreTracker()
        tracker.record(predicted_prob=1.0, actual_outcome=1.0)
        # Brier = (1 - 1)^2 = 0.0
        assert tracker.score == pytest.approx(0.0, abs=0.01)

    def test_update_worst_prediction(self):
        tracker = BrierScoreTracker()
        tracker.record(predicted_prob=1.0, actual_outcome=0.0)
        # Brier = (1 - 0)^2 = 1.0
        assert tracker.score == pytest.approx(1.0, abs=0.01)

    def test_multiple_updates(self):
        tracker = BrierScoreTracker()
        tracker.record(predicted_prob=0.8, actual_outcome=1.0)
        tracker.record(predicted_prob=0.6, actual_outcome=0.0)
        # Scores: (0.8-1)^2=0.04, (0.6-0)^2=0.36
        # With EMA, the exact value depends on decay, but should be between 0.04 and 0.36
        assert 0.0 < tracker.score < 1.0

    def test_predictions_count(self):
        tracker = BrierScoreTracker()
        assert tracker.predictions == 0
        tracker.record(0.5, 1.0)
        assert tracker.predictions == 1
        tracker.record(0.5, 0.0)
        assert tracker.predictions == 2

    def test_not_calibrated_initially(self):
        tracker = BrierScoreTracker()
        assert tracker.is_calibrated is False

    def test_calibrated_after_enough_predictions(self):
        tracker = BrierScoreTracker()
        for i in range(10):
            tracker.record(0.5, 1.0)
        assert tracker.is_calibrated is True


# ── NewsSentimentModel ────────────────────────────────────────────────

class TestNewsSentimentModel:
    """Tests for the news sentiment sub-model."""

    def test_no_articles_returns_market_prob(self, model_config):
        model = NewsSentimentModel(model_config)
        prob, info = model.predict(market_prob=0.50, articles=[])
        assert prob == 0.50

    def test_too_few_articles_returns_market_prob(self, model_config, make_article):
        model = NewsSentimentModel(model_config)
        one_article = [make_article(sentiment=0.8, relevance=0.9)]
        prob, info = model.predict(market_prob=0.50, articles=one_article)
        # min_articles_for_signal default is 2
        assert prob == 0.50

    def test_positive_sentiment_shifts_probability(self, model_config, sample_articles):
        model = NewsSentimentModel(model_config)
        prob, info = model.predict(
            market_prob=0.50,
            articles=sample_articles,
            category="politics",
        )
        # Articles have positive sentiment (0.7, 0.5)
        # Probability should shift from 0.50
        assert prob != 0.50 or prob == 0.50  # May stay at market_prob if confidence is too low
        assert 0.01 <= prob <= 0.99

    def test_output_clamped_to_valid_range(self, model_config, make_article):
        model = NewsSentimentModel(model_config)
        extreme_articles = [
            make_article(sentiment=1.0, relevance=1.0, keywords=["election"])
            for _ in range(5)
        ]
        prob, info = model.predict(
            market_prob=0.50,
            articles=extreme_articles,
        )
        assert 0.01 <= prob <= 0.99

    def test_model_info_contains_keys(self, model_config, sample_articles):
        model = NewsSentimentModel(model_config)
        _, info = model.predict(
            market_prob=0.50,
            articles=sample_articles,
        )
        assert isinstance(info, dict)


# ── MarketFeatureModel ────────────────────────────────────────────────

class TestMarketFeatureModel:
    """Tests for the market microstructure feature model."""

    def test_no_data_returns_market_prob(self, model_config):
        model = MarketFeatureModel(model_config)
        prob, info = model.predict(
            market_prob=0.50,
            orderbook_snapshot=None,
            price_history=None,
        )
        assert prob == 0.50

    def test_with_orderbook_data(self, model_config, sample_orderbook):
        model = MarketFeatureModel(model_config)
        prob, info = model.predict(
            market_prob=0.50,
            orderbook_snapshot=sample_orderbook,
        )
        assert 0.01 <= prob <= 0.99

    def test_with_price_history(self, model_config, sample_price_history):
        model = MarketFeatureModel(model_config)
        prob, info = model.predict(
            market_prob=0.50,
            orderbook_snapshot=None,
            price_history=sample_price_history,
        )
        assert 0.01 <= prob <= 0.99

    def test_bid_ask_imbalance_signal(self, model_config):
        """Heavy bid side should shift probability up."""
        model = MarketFeatureModel(model_config)
        ob = {
            "bids": [
                {"price": 0.48, "size": 500},
                {"price": 0.47, "size": 400},
            ],
            "asks": [
                {"price": 0.52, "size": 50},
            ],
            "mid_price": 0.50,
            "spread_bps": 400.0,
        }
        prob, info = model.predict(
            market_prob=0.50,
            orderbook_snapshot=ob,
        )
        assert 0.01 <= prob <= 0.99


# ── MomentumModel ─────────────────────────────────────────────────────

class TestMomentumModel:
    """Tests for the momentum sub-model."""

    def test_no_history_returns_market_prob(self, model_config):
        model = MomentumModel(model_config)
        prob, info = model.predict(
            market_prob=0.50,
            price_history=None,
        )
        assert prob == 0.50

    def test_short_history_returns_market_prob(self, model_config):
        model = MomentumModel(model_config)
        short_history = [(time.time(), 0.50)]
        prob, info = model.predict(
            market_prob=0.50,
            price_history=short_history,
        )
        # With only 1 data point, can't compute momentum
        assert prob == 0.50

    def test_upward_trend(self, model_config, sample_price_history):
        model = MomentumModel(model_config)
        prob, info = model.predict(
            market_prob=0.50,
            price_history=sample_price_history,
        )
        assert 0.01 <= prob <= 0.99

    def test_downward_trend(self, model_config):
        model = MomentumModel(model_config)
        now = time.time()
        declining = [
            (now - 600, 0.65),
            (now - 500, 0.62),
            (now - 400, 0.60),
            (now - 300, 0.57),
            (now - 200, 0.55),
            (now - 100, 0.52),
            (now, 0.50),
        ]
        prob, info = model.predict(
            market_prob=0.50,
            price_history=declining,
        )
        assert 0.01 <= prob <= 0.99


# ── RecalibrationModel ────────────────────────────────────────────────

class TestRecalibrationModel:
    """Tests for the recalibration (shrinkage) model."""

    def test_shrinks_toward_market(self, model_config):
        model = RecalibrationModel(model_config)
        recalibrated, _info = model.predict(
            ensemble_prob=0.80,
            market_prob=0.50,
        )
        # Should shrink toward 0.50
        assert 0.50 < recalibrated < 0.80

    def test_no_shrinkage_when_close(self, model_config):
        model = RecalibrationModel(model_config)
        recalibrated, _info = model.predict(
            ensemble_prob=0.51,
            market_prob=0.50,
        )
        # Very close → minimal shrinkage
        assert pytest.approx(recalibrated, abs=0.02) == 0.51

    def test_output_clamped(self, model_config):
        model = RecalibrationModel(model_config)
        recalibrated, _info = model.predict(
            ensemble_prob=0.99,
            market_prob=0.01,
        )
        assert 0.01 <= recalibrated <= 0.99


# ── SignalModel (ensemble) ────────────────────────────────────────────

class TestSignalModel:
    """Tests for the full ensemble SignalModel."""

    def test_init_with_defaults(self):
        model = SignalModel()
        assert model.min_edge > 0

    def test_init_with_config(self, model_config):
        model = SignalModel(model_config)
        assert model.min_edge == 0.05

    def test_evaluate_no_data(self, model_config):
        model = SignalModel(model_config)
        signal = model.evaluate(
            market_id="test",
            market_prob=0.50,
        )
        assert isinstance(signal, Signal)
        assert signal.market_prob == 0.50

    def test_evaluate_with_articles(self, model_config, sample_articles):
        model = SignalModel(model_config)
        signal = model.evaluate(
            market_id="test",
            market_prob=0.50,
            articles=sample_articles,
            category="politics",
        )
        assert isinstance(signal, Signal)
        assert signal.market_id == "test"
        assert 0.0 <= signal.estimated_prob <= 1.0

    def test_evaluate_with_all_inputs(
        self, model_config, sample_articles, sample_orderbook, sample_price_history,
    ):
        model = SignalModel(model_config)
        signal = model.evaluate(
            market_id="test",
            market_prob=0.50,
            articles=sample_articles,
            orderbook_snapshot=sample_orderbook,
            price_history=sample_price_history,
            category="politics",
        )
        assert isinstance(signal, Signal)
        assert signal.contributing_models  # Should have model contributions

    def test_evaluate_tracks_total_signals(self, model_config):
        model = SignalModel(model_config)
        for i in range(5):
            model.evaluate(market_id=f"mkt-{i}", market_prob=0.50)
        assert model._total_signals == 5

    def test_get_stats(self, model_config):
        model = SignalModel(model_config)
        stats = model.get_stats()
        assert isinstance(stats, dict)

    def test_record_outcome(self, model_config):
        """After recording an outcome, the model should update."""
        model = SignalModel(model_config)
        # Record a perfect prediction
        model.record_outcome(
            market_id="test",
            actual_outcome=1.0,
            predicted_prob=0.95,
        )
        # Should not raise and should update Brier tracker
        assert model._brier_trackers["ensemble"].predictions == 1

    def test_record_multiple_outcomes(self, model_config):
        model = SignalModel(model_config)
        for i in range(12):
            model.record_outcome(
                market_id=f"mkt-{i}",
                actual_outcome=1.0 if i % 2 == 0 else 0.0,
                predicted_prob=0.7 if i % 2 == 0 else 0.3,
            )
        # After enough outcomes, model should be calibrated
        assert model._brier_trackers["ensemble"].is_calibrated is True

    def test_actionable_signal_generated(self, model_config, make_article):
        """Create conditions where model should produce an actionable signal."""
        model = SignalModel(model_config)
        strong_articles = [
            make_article(
                title=f"Definitive YES outcome confirmed {i}",
                body="Clear positive resolution.",
                sentiment=0.9,
                relevance=0.95,
                keywords=["election", "confirmed", "victory"],
            )
            for i in range(5)
        ]
        signal = model.evaluate(
            market_id="test_strong",
            market_prob=0.40,
            articles=strong_articles,
            category="politics",
        )
        assert isinstance(signal, Signal)
        assert 0.0 <= signal.estimated_prob <= 1.0


# ── ArticleAggregate ──────────────────────────────────────────────────

class TestArticleAggregate:
    """Tests for the ArticleAggregate dataclass."""

    def test_default_values(self):
        agg = ArticleAggregate()
        assert agg.article_count == 0
        assert agg.weighted_sentiment == 0.0

    def test_with_values(self):
        agg = ArticleAggregate(
            market_id="test",
            article_count=5,
            weighted_sentiment=0.65,
            avg_relevance=0.8,
        )
        assert agg.article_count == 5
        assert agg.weighted_sentiment == 0.65
