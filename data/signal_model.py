"""Ensemble probability model for AI signal strategy.

Combines multiple signal sources into a unified probability estimate
and edge score for each market. Designed to be:

1. Modular — individual "sub-models" can be added/removed
2. Retrainable — model weights adapt based on prediction accuracy
3. Observable — every signal contribution is traceable

Sub-models:
 - NewsSentimentModel: Aggregates article sentiment weighted by recency/relevance
 - MarketFeatureModel: Order book imbalance, volume momentum, spread dynamics
 - MomentumModel: Recent price movement direction and strength
 - RecalibrationModel: Shrinks estimates toward market-implied probability

Ensemble combination:
 final_prob = Σ(w_i × model_i.predict()) / Σ(w_i)

 where weights are adaptively adjusted based on each sub-model's
 recent prediction accuracy (Brier score tracking).

Signal output:
 Signal:
   market_id: str
   estimated_prob: float    — model's probability estimate [0,1]
   market_prob: float       — current market-implied probability
   edge: float              — |estimated_prob - market_prob|
   direction: str           — "YES" or "NO" (which side to buy)
   confidence: float        — [0,1] how confident in the edge
   contributing_models: dict — per-model breakdown
   timestamp: float
"""

import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import structlog

logger = structlog.get_logger(__name__)

# ── Constants ──────────────────────────────────────────────────────────

MIN_WEIGHT = 0.01         # Floor weight to prevent a model from going silent
MAX_WEIGHT = 10.0         # Cap weight to prevent dominance
DEFAULT_DECAY = 0.995     # Exponential decay for accuracy tracking
MIN_EDGE_TO_TRADE = 0.05  # Minimum |edge| to consider a trade
MAX_ARTICLES_PER_MARKET = 20
FRESHNESS_WEIGHT = 0.7    # How much recent articles matter vs older ones


# ── Signal data structure ─────────────────────────────────────────────

@dataclass
class Signal:
    """Output of the ensemble model for a single market."""

    market_id: str
    estimated_prob: float = 0.5
    market_prob: float = 0.5
    edge: float = 0.0
    direction: str = "FLAT"  # "YES", "NO", or "FLAT"
    confidence: float = 0.0
    contributing_models: Dict[str, float] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self):
        """Derive computed fields."""
        self.edge = abs(self.estimated_prob - self.market_prob)
        if self.edge < MIN_EDGE_TO_TRADE:
            self.direction = "FLAT"
        elif self.estimated_prob > self.market_prob:
            self.direction = "YES"
        else:
            self.direction = "NO"

    @property
    def is_actionable(self) -> bool:
        """Whether this signal warrants a trade."""
        return self.direction != "FLAT" and self.confidence > 0.0

    @property
    def expected_value(self) -> float:
        """Expected value per dollar risked."""
        if not self.is_actionable:
            return 0.0
        return self.edge * self.confidence


# ── Article aggregate ─────────────────────────────────────────────────

@dataclass
class ArticleAggregate:
    """Aggregated sentiment from multiple articles for a market."""

    market_id: str = ""
    article_count: int = 0
    weighted_sentiment: float = 0.0
    avg_relevance: float = 0.0
    avg_freshness: float = 0.0     # 1.0 = just now, decays with age
    positive_count: int = 0
    negative_count: int = 0
    neutral_count: int = 0
    top_keywords: List[str] = field(default_factory=list)
    category: str = ""


# ── Sub-models ────────────────────────────────────────────────────────

