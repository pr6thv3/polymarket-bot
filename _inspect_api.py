"""Quick scanner test — limit pagination to 5 pages for speed."""
import asyncio
from dotenv import load_dotenv
load_dotenv()
from utils.helpers import load_config
from core.client import ClobClient
from core.orderbook import OrderBookManager
from data.market_scanner import MarketScanner

async def test():
    config = load_config()
    client = ClobClient(config)
    orderbook = OrderBookManager(config)
    scanner = MarketScanner(client, orderbook, config)
    
    # Temporarily limit pages for faster testing
    original_max = 50
    # Monkey-patch _fetch_and_score's max_pages would be complex,
    # so let's just call the scan and see what happens
    
    # Test _parse_market and _infer_category directly with sample data
    print("=== Testing _parse_market directly ===")
    sample = {
        "condition_id": "0xtest123",
        "question": "Will the Fed cut rates?",
        "tokens": [
            {"token_id": "tok1", "outcome": "Yes", "price": 0.6},
            {"token_id": "tok2", "outcome": "No", "price": 0.4},
        ],
        "tags": ["Finance", "federal reserve", "economy", "All"],
        "market_slug": "will-the-fed-cut-rates",
        "end_date_iso": "2026-12-31T00:00:00Z",
        "active": True,
        "closed": False,
        "accepting_orders": True,
        "enable_order_book": True,
    }
    info = scanner._parse_market(sample)
    if info:
        print(f"  Parsed: category={info.category} accepting={info.accepting_orders}")
        print(f"  Question: {info.question}")
        print(f"  Token: {info.token_id[:30]}...")
        print(f"  Eligible: {scanner._is_eligible(info)}")
        scanner._compute_score(info)
        print(f"  Score: {info.score:.1f}")
    else:
        print("  FAILED TO PARSE!")
    
    # Test with None tags
    print("\n=== Testing with None tags ===")
    sample_none = {
        "condition_id": "0xtest456",
        "question": "Some market",
        "tokens": None,
        "tags": None,
        "market_slug": "some-market",
        "end_date_iso": "2026-12-31T00:00:00Z",
        "active": True,
        "closed": True,
        "accepting_orders": True,
    }
    info2 = scanner._parse_market(sample_none)
    if info2:
        print(f"  Parsed OK: category={info2.category} accepting={info2.accepting_orders}")
    else:
        print("  FAILED TO PARSE!")

    # Test category inference
    print("\n=== Testing _infer_category ===")
    test_cases = [
        ({"tags": ["Politics", "election", "Trump"], "market_slug": "trump-wins"}, "politics"),
        ({"tags": ["Crypto", "bitcoin"], "market_slug": "btc-price"}, "crypto"),
        ({"tags": ["Finance", "fed"], "market_slug": "fed-rate-cut", "question": "Will the Fed cut?"}, "finance"),
        ({"tags": None, "market_slug": "ukraine-conflict"}, "geopolitics"),
        ({"tags": ["All"], "market_slug": "nba-lac-bos"}, "sports"),
        ({"tags": ["All"], "market_slug": "random-thing", "question": "something else"}, "politics"),
    ]
    for raw, expected in test_cases:
        result = scanner._infer_category(raw)
        status = "✅" if result == expected else "❌"
        print(f"  {status} tags={raw.get('tags')} slug={raw.get('market_slug','')} → {result} (expected {expected})")

    # Now do a real scan with the API (full pagination)
    print("\n=== Running REAL scan (all pages — may take ~30s) ===")
    result = await scanner.scan(force=True)
    print(f"\n  Total parsed:  {result.total_markets}")
    print(f"  Eligible:      {result.eligible_markets}")
    print(f"  Top markets:   {len(result.top_markets)}")
    print(f"  Errors:        {result.errors}")

    if result.top_markets:
        print("\n=== TOP MARKETS ===")
        for i, m in enumerate(result.top_markets[:10]):
            print(f"\n  {i+1}. [{m.category}] {m.question[:65]}")
            print(f"     score={m.score:.1f} days={m.days_to_resolution} accepting={m.accepting_orders}")
    else:
        # Debug: show stats
        from collections import Counter
        cats = Counter(m.category for m in scanner._markets.values())
        accepting = sum(1 for m in scanner._markets.values() if m.accepting_orders)
        target_match = sum(1 for m in scanner._markets.values() 
                          if m.category in scanner.target_categories)
        print(f"\n  Category breakdown: {dict(cats)}")
        print(f"  accepting_orders=True: {accepting}")
        print(f"  Category matches target: {target_match}")
        print(f"  Target categories: {scanner.target_categories}")

asyncio.run(test())
