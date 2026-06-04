"""News and social data fetcher — multi-source collector for AI signal strategy.

Collects textual data from multiple sources, normalizes it, and extracts
market-relevant signals. Designed to feed into the ensemble probability
model (SignalModel) for generating trading edges.

Sources:
 - RSS/Atom feeds (news outlets, blogs)
 - Polymarket comment/trend streams
 - Social media APIs (Twitter/X, Reddit)
 - Custom webhook sources

Architecture:
 NewsFetcher
 ├── FeedSource (pluggable source interface)
 │   ├── RSSFeedSource (RSS/Atom feeds)
 │   ├── WebhookSource (custom HTTP endpoints)
 │   └── MockSource (for testing)
 ├── ArticleStore (dedup + recency tracking)
 └── SentimentExtractor (basic keyword-based scoring)

Data format:
 Article:
   source: str        — feed name
   title: str         — headline
   body: str          — full text (may be truncated)
   url: str           — link
   timestamp: float   — publish time (epoch)
   keywords: list     — extracted market-relevant keywords
   sentiment: float   — initial sentiment score (-1.0 to +1.0)
   relevance: float   — market relevance (0.0 to 1.0)

Usage:
 fetcher = NewsFetcher(config)
 articles = await fetcher.fetch_all()
 scored = fetcher.score_for_market(articles, market_question="Will X happen?")
"""

import asyncio
import hashlib
import re
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

import structlog

logger = structlog.get_logger(__name__)


# ── Keywords mapped to Polymarket categories ──────────────────────────

CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "politics": [
        "election", "president", "congress", "senate", "governor", "vote",
        "ballot", "primary", "democrat", "republican", "legislation", "bill",
        "policy", "impeach", "campaign", "poll", "candidate", "swing state",
        "supreme court", "judicial", "veto", "filibuster", "lame duck",
    ],
    "geopolitics": [
        "war", "conflict", "sanctions", "treaty", "nato", "eu", "un ",
        "diplomat", "military", "invasion", "ceasefire", "annexation",
        "territory", "border", "sovereignty", "nuclear", "missile", "troop",
        "embargo", "tariff", "trade war", "alliance", "summit",
    ],
    "economics": [
        "gdp", "inflation", "recession", "fed ", "interest rate", "cpi",
        "unemployment", "jobs report", "fomc", "treasury", "yield",
        "stimulus", "quantitative", "deflation", "stagflation", "fiscal",
        "monetary", "debt ceiling", "budget", "deficit", "surplus",
    ],
    "finance": [
        "bitcoin", "ethereum", "crypto", "stock", "market cap", "ipo",
        "earnings", "dividend", "s&p", "dow", "nasdaq", "bull", "bear",
        "etf", "hedge fund", "merger", "acquisition", "buyout", "sec",
        "commodity", "gold", "oil", "crude", "bitcoin etf", "spot",
    ],
    "sports": [
        "super bowl", "nba", "nfl", "mlb", "nhl", "championship",
        "playoff", "finals", "world cup", "olympics", "fifa", "ufc",
        "boxing", "tennis", "grand slam", "mvp", "draft", "trade deadline",
    ],
    "crypto": [
        "bitcoin", "ethereum", "solana", "defi", "nft", "airdrop",
        "token", "blockchain", "smart contract", "layer 2", "staking",
        "bridge", "wallet", "exchange", "hack", "exploit", "rug pull",
        "sec crypto", "regulation crypto", "etf crypto",
    ],
}

# Sentiment-bearing words (simple keyword approach)
POSITIVE_WORDS = frozenset({
    "win", "victory", "success", "approve", "pass", "confirm", "boost",
    "rally", "surge", "gain", "rise", "bullish", "optimistic", "breakthrough",
    "deal", "agreement", "progress", "recovery", "growth", "upgrade",
    "positive", "strong", "record", "high", "beat", "exceed", "dominant",
})

NEGATIVE_WORDS = frozenset({
    "lose", "defeat", "fail", "reject", "veto", "block", "crash", "plunge",
    "drop", "fall", "bearish", "pessimistic", "setback", "collapse",
    "crisis", "recession", "downgrade", "negative", "weak", "low", "miss",
    "cancel", "delay", "postpone", "withdraw", "resign", "scandal",
})


# ── Data structures ───────────────────────────────────────────────────

