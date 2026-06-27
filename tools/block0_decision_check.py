#!/usr/bin/env python3
"""Validate that Block 0 human-owned decision inputs are complete.

This tool is intentionally dependency-free and read-only. It does not decide any
research methodology; it only fails closed when the manual Block 0 checklist
still has unresolved checkbox items.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

DEFAULT_TEMPLATE = Path("reports/block0_decision_inputs.md")
_CHECKBOX_RE = re.compile(r"^(?P<indent>\s*)- \[(?P<state>[ xX])\] (?P<label>.+?)\s*$")
_SECTION_RE = re.compile(r"^## (?P<section>.+?)\s*$")


@dataclass(frozen=True)
class DecisionIssue:
    """An unresolved or malformed Block 0 decision input."""

    line_number: int
    section: str
    label: str
    reason: str


def _selected_sections(raw: Iterable[str] | None) -> set[str] | None:
    if not raw:
        return None
    return {item.strip().lower() for item in raw if item.strip()}


def _has_missing_value(label: str) -> bool:
    """Return True when a checked item still has an empty value slot.

    A line such as ``Dataset source URL or local path:`` is not complete merely
    because the checkbox is checked. Parent/group labels such as ``Required
    columns and dtypes:`` may be checked without an inline value because their
    nested children carry the actual inputs.
    """
    if ":" not in label:
        return False
    before, after = label.split(":", 1)
    if not before.strip():
        return True
    if after.strip():
        return False
    parent_labels = {
        "required columns and dtypes",
    }
    return before.strip().lower() not in parent_labels


def find_decision_issues(
    template_text: str,
    *,
    sections: Iterable[str] | None = None,
    require_inline_values: bool = True,
) -> list[DecisionIssue]:
    """Find unresolved Block 0 decision inputs in markdown text.

    Args:
        template_text: Markdown checklist text.
        sections: Optional section names to validate. Matching is
            case-insensitive against ``##`` headings.
        require_inline_values: If True, checked checkbox lines ending in an
            empty ``:`` value slot are still considered incomplete.

    Returns:
        Decision issues sorted by file line order.
    """
    selected = _selected_sections(sections)
    current_section = "preamble"
    issues: list[DecisionIssue] = []

    for line_number, line in enumerate(template_text.splitlines(), start=1):
        section_match = _SECTION_RE.match(line)
        if section_match:
            current_section = section_match.group("section").strip()
            continue

        checkbox = _CHECKBOX_RE.match(line)
        if checkbox is None:
            continue
        if selected is not None and current_section.lower() not in selected:
            continue

        label = checkbox.group("label").strip()
        state = checkbox.group("state")
        if state == " ":
            issues.append(
                DecisionIssue(
                    line_number=line_number,
                    section=current_section,
                    label=label,
                    reason="unchecked",
                )
            )
        elif require_inline_values and _has_missing_value(label):
            issues.append(
                DecisionIssue(
                    line_number=line_number,
                    section=current_section,
                    label=label,
                    reason="missing_value",
                )
            )

    return issues


def format_issues(issues: list[DecisionIssue], *, path: Path) -> str:
    """Render decision issues for CLI output."""
    if not issues:
        return f"Block 0 decision inputs complete: {path}"
    lines = [f"Block 0 decision inputs incomplete: {path}"]
    for issue in issues:
        lines.append(
            f"{issue.line_number}: [{issue.section}] {issue.reason}: {issue.label}"
        )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument(
        "--section",
        action="append",
        help="Optional exact ## section title to validate; may be repeated.",
    )
    parser.add_argument(
        "--allow-empty-checked-values",
        action="store_true",
        help="Treat checked items with empty colon value slots as complete.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    template = args.template
    text = template.read_text(encoding="utf-8")
    issues = find_decision_issues(
        text,
        sections=args.section,
        require_inline_values=not args.allow_empty_checked_values,
    )
    print(format_issues(issues, path=template))
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
