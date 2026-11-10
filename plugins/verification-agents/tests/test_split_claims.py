"""
Unit tests for the claims splitter (scripts/split_claims.py).

The splitter decides which papers a simple library import script will see.
The property that matters is one-sided: a paper must never reach
`verified-claims.jsonl` unless every one of its claims has a verdict and
every verdict is `pass`. These tests attack that from each direction a
review found or suggested: a failure filed under another spelling of the
paper's identity, a claim with no verdict, a verdict that can't be
attributed, and a run folder whose last iteration is incomplete.
"""

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


# ---------------------------------------------------------------------------
# The ordinary cases
# ---------------------------------------------------------------------------


def test_a_paper_whose_every_claim_passed_is_verified() -> None:
    verified, unverified = split_claims.split(claims_for("10.1/a"), verdicts_for("10.1/a"))
    assert dois(verified) == {"10.1/a"} and unverified == []
    assert all("verification" not in claim for claim in verified)


@pytest.mark.parametrize("status", ["fail", "partial", "unverifiable"])
def test_one_verdict_short_of_pass_makes_the_whole_paper_unverified(status: str) -> None:
    corrections = verdicts_for("10.1/a", title=status)
    verified, unverified = split_claims.split(claims_for("10.1/a"), corrections)
    assert verified == [] and len(unverified) == 5
    assert unverified[0]["verification"] == [f"title: {status}"]


def test_one_paper_failing_leaves_another_verified() -> None:
    claims = claims_for("10.1/a") + claims_for("10.1/b")
    corrections = verdicts_for("10.1/a") + verdicts_for("10.1/b", year="fail")
    verified, unverified = split_claims.split(claims, corrections)
    assert dois(verified) == {"10.1/a"} and dois(unverified) == {"10.1/b"}


def test_doi_letter_case_and_web_address_forms_are_the_same_paper() -> None:
    corrections = verdicts_for("https://doi.org/10.1/ABC")
    for verdict, claim in zip(corrections, claims_for("10.1/abc"), strict=True):
        verdict["claim_id"] = claim["claim_id"]
    verified, unverified = split_claims.split(claims_for("10.1/abc"), corrections)
    assert dois(verified) == {"10.1/abc"} and unverified == []


# ---------------------------------------------------------------------------
# A claim without a verdict is not a pass
# ---------------------------------------------------------------------------


def test_a_paper_with_no_verdicts_is_unverified() -> None:
    claims = claims_for("10.1/a") + claims_for("10.1/b")
    verified, unverified = split_claims.split(claims, verdicts_for("10.1/a"))
    assert dois(verified) == {"10.1/a"} and dois(unverified) == {"10.1/b"}
    assert "title: no verdict" in unverified[0]["verification"]


def test_one_passing_verdict_does_not_verify_a_five_claim_paper() -> None:
    corrections = verdicts_for("10.1/a")[:1]
    verified, unverified = split_claims.split(claims_for("10.1/a"), corrections)
    assert verified == []
    assert unverified[0]["verification"] == [
        "year: no verdict", "title: no verdict",
        "citation_count: no verdict", "doi_resolves: no verdict",
    ]


def test_no_corrections_at_all_verifies_nothing() -> None:
    verified, unverified = split_claims.split(claims_for("10.1/a"), [])
    assert verified == [] and len(unverified) == 5


def test_a_later_pass_cannot_hide_an_earlier_failure_on_the_same_claim() -> None:
    corrections = verdicts_for("10.1/a", title="fail") + verdicts_for("10.1/a")
    verified, _ = split_claims.split(claims_for("10.1/a"), corrections)
    assert verified == []


# ---------------------------------------------------------------------------
# A failure filed under another spelling of the paper's identity
# ---------------------------------------------------------------------------


