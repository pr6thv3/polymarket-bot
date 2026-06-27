from tools.block0_decision_check import find_decision_issues, format_issues, main


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


def test_cli_returns_nonzero_for_incomplete_template(tmp_path, capsys):
    template = tmp_path / "block0.md"
    template.write_text("## Section\n\n- [ ] Missing input:\n", encoding="utf-8")

    exit_code = main(["--template", str(template)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Block 0 decision inputs incomplete" in captured.out
    assert "unchecked: Missing input:" in captured.out


def test_cli_returns_zero_for_complete_template(tmp_path, capsys):
    template = tmp_path / "block0.md"
    template.write_text("## Section\n\n- [x] Supplied input: value\n", encoding="utf-8")

    exit_code = main(["--template", str(template)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Block 0 decision inputs complete" in captured.out


def test_cli_section_filter_allows_incremental_preflight(tmp_path, capsys):
    template = tmp_path / "block0.md"
    template.write_text(
        "## Incomplete Section\n\n"
        "- [ ] Missing input:\n\n"
        "## Complete Section\n\n"
        "- [x] Supplied input: value\n",
        encoding="utf-8",
    )

    exit_code = main([
        "--template",
        str(template),
        "--section",
        "Complete Section",
    ])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Block 0 decision inputs complete" in captured.out