@dataclass
class Article:
    """A news article or social media post."""

    source: str
    title: str
    body: str = ""
    url: str = ""
    timestamp: float = field(default_factory=time.time)
    keywords: List[str] = field(default_factory=list)
    sentiment: float = 0.0    # -1.0 to +1.0
    relevance: float = 0.0    # 0.0 to 1.0
    article_id: str = ""

    def __post_init__(self):
        if not self.article_id:
            raw = f"{self.source}:{self.url or self.title}"
            self.article_id = hashlib.sha256(raw.encode()).hexdigest()[:16]

    @property
    def age_sec(self) -> float:
        """Seconds since publication."""
        return time.time() - self.timestamp

    @property
    def is_fresh(self) -> bool:
        """Article is less than 1 hour old."""
        return self.age_sec < 3600

    @property
    def is_recent(self) -> bool:
        """Article is less than 6 hours old."""
        return self.age_sec < 21600

    @property
    def text(self) -> str:
        """Combined title + body for analysis."""
        parts = [self.title]
        if self.body:
            parts.append(self.body)
        return " ".join(parts)


@dataclass
class FetchResult:
    """Result of a fetch cycle."""

    timestamp: float = field(default_factory=time.monotonic)
    articles_total: int = 0
    articles_new: int = 0
    articles_relevant: int = 0
    sources_queried: int = 0
    sources_failed: int = 0
    errors: int = 0


# ── Feed sources ──────────────────────────────────────────────────────

class FeedSource:
    """Base class for news feed sources.

    Subclasses must implement fetch().
    """

    def __init__(self, name: str, config: dict) -> None:
        self.name = name
        self.config = config
        self._last_fetch: float = 0.0
        self._total_fetched: int = 0
        self._total_errors: int = 0

    async def fetch(self) -> List[Article]:
        """Fetch articles from this source.

        Returns:
            List of Article objects.
        """
        raise NotImplementedError

    @property
    def min_fetch_interval_sec(self) -> float:
        """Minimum time between fetches."""
        return self.config.get("min_fetch_interval_sec", 60.0)

    @property
    def should_fetch(self) -> bool:
        """Check if enough time has passed since the last fetch."""
        return (time.monotonic() - self._last_fetch) >= self.min_fetch_interval_sec


class RSSFeedSource(FeedSource):
    """RSS/Atom feed source.

    Fetches and parses RSS feeds. Requires aiohttp for HTTP requests.
    Falls back to a stub if feedparser/aiohttp unavailable.
    """

    def __init__(self, name: str, url: str, config: dict) -> None:
        super().__init__(name, config)
        self.url = url
        self.max_articles = config.get("max_articles_per_fetch", 50)

    async def fetch(self) -> List[Article]:
        """Fetch articles from the RSS feed.

        Returns:
            List of Article objects parsed from the feed.
        """
        if not self.should_fetch:
            return []

        self._last_fetch = time.monotonic()
        articles: List[Article] = []

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.url,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        self._total_errors += 1
                        logger.warning(
                            "RSS fetch failed",
                            source=self.name,
                            url=self.url,
                            status=resp.status,
                        )
                        return []

                    text = await resp.text()

            # Try feedparser first
            try:
                import feedparser
                feed = feedparser.parse(text)
                for entry in feed.entries[:self.max_articles]:
                    article = Article(
                        source=self.name,
                        title=getattr(entry, "title", ""),
                        body=getattr(entry, "summary", ""),
                        url=getattr(entry, "link", ""),
                        timestamp=self._parse_time(getattr(entry, "published_parsed", None)),
                    )
                    articles.append(article)
            except ImportError:
                # Fallback: simple regex extraction of titles
                titles = re.findall(r"<title><!\[CDATA\[(.*?)\]\]></title>", text)
                if not titles:
                    titles = re.findall(r"<title>(.*?)</title>", text)
                for title_text in titles[:self.max_articles]:
                    articles.append(Article(
                        source=self.name,
                        title=title_text.strip(),
                    ))

            self._total_fetched += len(articles)
            logger.debug(
                "RSS fetch complete",
                source=self.name,
                articles=len(articles),
            )

        except Exception as exc:
            self._total_errors += 1
            logger.warning(
                "RSS fetch error",
                source=self.name,
                error=str(exc),
            )

        return articles

    @staticmethod
    def _parse_time(parsed_time) -> float:
        """Parse a feedparser time tuple to epoch timestamp.

        Args:
            parsed_time: time.struct_time or None.

        Returns:
            Epoch timestamp.
        """
        if parsed_time is None:
            return time.time()
        try:
            from time import mktime
            return mktime(parsed_time)
        except Exception:
            return time.time()


