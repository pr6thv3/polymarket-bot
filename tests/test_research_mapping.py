from pathlib import Path

import pytest

from research.mapping import MappingCatalog, MappingValidationError


def approved_mapping_yaml(extra: str = "") -> str:
    return f"""
version: 1
mappings:
  - mapping_id: france-world-cup-fixture
    version: 1
    status: approved
    polymarket:
      condition_id: "0xcondition"
      yes_token_id: "0xyes"
      no_token_id: "0xno"
    kalshi:
      event_ticker: "KX-FRANCE"
      market_ticker: "KX-FRANCE-26"
      series_ticker: "KXWC"
    canonical_proposition: "France wins the 2026 FIFA World Cup."
    yes_predicate: "France is the winner."
    resolution_source: "Venue rulebooks reviewed manually."
    cutoff_utc: "2026-07-20T00:00:00Z"
    timezone: "UTC"
    payout_convention: "Binary YES pays 1.00 if true, else 0.00."
    invalidation_behavior: "Reject if either venue changes or voids the contract."
    review_evidence:
      - "https://example.invalid/polymarket-rule"
      - "https://example.invalid/kalshi-rule"
    reviewer: "test"
    reviewed_at: "2026-06-25T13:10:38Z"
{extra}
"""


def test_catalog_loads_only_approved_mappings(tmp_path: Path):
    catalog_path = tmp_path / "catalog.yaml"
    catalog_path.write_text(
        """
version: 1
mappings:
  - mapping_id: candidate-only
    status: candidate
    canonical_proposition: "Candidate should not enter replay."
"""
        + approved_mapping_yaml().split("mappings:", 1)[1],
        encoding="utf-8",
    )

    catalog = MappingCatalog.load(catalog_path)

    assert len(catalog.mappings) == 1
    assert catalog.mappings[0].mapping_id == "france-world-cup-fixture"
    assert len(catalog.mappings[0].digest) == 64


def test_approved_mapping_requires_semantic_review_fields(tmp_path: Path):
    catalog_path = tmp_path / "bad.yaml"
    catalog_path.write_text(
        approved_mapping_yaml().replace("    resolution_source: \"Venue rulebooks reviewed manually.\"\n", ""),
        encoding="utf-8",
    )

    with pytest.raises(MappingValidationError, match="resolution_source"):
        MappingCatalog.load(catalog_path)


def test_duplicate_approved_mapping_ids_are_rejected(tmp_path: Path):
    catalog_path = tmp_path / "dupe.yaml"
    catalog_path.write_text(
        approved_mapping_yaml() + approved_mapping_yaml().split("mappings:", 1)[1],
        encoding="utf-8",
    )

    with pytest.raises(MappingValidationError, match="duplicate"):
        MappingCatalog.load(catalog_path)