class NewsSentimentModel:
    """Aggregates news article sentiment into a probability adjustment.

    Takes a collection of articles relevant to a market, computes
    a weighted sentiment score, and maps it to a probability adjustment.

    The mapping:
    - Strongly positive sentiment → probability estimate above market
    - Strongly negative sentiment → probability estimate below market
    - Neutral/mixed → stays close to market price

    Weighting scheme:
    - Recent articles matter more (exponential freshness decay)
    - High-relevance articles matter more
    - High-sentiment-magnitude articles matter more
    """

    def __init__(self, config: dict = None) -> None:
        cfg = config or {}
        self.sentiment_scale = cfg.get("sentiment_scale", 0.15)
        # How much a unit of sentiment shifts probability (capped)
        self.freshness_half_life_sec = cfg.get("freshness_half_life_sec", 3600.0)
        # Articles lose half their weight every hour
        self.min_articles = cfg.get("min_articles_for_signal", 2)
        # Minimum articles needed to generate a signal

    def predict(
        self,
        market_prob: float,
        articles: list,
        category: str = "",
    ) -> Tuple[float, Dict[str, Any]]:
        """Compute probability estimate from article sentiment.

        Args:
            market_prob: Current market-implied probability.
            articles: List of Article objects relevant to the market.
            category: Market category for context.

        Returns:
            Tuple of (estimated_probability, model_info_dict).
        """
        if not articles or len(articles) < self.min_articles:
            return market_prob, {"signal": 0.0, "articles_used": 0}

        aggregate = self._aggregate_articles(articles)

        if aggregate.article_count < self.min_articles:
            return market_prob, {"signal": 0.0, "articles_used": aggregate.article_count}

        # Compute sentiment signal
        # weighted_sentiment is in [-1, 1]
        # Scale it to a probability adjustment
        sentiment_signal = aggregate.weighted_sentiment * self.sentiment_scale

        # Apply freshness and relevance dampening
        quality_factor = aggregate.avg_relevance * aggregate.avg_freshness
        adjusted_signal = sentiment_signal * quality_factor

        # Shift market probability
        estimated = market_prob + adjusted_signal

        # Clamp to valid range
        estimated = max(0.01, min(0.99, estimated))

        model_info = {
            "signal": adjusted_signal,
            "raw_sentiment": aggregate.weighted_sentiment,
            "articles_used": aggregate.article_count,
            "avg_relevance": aggregate.avg_relevance,
            "avg_freshness": aggregate.avg_freshness,
            "positive": aggregate.positive_count,
            "negative": aggregate.negative_count,
            "neutral": aggregate.neutral_count,
        }

        return estimated, model_info

    def _aggregate_articles(self, articles: list) -> ArticleAggregate:
        """Aggregate sentiment from multiple articles.

        Args:
            articles: List of Article objects.

        Returns:
            ArticleAggregate with weighted sentiment.
        """
        agg = ArticleAggregate()
        total_weight = 0.0
        weighted_sent = 0.0
        weighted_rel = 0.0
        weighted_fresh = 0.0
        positive = 0
        negative = 0
        neutral = 0
        all_keywords: List[str] = []

        now = time.time()

        for art in articles:
            # Freshness: exponential decay
            age_sec = max(0.1, art.age_sec)
            freshness = math.exp(
                -0.693 * age_sec / self.freshness_half_life_sec
            )
            # ^^^ half-life formula: exp(-ln(2) * t / t_half)

            # Relevance weight
            relevance = getattr(art, "relevance", 0.5)

            # Combined weight
            weight = freshness * relevance
            total_weight += weight

            # Weighted sentiment
            sent = art.sentiment
            weighted_sent += sent * weight
            weighted_rel += relevance * weight
            weighted_fresh += freshness * weight

            # Count by sentiment direction
            if sent > 0.1:
                positive += 1
            elif sent < -0.1:
                negative += 1
            else:
                neutral += 1

            # Collect keywords
            if hasattr(art, "keywords") and art.keywords:
                all_keywords.extend(art.keywords)

        agg.article_count = len(articles)
        agg.positive_count = positive
        agg.negative_count = negative
        agg.neutral_count = neutral

        if total_weight > 0:
            agg.weighted_sentiment = weighted_sent / total_weight
            agg.avg_relevance = weighted_rel / total_weight
            agg.avg_freshness = weighted_fresh / total_weight
        else:
            agg.weighted_sentiment = 0.0
            agg.avg_relevance = 0.0
            agg.avg_freshness = 0.0

        # Deduplicate and limit keywords
        seen = set()
        for kw in all_keywords:
            if kw not in seen:
                seen.add(kw)
                agg.top_keywords.append(kw)
                if len(agg.top_keywords) >= 10:
                    break

        return agg