class WebhookSource(FeedSource):
    """Custom HTTP webhook source.

    Polls a configured HTTP endpoint for articles in JSON format.
    Expected response: list of dicts with 'title', 'body', 'url' keys.
    """

    def __init__(self, name: str, url: str, config: dict) -> None:
        super().__init__(name, config)
        self.url = url
        self.headers = config.get("headers", {})
        self.max_articles = config.get("max_articles_per_fetch", 50)

    async def fetch(self) -> List[Article]:
        """Fetch articles from the webhook endpoint.

        Returns:
            List of Article objects.
        """
        if not self.should_fetch:
            return []

        self._last_fetch = time.monotonic()
        articles: List[Article] = []

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.url,
                    headers=self.headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        self._total_errors += 1
                        return []
                    data = await resp.json()

            # Parse JSON response
            items = data if isinstance(data, list) else data.get("articles", [])
            for item in items[:self.max_articles]:
                if not isinstance(item, dict):
                    continue
                articles.append(Article(
                    source=self.name,
                    title=item.get("title", ""),
                    body=item.get("body", item.get("summary", "")),
                    url=item.get("url", item.get("link", "")),
                    timestamp=item.get("timestamp", time.time()),
                ))

            self._total_fetched += len(articles)

        except Exception as exc:
            self._total_errors += 1
            logger.warning("Webhook fetch error", source=self.name, error=str(exc))

        return articles


class MockSource(FeedSource):
    """Mock source for testing. Returns pre-configured articles."""

    def __init__(self, name: str, articles: List[Article], config: dict = None) -> None:
        super().__init__(name, config or {})
        self._articles = articles

    async def fetch(self) -> List[Article]:
        """Return pre-configured articles.

        Returns:
            List of Article objects.
        """
        self._last_fetch = time.monotonic()
        self._total_fetched += len(self._articles)
        return list(self._articles)


# ── Article store ─────────────────────────────────────────────────────

class ArticleStore:
    """Deduplication and recency tracking for articles.

    Maintains a bounded deque of article IDs to prevent reprocessing.
    Tracks article counts by source for monitoring.
    """

    def __init__(self, max_ids: int = 10_000, max_age_sec: float = 86400) -> None:
        """Initialize the article store.

        Args:
            max_ids: Maximum number of article IDs to track.
            max_age_sec: Maximum age of articles to consider fresh.
        """
        self._seen_ids: deque = deque(maxlen=max_ids)
        self._seen_set: Set[str] = set()
        self._max_age_sec = max_age_sec
        self._by_source: Dict[str, int] = {}

    def is_new(self, article: Article) -> bool:
        """Check if an article hasn't been seen before.

        Args:
            article: Article to check.

        Returns:
            True if the article is new.
        """
        return article.article_id not in self._seen_set

    def mark_seen(self, article: Article) -> None:
        """Mark an article as seen.

        Args:
            article: Article to mark.
        """
        aid = article.article_id
        if aid not in self._seen_set:
            self._seen_ids.append(aid)
            self._seen_set.add(aid)
            # Cleanup old IDs from set when deque wraps
            while len(self._seen_set) > self._seen_ids.maxlen:
                oldest = self._seen_ids[0]
                self._seen_set.discard(oldest)

        # Track by source
        self._by_source[article.source] = self._by_source.get(article.source, 0) + 1

    def is_fresh(self, article: Article) -> bool:
        """Check if an article is within the freshness window.

        Args:
            article: Article to check.

        Returns:
            True if the article is fresh enough to process.
        """
        return article.age_sec < self._max_age_sec

    @property
    def total_seen(self) -> int:
        """Total articles ever seen."""
        return sum(self._by_source.values())

    @property
    def source_counts(self) -> Dict[str, int]:
        """Article counts by source."""
        return dict(self._by_source)


# ── Sentiment extractor ──────────────────────────────────────────────

