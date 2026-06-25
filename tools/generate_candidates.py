#!/usr/bin/env python3
"""Generate Polymarket/Kalshi candidate pairs for manual review.

This standalone tool writes CANDIDATES ONLY to
``research_mappings/candidates.yaml``. No row produced here is replay-eligible.
Every candidate must be manually reviewed and promoted to
``research_mappings/catalog.yaml`` before capture/replay can use it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.transport import ReadOnlyTransport  # noqa: E402


GENERATOR_VERSION = "0.1.0"
POLYMARKET_GAMMA_BASE = "https://gamma-api.polymarket.com"
KALSHI_TRADE_API_BASE = "https://external-api.kalshi.com/trade-api/v2"
DEFAULT_OUTPUT = ROOT / "research_mappings" / "candidates.yaml"
ALLOWED_HOSTS = frozenset({"gamma-api.polymarket.com", "external-api.kalshi.com"})

STOP_WORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "the",
        "in",
        "on",
        "at",
        "by",
        "for",
        "to",
        "of",
        "be",
        "is",
        "are",
        "was",
        "were",
        "or",
        "and",
        "with",
        "this",
        "that",
        "it",
        "its",
        "as",
        "from",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "not",
        "no",
        "yes",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "before",
        "after",
        "between",
        "if",
        "when",
        "who",
        "what",
        "which",
        "how",
        "than",
        "then",
        "there",
        "their",
        "they",
        "he",
        "she",
        "we",
        "i",
        "you",
        "any",
        "all",
        "each",
        "both",
        "whether",
        "least",
        "most",
        "more",
        "less",
    }
)


def _get(transport: ReadOnlyTransport, url: str, params: dict[str, str] | None = None) -> Any:
    response = transport.request("GET", url, params=params)
    payload = response.json()
    if not isinstance(payload, (dict, list)):
        raise ValueError("candidate source returned non-container JSON")
    return payload


def tokenise(text: str) -> frozenset[str]:
    """Lower-case, strip punctuation, remove stop words and single chars."""
    normalized = re.sub(r"[^\w\s]", " ", text.lower())
    return frozenset(
        token for token in normalized.split() if token not in STOP_WORDS and len(token) > 1
    )


def jaccard(first: frozenset[str], second: frozenset[str]) -> float:
    if not first or not second:
        return 0.0
    union = first | second
    return round(len(first & second) / len(union), 4) if union else 0.0


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _normalise_polymarket_tokens(raw: dict[str, Any]) -> list[dict[str, str]]:
    tokens = raw.get("tokens")
    if isinstance(tokens, list):
        normalized = []
        for token in tokens:
            if not isinstance(token, dict):
                continue
            normalized.append(
                {
                    "outcome": str(token.get("outcome") or token.get("name") or ""),
                    "token_id": str(
                        token.get("token_id") or token.get("tokenId") or token.get("id") or ""
                    ),
                }
            )
        if normalized:
            return normalized

    outcomes = _as_list(raw.get("outcomes"))
    token_ids = _as_list(raw.get("clobTokenIds") or raw.get("clob_token_ids"))
    normalized = []
    for outcome, token_id in zip(outcomes, token_ids):
        normalized.append({"outcome": str(outcome), "token_id": str(token_id)})
    return normalized


def fetch_polymarket(transport: ReadOnlyTransport, fetch_limit: int) -> list[dict[str, Any]]:
    """Paginate Gamma markets for active, open Polymarket listings."""
    markets: list[dict[str, Any]] = []
    page_size = min(100, max(1, fetch_limit))
    offset = 0
    while len(markets) < fetch_limit:
        data = _get(
            transport,
            f"{POLYMARKET_GAMMA_BASE}/markets",
            params={
                "active": "true",
                "closed": "false",
                "limit": str(page_size),
                "offset": str(offset),
            },
        )
        batch = data if isinstance(data, list) else data.get("markets", [])
        if not isinstance(batch, list) or not batch:
            break
        markets.extend(item for item in batch if isinstance(item, dict))
        if len(batch) < page_size:
            break
        offset += page_size
    return markets[:fetch_limit]


def fetch_kalshi(transport: ReadOnlyTransport, fetch_limit: int) -> list[dict[str, Any]]:
    """Cursor-paginate Kalshi public Trade API markets."""
    markets: list[dict[str, Any]] = []
    cursor: str | None = None
    page_size = min(100, max(1, fetch_limit))
    while len(markets) < fetch_limit:
        params = {"limit": str(page_size), "status": "open"}
        if cursor:
            params["cursor"] = cursor
        data = _get(transport, f"{KALSHI_TRADE_API_BASE}/markets", params=params)
        if not isinstance(data, dict):
            break
        batch = data.get("markets", [])
        if not isinstance(batch, list) or not batch:
            break
        markets.extend(item for item in batch if isinstance(item, dict))
        cursor = data.get("cursor") if isinstance(data.get("cursor"), str) else None
        if not cursor:
            break
    return markets[:fetch_limit]


def norm_polymarket(raw: dict[str, Any]) -> dict[str, Any] | None:
    question = str(raw.get("question") or raw.get("title") or "").strip()
    condition_id = str(
        raw.get("conditionId") or raw.get("condition_id") or raw.get("conditionID") or ""
    ).strip()
    end_date = str(raw.get("endDate") or raw.get("end_date_iso") or raw.get("endDateIso") or "")
    tokens = _normalise_polymarket_tokens(raw)
    yes_token = next(
        (token for token in tokens if token["outcome"].strip().lower() in {"yes", "true"}),
        None,
    )
    no_token = next(
        (token for token in tokens if token["outcome"].strip().lower() in {"no", "false"}),
        None,
    )
    if not question or not condition_id or not yes_token or not no_token:
        return None
    return {
        "condition_id": condition_id,
        "yes_token_id": yes_token["token_id"],
        "no_token_id": no_token["token_id"],
        "question": question,
        "end_date_iso": end_date,
        "_tokens": tokenise(question),
    }


def norm_kalshi(raw: dict[str, Any]) -> dict[str, Any] | None:
    title = str(raw.get("title") or raw.get("yes_sub_title") or raw.get("subtitle") or "").strip()
    ticker = str(raw.get("ticker") or "").strip()
    if not title or not ticker:
        return None
    return {
        "market_ticker": ticker,
        "event_ticker": str(raw.get("event_ticker") or ""),
        "series_ticker": str(raw.get("series_ticker") or ""),
        "title": title,
        "close_time": str(raw.get("close_time") or ""),
        "_tokens": tokenise(title),
    }


def stable_id(pm_condition_id: str, kalshi_ticker: str) -> str:
    raw = f"{pm_condition_id}:{kalshi_ticker}".encode("utf-8")
    return f"cand-{hashlib.sha256(raw).hexdigest()[:12]}"


def build_candidate(
    pm_market: dict[str, Any],
    kalshi_market: dict[str, Any],
    score: float,
    shared_tokens: list[str],
) -> dict[str, Any]:
    return {
        "id": stable_id(pm_market["condition_id"], kalshi_market["market_ticker"]),
        "status": "candidate",
        "generator_version": GENERATOR_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "polymarket": {
            "condition_id": pm_market["condition_id"],
            "yes_token_id": pm_market["yes_token_id"],
            "no_token_id": pm_market["no_token_id"],
            "question": pm_market["question"],
            "end_date_iso": pm_market["end_date_iso"],
        },
        "kalshi": {
            "market_ticker": kalshi_market["market_ticker"],
            "event_ticker": kalshi_market["event_ticker"],
            "series_ticker": kalshi_market["series_ticker"],
            "title": kalshi_market["title"],
            "close_time": kalshi_market["close_time"],
        },
        "similarity": {
            "method": "jaccard_token_overlap",
            "score": score,
            "matched_tokens": shared_tokens,
        },
        "canonical_proposition": None,
        "yes_predicate": None,
        "resolution_source": None,
        "cutoff_utc": None,
        "timezone": None,
        "payout_convention": None,
        "invalidation_behavior": None,
        "review_evidence": None,
        "reviewer": None,
        "reviewed_at": None,
        "mapping_version": None,
    }


def score_and_select(
    polymarket_markets: list[dict[str, Any]],
    kalshi_markets: list[dict[str, Any]],
    threshold: float,
    limit: int,
) -> list[dict[str, Any]]:
    scored: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
    for pm_market in polymarket_markets:
        for kalshi_market in kalshi_markets:
            score = jaccard(pm_market["_tokens"], kalshi_market["_tokens"])
            if score >= threshold:
                scored.append((score, pm_market, kalshi_market))

    scored.sort(
        key=lambda item: (
            item[0],
            item[1]["condition_id"],
            item[2]["market_ticker"],
        ),
        reverse=True,
    )

    seen_pm: set[str] = set()
    seen_kalshi: set[str] = set()
    candidates: list[dict[str, Any]] = []
    for score, pm_market, kalshi_market in scored:
        if (
            pm_market["condition_id"] in seen_pm
            or kalshi_market["market_ticker"] in seen_kalshi
        ):
            continue
        seen_pm.add(pm_market["condition_id"])
        seen_kalshi.add(kalshi_market["market_ticker"])
        candidates.append(
            build_candidate(
                pm_market,
                kalshi_market,
                score,
                sorted(pm_market["_tokens"] & kalshi_market["_tokens"]),
            )
        )
        if len(candidates) >= limit:
            break
    return candidates


def write_candidates(
    *,
    output: Path,
    candidates: list[dict[str, Any]],
    threshold: float,
    fetch_limit: int,
    polymarket_fetched: int,
    polymarket_normalised: int,
    kalshi_fetched: int,
    kalshi_normalised: int,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": {
            "warning": (
                "CANDIDATES ONLY - none are eligible for replay. Promote to "
                "research_mappings/catalog.yaml only after completing every null "
                "review field and verifying semantic identity."
            ),
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "generator_version": GENERATOR_VERSION,
            "similarity_method": "jaccard_token_overlap",
            "threshold": threshold,
            "fetch_limit_per_venue": fetch_limit,
            "polymarket_fetched": polymarket_fetched,
            "polymarket_normalised": polymarket_normalised,
            "kalshi_fetched": kalshi_fetched,
            "kalshi_normalised": kalshi_normalised,
            "candidates_written": len(candidates),
        },
        "candidates": candidates,
    }
    output.write_text(
        yaml.safe_dump(
            payload,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        ),
        encoding="utf-8",
    )


def run(
    *,
    limit: int,
    threshold: float,
    fetch_limit: int,
    output: Path,
    dry_run: bool,
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    transport = ReadOnlyTransport(ALLOWED_HOSTS, timeout_seconds=timeout_seconds)
    try:
        print(f"Fetching up to {fetch_limit} Polymarket markets...")
        polymarket_raw = fetch_polymarket(transport, fetch_limit)
        print(f"  {len(polymarket_raw)} fetched")

        print(f"Fetching up to {fetch_limit} Kalshi markets...")
        kalshi_raw = fetch_kalshi(transport, fetch_limit)
        print(f"  {len(kalshi_raw)} fetched")
    finally:
        transport.close()

    polymarket_markets = [
        normalized
        for market in polymarket_raw
        if (normalized := norm_polymarket(market)) is not None
    ]
    kalshi_markets = [
        normalized for market in kalshi_raw if (normalized := norm_kalshi(market)) is not None
    ]
    print(
        f"\nNormalised: {len(polymarket_markets)} PM x {len(kalshi_markets)} Kalshi "
        f"= {len(polymarket_markets) * len(kalshi_markets):,} pairs to score"
    )

    candidates = score_and_select(polymarket_markets, kalshi_markets, threshold, limit)
    scores = [candidate["similarity"]["score"] for candidate in candidates]
    print(f"\nCandidates >= {threshold}: {len(candidates)} (limit {limit})")
    if scores:
        ordered = sorted(scores)
        print(f"  Score range : {ordered[0]:.3f} - {ordered[-1]:.3f}")
        print(f"  Median      : {ordered[len(ordered) // 2]:.3f}")

    if dry_run:
        print("\n[--dry-run] Top candidates (not written):")
        for candidate in candidates[:10]:
            print(f"\n  [{candidate['similarity']['score']:.3f}] {candidate['polymarket']['question'][:70]}")
            print(f"         <-> {candidate['kalshi']['title'][:70]}")
            print(f"         shared: {' '.join(candidate['similarity']['matched_tokens'][:6])}")
        return candidates

    write_candidates(
        output=output,
        candidates=candidates,
        threshold=threshold,
        fetch_limit=fetch_limit,
        polymarket_fetched=len(polymarket_raw),
        polymarket_normalised=len(polymarket_markets),
        kalshi_fetched=len(kalshi_raw),
        kalshi_normalised=len(kalshi_markets),
    )
    print(f"\nWritten -> {output}")
    print("Next: manually review candidates, then promote approved mappings to catalog.yaml")
    return candidates


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--threshold", type=float, default=0.25)
    parser.add_argument("--fetch-limit", type=int, default=300)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run(
        limit=args.limit,
        threshold=args.threshold,
        fetch_limit=args.fetch_limit,
        output=args.output,
        dry_run=args.dry_run,
        timeout_seconds=args.timeout_seconds,
    )


if __name__ == "__main__":
    main()
