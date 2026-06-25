"""Versioned source-contract loading and deterministic schema validation."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTRACT_DIR = PROJECT_ROOT / "research_contracts"


class SourceContractError(ValueError):
    """Raised when a live or fixture payload violates a pinned contract."""


def load_contract(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not payload.get("contract_id"):
        raise SourceContractError(f"invalid source contract: {path}")
    return payload


def load_contracts(directory: str | Path = DEFAULT_CONTRACT_DIR) -> dict[str, dict[str, Any]]:
    root = Path(directory)
    contracts: dict[str, dict[str, Any]] = {}
    for path in sorted(root.glob("*_v*.json")):
        contract = load_contract(path)
        contracts[contract["contract_id"]] = contract
    if not contracts:
        raise SourceContractError(f"no source contracts found in {root}")
    return contracts


def _lookup(payload: Mapping[str, Any], dotted_path: str) -> Any:
    current: Any = payload
    for part in dotted_path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            raise SourceContractError(f"required field missing: {dotted_path}")
        current = current[part]
    return current


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "object":
        return isinstance(value, Mapping)
    if expected == "array":
        return isinstance(value, list)
    if expected == "null":
        return value is None
    raise SourceContractError(f"unsupported source-contract type: {expected}")


def validate_payload(contract: Mapping[str, Any], endpoint: str, payload: Mapping[str, Any]) -> None:
    """Validate only the pinned fields consumed by an adapter."""
    endpoints = contract.get("endpoints", {})
    rule = endpoints.get(endpoint) if isinstance(endpoints, Mapping) else None
    if not isinstance(rule, Mapping):
        raise SourceContractError(f"endpoint {endpoint!r} is not declared")

    for field in rule.get("required_fields", []):
        if not isinstance(field, Mapping):
            raise SourceContractError("required_fields entries must be objects")
        value = _lookup(payload, str(field["path"]))
        expected = field.get("types", [])
        if not isinstance(expected, list) or not expected:
            raise SourceContractError(f"field {field['path']} has no allowed types")
        if not any(_matches_type(value, str(kind)) for kind in expected):
            actual = type(value).__name__
            raise SourceContractError(
                f"field {field['path']} has type {actual}; expected one of {expected}"
            )


def validate_contract_fixtures(
    directory: str | Path = DEFAULT_CONTRACT_DIR,
) -> list[str]:
    """Validate the sanitized fixtures committed with every source contract."""
    root = Path(directory)
    validated: list[str] = []
    for contract in load_contracts(root).values():
        for endpoint, rule in contract["endpoints"].items():
            fixture = root / str(rule["fixture"])
            payload = json.loads(fixture.read_text(encoding="utf-8"))
            validate_payload(contract, endpoint, payload)
            validated.append(f"{contract['contract_id']}:{endpoint}")
    return validated