class SentimentExtractor:
    """Keyword-based sentiment scorer for article text.

    Uses positive/negative word lists and category keywords to
    compute a sentiment score and market relevance.

    This is a lightweight alternative to LLM-based analysis,
    suitable for real-time scoring where latency matters.
    For deeper analysis, the SignalModel wraps an LLM call.
    """

    def __init__(self, config: dict = None) -> None:
        self.positive = POSITIVE_WORDS
        self.negative = NEGATIVE_WORDS
        self.category_keywords = CATEGORY_KEYWORDS
        cfg = config or {}

        # Custom overrides
        custom_pos = cfg.get("positive_words", [])
        custom_neg = cfg.get("negative_words", [])
        if custom_pos:
            self.positive = self.positive | frozenset(w.lower() for w in custom_pos)
        if custom_neg:
            self.negative = self.negative | frozenset(w.lower() for w in custom_neg)

    def score_sentiment(self, text: str) -> float:
        """Score the sentiment of a text string.

        Args:
            text: Input text.

        Returns:
            Sentiment score from -1.0 (very negative) to +1.0 (very positive).
        """
        words = self._tokenize(text)
        if not words:
            return 0.0

        pos_count = sum(1 for w in words if w in self.positive)
        neg_count = sum(1 for w in words if w in self.negative)
        total = pos_count + neg_count

        if total == 0:
            return 0.0

        return (pos_count - neg_count) / total

    def extract_keywords(self, text: str) -> List[str]:
        """Extract market-relevant keywords from text.

        Args:
            text: Input text.

        Returns:
            List of matched category keywords.
        """
        words = self._tokenize(text)
        matched: List[str] = []

        for _category, keywords in self.category_keywords.items():
            for kw in keywords:
                # Support multi-word keywords
                if " " in kw:
                    if kw in text.lower():
                        matched.append(kw)
                else:
                    if kw in words:
                        matched.append(kw)

        return list(set(matched))

    def score_relevance(self, text: str, market_question: str = "") -> float:
        """Score how relevant an article is to a specific market.

        Args:
            text: Article text.
            market_question: The market question to match against.

        Returns:
            Relevance score from 0.0 (irrelevant) to 1.0 (highly relevant).
        """
        text_lower = text.lower()
        q_lower = market_question.lower()

        # Direct keyword overlap with market question
        question_words = set(self._tokenize(q_lower))
        article_words = set(self._tokenize(text_lower))

        # Remove common stop words
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "shall", "can",
            "this", "that", "these", "those", "it", "its", "in", "on",
            "at", "to", "for", "of", "with", "by", "from", "and", "or",
            "but", "not", "no", "if", "then", "than", "so", "as", "up",
        }
        question_words -= stop_words
        article_words -= stop_words

        if not question_words:
            return 0.0

        overlap = len(question_words & article_words)
        jaccard = overlap / max(1, len(question_words))

        # Category keyword bonus
        keywords = self.extract_keywords(text)
        category_bonus = min(0.3, len(keywords) * 0.05)

        return min(1.0, jaccard + category_bonus)

    def classify_category(self, text: str) -> str:
        """Classify an article into a Polymarket category.

        Args:
            text: Article text.

        Returns:
            Most likely category string.
        """
        words = self._tokenize(text)
        scores: Dict[str, int] = {}

        for category, keywords in self.category_keywords.items():
            score = 0
            for kw in keywords:
                if " " in kw:
                    if kw in text.lower():
                        score += 2  # Multi-word matches are stronger signals
                else:
                    if kw in words:
                        score += 1
            scores[category] = score

        if not scores or max(scores.values()) == 0:
            return ""

        return max(scores, key=scores.get)  # type: ignore[arg-type]

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """Simple tokenizer: lowercase, strip punctuation.

        Args:
            text: Input text.

        Returns:
            List of lowercase word tokens.
        """
        cleaned = re.sub(r"[^\w\s]", " ", text.lower())
        return cleaned.split()


# ── Main fetcher ──────────────────────────────────────────────────────

