from tools.block0_decision_check import find_decision_issues, format_issues


def test_unchecked_decision_inputs_fail_closed():
    text = """# Template

## 1. Fill-probability calibration spec for Task 3.2

- [ ] Dataset source URL or local path:
- [x] Required columns and dtypes:
  - [x] market identifier: market_id
"""

    issues = find_decision_issues(text)

    assert len(issues) == 1
    assert issues[0].reason == "unchecked"
    assert issues[0].label == "Dataset source URL or local path:"


def test_checked_empty_value_slots_are_still_incomplete():
    text = """# Template

## 1. Fill-probability calibration spec for Task 3.2

- [x] Dataset source URL or local path:
- [x] Required columns and dtypes:
  - [x] market identifier: market_id
"""

    issues = find_decision_issues(text)

    assert len(issues) == 1
    assert issues[0].reason == "missing_value"
    assert issues[0].label == "Dataset source URL or local path:"


def test_completed_decision_inputs_pass():
    text = """# Template

## 1. Fill-probability calibration spec for Task 3.2

- [x] Dataset source URL or local path: data/fills.csv
- [x] Dataset file format: csv
- [x] Required columns and dtypes:
  - [x] market identifier: string
  - [x] timestamp / event time: unix_ms
"""

    assert find_decision_issues(text) == []


def test_section_filter_limits_validation_scope():
    text = """# Template

## 1. Fill-probability calibration spec for Task 3.2

- [ ] Dataset source URL or local path:

## 2. Binary-outcome market-making replacement theory for Task 6.1

- [x] Chosen theory/framework: supplied externally
"""

    issues = find_decision_issues(
        text,
        sections=("2. Binary-outcome market-making replacement theory for Task 6.1",),
    )

    assert issues == []


def test_format_issues_includes_path_line_section_and_reason(tmp_path):
    template = tmp_path / "block0.md"
    issues = find_decision_issues("## Section\n\n- [ ] Missing input:")

    rendered = format_issues(issues, path=template)

    assert "Block 0 decision inputs incomplete" in rendered
    assert "3: [Section] unchecked: Missing input:" in rendered
