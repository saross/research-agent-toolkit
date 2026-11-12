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


B, E = "<!-- BEGIN claims.jsonl -->", "<!-- END claims.jsonl -->"
LINE = '{"claim_id":"a-year","status":"pass"}'


@pytest.mark.parametrize(
    "text",
    [
        "no markers here",
        f"{B}\nno fence\n{E}",
        f"```jsonl\n{LINE}\n```\n{B}\n{E}",
        f"{B}\n```jsonl\n{LINE}\n```",  # no END marker
        f"{B}\n```jsonl\n{LINE}\n{E}",  # no closing fence
        f"{B}\n```jsonl\n{LINE}",  # cut off after one verdict
        f"{B}\n```jsonlines\n{LINE}\n```\n{E}",  # another fence language
        f"{B}\n```json\n{LINE}\n```\n{E}",
        f"{B}\ntext first\n```jsonl\n{LINE}\n```\n{E}",  # the fence isn't next
        f"{B}\n```jsonl\n{LINE}\n```\ntrailing text\n{E}",  # END isn't next
        f"{B}\n```jsonl\n{LINE}\n<!-- BEGIN other.jsonl -->\n{LINE}\n```\n{E}",  # nested
        f"{B}\n<!-- BEGIN other.jsonl -->\n```jsonl\n{LINE}\n```\n{E}",
        f"{B}\n```jsonl\n{LINE}\n```\n{E}\n{B}\n```jsonl\n{LINE}\n```\n{E}",  # two blocks
        f"{B}\n{B}\n```jsonl\n{LINE}\n```\n{E}",
        f"{E}\n{B}\n```jsonl\n{LINE}\n```",  # END before BEGIN
    ],
)
def test_extract_refuses_anything_but_one_complete_block(text: str) -> None:
    """A truncated or misnested report must not pass as a short clean one."""
    assert loop_tools.extract_block(text, "claims.jsonl") is None


def test_extract_returns_an_empty_list_for_a_complete_but_empty_block() -> None:
    assert loop_tools.extract_block(f"{B}\n\n```jsonl\n```\n\n{E}", "claims.jsonl") == []


def test_extract_command_fails_and_empties_the_output_on_a_truncated_block(
    tmp_path: Path,
) -> None:
    source, target = tmp_path / "report.md", tmp_path / "out.jsonl"
    source.write_text(f"{B}\n```jsonl\n{LINE}\n")
    target.write_text("stale\n")
    argv = ["loop_tools.py", "extract", str(source), "claims.jsonl", str(target)]
    assert loop_tools.main(argv) == 1
    assert target.read_text() == ""


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
    assert "no complete absent.jsonl block" in capsys.readouterr().err


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
    result = loop_tools.count_verdicts("\n".join(lines) + "\n", "lit-scout")
    assert (result["PASS_CT"], result["FAIL_CT"], result["PARTIAL_CT"], result["UNVER_CT"]) == (
        1, 1, 1, 1,
    )
    assert result["TOTAL_CT"] == 4 and result["INVALID_CT"] == 0
    assert result["FAIL_SET"] == "a-title" and result["VERDICT"] == "FAIL"


def test_count_keeps_the_legacy_placeholder_out_of_unverifiable() -> None:
    text = verdict("_legacy", "unverifiable") + "\n" + verdict("a-year", "unverifiable") + "\n"
    result = loop_tools.count_verdicts(text, "lit-scout")
    assert (result["LEGACY_CT"], result["UNVER_CT"], result["TOTAL_CT"]) == (1, 1, 2)
    assert result["VERDICT"] == "LEGACY"


def test_count_recognises_documentation_defects_and_letter_case() -> None:
    text = verdict("a-licence", "documentation_defect") + "\n" + verdict("a-url", "FAIL") + "\n"
    result = loop_tools.count_verdicts(text, "prior-art")
    assert (result["DOCDEF_CT"], result["FAIL_CT"], result["FAIL_SET"]) == (1, 1, "a-url")


@pytest.mark.parametrize(
    "line",
    ["not json", "[1, 2]", "{}", '{"status": "fail"}', '{"claim_id": "a", "status": "passed"}',
     '{"claim_id": "a", "status": null}', '{"claim_id": "a-title", "status": "fail"',
     '{"claim_id": "a-title", "status": "fail", "status": "pass"}',
     '{"claim_id": "a-title", "claim_id": "b-title", "status": "pass"}',
     '{"claim_id": "_legacy", "status": "fail"}', '{"claim_id": "_legacy", "status": "pass"}',
     '{"claim_id": "_legacy"}'],
)
@pytest.mark.parametrize("loop", ["lit-scout", "prior-art"])
def test_a_line_that_is_not_a_verdict_is_invalid_and_blocks_a_pass(line: str, loop: str) -> None:
    result = loop_tools.count_verdicts(verdict("a-year", "pass") + "\n" + line + "\n", loop)
    assert result["INVALID_CT"] == 1 and result["PASS_CT"] == 1 and result["TOTAL_CT"] == 2
    assert result["VERDICT"] == "INVALID"


def test_a_status_from_the_other_loop_is_invalid_for_lit_scout() -> None:
    text = verdict("a-licence", "documentation_defect") + "\n"
    assert loop_tools.count_verdicts(text, "lit-scout")["VERDICT"] == "INVALID"
    assert loop_tools.count_verdicts(text, "prior-art")["VERDICT"] == "PARTIAL"


