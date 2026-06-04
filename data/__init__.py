"""Data layer: market scanning, news fetching, signal modeling, and whale tracking."""

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


def __getattr__(name):
    """Lazy import to avoid circular dependency chains."""
    if name in __all__:
        import importlib
        module_map = {
            "MarketScanner": "data.market_scanner",
            "MarketInfo": "data.market_scanner",
            "ScanResult": "data.market_scanner",
            "NewsFetcher": "data.news_fetcher",
            "Article": "data.news_fetcher",
            "ArticleStore": "data.news_fetcher",
            "SentimentExtractor": "data.news_fetcher",
            "FeedSource": "data.news_fetcher",
            "MockSource": "data.news_fetcher",
            "RSSFeedSource": "data.news_fetcher",
            "SignalModel": "data.signal_model",
            "Signal": "data.signal_model",
            "BrierScoreTracker": "data.signal_model",
            "NewsSentimentModel": "data.signal_model",
            "MarketFeatureModel": "data.signal_model",
            "MomentumModel": "data.signal_model",
            "RecalibrationModel": "data.signal_model",
            "WhaleTracker": "data.whale_tracker",
            "WhaleSignal": "data.whale_tracker",
        }
        mod = importlib.import_module(module_map[name])
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
