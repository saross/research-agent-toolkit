"""
Unit tests for the loop helper (scripts/loop_tools.py).

The closed-loop commands decide PASS or FAIL from the counts this helper
prints, so a miscount is a wrong verdict. The earlier shell version counted
nothing when the verifier wrote its JSON with a space after the colon, and a
run with failed claims would have been reported as a pass. These tests pin
the counting against spacing, letter case, and malformed lines, and the
extraction against indentation and missing blocks.
"""

import json
import sys
from pathlib import Path

import pytest

# The helper lives in the plugin's scripts folder.
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import loop_tools  # noqa: E402

DRAFT = """# Report

<!-- BEGIN claims.jsonl -->
```jsonl
{"claim_id":"10.1-a-year","value":2024}
{"claim_id":"10.1-a-title","value":"T"}
```
<!-- END claims.jsonl -->

<!-- BEGIN corrections.jsonl -->
```jsonl
{"claim_id":"10.1-a-year","status":"pass"}
```
<!-- END corrections.jsonl -->
"""


def verdict(claim_id: str, status: str, spaced: bool = False) -> str:
    """Return one verdict line, with or without spaces after separators."""
    record = {"claim_id": claim_id, "status": status}
    return json.dumps(record) if spaced else json.dumps(record, separators=(",", ":"))


# ---------------------------------------------------------------------------
# extract
# ---------------------------------------------------------------------------


def test_extract_returns_only_the_named_block() -> None:
    assert loop_tools.extract_block(DRAFT, "claims.jsonl") == [
        '{"claim_id":"10.1-a-year","value":2024}',
        '{"claim_id":"10.1-a-title","value":"T"}',
    ]
    assert len(loop_tools.extract_block(DRAFT, "corrections.jsonl")) == 1


def test_extract_ignores_indentation_on_every_line() -> None:
    """Agent output is sometimes relayed with each line indented."""
    indented = "".join(f"  {line}\n" for line in DRAFT.splitlines())
    expected = loop_tools.extract_block(DRAFT, "claims.jsonl")
    assert loop_tools.extract_block(indented, "claims.jsonl") == expected


@pytest.mark.parametrize(
    "text",
    [
        "no markers here",
        "<!-- BEGIN claims.jsonl -->\nno fence\n<!-- END claims.jsonl -->",
        "<!-- BEGIN claims.jsonl -->\n```jsonl\n```\n<!-- END claims.jsonl -->",
        "```jsonl\n{}\n```\n<!-- BEGIN claims.jsonl -->\n<!-- END claims.jsonl -->",
    ],
)
def test_extract_finds_nothing_without_a_filled_block(text: str) -> None:
    assert loop_tools.extract_block(text, "claims.jsonl") == []


def test_extract_command_writes_the_file_and_reports_a_missing_block(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source, target = tmp_path / "draft.md", tmp_path / "claims.jsonl"
    source.write_text(DRAFT)
    argv = ["loop_tools.py", "extract", str(source), "claims.jsonl", str(target)]
    assert loop_tools.main(argv) == 0
    assert len(target.read_text().splitlines()) == 2

    argv[3] = "absent.jsonl"
    assert loop_tools.main(argv) == 1
    assert target.read_text() == ""
    assert "no absent.jsonl block" in capsys.readouterr().err


def test_arguments_with_shell_characters_are_plain_text(tmp_path: Path) -> None:
    """The marker and paths are data: nothing in them is run or expanded."""
    source = tmp_path / "draft $(touch x).md"
    source.write_text(DRAFT)
    target = tmp_path / "out.jsonl"
    argv = ["loop_tools.py", "extract", str(source), "claims.jsonl", str(target)]
    assert loop_tools.main(argv) == 0
    assert not (tmp_path / "x").exists() and not Path("x").exists()


# ---------------------------------------------------------------------------
# count
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spaced", [False, True])
def test_count_does_not_depend_on_json_spacing(spaced: bool) -> None:
    """The defect this helper replaces: `"status": "pass"` counted as nothing."""
    lines = [
        verdict("a-year", "pass", spaced), verdict("a-title", "fail", spaced),
        verdict("b-year", "partial", spaced), verdict("b-title", "unverifiable", spaced),
    ]
    result = loop_tools.count_verdicts("\n".join(lines) + "\n")
    assert (result["PASS_CT"], result["FAIL_CT"], result["PARTIAL_CT"], result["UNVER_CT"]) == (
        1, 1, 1, 1,
    )
    assert result["TOTAL_CT"] == 4 and result["INVALID_CT"] == 0
    assert result["FAIL_SET"] == "a-title"


def test_count_keeps_the_legacy_placeholder_out_of_unverifiable() -> None:
    text = verdict("_legacy", "unverifiable") + "\n" + verdict("a-year", "unverifiable") + "\n"
    result = loop_tools.count_verdicts(text)
    assert (result["LEGACY_CT"], result["UNVER_CT"], result["TOTAL_CT"]) == (1, 1, 2)


def test_count_recognises_documentation_defects_and_letter_case() -> None:
    text = verdict("a-licence", "documentation_defect") + "\n" + verdict("a-url", "FAIL") + "\n"
    result = loop_tools.count_verdicts(text)
    assert (result["DOCDEF_CT"], result["FAIL_CT"], result["FAIL_SET"]) == (1, 1, "a-url")


@pytest.mark.parametrize(
    "line",
    ["not json", "[1, 2]", "{}", '{"status": "fail"}', '{"claim_id": "a", "status": "passed"}',
     '{"claim_id": "a", "status": null}', '{"claim_id": "a-title", "status": "fail"'],
)
def test_a_line_that_is_not_a_verdict_is_counted_as_invalid_never_dropped(line: str) -> None:
    result = loop_tools.count_verdicts(verdict("a-year", "pass") + "\n" + line + "\n")
    assert result["INVALID_CT"] == 1 and result["PASS_CT"] == 1 and result["TOTAL_CT"] == 2


def test_the_counts_always_add_up_to_the_total() -> None:
    lines = [verdict(f"c{i}", s) for i, s in enumerate(loop_tools.STATUSES * 3)]
    lines += ["junk", verdict("_legacy", "unverifiable")]
    result = loop_tools.count_verdicts("\n\n".join(lines))
    parts = sum(v for k, v in result.items() if k.endswith("_CT") and k != "TOTAL_CT")
    assert parts == result["TOTAL_CT"] == 17


def test_the_failed_set_is_sorted_and_free_of_repeats() -> None:
    text = "\n".join(verdict(c, "fail") for c in ("b-year", "a-year", "b-year"))
    assert loop_tools.count_verdicts(text)["FAIL_SET"] == "a-year b-year"


def test_count_command_prints_the_values_and_fails_on_invalid_or_empty_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "corrections.jsonl"
    path.write_text(verdict("a-year", "pass", spaced=True) + "\n")
    assert loop_tools.main(["loop_tools.py", "count", str(path)]) == 0
    out = capsys.readouterr().out
    assert "PASS_CT=1\n" in out and "TOTAL_CT=1\n" in out and "FAIL_SET=\n" in out

    path.write_text(verdict("a-year", "pass") + "\nnot json\n")
    assert loop_tools.main(["loop_tools.py", "count", str(path)]) == 1
    assert "INVALID_CT=1\n" in capsys.readouterr().out

    path.write_text("")
    assert loop_tools.main(["loop_tools.py", "count", str(path)]) == 1
    assert loop_tools.main(["loop_tools.py", "count", str(tmp_path / "absent")]) == 1
    assert loop_tools.main(["loop_tools.py"]) == 2
