#!/usr/bin/env python3
"""Data collection utility — periodically fetches orderbook snapshots for backtesting.

Collects snapshots for the top 3 eligible markets simultaneously.
Usage:
  python tools/collect_backtest_data.py --duration-minutes 5 --interval-seconds 3
"""

import asyncio
import argparse
import json
import os
import time
from datetime import datetime, timezone
from types import SimpleNamespace
import structlog

from utils.helpers import load_config
from core.client import ClobClient
from core.orderbook import OrderBookManager
from data.market_scanner import MarketScanner

# Setup logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ]
)
logger = structlog.get_logger("data_collector")

async def main():
    parser = argparse.ArgumentParser(description="Collect historical orderbook snapshots from Polymarket.")
    parser.add_argument(
        "--duration-minutes",
        type=int,
        default=5,
        help="Duration of data collection in minutes (default: 5)",
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=3,
        help="Time between snapshots in seconds (default: 3)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/backtest",
        help="Directory to save the snapshots (default: data/backtest)",
    )
    parser.add_argument(
        "--from-current-snapshot",
        action="store_true",
        help="Collect top passing markets from reports/current_market_snapshot.json instead of the scanner",
    )
    parser.add_argument(
        "--markets",
        type=int,
        default=3,
        help="Number of markets to collect (default: 3)",
    )
    args = parser.parse_args()

    # Load configuration
    config = load_config()

    # Initialize client & scanner
    logger.info("Initializing CLOB client and scanner...")
    client = ClobClient(config)
    orderbook = OrderBookManager(config)
    scanner = MarketScanner(client, orderbook, config)

    # Perform initial scan to find top markets
    if args.from_current_snapshot:
        snapshot_path = "reports/current_market_snapshot.json"
        logger.info("Loading targeted markets from current snapshot", path=snapshot_path)
        with open(snapshot_path, "r", encoding="utf-8") as f:
            rows = json.load(f)
        passing_rows = [
            row for row in rows
            if 100 <= float(row.get("spread_bps", 0)) <= 800
            and min(float(row.get("bid_touch_usd", 0)), float(row.get("ask_touch_usd", 0))) >= 25
            and int(row.get("days_to_resolution", 0)) >= 3
            and row.get("token_id")
        ]
        top_markets = [
            SimpleNamespace(
                market_id=row["condition_id"],
                token_id=row["token_id"],
                question=row.get("question", ""),
                category=row.get("category", "unknown"),
                daily_volume_usd=float(row.get("volume_24h", 0.0)),
            )
            for row in passing_rows[: args.markets]
        ]
    else:
        logger.info("Scanning for eligible markets...")
        scan_result = await scanner.scan(force=True)
        top_markets = scan_result.top_markets[: args.markets]

    if not top_markets:
        logger.error("No top eligible markets found to collect data for!")
        return

    # Select target markets
    logger.info("Selected markets for collection:", count=len(top_markets))
    for idx, mkt in enumerate(top_markets, 1):
        logger.info(
            f"  {idx}. {mkt.question}",
            market_id=mkt.market_id,
            category=mkt.category,
            volume_24h=mkt.daily_volume_usd,
        )

    # Create output directory
    os.makedirs(args.output_dir, exist_ok=True)

    # Open snapshot files
    files = {}
    for mkt in top_markets:
        filepath = os.path.join(args.output_dir, f"{mkt.market_id}.jsonl")
        files[mkt.market_id] = open(filepath, "a", encoding="utf-8")
        logger.info(f"Writing data for {mkt.market_id[:10]}... to {filepath}")

    duration_sec = args.duration_minutes * 60
    start_time = time.time()
    end_time = start_time + duration_sec
    ticks_collected = 0
    snapshots_written = {mkt.market_id: 0 for mkt in top_markets}
    error_count = 0
    fetch_latencies_sec = []

    logger.info(
        "Starting snapshot collection loop...",
        duration_min=args.duration_minutes,
        interval_sec=args.interval_seconds,
    )

    try:
        while time.time() < end_time:
            loop_start = time.time()

            # Query orderbooks for all target markets concurrently
            fetch_start = time.time()
            tasks = [client.get_orderbook(mkt.token_id) for mkt in top_markets]
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            fetch_latency_sec = time.time() - fetch_start
            fetch_latencies_sec.append(fetch_latency_sec)

            timestamp = time.time()
            for mkt, response in zip(top_markets, responses):
                if isinstance(response, Exception):
                    error_count += 1
                    logger.warning(
                        "Failed to fetch orderbook",
                        market_id=mkt.market_id,
                        error=str(response),
                    )
                    continue

                # Parse bids and asks
                bids = [
                    [float(b.get("price", 0)), float(b.get("size", 0))]
                    for b in response.get("bids", [])
                ]
                asks = [
                    [float(a.get("price", 0)), float(a.get("size", 0))]
                    for a in response.get("asks", [])
                ]

                # Bids descending, asks ascending
                bids.sort(key=lambda x: x[0], reverse=True)
                asks.sort(key=lambda x: x[0])

                best_bid = bids[0][0] if bids else None
                best_ask = asks[0][0] if asks else None
                mid = (best_bid + best_ask) / 2.0 if (best_bid and best_ask) else 0.5

                snapshot = {
                    "timestamp": timestamp,
                    "market_id": mkt.market_id,
                    "bids": bids,
                    "asks": asks,
                    "mid": round(mid, 4),
                    "volume_24h": int(mkt.daily_volume_usd),
                }

                # Write line
                files[mkt.market_id].write(json.dumps(snapshot) + "\n")
                files[mkt.market_id].flush()
                snapshots_written[mkt.market_id] += 1

            ticks_collected += 1
            elapsed = time.time() - loop_start
            sleep_time = max(0.1, args.interval_seconds - elapsed)

            remaining_min = max(0.0, (end_time - time.time()) / 60)
            logger.info(
                "Snapshot iteration complete",
                iteration=ticks_collected,
                remaining_minutes=round(remaining_min, 2),
            )

            await asyncio.sleep(sleep_time)

    except KeyboardInterrupt:
        logger.info("Collection interrupted by user.")
    finally:
        # Close all files
        for f in files.values():
            f.close()
        avg_latency = (
            sum(fetch_latencies_sec) / len(fetch_latencies_sec)
            if fetch_latencies_sec else None
        )
        summary = {
            "started_at_epoch": start_time,
            "finished_at_epoch": time.time(),
            "duration_minutes_requested": args.duration_minutes,
            "interval_seconds": args.interval_seconds,
            "total_iterations": ticks_collected,
            "error_count": error_count,
            "average_request_latency_sec": avg_latency,
            "snapshots_written": snapshots_written,
            "selected_markets": [
                {
                    "market_id": mkt.market_id,
                    "token_id": mkt.token_id,
                    "question": mkt.question,
                    "category": mkt.category,
                }
                for mkt in top_markets
            ],
        }
        summary_path = os.path.join(args.output_dir, "collection_summary.json")
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        logger.info(
            "Data collection finished successfully.",
            total_iterations=ticks_collected,
            error_count=error_count,
            average_request_latency_sec=avg_latency,
            summary_path=summary_path,
        )

if __name__ == "__main__":
    asyncio.run(main())
