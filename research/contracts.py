"""Versioned source-contract loading and deterministic schema validation."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
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


def _lookup(payload: Any, dotted_path: str) -> Any:
    if dotted_path == "$":
        return payload
    current: Any = payload
    for part in dotted_path.split("."):
        if part == "$":
            continue
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


def _expected_types(field: Mapping[str, Any]) -> list[str]:
    expected = field.get("types", [])
    if not isinstance(expected, list) or not expected:
        raise SourceContractError(f"field {field.get('path')} has no allowed types")
    return [str(kind) for kind in expected]


def _validate_field(payload: Any, field: Mapping[str, Any], *, prefix: str = "") -> None:
    path = str(field["path"])
    value = _lookup(payload, path)
    expected = _expected_types(field)
    if not any(_matches_type(value, kind) for kind in expected):
        actual = type(value).__name__
        raise SourceContractError(
            f"field {prefix}{path} has type {actual}; expected one of {expected}"
        )


def _validate_alternative_group(
    payload: Any,
    group: Mapping[str, Any],
    *,
    prefix: str = "",
) -> None:
    alternatives = group.get("alternatives", [])
    if not isinstance(alternatives, list) or not alternatives:
        raise SourceContractError("alternative group has no alternatives")

    errors: list[str] = []
    for alternative in alternatives:
        fields = alternative
        if isinstance(alternative, Mapping):
            fields = alternative.get("fields", [])
        if not isinstance(fields, list) or not fields:
            raise SourceContractError("alternative entries must be non-empty field lists")
        try:
            for field in fields:
                if not isinstance(field, Mapping):
                    raise SourceContractError("alternative fields must be objects")
                _validate_field(payload, field, prefix=prefix)
        except SourceContractError as exc:
            errors.append(str(exc))
        else:
            return

    name = str(group.get("name") or "required alternative")
    raise SourceContractError(
        f"{prefix}{name} did not match any required alternative: " + " | ".join(errors)
    )


def _find_item_array(payload: Any, paths: Sequence[str]) -> tuple[list[Any], str]:
    errors: list[str] = []
    for path in paths:
        if path == "$":
            if isinstance(payload, list):
                return payload, "$"
            errors.append("root payload is not an array")
            continue
        try:
            value = _lookup(payload, path)
        except SourceContractError as exc:
            errors.append(str(exc))
            continue
        if isinstance(value, list):
            return value, path
        errors.append(f"field {path} has type {type(value).__name__}; expected array")
    raise SourceContractError("no declared item array matched payload: " + " | ".join(errors))


def validate_payload(contract: Mapping[str, Any], endpoint: str, payload: Any) -> None:
    """Validate only the pinned fields consumed by an adapter."""
    endpoints = contract.get("endpoints", {})
    rule = endpoints.get(endpoint) if isinstance(endpoints, Mapping) else None
    if not isinstance(rule, Mapping):
        raise SourceContractError(f"endpoint {endpoint!r} is not declared")

    root_types = rule.get("root_types", [])
    if root_types:
        if not isinstance(root_types, list):
            raise SourceContractError("root_types must be a list")
        if not any(_matches_type(payload, str(kind)) for kind in root_types):
            actual = type(payload).__name__
            raise SourceContractError(
                f"root payload has type {actual}; expected one of {root_types}"
            )

    for field in rule.get("required_fields", []):
        if not isinstance(field, Mapping):
            raise SourceContractError("required_fields entries must be objects")
        _validate_field(payload, field)

    for group in rule.get("alternative_groups", []):
        if not isinstance(group, Mapping):
            raise SourceContractError("alternative_groups entries must be objects")
        _validate_alternative_group(payload, group)

    item_fields = rule.get("array_item_required_fields", [])
    item_groups = rule.get("array_item_alternative_groups", [])
    if item_fields or item_groups:
        paths = rule.get("item_array_paths", ["$"])
        if not isinstance(paths, list) or not paths:
            raise SourceContractError("item_array_paths must be a non-empty list")
        items, array_path = _find_item_array(payload, [str(path) for path in paths])
        for index, item in enumerate(items):
            if not isinstance(item, Mapping):
                raise SourceContractError(
                    f"field {array_path}[{index}] has type {type(item).__name__}; expected object"
                )
            prefix = f"{array_path}[{index}]."
            for field in item_fields:
                if not isinstance(field, Mapping):
                    raise SourceContractError("array_item_required_fields entries must be objects")
                _validate_field(item, field, prefix=prefix)
            for group in item_groups:
                if not isinstance(group, Mapping):
                    raise SourceContractError("array_item_alternative_groups entries must be objects")
                _validate_alternative_group(item, group, prefix=prefix)


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