class MarketFeatureModel:
    """Extracts probability signals from order book and market features.

    Signals derived from market microstructure:
    - Order book imbalance: (bid_vol - ask_vol) / (bid_vol + ask_vol)
      → Positive imbalance suggests YES is underpriced
    - Spread dynamics: widening spreads suggest uncertainty
    - Volume momentum: increasing volume signals incoming price moves
    - Price drift: gradual price movement in one direction

    This model produces a small adjustment to the market probability,
    since microstructure signals are weaker than fundamental signals.
    """

    def __init__(self, config: dict = None) -> None:
        cfg = config or {}
        self.imbalance_scale = cfg.get("imbalance_scale", 0.03)
        self.drift_scale = cfg.get("drift_scale", 0.02)
        self.min_imbalance = cfg.get("min_imbalance_threshold", 0.2)
        # Minimum imbalance magnitude to generate a signal

    def predict(
        self,
        market_prob: float,
        orderbook_snapshot: dict = None,
        price_history: list = None,
    ) -> Tuple[float, Dict[str, Any]]:
        """Compute probability estimate from market features.

        Args:
            market_prob: Current market-implied probability.
            orderbook_snapshot: Dict with 'bids', 'asks', 'mid_price', etc.
            price_history: List of (timestamp, price) tuples for drift calc.

        Returns:
            Tuple of (estimated_probability, model_info_dict).
        """
        signal = 0.0
        model_info: Dict[str, Any] = {
            "imbalance_signal": 0.0,
            "drift_signal": 0.0,
        }

        # 1. Order book imbalance
        if orderbook_snapshot:
            imbalance = self._compute_imbalance(orderbook_snapshot)
            model_info["imbalance_signal"] = imbalance
            if abs(imbalance) >= self.min_imbalance:
                signal += imbalance * self.imbalance_scale

        # 2. Price drift
        if price_history and len(price_history) >= 3:
            drift = self._compute_drift(price_history)
            model_info["drift_signal"] = drift
            signal += drift * self.drift_scale

        estimated = market_prob + signal
        estimated = max(0.01, min(0.99, estimated))

        model_info["total_signal"] = signal
        return estimated, model_info

    @staticmethod
    def _compute_imbalance(snapshot: dict) -> float:
        """Compute order book imbalance.

        Args:
            snapshot: Dict with 'bids' and 'asks' lists.

        Returns:
            Imbalance in [-1, 1]. Positive = more bid volume.
        """
        bids = snapshot.get("bids", [])
        asks = snapshot.get("asks", [])

        bid_vol = sum(float(b.get("size", 0)) for b in bids) if bids else 0.0
        ask_vol = sum(float(a.get("size", 0)) for a in asks) if asks else 0.0

        total = bid_vol + ask_vol
        if total <= 0:
            return 0.0

        return (bid_vol - ask_vol) / total

    @staticmethod
    def _compute_drift(price_history: list) -> float:
        """Compute recent price drift direction.

        Args:
            price_history: List of (timestamp, price) tuples, sorted ascending.

        Returns:
            Drift in [-1, 1]. Positive = price increasing.
        """
        if len(price_history) < 2:
            return 0.0

        # Use last 5 data points or all available
        recent = price_history[-5:]
        prices = [p for _, p in recent]

        if len(prices) < 2:
            return 0.0

        # Simple linear drift: (last - first) / first
        first = prices[0]
        last = prices[-1]

        if first <= 0:
            return 0.0

        drift = (last - first) / first

        # Normalize to [-1, 1]
        return max(-1.0, min(1.0, drift * 10.0))


