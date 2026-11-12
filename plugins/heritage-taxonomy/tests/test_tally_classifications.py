"""
Tests for scripts/tally_classifications.py, the entity-classifier's tally.

The skill tells the model to fill a report's classification summary from
this script's output, so the script carries the roll-up rule: a
provisional union over all of an entity's mentions, a supported union that
leaves out mentions still for review ("unresolved" when none is left), and
"pending review" wherever the two differ. These tests pin that rule on the
cases the rule was written for, pin the loud failure on a malformed record,
and check that the printed tables use the report template's own column
headings.

Every report below is invented; nothing here reads a real collection.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_PLUGIN = Path(__file__).resolve().parent.parent
_SCRIPT = _PLUGIN / "scripts" / "tally_classifications.py"
_TEMPLATE = _PLUGIN / "skills" / "entity-classifier" / "templates" / "classification-report.md"


@pytest.fixture(scope="module")
def tally() -> Any:
    """Load the script by path and return it as a module.

    The module is registered in ``sys.modules`` before it runs, because its
    dataclass looks its own module up there.
    """
    spec = importlib.util.spec_from_file_location("tally_classifications", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def record(
    number: int,
    entity: str,
    label: str,
    *,
    confidence: str = "high",
    flag: str = "none",
    omit: str | None = None,
) -> str:
    """Return one per-mention record in the skill's template format.

    ``omit`` names a field line (Entity, Classification, Confidence, or
    Flag) to leave out, to make a malformed record.
    """
    fields = {
        "Entity": entity,
        "Classification": label,
        "Confidence": confidence,
        "Flag": flag,
    }
    lines = [f"### Mention {number}: an invented mention of {entity}"]
    for key in ("Entity", "Item", "Classification", "Confidence", "Flag"):
        if key == "Item":
            lines.append("**Item:** (test)")
        elif key != omit:
            lines.append(f"**{key}:** {fields[key]}")
    lines += [
        "",
        "**Reasoning:**",
        "Invented for the test.",
        "",
        "**Indicators found:**",
        "",
        "- Building: none",
        "- Organisation: none",
        "",
        "**Context:**",
        f"> \"An invented sentence naming the {entity}.\"",
        "",
        "**HUMAN REVIEW:**",
        "",
        "- [ ] Confirm classification",
        "",
        "---",
        "",
    ]
    return "\n".join(lines)


def report(*records: str) -> str:
    """Return a report around the records, with the template's fenced example.

    The fenced block holds a ``### Mention N:`` heading and field lines, as
    the template's review-block example does; it must not be counted.
    """
    head = (
        "# Hotels classification results\n\n"
        "**Entity type:** hotels\n\n"
        "## Detailed analysis\n\n"
        "```text\n"
        "### Mention N: short title\n"
        "**Entity:** Example Hotel\n"
        "**Classification:** both\n"
        "**Confidence:** high\n"
        "**Flag:** none\n"
        "```\n\n"
    )
    tail = "## Pattern analysis\n\n**Flag:** for review: a stray line outside any record\n"
    return head + "\n".join(records) + tail


def entity_row(summary: dict[str, Any], name: str) -> dict[str, Any]:
    """Return the roll-up row for one entity."""
    rows = [e for e in summary["entities"] if e["entity"] == name]
    assert len(rows) == 1, f"expected one row for {name}, got {rows}"
    return rows[0]


def run_cli(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run the script as the skill does, in isolated mode."""
    return subprocess.run(
        [sys.executable, "-I", str(_SCRIPT), str(path), *args],
        capture_output=True, text=True, check=False,
    )


# --- The roll-up rule -------------------------------------------------------


def test_building_only_entity(tally: Any) -> None:
    """An entity with only building mentions is building on both unions."""
    summary = tally.tally(tally.parse_report(report(
        record(1, "Carrington Hotel", "building"),
        record(2, "Carrington Hotel", "building", confidence="medium"),
    )))
    row = entity_row(summary, "Carrington Hotel")
    assert (row["mentions"], row["building"], row["flagged"]) == (2, 2, 0)
    assert (row["provisional"], row["supported"], row["recommendation"]) == (
        "building", "building", "building")


