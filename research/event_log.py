"""Append-only research run log with deterministic record hashes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research.adapters import canonical_payload_hash


class ResearchLogError(RuntimeError):
    """Raised when a research log cannot preserve append-only semantics."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def record_hash(record: dict[str, Any]) -> str:
    clean = {key: value for key, value in record.items() if key != "record_hash"}
    return canonical_payload_hash(clean)


@dataclass(frozen=True)
class AppendResult:
    path: Path
    record_hash: str
    appended: bool


class ResearchRunLog:
    """JSONL append-only files plus run manifests.

    Exact duplicate records are skipped so interrupted captures can resume
    without double-counting previously flushed rows.
    """

    RAW_FILE = "raw_payloads.jsonl"
    SNAPSHOT_FILE = "paired_snapshots.jsonl"
    REJECTION_FILE = "rejections.jsonl"

    def __init__(
        self,
        root: str | Path,
        run_id: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.root = Path(root)
        self.run_id = run_id
        self.run_dir = self.root / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._hashes: dict[str, set[str]] = {}
        for name in (self.RAW_FILE, self.SNAPSHOT_FILE, self.REJECTION_FILE):
            self._hashes[name] = self._load_hashes(name)
        manifest = self.run_dir / "manifest.json"
        if not manifest.exists():
            manifest.write_text(
                json.dumps(
                    {
                        "run_id": run_id,
                        "created_at": utc_now_iso(),
                        "metadata": metadata or {},
                        "files": {
                            "raw_payloads": self.RAW_FILE,
                            "paired_snapshots": self.SNAPSHOT_FILE,
                            "rejections": self.REJECTION_FILE,
                        },
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

    def _load_hashes(self, name: str) -> set[str]:
        path = self.run_dir / name
        if not path.exists():
            return set()
        hashes: set[str] = set()
        with path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ResearchLogError(f"invalid JSONL {path}:{line_no}") from exc
                value = payload.get("record_hash")
                if isinstance(value, str):
                    hashes.add(value)
        return hashes

    def append(self, name: str, record: dict[str, Any]) -> AppendResult:
        if name not in self._hashes:
            raise ResearchLogError(f"unknown research log file: {name}")
        path = self.run_dir / name
        digest = record_hash(record)
        if digest in self._hashes[name]:
            return AppendResult(path=path, record_hash=digest, appended=False)
        payload = dict(record)
        payload["record_hash"] = digest
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
        self._hashes[name].add(digest)
        return AppendResult(path=path, record_hash=digest, appended=True)

    def append_raw_payload(
        self,
        *,
        venue: str,
        endpoint: str,
        payload: dict[str, Any],
        receipt_timestamp: str,
        source_contract_version: str,
    ) -> AppendResult:
        return self.append(
            self.RAW_FILE,
            {
                "record_type": "raw_payload",
                "venue": venue,
                "endpoint": endpoint,
                "receipt_timestamp": receipt_timestamp,
                "source_contract_version": source_contract_version,
                "payload_hash": canonical_payload_hash(payload),
                "payload": payload,
            },
        )

    def append_snapshot(self, snapshot: dict[str, Any]) -> AppendResult:
        return self.append(self.SNAPSHOT_FILE, snapshot)

    def append_rejection(self, rejection: dict[str, Any]) -> AppendResult:
        return self.append(
            self.REJECTION_FILE,
            {
                "record_type": "rejection",
                "recorded_at": utc_now_iso(),
                **rejection,
            },
        )

    def finalize(self, summary: dict[str, Any]) -> Path:
        path = self.run_dir / "manifest.final.json"
        path.write_text(
            json.dumps(
                {
                    "run_id": self.run_id,
                    "finalized_at": utc_now_iso(),
                    "summary": summary,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return path
