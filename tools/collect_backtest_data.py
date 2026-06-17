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
    args = parser.parse_args()

    # Load configuration
    config = load_config()

    # Initialize client & scanner
    logger.info("Initializing CLOB client and scanner...")
    client = ClobClient(config)
    orderbook = OrderBookManager(config)
    scanner = MarketScanner(client, orderbook, config)

    # Perform initial scan to find top markets
    logger.info("Scanning for eligible markets...")
    scan_result = await scanner.scan(force=True)
    if not scan_result.top_markets:
        logger.error("No top eligible markets found to collect data for!")
        return

    # Select top 3 markets
    top_3 = scan_result.top_markets[:3]
    logger.info("Selected top 3 markets for collection:")
    for idx, mkt in enumerate(top_3, 1):
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
    for mkt in top_3:
        filepath = os.path.join(args.output_dir, f"{mkt.market_id}.jsonl")
        files[mkt.market_id] = open(filepath, "a", encoding="utf-8")
        logger.info(f"Writing data for {mkt.market_id[:10]}... to {filepath}")

    duration_sec = args.duration_minutes * 60
    start_time = time.time()
    end_time = start_time + duration_sec
    ticks_collected = 0

    logger.info(
        "Starting snapshot collection loop...",
        duration_min=args.duration_minutes,
        interval_sec=args.interval_seconds,
    )

    try:
        while time.time() < end_time:
            loop_start = time.time()

            # Query orderbooks for all 3 markets concurrently
            tasks = [client.get_orderbook(mkt.token_id) for mkt in top_3]
            responses = await asyncio.gather(*tasks, return_exceptions=True)

            timestamp = time.time()
            for mkt, response in zip(top_3, responses):
                if isinstance(response, Exception):
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
        logger.info("Data collection finished successfully.", total_iterations=ticks_collected)

if __name__ == "__main__":
    asyncio.run(main())