def test_two_mentions_roll_up_to_both(tally: Any) -> None:
    """A building mention and an organisation mention make the entity both."""
    summary = tally.tally(tally.parse_report(report(
        record(1, "Megalong Hotel", "organisation"),
        record(2, "Megalong Hotel", "building"),
    )))
    row = entity_row(summary, "Megalong Hotel")
    assert (row["building"], row["organisation"], row["both"]) == (1, 1, 0)
    assert (row["provisional"], row["supported"], row["recommendation"]) == (
        "both", "both", "both")


def test_single_both_mention(tally: Any) -> None:
    """One mention labelled both makes the entity both."""
    summary = tally.tally(tally.parse_report(report(
        record(1, "Carrington Hotel", "both"),
    )))
    row = entity_row(summary, "Carrington Hotel")
    assert (row["provisional"], row["supported"], row["recommendation"]) == (
        "both", "both", "both")
    assert summary["mentions"]["by_label"]["both"] == {
        "count": 1, "percentage": 100.0, "flagged": 0}


def test_flagged_only_entity_is_unresolved_and_pending(tally: Any) -> None:
    """With no unflagged evidence the supported union is unresolved."""
    summary = tally.tally(tally.parse_report(report(
        record(1, "Wesleyan Church, Lawson", "organisation", confidence="low",
               flag="for review: congregation, or the place he comes from?"),
    )))
    row = entity_row(summary, "Wesleyan Church, Lawson")
    assert (row["provisional"], row["supported"], row["recommendation"]) == (
        "organisation", "unresolved", "pending review")
    assert row["flagged"] == 1
    # The flagged mention still counts in the descriptive totals.
    assert summary["mentions"]["total"] == 1
    assert summary["mentions"]["by_label"]["organisation"]["count"] == 1
    assert summary["by_recommendation"]["pending review"] == 1


def test_building_plus_flagged_organisation_is_pending(tally: Any) -> None:
    """A doubtful organisation reading cannot silently make an entity both."""
    summary = tally.tally(tally.parse_report(report(
        record(1, "Railway Hotel", "building"),
        record(2, "Railway Hotel", "organisation", confidence="low",
               flag="for review: the proprietor, or a lodger?"),
    )))
    row = entity_row(summary, "Railway Hotel")
    assert (row["provisional"], row["supported"], row["recommendation"]) == (
        "both", "building", "pending review")
    assert (row["mentions"], row["building"], row["organisation"], row["flagged"]) == (
        2, 1, 1, 1)
    labels = summary["mentions"]["by_label"]
    assert labels["organisation"] == {"count": 1, "percentage": 50.0, "flagged": 1}
    assert summary["mentions"]["flagged"] == 1


def test_resolved_flag_counts_as_supported(tally: Any) -> None:
    """A flag the reviewer has settled no longer holds the entity back."""
    summary = tally.tally(tally.parse_report(report(
        record(1, "Railway Hotel", "building"),
        record(2, "Railway Hotel", "organisation",
               flag="resolved: the proprietor, per the licensing register"),
    )))
    row = entity_row(summary, "Railway Hotel")
    assert (row["provisional"], row["supported"], row["recommendation"]) == (
        "both", "both", "both")
    assert (row["flagged"], row["resolved"]) == (0, 1)


def test_flagged_mention_that_agrees_is_not_pending(tally: Any) -> None:
    """A flagged mention that changes neither union leaves the facet alone."""
    summary = tally.tally(tally.parse_report(report(
        record(1, "Railway Hotel", "building"),
        record(2, "Railway Hotel", "building", confidence="low",
               flag="for review: does 'It' refer back to this hotel?"),
    )))
    row = entity_row(summary, "Railway Hotel")
    assert row["recommendation"] == "building"
    assert row["flagged"] == 1