class NewsFetcher:
    """Multi-source news and social data collector.

    Orchestrates multiple FeedSources, deduplicates articles,
    scores sentiment and relevance, and provides market-specific
    article filtering.

    Usage:
        fetcher = NewsFetcher(config)
        result = await fetcher.fetch_all()
        relevant = fetcher.get_articles_for_market(
            market_id="...",
            market_question="Will X happen by Y?",
            category="politics",
        )
    """

    def __init__(self, config: dict) -> None:
        """Initialize the news fetcher.

        Args:
            config: Full config dict (reads from strategies.ai_signals section).
        """
        self.config = config
        ai_cfg = config.get("strategies", {}).get("ai_signals", {})

        # Store and sentiment
        max_age = ai_cfg.get("max_article_age_sec", 86400)
        self.store = ArticleStore(max_age_sec=max_age)
        self.sentiment = SentimentExtractor(config)

        # Registered sources
        self._sources: Dict[str, FeedSource] = {}

        # Article cache (by category)
        self._articles: List[Article] = []
        self._by_category: Dict[str, List[Article]] = {}
        self._last_fetch_time: float = 0.0
        self._fetch_count: int = 0

        # Configuration
        self.fetch_interval_sec = ai_cfg.get("news_fetch_interval_sec", 120.0)
        self.max_articles_per_market = ai_cfg.get("max_articles_per_market", 20)
        self.min_relevance_score = ai_cfg.get("min_relevance_score", 0.15)

        # Register configured sources
        self._register_sources(ai_cfg)

    def _register_sources(self, ai_cfg: dict) -> None:
        """Register feed sources from config.

        Args:
            ai_cfg: AI signals config section.
        """
        sources_cfg = ai_cfg.get("sources", [])
        for src in sources_cfg:
            if not isinstance(src, dict):
                continue
            kind = src.get("type", "").lower()
            name = src.get("name", "unknown")
            url = src.get("url", "")

            if kind == "rss" and url:
                self.add_source(RSSFeedSource(name=name, url=url, config=src))
            elif kind == "webhook" and url:
                self.add_source(WebhookSource(name=name, url=url, config=src))
            else:
                logger.warning("Unknown or misconfigured source", name=name, type=kind)

    def add_source(self, source: FeedSource) -> None:
        """Register a feed source.

        Args:
            source: FeedSource instance.
        """
        self._sources[source.name] = source
        logger.info("News source registered", name=source.name)

    async def fetch_all(self) -> FetchResult:
        """Fetch articles from all registered sources.

        Returns:
            FetchResult with counts and stats.
        """
        result = FetchResult()
        self._fetch_count += 1
        self._last_fetch_time = time.monotonic()

        all_articles: List[Article] = []

        for name, source in self._sources.items():
            result.sources_queried += 1
            try:
                articles = await source.fetch()
                for art in articles:
                    # Deduplicate
                    if not self.store.is_new(art):
                        continue
                    self.store.mark_seen(art)

                    # Score sentiment and keywords
                    text = art.text
                    art.sentiment = self.sentiment.score_sentiment(text)
                    art.keywords = self.sentiment.extract_keywords(text)

                    # Classify category
                    category = self.sentiment.classify_category(text)
                    if category:
                        self._by_category.setdefault(category, []).append(art)

                    all_articles.append(art)
                    result.articles_new += 1

                result.articles_total += len(articles)

            except Exception as exc:
                result.sources_failed += 1
                result.errors += 1
                logger.warning(
                    "Source fetch failed",
                    source=name,
                    error=str(exc),
                )

        # Filter by freshness
        fresh = [a for a in all_articles if self.store.is_fresh(a)]
        self._articles.extend(fresh)

        # Trim cache
        if len(self._articles) > 5000:
            self._articles = self._articles[-5000:]

        result.articles_relevant = len(fresh)

        logger.info(
            "News fetch complete",
            total=result.articles_total,
            new=result.articles_new,
            fresh=result.articles_relevant,
            sources=result.sources_queried,
            errors=result.errors,
        )

        return result

    def get_articles_for_market(
        self,
        market_id: str,
        market_question: str = "",
        category: str = "",
        max_age_sec: float = 21600,  # 6 hours
        max_articles: int = 20,
    ) -> List[Article]:
        """Get articles relevant to a specific market.

        Filters and scores articles by relevance to the market question,
        recency, and category match.

        Args:
            market_id: Market ID.
            market_question: The market's question text.
            category: Market category for filtering.
            max_age_sec: Maximum article age in seconds.
            max_articles: Maximum articles to return.

        Returns:
            List of Articles sorted by relevance (descending).
        """
        candidates = self._articles

        # Filter by age
        candidates = [a for a in candidates if a.age_sec < max_age_sec]

        # Filter by category if specified
        if category and category in self._by_category:
            # Prefer category-matched articles but don't exclude others
            cat_articles = set(a.article_id for a in self._by_category.get(category, []))
            # Boost category-matched, but keep others for cross-category signals
            candidates = sorted(
                candidates,
                key=lambda a: (1.0 if a.article_id in cat_articles else 0.0),
                reverse=True,
            )

        # Score relevance
        scored: List[Tuple[float, Article]] = []
        for art in candidates:
            if market_question:
                rel = self.sentiment.score_relevance(art.text, market_question)
            else:
                rel = 0.5 if not category or art.keywords else 0.0
            art.relevance = rel
            scored.append((rel, art))

        # Filter by minimum relevance
        scored = [(r, a) for r, a in scored if r >= self.min_relevance_score]

        # Sort by relevance descending
        scored.sort(key=lambda x: x[0], reverse=True)

        return [a for _, a in scored[:max_articles]]

    def get_stats(self) -> Dict[str, any]:
        """Get fetcher statistics.

        Returns:
            Dict with stats.
        """
        return {
            "sources": len(self._sources),
            "total_articles": len(self._articles),
            "total_seen": self.store.total_seen,
            "source_counts": self.store.source_counts,
            "fetch_count": self._fetch_count,
            "last_fetch_time": self._last_fetch_time,
            "categories": {k: len(v) for k, v in self._by_category.items()},
        }

    @property
    def should_fetch(self) -> bool:
        """Check if enough time has passed for another fetch cycle."""
        return (time.monotonic() - self._last_fetch_time) >= self.fetch_interval_sec