# ---------------------------------------------------------------------------
# The verdict: PASS only when every verdict is a pass
# ---------------------------------------------------------------------------

EXPECTED = {
    ("lit-scout", "pass"): "PASS", ("lit-scout", "partial"): "PARTIAL",
    ("lit-scout", "fail"): "FAIL", ("lit-scout", "unverifiable"): "UNVERIFIABLE",
    ("prior-art", "pass"): "PASS", ("prior-art", "partial"): "PARTIAL",
    ("prior-art", "fail"): "FAIL", ("prior-art", "unverifiable"): "PARTIAL",
    ("prior-art", "documentation_defect"): "PARTIAL",
}


@pytest.mark.parametrize(("loop", "status"), sorted(EXPECTED))
def test_each_status_alone_gives_its_verdict(loop: str, status: str) -> None:
    result = loop_tools.count_verdicts(verdict("a-title", status) + "\n", loop)
    assert result["VERDICT"] == EXPECTED[(loop, status)]


@pytest.mark.parametrize(("loop", "status"), [k for k in sorted(EXPECTED) if k[1] != "pass"])
def test_one_verdict_short_of_pass_among_many_passes_is_never_a_pass(
    loop: str, status: str
) -> None:
    lines = [verdict(f"p{i}-year", "pass") for i in range(20)] + [verdict("a-title", status)]
    assert loop_tools.count_verdicts("\n".join(lines), loop)["VERDICT"] != "PASS"


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        (["pass", "partial", "unverifiable"], "UNVERIFIABLE"),
        (["pass", "partial"], "PARTIAL"),
        (["partial", "unverifiable", "fail"], "FAIL"),
    ],
)
def test_mixtures_follow_the_stated_order_for_lit_scout(
    statuses: list[str], expected: str
) -> None:
    text = "\n".join(verdict(f"c{i}", s) for i, s in enumerate(statuses))
    assert loop_tools.count_verdicts(text, "lit-scout")["VERDICT"] == expected


def test_the_legacy_placeholder_outranks_a_failure() -> None:
    text = verdict("_legacy", "unverifiable") + "\n" + verdict("a-title", "fail")
    assert loop_tools.count_verdicts(text, "prior-art")["VERDICT"] == "LEGACY"


def test_an_empty_file_is_invalid_not_a_pass() -> None:
    assert loop_tools.count_verdicts("\n\n", "lit-scout")["VERDICT"] == "INVALID"


def test_the_counts_always_add_up_to_the_total() -> None:
    lines = [verdict(f"c{i}", s) for i, s in enumerate(loop_tools.LOOPS["prior-art"] * 3)]
    lines += ["junk", verdict("_legacy", "unverifiable")]
    result = loop_tools.count_verdicts("\n\n".join(lines), "prior-art")
    parts = sum(v for k, v in result.items() if k.endswith("_CT") and k != "TOTAL_CT")
    assert parts == result["TOTAL_CT"] == 17


def test_the_failed_set_is_sorted_and_free_of_repeats() -> None:
    text = "\n".join(verdict(c, "fail") for c in ("b-year", "a-year", "b-year"))
    assert loop_tools.count_verdicts(text, "lit-scout")["FAIL_SET"] == "a-year b-year"


def test_count_command_prints_the_values_and_fails_on_invalid_or_empty_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "corrections.jsonl"
    path.write_text(verdict("a-year", "pass", spaced=True) + "\n")
    assert loop_tools.main(["loop_tools.py", "count", "lit-scout", str(path)]) == 0
    out = capsys.readouterr().out
    assert "PASS_CT=1\n" in out and "TOTAL_CT=1\n" in out and "FAIL_SET=\n" in out
    assert out.endswith("VERDICT=PASS\n")

    path.write_text(verdict("a-year", "pass") + "\nnot json\n")
    assert loop_tools.main(["loop_tools.py", "count", "lit-scout", str(path)]) == 1
    assert "VERDICT=INVALID\n" in capsys.readouterr().out

    path.write_text("")
    assert loop_tools.main(["loop_tools.py", "count", "prior-art", str(path)]) == 1
    assert loop_tools.main(["loop_tools.py", "count", "lit-scout", str(tmp_path / "absent")]) == 1
    assert loop_tools.main(["loop_tools.py", "count", "other-loop", str(path)]) == 2
    assert loop_tools.main(["loop_tools.py", "count", str(path)]) == 2
    assert loop_tools.main(["loop_tools.py"]) == 2


def test_the_lit_scout_count_prints_no_documentation_defect_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Its command doesn't mention that count, so printing it only confused."""
    path = tmp_path / "corrections.jsonl"
    path.write_text(verdict("a-year", "pass") + "\n")
    loop_tools.main(["loop_tools.py", "count", "lit-scout", str(path)])
    assert "DOCDEF_CT" not in capsys.readouterr().out
    loop_tools.main(["loop_tools.py", "count", "prior-art", str(path)])
    assert "DOCDEF_CT=0\n" in capsys.readouterr().out


def test_the_data_profile_loop_never_passes_on_a_verdict_short_of_pass() -> None:
    for status in ("partial", "fail", "unverifiable", "documentation_defect"):
        text = verdict("c1", "pass") + "\n" + verdict("c2", status) + "\n"
        assert loop_tools.count_verdicts(text, "data-profile")["VERDICT"] != "PASS"
    assert loop_tools.count_verdicts(verdict("c1", "pass"), "data-profile")["VERDICT"] == "PASS"