class MomentumModel:
    """Detects short-term momentum in market price movements.

    Uses recent price changes to detect momentum that may continue.
    This is a contrarian model at extremes (mean-reversion) and
    a momentum model in the middle range.

    The signal function:
    - If price moved >5% recently and volume is increasing → momentum
    - If price moved >15% recently → mean-reversion (expect pullback)
    """

    def __init__(self, config: dict = None) -> None:
        cfg = config or {}
        self.momentum_threshold = cfg.get("momentum_threshold", 0.05)
        self.reversion_threshold = cfg.get("reversion_threshold", 0.15)
        self.momentum_scale = cfg.get("momentum_scale", 0.02)
        self.reversion_scale = cfg.get("reversion_scale", 0.04)

    def predict(
        self,
        market_prob: float,
        price_history: list = None,
        volume_history: list = None,
    ) -> Tuple[float, Dict[str, Any]]:
        """Compute probability estimate from momentum signals.

        Args:
            market_prob: Current market-implied probability.
            price_history: List of (timestamp, price) tuples.
            volume_history: List of (timestamp, volume) tuples.

        Returns:
            Tuple of (estimated_probability, model_info_dict).
        """
        signal = 0.0
        model_info: Dict[str, Any] = {"signal_type": "none"}

        if not price_history or len(price_history) < 3:
            return market_prob, model_info

        # Compute recent price change
        recent_prices = [p for _, p in price_history[-10:]]
        if len(recent_prices) < 2 or recent_prices[0] <= 0:
            return market_prob, model_info

        price_change = (recent_prices[-1] - recent_prices[0]) / recent_prices[0]
        direction = 1.0 if price_change > 0 else -1.0
        magnitude = abs(price_change)

        if magnitude >= self.reversion_threshold:
            # Mean reversion: expect pullback
            signal = -direction * self.reversion_scale * min(1.0, magnitude)
            model_info["signal_type"] = "mean_reversion"
        elif magnitude >= self.momentum_threshold:
            # Momentum: expect continuation
            signal = direction * self.momentum_scale * min(1.0, magnitude)
            model_info["signal_type"] = "momentum"

        model_info["price_change"] = price_change
        model_info["signal"] = signal

        estimated = market_prob + signal
        estimated = max(0.01, min(0.99, estimated))

        return estimated, model_info


class RecalibrationModel:
    """Recalibrates probability estimates toward the market-implied probability.

    This model implements shrinkage toward the market price, which
    acts as a wisdom-of-crowds anchor. Without recalibration,
    the ensemble can overfit to noisy signals.

    Shrinkage formula:
    recalibrated = λ × ensemble_estimate + (1 - λ) × market_prob

    where λ depends on the ensemble's confidence and historical accuracy.
    """

    def __init__(self, config: dict = None) -> None:
        cfg = config or {}
        self.base_shrinkage = cfg.get("base_shrinkage", 0.7)
        # How much to trust the ensemble vs market (0.7 = 70% ensemble)
        self.confidence_threshold = cfg.get("confidence_threshold", 0.3)
        # Below this confidence, shrink more aggressively

    def predict(
        self,
        ensemble_prob: float,
        market_prob: float,
        confidence: float = 0.5,
    ) -> Tuple[float, Dict[str, Any]]:
        """Recalibrate the ensemble probability estimate.

        Args:
            ensemble_prob: Raw ensemble probability estimate.
            market_prob: Current market-implied probability.
            confidence: Ensemble confidence [0, 1].

        Returns:
            Tuple of (recalibrated_probability, model_info_dict).
        """
        # Adjust shrinkage based on confidence
        # Low confidence → shrink more toward market
        if confidence < self.confidence_threshold:
            shrinkage = self.base_shrinkage * (confidence / self.confidence_threshold)
        else:
            shrinkage = self.base_shrinkage

        shrinkage = max(0.1, min(0.95, shrinkage))

        recalibrated = shrinkage * ensemble_prob + (1 - shrinkage) * market_prob
        recalibrated = max(0.01, min(0.99, recalibrated))

        model_info = {
            "shrinkage": shrinkage,
            "raw_ensemble": ensemble_prob,
            "adjustment": recalibrated - ensemble_prob,
        }

        return recalibrated, model_info


