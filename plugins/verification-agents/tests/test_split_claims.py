"""
Unit tests for the claims splitter (scripts/split_claims.py).

The splitter decides which papers a simple library import script will see.
The property that matters is one-sided: a paper must never reach
`verified-claims.jsonl` unless the verifier gave it at least one verdict and
every verdict was `pass`. These tests pin that for each way a paper can fall
short, and check the files the script writes.
"""

import json
import sys
from pathlib import Path

import pytest

# The script lives in the plugin's scripts folder.
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import split_claims  # noqa: E402

CATEGORIES = ("authors", "year", "title", "citation_count", "doi_resolves")


def claims_for(doi: str) -> list[dict]:
    """Return the five claims a proposer emits for one paper."""
    slug = doi.replace("/", "-")
    return [{"claim_id": f"{slug}-{c}", "doi": doi, "category": c} for c in CATEGORIES]


def verdicts_for(doi: str, **overrides: str) -> list[dict]:
    """Return five verdicts for one paper: `pass`, except where overridden."""
    slug = doi.replace("/", "-")
    return [
        {"claim_id": f"{slug}-{c}", "doi": doi, "category": c, "status": overrides.get(c, "pass")}
        for c in CATEGORIES
    ]


def dois(records: list[dict]) -> set[str]:
    """Return the DOIs present in a list of claims."""
    return {r["doi"] for r in records}


def test_a_paper_with_every_verdict_pass_is_verified() -> None:
    verified, unverified = split_claims.split(claims_for("10.1/a"), verdicts_for("10.1/a"))
    assert dois(verified) == {"10.1/a"} and unverified == []
    assert all("verification" not in claim for claim in verified)


@pytest.mark.parametrize("status", ["fail", "partial", "unverifiable", "", "PASSED"])
def test_one_verdict_short_of_pass_makes_the_whole_paper_unverified(status: str) -> None:
    corrections = verdicts_for("10.1/a", title=status)
    verified, unverified = split_claims.split(claims_for("10.1/a"), corrections)
    assert verified == []
    assert len(unverified) == 5
    assert unverified[0]["verification"] == [f"title: {status.lower() or 'no status'}"]


def test_a_paper_with_no_verdict_is_unverified_not_verified() -> None:
    """Absence of a check is not a pass."""
    claims = claims_for("10.1/a") + claims_for("10.1/b")
    verified, unverified = split_claims.split(claims, verdicts_for("10.1/a"))
    assert dois(verified) == {"10.1/a"}
    assert dois(unverified) == {"10.1/b"}
    assert unverified[0]["verification"] == ["not checked"]


def test_no_corrections_at_all_verifies_nothing() -> None:
    verified, unverified = split_claims.split(claims_for("10.1/a"), [])
    assert verified == [] and len(unverified) == 5


def test_doi_matching_ignores_letter_case() -> None:
    corrections = verdicts_for("10.1/ABC", year="fail")
    verified, unverified = split_claims.split(claims_for("10.1/abc"), corrections)
    assert verified == [] and dois(unverified) == {"10.1/abc"}


def test_records_without_a_doi_are_matched_by_claim_id() -> None:
    claims = [{"claim_id": "10.1-a-year", "category": "year"}]
    passing = [{"claim_id": "10.1-a-year", "category": "year", "status": "pass"}]
    failing = [{"claim_id": "10.1-a-title", "category": "title", "status": "fail"}]
    assert split_claims.split(claims, passing)[0] == claims
    assert split_claims.split(claims, passing + failing)[0] == []


def test_the_legacy_placeholder_verifies_nothing() -> None:
    corrections = [{"claim_id": "_legacy", "status": "unverifiable"}]
    verified, _ = split_claims.split(claims_for("10.1/a"), corrections)
    assert verified == []


def write_iteration(run: Path, n: int, claims: list[dict], corrections: list[dict]) -> None:
    """Create an `iter-N` folder with the two files the splitter reads."""
    folder = run / f"iter-{n}"
    folder.mkdir()
    split_claims.write_jsonl(folder / "claims.jsonl", claims)
    split_claims.write_jsonl(folder / "corrections.jsonl", corrections)


def test_main_uses_the_highest_numbered_iteration_and_writes_both_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_iteration(tmp_path, 2, claims_for("10.1/old"), verdicts_for("10.1/old"))
    final_claims = claims_for("10.1/a") + claims_for("10.1/b")
    final_corrections = verdicts_for("10.1/a") + verdicts_for("10.1/b", doi_resolves="unverifiable")
    write_iteration(tmp_path, 10, final_claims, final_corrections)

    assert split_claims.main(["split_claims.py", str(tmp_path)]) == 0
    verified = split_claims.load_jsonl(tmp_path / "verified-claims.jsonl")
    unverified = split_claims.load_jsonl(tmp_path / "unverified-claims.jsonl")
    assert dois(verified) == {"10.1/a"}
    assert dois(unverified) == {"10.1/b"}
    assert unverified[0]["verification"] == ["doi_resolves: unverifiable"]
    assert "iter-10: 1 verified papers, 1 unverified" in capsys.readouterr().out


def test_main_fails_when_the_run_has_no_claims(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "iter-0").mkdir()
    assert split_claims.main(["split_claims.py", str(tmp_path)]) == 2
    assert not (tmp_path / "verified-claims.jsonl").exists()
    assert "no iter-N/claims.jsonl" in capsys.readouterr().err


def test_an_unreadable_verdict_line_verifies_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A verdict that can't be read might have been a failure."""
    write_iteration(tmp_path, 0, claims_for("10.1/a"), verdicts_for("10.1/a"))
    with (tmp_path / "iter-0" / "corrections.jsonl").open("a") as handle:
        handle.write('{"claim_id": "10.1-a-title", "status": "fail"\n')  # truncated line
    assert split_claims.main(["split_claims.py", str(tmp_path)]) == 0
    assert split_claims.load_jsonl(tmp_path / "verified-claims.jsonl") == []
    assert len(split_claims.load_jsonl(tmp_path / "unverified-claims.jsonl")) == 5
    assert "unreadable" in capsys.readouterr().err


def test_unparseable_lines_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"
    path.write_text('{"a": 1}\nnot json\n\n[1, 2]\n{"b": 2}\n')
    assert split_claims.load_jsonl(path) == [{"a": 1}, {"b": 2}]
    assert json.loads(json.dumps(split_claims.load_jsonl(tmp_path / "absent.jsonl"))) == []
