from tools.generate_candidates import (
    build_candidate,
    jaccard,
    norm_kalshi,
    norm_polymarket,
    score_and_select,
    stable_id,
    tokenise,
)


def pm_market(condition_id: str, question: str) -> dict:
    return {
        "condition_id": condition_id,
        "yes_token_id": f"{condition_id}-yes",
        "no_token_id": f"{condition_id}-no",
        "question": question,
        "end_date_iso": "2026-12-31T00:00:00Z",
        "_tokens": tokenise(question),
    }


def kalshi_market(ticker: str, title: str) -> dict:
    return {
        "market_ticker": ticker,
        "event_ticker": f"{ticker}-EVENT",
        "series_ticker": "KXTEST",
        "title": title,
        "close_time": "2026-12-31T00:00:00Z",
        "_tokens": tokenise(title),
    }


def test_tokenise_and_jaccard_are_human_readable():
    first = tokenise("Will France win the 2026 FIFA World Cup?")
    second = tokenise("France to win FIFA World Cup in 2026?")

    assert "france" in first
    assert "will" not in first
    assert jaccard(first, second) > 0.5


def test_norm_polymarket_handles_tokens_array_and_requires_binary_tokens():
    raw = {
        "question": "Will France win the 2026 FIFA World Cup?",
        "conditionId": "0xcondition",
        "endDate": "2026-07-20T00:00:00Z",
        "tokens": [
            {"outcome": "Yes", "token_id": "0xyes"},
            {"outcome": "No", "token_id": "0xno"},
        ],
    }

    normalized = norm_polymarket(raw)

    assert normalized["condition_id"] == "0xcondition"
    assert normalized["yes_token_id"] == "0xyes"
    assert normalized["no_token_id"] == "0xno"


def test_norm_polymarket_handles_gamma_json_encoded_tokens():
    raw = {
        "question": "Will France win the 2026 FIFA World Cup?",
        "conditionId": "0xcondition",
        "outcomes": '["Yes", "No"]',
        "clobTokenIds": '["0xyes", "0xno"]',
    }

    normalized = norm_polymarket(raw)

    assert normalized["yes_token_id"] == "0xyes"
    assert normalized["no_token_id"] == "0xno"


def test_norm_kalshi_extracts_listing_fields():
    raw = {
        "ticker": "KXFRANCE-26",
        "event_ticker": "KXFRANCE",
        "series_ticker": "KXWC",
        "title": "France to win FIFA World Cup in 2026?",
        "close_time": "2026-07-20T00:00:00Z",
    }

    normalized = norm_kalshi(raw)

    assert normalized["market_ticker"] == "KXFRANCE-26"
    assert normalized["event_ticker"] == "KXFRANCE"
    assert normalized["series_ticker"] == "KXWC"


def test_stable_id_is_repeatable_for_same_pair():
    assert stable_id("0xcondition", "KXFRANCE-26") == stable_id(
        "0xcondition", "KXFRANCE-26"
    )
    assert stable_id("0xcondition", "KXFRANCE-26").startswith("cand-")


def test_candidate_review_fields_are_explicitly_null():
    candidate = build_candidate(
        pm_market("0xcondition", "Will France win the 2026 FIFA World Cup?"),
        kalshi_market("KXFRANCE-26", "France to win FIFA World Cup in 2026?"),
        0.75,
        ["2026", "cup", "fifa", "france", "world"],
    )

    assert candidate["status"] == "candidate"
    for field in (
        "canonical_proposition",
        "yes_predicate",
        "resolution_source",
        "cutoff_utc",
        "timezone",
        "payout_convention",
        "invalidation_behavior",
        "review_evidence",
        "reviewer",
        "reviewed_at",
        "mapping_version",
    ):
        assert candidate[field] is None


def test_score_and_select_is_one_to_one_best_match():
    pm_markets = [
        pm_market("pm-france", "France to win FIFA World Cup in 2026"),
        pm_market("pm-brazil", "Brazil to win FIFA World Cup in 2026"),
    ]
    kalshi_markets = [
        kalshi_market("KXFRANCE", "France to win FIFA World Cup in 2026"),
        kalshi_market("KXFRANCE-DUPE", "France wins FIFA World Cup"),
        kalshi_market("KXBRAZIL", "Brazil to win FIFA World Cup in 2026"),
    ]

    candidates = score_and_select(pm_markets, kalshi_markets, threshold=0.25, limit=10)

    assert len(candidates) == 2
    assert len({candidate["polymarket"]["condition_id"] for candidate in candidates}) == 2
    assert len({candidate["kalshi"]["market_ticker"] for candidate in candidates}) == 2
