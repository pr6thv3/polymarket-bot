#!/usr/bin/env python3
"""Read-only Polymarket data-path reliability gate.

This tool measures whether the local/proxy/CLOB read path is reliable enough for
latency-sensitive strategies or slower reward research. It never places orders.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.client import ClobClient
from utils.helpers import load_config

REPORT_MD = Path("reports/data_path_reliability_report.md")
REPORT_JSON = Path("reports/data_path_reliability_report.json")


@dataclass(frozen=True)
class ReliabilityGates:
    latency_sensitive_pass: bool
    research_pass: bool
    simulator_results_reliable: bool
    reasons: list[str]


@dataclass(frozen=True)
class ReliabilityReport:
    generated_at: str
    endpoint_tested: str
    total_requests: int
    successful_requests: int
    failed_requests: int
    error_rate_pct: float
    average_latency_ms: float | None
    p50_latency_ms: float | None
    p95_latency_ms: float | None
    p99_latency_ms: float | None
    timeout_count: int
    retry_count: int
    consecutive_failure_max: int
    duration_minutes: float
    interval_seconds: float
    max_pages: int
    max_markets: int
    prior_blocker_reference: str
    gates: ReliabilityGates
    errors: list[str]


def percentile(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile with linear interpolation for small samples."""
    if not values:
        return None
    if pct <= 0:
        return min(values)
    if pct >= 100:
        return max(values)
    xs = sorted(values)
    pos = (len(xs) - 1) * pct / 100.0
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return xs[int(pos)]
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def evaluate_reliability_gate(error_rate_pct: float, p95_latency_ms: float | None, consecutive_failure_max: int) -> ReliabilityGates:
    reasons: list[str] = []
    latency_sensitive_pass = True
    research_pass = True

    if error_rate_pct >= 5.0:
        latency_sensitive_pass = False
        reasons.append(f"latency-sensitive error rate {error_rate_pct:.2f}% >= 5%")
    if p95_latency_ms is None:
        latency_sensitive_pass = False
        reasons.append("latency-sensitive p95 latency unavailable")
    elif p95_latency_ms >= 1000.0:
        latency_sensitive_pass = False
        reasons.append(f"latency-sensitive p95 latency {p95_latency_ms:.0f}ms >= 1000ms")
    if consecutive_failure_max >= 3:
        latency_sensitive_pass = False
        reasons.append(f"long consecutive failure streak: {consecutive_failure_max}")

    if error_rate_pct >= 20.0:
        research_pass = False
        reasons.append(f"reward research error rate {error_rate_pct:.2f}% >= 20%")

    simulator_results_reliable = research_pass
    return ReliabilityGates(
        latency_sensitive_pass=latency_sensitive_pass,
        research_pass=research_pass,
        simulator_results_reliable=simulator_results_reliable,
        reasons=reasons,
    )


