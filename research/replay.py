"""Deterministic replay and executable-route economics for paired snapshots."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

from research.event_log import ResearchRunLog
from research.mapping import MappingCatalog
from research.quotes import (
    ONE,
    ZERO,
    FeeRule,
    OutcomeQuote,
    PairedSnapshot,
    decimal_to_json,
)


@dataclass(frozen=True)
class QualityPolicy:
    max_pair_skew_ms: int = 1000
    max_quote_age_ms: int = 1000


@dataclass(frozen=True)
class RouteEvaluation:
    mapping_id: str
    route_id: str
    yes_venue: str
    no_venue: str
    quantity: Decimal | None
    yes_price: Decimal | None
    no_price: Decimal | None
    yes_fee: Decimal | None
    no_fee: Decimal | None
    gross_cost: Decimal | None
    capital_lockup: Decimal | None
    guaranteed_payout: Decimal | None
    edge: Decimal | None
    rejected_reason: str | None

    @property
    def accepted(self) -> bool:
        return self.rejected_reason is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mapping_id": self.mapping_id,
            "route_id": self.route_id,
            "yes_venue": self.yes_venue,
            "no_venue": self.no_venue,
            "quantity": decimal_to_json(self.quantity),
            "yes_price": decimal_to_json(self.yes_price),
            "no_price": decimal_to_json(self.no_price),
            "yes_fee": decimal_to_json(self.yes_fee),
            "no_fee": decimal_to_json(self.no_fee),
            "gross_cost": decimal_to_json(self.gross_cost),
            "capital_lockup": decimal_to_json(self.capital_lockup),
            "guaranteed_payout": decimal_to_json(self.guaranteed_payout),
            "edge": decimal_to_json(self.edge),
            "edge_per_contract": decimal_to_json(
                self.edge / self.quantity
                if self.edge is not None and self.quantity and self.quantity > ZERO
                else None
            ),
            "rejected_reason": self.rejected_reason,
        }


def _rejected_route(
    *,
    mapping_id: str,
    route_id: str,
    yes_venue: str,
    no_venue: str,
    reason: str,
    yes_quote: OutcomeQuote | None = None,
    no_quote: OutcomeQuote | None = None,
) -> RouteEvaluation:
    return RouteEvaluation(
        mapping_id=mapping_id,
        route_id=route_id,
        yes_venue=yes_venue,
        no_venue=no_venue,
        quantity=None,
        yes_price=yes_quote.ask_price if yes_quote else None,
        no_price=no_quote.ask_price if no_quote else None,
        yes_fee=None,
        no_fee=None,
        gross_cost=None,
        capital_lockup=None,
        guaranteed_payout=None,
        edge=None,
        rejected_reason=reason,
    )


def evaluate_complement_route(
    *,
    mapping_id: str,
    route_id: str,
    yes_venue: str,
    yes_quote: OutcomeQuote,
    yes_fee_rule: FeeRule | None,
    yes_min_order_size: Decimal | None,
    no_venue: str,
    no_quote: OutcomeQuote,
    no_fee_rule: FeeRule | None,
    no_min_order_size: Decimal | None,
) -> RouteEvaluation:
    """Evaluate buying YES on one venue and NO on the other from executable asks."""
    if yes_quote.ask_price is None or no_quote.ask_price is None:
        return _rejected_route(
            mapping_id=mapping_id,
            route_id=route_id,
            yes_venue=yes_venue,
            no_venue=no_venue,
            reason="missing_ask",
            yes_quote=yes_quote,
            no_quote=no_quote,
        )
    if (
        yes_quote.missing_depth
        or no_quote.missing_depth
        or yes_quote.ask_size is None
        or no_quote.ask_size is None
        or yes_quote.ask_size <= ZERO
        or no_quote.ask_size <= ZERO
    ):
        return _rejected_route(
            mapping_id=mapping_id,
            route_id=route_id,
            yes_venue=yes_venue,
            no_venue=no_venue,
            reason="missing_depth",
            yes_quote=yes_quote,
            no_quote=no_quote,
        )
    if yes_fee_rule is None or no_fee_rule is None or not yes_fee_rule.verified or not no_fee_rule.verified:
        return _rejected_route(
            mapping_id=mapping_id,
            route_id=route_id,
            yes_venue=yes_venue,
            no_venue=no_venue,
            reason="missing_fee_data",
            yes_quote=yes_quote,
            no_quote=no_quote,
        )

    quantity = min(yes_quote.ask_size, no_quote.ask_size)
    minimum = max(yes_min_order_size or ZERO, no_min_order_size or ZERO)
    if quantity < minimum:
        return _rejected_route(
            mapping_id=mapping_id,
            route_id=route_id,
            yes_venue=yes_venue,
            no_venue=no_venue,
            reason="below_venue_minimum",
            yes_quote=yes_quote,
            no_quote=no_quote,
        )

    yes_fee = yes_fee_rule.cost(quantity, yes_quote.ask_price)
    no_fee = no_fee_rule.cost(quantity, no_quote.ask_price)
    gross_cost = (quantity * yes_quote.ask_price) + (quantity * no_quote.ask_price)
    capital_lockup = gross_cost + yes_fee + no_fee
    guaranteed_payout = quantity * ONE
    edge = guaranteed_payout - capital_lockup
    rejected_reason = "non_positive_edge" if edge <= ZERO else None
    return RouteEvaluation(
        mapping_id=mapping_id,
        route_id=route_id,
        yes_venue=yes_venue,
        no_venue=no_venue,
        quantity=quantity,
        yes_price=yes_quote.ask_price,
        no_price=no_quote.ask_price,
        yes_fee=yes_fee,
        no_fee=no_fee,
        gross_cost=gross_cost,
        capital_lockup=capital_lockup,
        guaranteed_payout=guaranteed_payout,
        edge=edge,
        rejected_reason=rejected_reason,
    )


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    if raw.isdigit():
        number = int(raw)
        if number > 10_000_000_000:
            number = number / 1000
        return datetime.fromtimestamp(number, tz=timezone.utc)
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _milliseconds_between(first: datetime | None, second: datetime | None) -> int | None:
    if first is None or second is None:
        return None
    return int(abs((second - first).total_seconds() * 1000))


def quality_rejections(snapshot: PairedSnapshot, policy: QualityPolicy) -> list[str]:
    reasons: list[str] = []
    if snapshot.rejection_reason:
        reasons.append(snapshot.rejection_reason)
    if snapshot.pair_skew_ms is None:
        pm_receipt = _parse_timestamp(snapshot.polymarket.receipt_timestamp)
        ks_receipt = _parse_timestamp(snapshot.kalshi.receipt_timestamp)
        skew = _milliseconds_between(pm_receipt, ks_receipt)
    else:
        skew = snapshot.pair_skew_ms
    if skew is None:
        reasons.append("missing_pair_skew")
    elif skew > policy.max_pair_skew_ms:
        reasons.append("excessive_pair_skew")

    for venue in (snapshot.polymarket, snapshot.kalshi):
        source = _parse_timestamp(venue.source_timestamp)
        receipt = _parse_timestamp(venue.receipt_timestamp)
        age = _milliseconds_between(source, receipt)
        if age is None:
            reasons.append(f"{venue.venue}_missing_quote_age")
        elif age > policy.max_quote_age_ms:
            reasons.append(f"{venue.venue}_stale_quote")
    return reasons


def evaluate_snapshot(snapshot: PairedSnapshot, policy: QualityPolicy | None = None) -> list[RouteEvaluation]:
    policy = policy or QualityPolicy()
    quality = quality_rejections(snapshot, policy)
    if quality:
        reason = ",".join(sorted(set(quality)))
        return [
            _rejected_route(
                mapping_id=snapshot.mapping_id,
                route_id="polymarket_yes_kalshi_no",
                yes_venue="polymarket",
                no_venue="kalshi",
                reason=reason,
                yes_quote=snapshot.polymarket.yes,
                no_quote=snapshot.kalshi.no,
            ),
            _rejected_route(
                mapping_id=snapshot.mapping_id,
                route_id="kalshi_yes_polymarket_no",
                yes_venue="kalshi",
                no_venue="polymarket",
                reason=reason,
                yes_quote=snapshot.kalshi.yes,
                no_quote=snapshot.polymarket.no,
            ),
        ]

    return [
        evaluate_complement_route(
            mapping_id=snapshot.mapping_id,
            route_id="polymarket_yes_kalshi_no",
            yes_venue="polymarket",
            yes_quote=snapshot.polymarket.yes,
            yes_fee_rule=snapshot.polymarket.fee_rule,
            yes_min_order_size=snapshot.polymarket.min_order_size,
            no_venue="kalshi",
            no_quote=snapshot.kalshi.no,
            no_fee_rule=snapshot.kalshi.fee_rule,
            no_min_order_size=snapshot.kalshi.min_order_size,
        ),
        evaluate_complement_route(
            mapping_id=snapshot.mapping_id,
            route_id="kalshi_yes_polymarket_no",
            yes_venue="kalshi",
            yes_quote=snapshot.kalshi.yes,
            yes_fee_rule=snapshot.kalshi.fee_rule,
            yes_min_order_size=snapshot.kalshi.min_order_size,
            no_venue="polymarket",
            no_quote=snapshot.polymarket.no,
            no_fee_rule=snapshot.polymarket.fee_rule,
            no_min_order_size=snapshot.polymarket.min_order_size,
        ),
    ]


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(json.loads(line))
    return records


def _clustered_lower_bound(edges_by_mapping: dict[str, list[float]]) -> float | None:
    if len(edges_by_mapping) < 2:
        return None
    cluster_means = [mean(values) for values in edges_by_mapping.values() if values]
    if len(cluster_means) < 2:
        return None
    return mean(cluster_means) - 1.96 * (pstdev(cluster_means) / math.sqrt(len(cluster_means)))


def replay_run(
    run_dir: str | Path,
    *,
    mapping_catalog: MappingCatalog | None = None,
    policy: QualityPolicy | None = None,
) -> dict[str, Any]:
    run_path = Path(run_dir)
    policy = policy or QualityPolicy()
    approved = {mapping.mapping_id: mapping for mapping in mapping_catalog.mappings} if mapping_catalog else None
    snapshot_records = _load_jsonl(run_path / ResearchRunLog.SNAPSHOT_FILE)
    rejection_records = _load_jsonl(run_path / ResearchRunLog.REJECTION_FILE)

    route_evaluations: list[RouteEvaluation] = []
    manifest_rejections: list[dict[str, Any]] = []
    for record in snapshot_records:
        snapshot = PairedSnapshot.from_dict(record)
        if approved is not None and snapshot.mapping_id not in approved:
            manifest_rejections.append(
                {"mapping_id": snapshot.mapping_id, "reason": "mapping_not_approved"}
            )
            continue
        route_evaluations.extend(evaluate_snapshot(snapshot, policy))

    accepted = [route for route in route_evaluations if route.accepted]
    rejected = [route for route in route_evaluations if not route.accepted]
    edges_by_mapping: dict[str, list[float]] = defaultdict(list)
    for route in accepted:
        if route.edge is not None:
            edges_by_mapping[route.mapping_id].append(float(route.edge))

    accepted_edges = [float(route.edge) for route in accepted if route.edge is not None]
    rejection_counts = Counter(route.rejected_reason for route in rejected)
    rejection_counts.update(item.get("reason") for item in manifest_rejections)
    rejection_counts.update(item.get("reason") for item in rejection_records)

    by_mapping = Counter(record.get("mapping_id") for record in snapshot_records)
    total_snapshots = len(snapshot_records)
    concentration = {
        str(mapping_id): count / total_snapshots
        for mapping_id, count in by_mapping.items()
        if mapping_id is not None and total_snapshots
    }

    return {
        "run_dir": str(run_path),
        "policy": {
            "max_pair_skew_ms": policy.max_pair_skew_ms,
            "max_quote_age_ms": policy.max_quote_age_ms,
        },
        "snapshot_count": total_snapshots,
        "route_evaluation_count": len(route_evaluations),
        "accepted_route_count": len(accepted),
        "rejected_route_count": len(rejected) + len(manifest_rejections) + len(rejection_records),
        "rejection_reasons": dict(sorted((str(key), value) for key, value in rejection_counts.items() if key)),
        "executable_edge_distribution": {
            "count": len(accepted_edges),
            "min": min(accepted_edges) if accepted_edges else None,
            "mean": mean(accepted_edges) if accepted_edges else None,
            "max": max(accepted_edges) if accepted_edges else None,
            "mapping_clustered_95_lower_bound": _clustered_lower_bound(edges_by_mapping),
        },
        "concentration_by_mapping": concentration,
        "rebates_and_liquidity_programs": "excluded_zero_credit",
        "route_evaluations": [route.to_dict() for route in route_evaluations],
    }


def write_evidence_pack(report: dict[str, Any], output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
