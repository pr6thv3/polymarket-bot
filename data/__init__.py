"""Data layer: market scanning, news fetching, signal modeling, and whale tracking."""

from data.market_scanner import MarketScanner, MarketInfo, ScanResult
from data.news_fetcher import NewsFetcher, Article, ArticleStore, SentimentExtractor, FeedSource, MockSource, RSSFeedSource
from data.signal_model import SignalModel, Signal, BrierScoreTracker, NewsSentimentModel, MarketFeatureModel, MomentumModel, RecalibrationModel
from data.whale_tracker import WhaleTracker, WhaleSignal

__all__ = [
    "MarketScanner",
    "MarketInfo",
    "ScanResult",
    "NewsFetcher",
    "Article",
    "ArticleStore",
    "SentimentExtractor",
    "FeedSource",
    "MockSource",
    "RSSFeedSource",
    "SignalModel",
    "Signal",
    "BrierScoreTracker",
    "NewsSentimentModel",
    "MarketFeatureModel",
    "MomentumModel",
    "RecalibrationModel",
    "WhaleTracker",
    "WhaleSignal",
]