# ── Brier score tracker ───────────────────────────────────────────────

class BrierScoreTracker:
    """Tracks prediction accuracy for adaptive weight adjustment.

    Brier score = (predicted_prob - actual_outcome)²
    Lower is better. A perfect predictor scores 0.0.
    Random guessing scores ~0.25 on binary outcomes.

    Uses exponential moving average to weight recent predictions
    more heavily than old ones.
    """

    def __init__(self, decay: float = DEFAULT_DECAY) -> None:
        self.decay = decay
        self._scores: deque = deque(maxlen=500)
        self._weighted_sum: float = 0.0
        self._weight_total: float = 0.0
        self._predictions: int = 0

    def record(self, predicted_prob: float, actual_outcome: float) -> None:
        """Record a prediction and its actual outcome.

        Args:
            predicted_prob: The probability that was predicted.
            actual_outcome: 1.0 if YES won, 0.0 if NO won.
        """
        brier = (predicted_prob - actual_outcome) ** 2
        self._scores.append(brier)
        self._predictions += 1

        # Exponential weighting
        weight = self.decay ** (len(self._scores) - 1)
        self._weighted_sum += brier * weight
        self._weight_total += weight

    @property
    def score(self) -> float:
        """Current Brier score (lower is better)."""
        if self._weight_total <= 0:
            return 0.25  # Random baseline
        return self._weighted_sum / self._weight_total

    @property
    def predictions(self) -> int:
        """Total number of recorded predictions."""
        return self._predictions

    @property
    def is_calibrated(self) -> bool:
        """Whether we have enough predictions to trust the score."""
        return self._predictions >= 10


# ── Ensemble model ────────────────────────────────────────────────────