def test_a_failure_with_no_doi_field_still_reaches_its_paper() -> None:
    """Four passes carry the DOI; the failing verdict carries only the claim_id."""
    corrections = verdicts_for("10.1000/abc-def", title="fail")
    del corrections[2]["doi"]
    verified, unverified = split_claims.split(claims_for("10.1000/abc-def"), corrections)
    assert verified == [] and unverified[0]["verification"] == ["title: fail"]


def test_a_failure_with_the_doi_as_a_web_address_still_reaches_its_paper() -> None:
    corrections = verdicts_for("10.1000/abc-def", title="fail")
    corrections[2]["doi"] = "https://doi.org/10.1000/ABC-DEF"
    verified, _ = split_claims.split(claims_for("10.1000/abc-def"), corrections)
    assert verified == []


def test_a_verdict_naming_another_doi_unverifies_both_papers() -> None:
    claims = claims_for("10.1/a") + claims_for("10.1/b")
    corrections = verdicts_for("10.1/a") + verdicts_for("10.1/b")
    corrections[0]["doi"] = "10.1/b"  # a verdict for paper a that says it is about b
    verified, unverified = split_claims.split(claims, corrections)
    assert verified == [] and dois(unverified) == {"10.1/a", "10.1/b"}


def test_a_claim_id_shared_by_two_papers_unverifies_both() -> None:
    claims = claims_for("10.1/a") + claims_for("10.1/b")
    claims[5]["claim_id"] = claims[0]["claim_id"]
    corrections = verdicts_for("10.1/a") + verdicts_for("10.1/b")
    verified, _ = split_claims.split(claims, corrections)
    assert verified == []


def test_claims_without_a_doi_are_grouped_by_claim_id() -> None:
    claims = [{"claim_id": f"10.1-a-{c}", "category": c} for c in ("year", "title")]
    passing = [{"claim_id": c["claim_id"], "status": "pass"} for c in claims]
    assert split_claims.split(claims, passing)[0] == claims
    assert split_claims.split(claims, passing[:1])[0] == []


# ---------------------------------------------------------------------------
# Verdicts that can't be attributed make every paper unverified
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stray",
    [
        {},
        {"status": "fail"},
        {"claim_id": "10.9-unknown-title", "status": "fail"},
        {"claim_id": "10.9-unknown-title", "status": "unverifiable"},
        {"claim_id": "10.1-a-title", "status": "PASSED"},
        {"claim_id": "10.1-a-title", "status": None},
        {"claim_id": "_legacy", "status": "unverifiable"},
    ],
)
def test_a_stray_verdict_that_could_hide_a_failure_verifies_nothing(stray: dict) -> None:
    claims = claims_for("10.1/a") + claims_for("10.1/b")
    corrections = verdicts_for("10.1/a") + verdicts_for("10.1/b") + [stray]
    verified, unverified = split_claims.split(claims, corrections)
    assert verified == [] and len(unverified) == 10


def test_a_pass_for_a_claim_nobody_made_changes_nothing() -> None:
    corrections = verdicts_for("10.1/a") + [{"claim_id": "10.9-x-title", "status": "pass"}]
    verified, _ = split_claims.split(claims_for("10.1/a"), corrections)
    assert dois(verified) == {"10.1/a"}


def test_an_unreadable_line_count_verifies_nothing() -> None:
    verified, unverified = split_claims.split(
        claims_for("10.1/a"), verdicts_for("10.1/a"), unreadable=1
    )
    assert verified == []
    assert unverified[0]["verification"] == ["1 unreadable line(s) in corrections.jsonl"]


# ---------------------------------------------------------------------------
# The run folder
# ---------------------------------------------------------------------------


def write_iteration(run: Path, name: str, claims: list[dict], corrections: list[dict]) -> None:
    """Create an iteration folder with the two files the splitter reads."""
    folder = run / name
    folder.mkdir()
    split_claims.write_jsonl(folder / "claims.jsonl", claims)
    split_claims.write_jsonl(folder / "corrections.jsonl", corrections)