def _err_text(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


async def run_reliability_probe(duration_minutes: float, interval_seconds: float, max_pages: int, max_markets: int) -> ReliabilityReport:
    client = ClobClient(load_config("config.yaml"))
    deadline = time.monotonic() + max(0.0, duration_minutes) * 60.0
    latencies_ms: list[float] = []
    errors: list[str] = []
    total = success = failed = timeout_count = 0
    consecutive = max_consecutive = 0
    endpoint = "CLOB get_markets + sampled get_orderbook (read-only)"

    async def measured(label: str, fn):
        nonlocal total, success, failed, timeout_count, consecutive, max_consecutive
        total += 1
        start = time.perf_counter()
        try:
            result = await fn()
        except TimeoutError as exc:
            timeout_count += 1
            failed += 1
            consecutive += 1
            max_consecutive = max(max_consecutive, consecutive)
            errors.append(f"{label}: {_err_text(exc)}")
            return None
        except Exception as exc:  # noqa: BLE001 - reliability probe must capture all failures
            if "timeout" in str(exc).lower():
                timeout_count += 1
            failed += 1
            consecutive += 1
            max_consecutive = max(max_consecutive, consecutive)
            errors.append(f"{label}: {_err_text(exc)}")
            return None
        else:
            latencies_ms.append((time.perf_counter() - start) * 1000.0)
            success += 1
            consecutive = 0
            return result

    first = True
    while first or time.monotonic() < deadline:
        first = False
        cursor = None
        markets_seen = 0
        for page in range(max_pages):
            data = await measured(f"get_markets page={page}", lambda cursor=cursor: client.get_markets(cursor))
            if not isinstance(data, dict):
                break
            for market in data.get("data", []):
                # Only probe order books for markets that advertise live CLOB books.
                # 404 "No orderbook exists" on non-book markets is market metadata,
                # not a proxy/data-path reliability failure.
                if not (market.get("accepting_orders") and market.get("enable_order_book") and not market.get("closed")):
                    continue
                tokens = market.get("tokens") or []
                if not tokens:
                    continue
                markets_seen += 1
                for token in tokens[:2]:
                    token_id = token.get("token_id")
                    if token_id:
                        await measured(f"get_orderbook token={str(token_id)[:12]}", lambda token_id=str(token_id): client.get_orderbook(token_id))
                if markets_seen >= max_markets:
                    break
            cursor = data.get("next_cursor")
            if not cursor or markets_seen >= max_markets:
                break
        remaining = deadline - time.monotonic()
        if remaining > 0 and interval_seconds > 0:
            await asyncio.sleep(min(interval_seconds, remaining))

    error_rate = (failed / total * 100.0) if total else 100.0
    avg = (sum(latencies_ms) / len(latencies_ms)) if latencies_ms else None
    gates = evaluate_reliability_gate(error_rate, percentile(latencies_ms, 95), max_consecutive)
    return ReliabilityReport(
        generated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        endpoint_tested=endpoint,
        total_requests=total,
        successful_requests=success,
        failed_requests=failed,
        error_rate_pct=error_rate,
        average_latency_ms=avg,
        p50_latency_ms=percentile(latencies_ms, 50),
        p95_latency_ms=percentile(latencies_ms, 95),
        p99_latency_ms=percentile(latencies_ms, 99),
        timeout_count=timeout_count,
        retry_count=0,
        consecutive_failure_max=max_consecutive,
        duration_minutes=duration_minutes,
        interval_seconds=interval_seconds,
        max_pages=max_pages,
        max_markets=max_markets,
        prior_blocker_reference="Previous collector: 161 errors / 346 iterations = 46.5% error rate.",
        gates=gates,
        errors=errors[-25:],
    )


def _fmt_ms(value: float | None) -> str:
    return "not available" if value is None else f"{value:.0f} ms"


def write_reports(report: ReliabilityReport, md_path: Path = REPORT_MD, json_path: Path = REPORT_JSON) -> None:
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(report)
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    gate_rows = [
        ["Latency-sensitive strategies", "PASS" if report.gates.latency_sensitive_pass else "FAIL"],
        ["Reward simulator/read-only research", "PASS" if report.gates.research_pass else "FAIL"],
        ["Simulator results reliable", "YES" if report.gates.simulator_results_reliable else "NO"],
    ]
    md = [
        "# Data-Path Reliability Report",
        "",
        f"Generated: `{report.generated_at}`",
        "",
        "This is read-only. It does not place, amend, cancel, or submit orders.",
        "",
        "## Metrics",
        "",
        "|Metric|Value|",
        "|---|---:|",
        f"|Endpoint tested|{report.endpoint_tested}|",
        f"|Total requests|{report.total_requests}|",
        f"|Successful requests|{report.successful_requests}|",
        f"|Failed requests|{report.failed_requests}|",
        f"|Error rate|{report.error_rate_pct:.2f}%|",
        f"|Average latency|{_fmt_ms(report.average_latency_ms)}|",
        f"|p50 latency|{_fmt_ms(report.p50_latency_ms)}|",
        f"|p95 latency|{_fmt_ms(report.p95_latency_ms)}|",
        f"|p99 latency|{_fmt_ms(report.p99_latency_ms)}|",
        f"|Timeout count|{report.timeout_count}|",
        f"|Retry count available|{report.retry_count}|",
        f"|Max consecutive failures|{report.consecutive_failure_max}|",
        "",
        "## Gate results",
        "",
        "|Gate|Result|",
        "|---|---|",
    ]
    md.extend(f"|{name}|{result}|" for name, result in gate_rows)
    md.extend([
        "",
        "## Prior blocker",
        "",
        report.prior_blocker_reference,
        "",
        "## Reasons",
        "",
        *(f"- {r}" for r in (report.gates.reasons or ["No gate failures."])),
        "",
        "## Recent errors",
        "",
        *(f"- `{e}`" for e in (report.errors or ["none"])),
        "",
    ])
    md_path.write_text("\n".join(md), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--duration-minutes", type=float, default=1.0)
    p.add_argument("--interval-seconds", type=float, default=10.0)
    p.add_argument("--max-pages", type=int, default=3)
    p.add_argument("--max-markets", type=int, default=10)
    return p.parse_args()


async def async_main() -> None:
    args = parse_args()
    report = await run_reliability_probe(args.duration_minutes, args.interval_seconds, args.max_pages, args.max_markets)
    write_reports(report)
    print(json.dumps(asdict(report), indent=2))


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