def test_mixed_report_counts_entities_by_recommendation(tally: Any) -> None:
    """Entities keep their order of first appearance; facets are counted."""
    summary = tally.tally(tally.parse_report(report(
        record(1, "Carrington Hotel", "building"),
        record(2, "Imperial Hotel", "organisation"),
        record(3, "Railway Hotel", "building"),
        record(4, "Imperial Hotel", "building"),
        record(5, "Presbyterian Church, Leura", "building", confidence="low",
               flag="for review: an address, or the congregation?"),
    )))
    assert [e["entity"] for e in summary["entities"]] == [
        "Carrington Hotel", "Imperial Hotel", "Railway Hotel", "Presbyterian Church, Leura"]
    assert summary["by_recommendation"] == {
        "building": 2, "organisation": 0, "both": 1, "pending review": 1}
    assert summary["mentions"]["by_label"]["building"]["percentage"] == 80.0
    assert summary["mentions"]["by_confidence"] == {"high": 4, "medium": 0, "low": 1}


def test_fenced_examples_and_stray_lines_are_not_counted(tally: Any) -> None:
    """The fenced template example and a field line after another heading are ignored."""
    mentions = tally.parse_report(report(record(1, "Carrington Hotel", "building")))
    assert [(m.number, m.entity, m.flag) for m in mentions] == [
        (1, "Carrington Hotel", "none")]


# --- Loud failure -----------------------------------------------------------


@pytest.mark.parametrize("omit", ["Entity", "Classification", "Confidence", "Flag"])
def test_record_missing_a_required_line_fails(tally: Any, omit: str) -> None:
    """A record without one of the four lines stops the tally, naming it."""
    text = report(
        record(1, "Carrington Hotel", "building"),
        record(2, "Imperial Hotel", "organisation", omit=omit),
    )
    with pytest.raises(tally.ReportError, match=rf"mention 2 .*\*\*{omit}:\*\*"):
        tally.parse_report(text)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("label", "organization"),
        ("confidence", "certain"),
        ("flag", "maybe"),
        ("flag", "for review"),
    ],
)
def test_invalid_value_fails(tally: Any, field: str, value: str) -> None:
    """A value outside the template's options stops the tally."""
    kwargs = {"label": "building", "confidence": "high", "flag": "none", field: value}
    label = kwargs.pop("label")
    text = report(record(1, "Carrington Hotel", label, **kwargs))
    with pytest.raises(tally.ReportError, match="mention 1"):
        tally.parse_report(text)


def test_repeated_line_fails(tally: Any) -> None:
    """Two Classification lines in one record stop the tally."""
    text = report(record(1, "Carrington Hotel", "building")).replace(
        "**Confidence:** high", "**Classification:** organisation\n**Confidence:** high")
    with pytest.raises(tally.ReportError, match="second \\*\\*Classification:\\*\\*"):
        tally.parse_report(text)


def test_duplicate_mention_number_fails(tally: Any) -> None:
    """A record pasted twice would be counted twice, so it stops the tally."""
    text = report(
        record(1, "Carrington Hotel", "building"),
        record(1, "Carrington Hotel", "building"),
    )
    with pytest.raises(tally.ReportError, match="appears twice"):
        tally.parse_report(text)


def test_report_without_records_fails(tally: Any) -> None:
    """A file with no mention records is an error, not an empty tally."""
    with pytest.raises(tally.ReportError, match="no '### Mention N:' records"):
        tally.parse_report("# Results\n\nNothing here.\n")


def test_cli_malformed_record_exits_1_with_nothing_on_stdout(tmp_path: Path) -> None:
    """From the command line, a malformed record gives exit 1 and a message."""
    path = tmp_path / "results.md"
    path.write_text(report(record(3, "Imperial Hotel", "organisation", omit="Flag")))
    result = run_cli(path)
    assert result.returncode == 1
    assert result.stdout == ""
    assert "mention 3" in result.stderr and "**Flag:**" in result.stderr


# --- The printed output -----------------------------------------------------


