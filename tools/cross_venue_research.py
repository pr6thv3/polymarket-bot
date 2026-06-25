#!/usr/bin/env python3
"""Read-only Polymarket/Kalshi capture and deterministic replay CLI.

This entrypoint intentionally imports only the isolated ``research`` package.
It must never import bot clients, executors, strategies, or ``main.py``.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.adapters import (
    fetch_kalshi_fee_changes,
    fetch_kalshi_market,
    fetch_kalshi_orderbook,
    fetch_polymarket_book,
    build_kalshi_snapshot,
    build_polymarket_snapshot,
)
from research.contracts import (
    DEFAULT_CONTRACT_DIR,
    SourceContractError,
    load_contracts,
    validate_contract_fixtures,
    validate_payload,
)
from research.event_log import ResearchRunLog, utc_now_iso
from research.mapping import MappingCatalog
from research.quotes import PairedSnapshot
from research.replay import QualityPolicy, replay_run, write_evidence_pack
from research.safety import ResearchSafetyError, assert_read_only_config
from research.transport import ReadOnlyTransport


DEFAULT_ALLOWED_HOSTS = {
    "clob.polymarket.com",
    "external-api.kalshi.com",
    "api.elections.kalshi.com",
}


def load_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ResearchSafetyError("config must be a YAML object")
    return payload


def _research_settings(config: dict[str, Any]) -> dict[str, Any]:
    settings = config.get("research", {})
    return settings if isinstance(settings, dict) else {}


def _allowed_hosts(config: dict[str, Any]) -> set[str]:
    hosts = _research_settings(config).get("allowed_hosts", DEFAULT_ALLOWED_HOSTS)
    if not isinstance(hosts, list | tuple | set):
        return set(DEFAULT_ALLOWED_HOSTS)
    return {str(host) for host in hosts}


def _utc_ms_between(first: str, second: str) -> int:
    left = datetime.fromisoformat(first.replace("Z", "+00:00"))
    right = datetime.fromisoformat(second.replace("Z", "+00:00"))
    return int(abs((right - left).total_seconds() * 1000))


def cmd_verify_contracts(args: argparse.Namespace) -> int:
    contracts = load_contracts(args.contract_dir)
    validated = validate_contract_fixtures(args.contract_dir)
    if args.live:
        if not args.polymarket_token_id:
            raise SourceContractError("--polymarket-token-id is required for --live")
        if not args.kalshi_ticker:
            raise SourceContractError("--kalshi-ticker is required for --live")
        transport = ReadOnlyTransport(DEFAULT_ALLOWED_HOSTS)
        try:
            polymarket_book = fetch_polymarket_book(transport, args.polymarket_token_id)
            validate_payload(
                contracts["polymarket_clob_v1"],
                "get_order_book",
                polymarket_book,
            )
            kalshi_market = fetch_kalshi_market(transport, args.kalshi_ticker)
            validate_payload(
                contracts["kalshi_trade_api_v1"],
                "get_market",
                kalshi_market,
            )
            kalshi_orderbook = fetch_kalshi_orderbook(transport, args.kalshi_ticker)
            validate_payload(
                contracts["kalshi_trade_api_v1"],
                "get_market_orderbook",
                kalshi_orderbook,
            )
            kalshi_fee_changes = fetch_kalshi_fee_changes(transport, args.kalshi_series_ticker)
            validate_payload(
                contracts["kalshi_trade_api_v1"],
                "get_series_fee_changes",
                kalshi_fee_changes,
            )
        finally:
            transport.close()
        validated.append("live_read_only_contract_probe")
    print("\n".join(validated))
    return 0


def cmd_capture(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    assert_read_only_config(config)
    catalog = MappingCatalog.load(args.mapping_catalog)
    if not catalog.mappings:
        raise ResearchSafetyError("capture requires at least one approved mapping")

    contracts = load_contracts(args.contract_dir)
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log = ResearchRunLog(
        args.output_dir,
        run_id,
        metadata={
            "mode": "read_only_public_rest",
            "mapping_catalog_version": catalog.version,
            "source_contracts": sorted(contracts.keys()),
        },
    )
    transport = ReadOnlyTransport(_allowed_hosts(config))
    deadline = time.monotonic() + (args.duration_hours * 3600)
    iterations = 0
    try:
        while time.monotonic() < deadline:
            for mapping in catalog.mappings:
                pm_yes_receipt = utc_now_iso()
                pm_yes = fetch_polymarket_book(transport, mapping.polymarket_yes_token_id)
                validate_payload(contracts["polymarket_clob_v1"], "get_order_book", pm_yes)
                log.append_raw_payload(
                    venue="polymarket",
                    endpoint="get_order_book:yes",
                    payload=pm_yes,
                    receipt_timestamp=pm_yes_receipt,
                    source_contract_version="polymarket_clob_v1",
                )

                pm_no_receipt = utc_now_iso()
                pm_no = fetch_polymarket_book(transport, mapping.polymarket_no_token_id)
                validate_payload(contracts["polymarket_clob_v1"], "get_order_book", pm_no)
                log.append_raw_payload(
                    venue="polymarket",
                    endpoint="get_order_book:no",
                    payload=pm_no,
                    receipt_timestamp=pm_no_receipt,
                    source_contract_version="polymarket_clob_v1",
                )

                ks_market_receipt = utc_now_iso()
                ks_market = fetch_kalshi_market(transport, mapping.kalshi_market_ticker)
                validate_payload(contracts["kalshi_trade_api_v1"], "get_market", ks_market)
                log.append_raw_payload(
                    venue="kalshi",
                    endpoint="get_market",
                    payload=ks_market,
                    receipt_timestamp=ks_market_receipt,
                    source_contract_version="kalshi_trade_api_v1",
                )

                ks_orderbook_receipt = utc_now_iso()
                ks_orderbook = fetch_kalshi_orderbook(transport, mapping.kalshi_market_ticker)
                validate_payload(
                    contracts["kalshi_trade_api_v1"],
                    "get_market_orderbook",
                    ks_orderbook,
                )
                log.append_raw_payload(
                    venue="kalshi",
                    endpoint="get_market_orderbook",
                    payload=ks_orderbook,
                    receipt_timestamp=ks_orderbook_receipt,
                    source_contract_version="kalshi_trade_api_v1",
                )

                ks_fee_receipt = utc_now_iso()
                ks_fee_changes = fetch_kalshi_fee_changes(
                    transport, mapping.kalshi_series_ticker
                )
                validate_payload(
                    contracts["kalshi_trade_api_v1"],
                    "get_series_fee_changes",
                    ks_fee_changes,
                )
                log.append_raw_payload(
                    venue="kalshi",
                    endpoint="get_series_fee_changes",
                    payload=ks_fee_changes,
                    receipt_timestamp=ks_fee_receipt,
                    source_contract_version="kalshi_trade_api_v1",
                )

                polymarket_snapshot = build_polymarket_snapshot(
                    mapping=mapping,
                    yes_payload=pm_yes,
                    no_payload=pm_no,
                    receipt_timestamp=pm_no_receipt,
                    source_contract_version="polymarket_clob_v1",
                    fee_rule=None,
                    fee_schedule_reference="not_captured_dynamic_market_fee",
                )
                kalshi_snapshot = build_kalshi_snapshot(
                    mapping=mapping,
                    market_payload=ks_market,
                    orderbook_payload=ks_orderbook,
                    receipt_timestamp=ks_orderbook_receipt,
                    source_contract_version="kalshi_trade_api_v1",
                    fee_rule=None,
                    fee_schedule_reference="series_fee_changes_captured_without_trade_fee_resolution",
                )
                pair_skew_ms = _utc_ms_between(pm_no_receipt, ks_orderbook_receipt)
                paired = PairedSnapshot(
                    mapping_id=mapping.mapping_id,
                    mapping_version=mapping.version,
                    mapping_digest=mapping.digest,
                    captured_at=utc_now_iso(),
                    pair_skew_ms=pair_skew_ms,
                    polymarket=polymarket_snapshot,
                    kalshi=kalshi_snapshot,
                    rejection_reason="missing_fee_data",
                )
                log.append_snapshot(paired.to_dict())
                log.append_rejection(
                    {
                        "mapping_id": mapping.mapping_id,
                        "reason": "missing_fee_data",
                        "detail": "dynamic match-time fee rule not resolved for both venues",
                    }
                )
            iterations += 1
            if args.interval_seconds <= 0:
                break
            time.sleep(args.interval_seconds)
    finally:
        transport.close()

    final_path = log.finalize({"iterations": iterations})
    print(str(final_path))
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    catalog = MappingCatalog.load(args.mapping_catalog) if args.mapping_catalog else None
    report = replay_run(
        args.run_dir,
        mapping_catalog=catalog,
        policy=QualityPolicy(
            max_pair_skew_ms=args.max_pair_skew_ms,
            max_quote_age_ms=args.max_quote_age_ms,
        ),
    )
    output = args.output or Path(args.run_dir) / "evidence_pack.json"
    path = write_evidence_pack(report, output)
    print(str(path))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify = subparsers.add_parser("verify-contracts")
    verify.add_argument("--contract-dir", default=str(DEFAULT_CONTRACT_DIR))
    verify.add_argument("--live", action="store_true")
    verify.add_argument("--polymarket-token-id")
    verify.add_argument("--kalshi-ticker")
    verify.add_argument("--kalshi-series-ticker")
    verify.set_defaults(func=cmd_verify_contracts)

    capture = subparsers.add_parser("capture")
    capture.add_argument("--config", default="config.yaml")
    capture.add_argument("--mapping-catalog", default="research_mappings/catalog.yaml")
    capture.add_argument("--contract-dir", default=str(DEFAULT_CONTRACT_DIR))
    capture.add_argument("--output-dir", default="data/research_runs")
    capture.add_argument("--run-id")
    capture.add_argument("--duration-hours", type=float, default=24.0)
    capture.add_argument("--interval-seconds", type=float, default=60.0)
    capture.set_defaults(func=cmd_capture)

    replay = subparsers.add_parser("replay")
    replay.add_argument("--run-dir", required=True)
    replay.add_argument("--mapping-catalog")
    replay.add_argument("--output")
    replay.add_argument("--max-pair-skew-ms", type=int, default=1000)
    replay.add_argument("--max-quote-age-ms", type=int, default=1000)
    replay.set_defaults(func=cmd_replay)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