class SignalModel:
    """Ensemble probability model combining multiple sub-models.

    Sub-models produce probability estimates, which are combined
    using adaptive weights based on recent Brier scores. The
    recalibration model then shrinks the final estimate toward
    the market-implied probability.

    Usage:
        model = SignalModel(config)
        signal = model.evaluate(
            market_id="0x123...",
            market_prob=0.65,
            articles=[...],
            orderbook_snapshot={...},
            price_history=[...],
        )
        if signal.is_actionable:
            # Place trade
    """

    def __init__(self, config: dict = None) -> None:
        """Initialize the ensemble signal model.

        Args:
            config: AI signals config section.
        """
        self.config = config or {}
        ai_cfg = self.config

        # Sub-models
        self.news_model = NewsSentimentModel(ai_cfg)
        self.feature_model = MarketFeatureModel(ai_cfg)
        self.momentum_model = MomentumModel(ai_cfg)
        self.recalibration_model = RecalibrationModel(ai_cfg)

        # Model weights (adaptive)
        self._base_weights: Dict[str, float] = {
            "news_sentiment": ai_cfg.get("weight_news", 0.50),
            "market_features": ai_cfg.get("weight_features", 0.25),
            "momentum": ai_cfg.get("weight_momentum", 0.25),
        }
        self._weights: Dict[str, float] = dict(self._base_weights)

        # Accuracy trackers
        self._brier_trackers: Dict[str, BrierScoreTracker] = {
            name: BrierScoreTracker() for name in self._base_weights
        }
        self._brier_trackers["ensemble"] = BrierScoreTracker()

        # Edge thresholds
        self.min_edge = ai_cfg.get("min_edge_to_trade", MIN_EDGE_TO_TRADE)
        self.confidence_scale = ai_cfg.get("confidence_scale", 1.0)

        # Prediction history (for later retraining / analysis)
        self._predictions: deque = deque(maxlen=1000)
        self._total_signals: int = 0
        self._actionable_signals: int = 0

    def evaluate(
        self,
        market_id: str,
        market_prob: float,
        articles: list = None,
        orderbook_snapshot: dict = None,
        price_history: list = None,
        category: str = "",
    ) -> Signal:
        """Evaluate a market and produce a trading signal.

        Args:
            market_id: Market/condition ID.
            market_prob: Current market-implied probability.
            articles: List of Article objects for the market.
            orderbook_snapshot: Order book dict with bids/asks.
            price_history: List of (timestamp, price) tuples.
            category: Market category.

        Returns:
            Signal with estimated probability, edge, and direction.
        """
        articles = articles or []
        self._total_signals += 1

        # 1. Run each sub-model
        news_prob, news_info = self.news_model.predict(
            market_prob, articles, category
        )
        feature_prob, feature_info = self.feature_model.predict(
            market_prob, orderbook_snapshot, price_history
        )
        momentum_prob, momentum_info = self.momentum_model.predict(
            market_prob, price_history
        )

        # 2. Weighted ensemble combination
        model_outputs = {
            "news_sentiment": news_prob,
            "market_features": feature_prob,
            "momentum": momentum_prob,
        }

        total_weight = 0.0
        weighted_sum = 0.0

        for model_name, prob in model_outputs.items():
            w = self._weights.get(model_name, 1.0)
            w = max(MIN_WEIGHT, min(MAX_WEIGHT, w))
            weighted_sum += w * prob
            total_weight += w

        ensemble_prob = weighted_sum / total_weight if total_weight > 0 else market_prob

        # 3. Compute raw confidence
        # Confidence is based on:
        #   a) Model agreement (low variance → high confidence)
        #   b) Edge magnitude (larger edge → higher confidence)
        #   c) Data quality (more articles, more data → higher confidence)
        confidence = self._compute_confidence(
            model_outputs, ensemble_prob, market_prob, articles
        )

        # 4. Recalibrate
        recalibrated_prob, recal_info = self.recalibration_model.predict(
            ensemble_prob, market_prob, confidence
        )

        # 5. Build signal
        signal = Signal(
            market_id=market_id,
            estimated_prob=recalibrated_prob,
            market_prob=market_prob,
            confidence=confidence,
            contributing_models={
                "news_sentiment": news_prob,
                "market_features": feature_prob,
                "momentum": momentum_prob,
                "ensemble_raw": ensemble_prob,
                "recalibrated": recalibrated_prob,
            },
        )

        # 6. Track prediction
        self._predictions.append({
            "market_id": market_id,
            "timestamp": time.time(),
            "estimated": recalibrated_prob,
            "market": market_prob,
            "edge": signal.edge,
            "direction": signal.direction,
            "confidence": confidence,
        })

        if signal.is_actionable:
            self._actionable_signals += 1

        return signal

    def record_outcome(
        self,
        market_id: str,
        actual_outcome: float,
        predicted_prob: float,
    ) -> None:
        """Record the actual outcome of a market for model retraining.

        Args:
            market_id: Market ID.
            actual_outcome: 1.0 if YES won, 0.0 if NO won.
            predicted_prob: The ensemble's predicted probability.
        """
        # Update ensemble Brier score
        self._brier_trackers["ensemble"].record(predicted_prob, actual_outcome)

        # Update individual model Brier scores (if we tracked them per-market)
        # For now, use the ensemble score as a proxy
        logger.info(
            "Recorded market outcome",
            market_id=market_id,
            predicted=predicted_prob,
            actual=actual_outcome,
            brier=self._brier_trackers["ensemble"].score,
        )

        # Adapt weights based on accuracy
        self._adapt_weights()

    def _adapt_weights(self) -> None:
        """Adapt model weights based on recent Brier scores.

        Models with lower (better) Brier scores get higher weights.
        Uses a simple inverse-Brier weighting scheme.
        """
        # Check if we have enough data
        tracker = self._brier_trackers["ensemble"]
        if not tracker.is_calibrated:
            return

        # Compute inverse-Brier weights
        inv_brier: Dict[str, float] = {}
        for name, t in self._brier_trackers.items():
            if t.is_calibrated:
                # Inverse Brier: lower score → higher weight
                score = max(0.01, t.score)  # Prevent division by zero
                inv_brier[name] = 1.0 / score
            else:
                inv_brier[name] = self._base_weights.get(name, 1.0)

        # Normalize and blend with base weights (don't diverge too far)
        total_inv = sum(inv_brier.values())
        if total_inv <= 0:
            return

        for name in self._base_weights:
            if name in inv_brier:
                adapted = inv_brier[name] / total_inv * sum(self._base_weights.values())
                # Blend: 70% adapted, 30% base (prevent wild swings)
                self._weights[name] = 0.7 * adapted + 0.3 * self._base_weights[name]
                self._weights[name] = max(MIN_WEIGHT, min(MAX_WEIGHT, self._weights[name]))

    def _compute_confidence(
        self,
        model_outputs: Dict[str, float],
        ensemble_prob: float,
        market_prob: float,
        articles: list,
    ) -> float:
        """Compute signal confidence.

        Args:
            model_outputs: Per-model probability estimates.
            ensemble_prob: Weighted ensemble estimate.
            market_prob: Market-implied probability.
            articles: Articles used for the signal.

        Returns:
            Confidence score [0, 1].
        """
        # 1. Model agreement (low variance = high agreement = high confidence)
        probs = list(model_outputs.values())
        if len(probs) > 1:
            mean = sum(probs) / len(probs)
            variance = sum((p - mean) ** 2 for p in probs) / len(probs)
            # Normalize: variance of 0 → perfect agreement (1.0)
            #            variance of 0.1+ → disagreement (0.0)
            agreement = max(0.0, 1.0 - variance * 20.0)
        else:
            agreement = 0.3

        # 2. Edge magnitude (larger edge → more confidence, up to a point)
        edge = abs(ensemble_prob - market_prob)
        edge_confidence = min(1.0, edge * 5.0)  # 20% edge → full confidence

        # 3. Data quality (article count)
        article_count = len(articles)
        if article_count >= 5:
            data_confidence = 1.0
        elif article_count >= 2:
            data_confidence = article_count / 5.0
        else:
            data_confidence = 0.2

        # 4. Historical accuracy (if available)
        tracker = self._brier_trackers["ensemble"]
        if tracker.is_calibrated:
            # Lower Brier score → higher confidence
            # 0.0 = perfect, 0.25 = random, 0.5 = terrible
            accuracy_confidence = max(0.0, 1.0 - tracker.score * 4.0)
        else:
            accuracy_confidence = 0.5  # Neutral when no data

        # Weighted combination
        confidence = (
            0.35 * agreement
            + 0.25 * edge_confidence
            + 0.15 * data_confidence
            + 0.25 * accuracy_confidence
        )

        # Apply confidence scale from config
        confidence *= self.confidence_scale

        return max(0.0, min(1.0, confidence))

    def get_stats(self) -> Dict[str, any]:
        """Get model statistics.

        Returns:
            Dict with model stats and Brier scores.
        """
        return {
            "total_signals": self._total_signals,
            "actionable_signals": self._actionable_signals,
            "actionable_rate": (
                self._actionable_signals / max(1, self._total_signals)
            ),
            "weights": dict(self._weights),
            "base_weights": dict(self._base_weights),
            "brier_scores": {
                name: tracker.score
                for name, tracker in self._brier_trackers.items()
            },
            "predictions_recorded": self._brier_trackers["ensemble"].predictions,
        }

    def get_model_weights(self) -> Dict[str, float]:
        """Get current model weights.

        Returns:
            Dict of model_name → weight.
        """
        return dict(self._weights)

    def set_model_weights(self, weights: Dict[str, float]) -> None:
        """Manually override model weights.

        Args:
            weights: Dict of model_name → weight.
        """
        for name, weight in weights.items():
            if name in self._weights:
                self._weights[name] = max(MIN_WEIGHT, min(MAX_WEIGHT, weight))