def test_cli_markdown_uses_the_template_headings(tmp_path: Path) -> None:
    """The printed tables can be pasted into the template's summary as they stand."""
    path = tmp_path / "results.md"
    path.write_text(report(
        record(1, "Railway Hotel", "building"),
        record(2, "Railway Hotel", "organisation", confidence="low",
               flag="for review: the proprietor, or a lodger?"),
    ))
    result = run_cli(path)
    assert result.returncode == 0, result.stderr
    out = result.stdout.splitlines()
    template = _TEMPLATE.read_text().splitlines()
    for header in ("| Mention label |", "| Entity |"):
        printed = [line for line in out if line.startswith(header)]
        expected = [line for line in template if line.startswith(header)]
        assert printed == expected, f"{header}: {printed} != {expected}"
    assert "| Organisation | 1 | 50.0% | 1 |" in out
    assert "| **Total** | **2** | **100%** | **1** |" in out
    assert "| Railway Hotel | 2 | 1 | 1 | 0 | 1 | both | building | pending review |" in out
    assert any(line.startswith("**Entities by recommendation:** 0 building only")
               and "1 pending review" in line for line in out)


def test_cli_json(tmp_path: Path) -> None:
    """--json prints the same figures as data."""
    path = tmp_path / "results.md"
    path.write_text(report(
        record(1, "Wesleyan Church, Lawson", "organisation", confidence="low",
               flag="for review: congregation, or the place he comes from?"),
    ))
    result = run_cli(path, "--json")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["mentions"]["total"] == 1
    assert data["entities"][0]["supported"] == "unresolved"
    assert data["entities"][0]["recommendation"] == "pending review"
    assert data["entities"][0]["mention_numbers"] == [1]


def test_cli_warns_on_names_differing_only_in_case(tmp_path: Path) -> None:
    """Two spellings of one name are counted apart, with a warning."""
    path = tmp_path / "results.md"
    path.write_text(report(
        record(1, "Imperial Hotel", "building"),
        record(2, "Imperial hotel", "organisation"),
    ))
    result = run_cli(path)
    assert result.returncode == 0
    assert "warning" in result.stderr and "Imperial hotel" in result.stderr



# --- Review findings R42 and R43 (GPT in Codex, lane astra, 12 Nov 2026) ----


@pytest.mark.parametrize("heading", [
    "#### Mention 2: an invented mention of Imperial Hotel",
    "### Mention two: an invented mention of Imperial Hotel",
    "### mention 2 an invented mention of Imperial Hotel",
])
def test_cli_malformed_mention_heading_fails_loudly(tmp_path: Path, heading: str) -> None:
    """A second, complete record under a malformed heading is never silently dropped."""
    bad = record(2, "Imperial Hotel", "organisation").replace(
        "### Mention 2: an invented mention of Imperial Hotel", heading)
    path = tmp_path / "results.md"
    path.write_text(report(record(1, "Carrington Hotel", "building"), bad))
    result = run_cli(path)
    assert result.returncode == 1
    assert result.stdout == ""
    assert "malformed mention heading" in result.stderr


def test_cli_orphaned_record_block_fails_loudly(tmp_path: Path) -> None:
    """Field lines cut off from their record by a sub-heading are an error, not ignored."""
    orphan = "#### Notes\n**Entity:** Imperial Hotel\n**Classification:** building\n"
    path = tmp_path / "results.md"
    path.write_text(report(record(1, "Carrington Hotel", "building"), orphan))
    result = run_cli(path)
    assert result.returncode == 1
    assert result.stdout == ""
    assert "outside any '### Mention N:' record" in result.stderr


@pytest.mark.parametrize("flag", ["resolved:", "resolved:   ", "for review:", "for review: \t"])
def test_a_flag_with_nothing_after_the_colon_fails(tally: Any, flag: str) -> None:
    """Both flag forms need a question or a decision after the colon."""
    with pytest.raises(tally.ReportError):
        tally.parse_report(report(record(1, "Wesleyan Church", "organisation", flag=flag)))


def test_cli_empty_resolution_gives_no_tally(tmp_path: Path) -> None:
    """An empty "resolved:" cannot turn a pending entity firm."""
    path = tmp_path / "results.md"
    path.write_text(report(record(1, "Wesleyan Church", "organisation", flag="resolved:")))
    result = run_cli(path)
    assert result.returncode == 1 and result.stdout == ""


def test_a_resolution_with_a_decision_still_counts(tally: Any) -> None:
    """The positive guard: a settled flag that records its decision is supported."""
    flag = "resolved: the reviewer read it as the congregation"
    mentions = tally.parse_report(report(record(1, "Wesleyan Church", "organisation", flag=flag)))
    assert mentions[0].flag == "resolved"