def read(path: Path) -> list[dict]:
    """Read back one of the splitter's output files."""
    return split_claims.read_jsonl(path)[0]


def test_main_uses_the_highest_numbered_iteration_and_writes_both_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_iteration(tmp_path, "iter-2", claims_for("10.1/old"), verdicts_for("10.1/old"))
    final_claims = claims_for("10.1/a") + claims_for("10.1/b")
    final_corrections = verdicts_for("10.1/a") + verdicts_for("10.1/b", doi_resolves="unverifiable")
    write_iteration(tmp_path, "iter-10", final_claims, final_corrections)

    assert split_claims.main(["split_claims.py", str(tmp_path)]) == 0
    assert dois(read(tmp_path / "verified-claims.jsonl")) == {"10.1/a"}
    unverified = read(tmp_path / "unverified-claims.jsonl")
    assert dois(unverified) == {"10.1/b"}
    assert unverified[0]["verification"] == ["doi_resolves: unverifiable"]
    assert "iter-10: 1 papers verified, 1 unverified" in capsys.readouterr().out


def test_main_does_not_fall_back_past_an_incomplete_last_iteration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An interrupted iter-1 must not let a passing iter-0 be imported."""
    write_iteration(tmp_path, "iter-0", claims_for("10.1/a"), verdicts_for("10.1/a"))
    (tmp_path / "iter-1").mkdir()
    (tmp_path / "verified-claims.jsonl").write_text('{"stale": true}\n')
    assert split_claims.main(["split_claims.py", str(tmp_path)]) == 2
    assert not (tmp_path / "verified-claims.jsonl").exists()
    assert not (tmp_path / "unverified-claims.jsonl").exists()
    assert "not falling back" in capsys.readouterr().err


def test_main_ignores_folders_that_are_not_plainly_numbered(tmp_path: Path) -> None:
    """A superscript digit is a digit to `str.isdigit` but not a number here."""
    write_iteration(tmp_path, "iter-0", claims_for("10.1/a"), verdicts_for("10.1/a"))
    write_iteration(tmp_path, "iter-²", claims_for("10.1/odd"), verdicts_for("10.1/odd"))
    write_iteration(tmp_path, "iter-final", claims_for("10.1/odd"), verdicts_for("10.1/odd"))
    assert split_claims.main(["split_claims.py", str(tmp_path)]) == 0
    assert dois(read(tmp_path / "verified-claims.jsonl")) == {"10.1/a"}


def test_main_counts_an_unreadable_verdict_line_against_every_paper(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_iteration(tmp_path, "iter-0", claims_for("10.1/a"), verdicts_for("10.1/a"))
    with (tmp_path / "iter-0" / "corrections.jsonl").open("a") as handle:
        handle.write('{"claim_id": "10.1-a-title", "status": "fail"\n')  # truncated line
        handle.write("[1, 2]\n")  # valid JSON, but not a record
    assert split_claims.main(["split_claims.py", str(tmp_path)]) == 0
    assert read(tmp_path / "verified-claims.jsonl") == []
    assert len(read(tmp_path / "unverified-claims.jsonl")) == 5
    assert "0 papers verified, 1 unverified" in capsys.readouterr().out


@pytest.mark.parametrize("content", ["", "not json\n"])
def test_main_fails_when_the_final_claims_are_missing_or_unreadable(
    tmp_path: Path, content: str
) -> None:
    (tmp_path / "iter-0").mkdir()
    (tmp_path / "iter-0" / "claims.jsonl").write_text(content)
    assert split_claims.main(["split_claims.py", str(tmp_path)]) == 2
    assert not (tmp_path / "verified-claims.jsonl").exists()


def test_main_fails_without_any_iteration(tmp_path: Path) -> None:
    assert split_claims.main(["split_claims.py", str(tmp_path)]) == 2
    assert split_claims.main(["split_claims.py"]) == 2
