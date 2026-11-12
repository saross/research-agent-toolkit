#!/usr/bin/env python3
"""
split_claims.py
===============

Split a finished lit-scout-iterate run's claims into verified and unverified.

A library import command receives the run folder. Its final `claims.jsonl`
holds every row of the findings table, including rows whose checks failed or
never completed. An import script that read that file alone would put
unverified references into the user's library with nothing to mark them.

This script makes the safe choice the easy one. It writes two files into the
run folder:

    verified-claims.jsonl    claims for papers whose every claim passed
    unverified-claims.jsonl  claims for all other papers, each with a
                             `verification` field listing what was wrong

An import script that reads only `verified-claims.jsonl` can't import an
unverified reference by accident.

The rule is one-sided: when in doubt, a paper is unverified. A paper is
verified only when **every one of its claims** has at least one verdict in
the verifier's `corrections.jsonl`, and every verdict on every claim is
`pass`. Otherwise it is unverified, which covers:

- a claim with a `partial`, `fail`, or `unverifiable` verdict;
- a claim with no verdict at all (absence of a check is not a pass);
- a claim with no `doi` field, since an import needs the full DOI and it
  can't be rebuilt from the `claim_id`;
- a verdict whose DOI disagrees with its claim's DOI;
- claims that share an identifier but name different DOIs.

Some defects in `corrections.jsonl` can't be tied to one paper, and any of
them might hide a failure. Each makes **every** paper unverified: a line
that isn't a JSON object; a record without a `claim_id` or with a status
other than the four the verifier uses; a verdict short of `pass` for a claim
this run never made; and the `_legacy` placeholder.

Verdicts are matched to claims by `claim_id`, which the verifier copies
exactly. Two claims belong to the same paper if they have the same DOI
(compared without regard to letter case or a leading `https://doi.org/` or
`doi:`) or the same `claim_id` once its category suffix is removed. So a
claim that lacks its `doi` still joins the paper its identifier names, and
that paper is judged as a whole: its claims all land in the same file. The
DOI is never rebuilt from the `claim_id`, which loses information.

The claims come from the highest-numbered `iter-N` folder. If that folder
has no claims (an interrupted iteration, say), the script fails instead of
falling back to an earlier iteration, whose table the run had already moved
on from. On any failure it leaves neither output file behind.

Uses the standard library only.

Usage:
    python3 split_claims.py RUN_FOLDER

Exit status: 0 on success; 2 when the split could not be made.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

CATEGORY_SUFFIX = re.compile(r"-(authors|year|title|citation_count|doi_resolves)$")
ITERATION_NAME = re.compile(r"iter-([0-9]+)", re.ASCII)
STATUSES = ("pass", "partial", "fail", "unverifiable")
DOI_PREFIXES = (
    "https://doi.org/",
    "http://doi.org/",
    "https://dx.doi.org/",
    "http://dx.doi.org/",
    "doi:",
)
VERIFIED_NAME = "verified-claims.jsonl"
UNVERIFIED_NAME = "unverified-claims.jsonl"


class SplitError(Exception):
    """The run folder can't be split; the message says why."""


def canonical_doi(value: object) -> str:
    """
    Reduce a DOI to a form that can be compared.

    Args:
        value: A record's `doi` field, of any type.

    Returns:
        The DOI in lower case, without surrounding space or a leading web
        address or `doi:`. Empty for a missing or non-text value.
    """
    if not isinstance(value, str):
        return ""
    text = value.strip().lower()
    for prefix in DOI_PREFIXES:
        if text.startswith(prefix):
            return text[len(prefix):].strip()
    return text


def read_jsonl(path: Path) -> tuple[list[dict], int]:
    """
    Read a JSON Lines file.

    Args:
        path: The file to read. A missing file gives no records.

    Returns:
        The lines that are JSON objects, in order, and the number of
        non-blank lines that are not.
    """
    if not path.is_file():
        return [], 0
    records: list[dict] = []
    unreadable = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            unreadable += 1
            continue
        if isinstance(record, dict):
            records.append(record)
        else:
            unreadable += 1
    return records, unreadable


def final_iteration(run_folder: Path) -> Path:
    """
    Return the highest-numbered `iter-N` folder.

    Args:
        run_folder: The lit-scout-iterate run folder.

    Returns:
        The folder for the last iteration the run started.

    Raises:
        SplitError: If there is no `iter-N` folder, or the last one has no
            claims. An earlier iteration is never used in its place.
    """
    numbered = []
    for path in run_folder.glob("iter-*"):
        match = ITERATION_NAME.fullmatch(path.name)
        if match and path.is_dir():
            numbered.append((int(match.group(1)), path))
    if not numbered:
        raise SplitError(f"no iter-N folder under {run_folder}")
    final = max(numbered)[1]
    claims = final / "claims.jsonl"
    if not claims.is_file() or claims.stat().st_size == 0:
        raise SplitError(
            f"{final.name} is the last iteration and has no claims.jsonl; "
            "not falling back to an earlier iteration"
        )
    return final


def group_papers(claims: list[dict]) -> list[int]:
    """
    Assign each claim to a paper.

    Two claims are the same paper if they share a canonical DOI, or share a
    `claim_id` once its category suffix is removed. The relation is followed
    through chains, so a claim without a DOI joins the claims its identifier
    names, and those join every claim with their DOI.

    Args:
        claims: The claim records.

    Returns:
        For each claim, in order, the number of its paper. Claims with
        neither a DOI nor a `claim_id` each form a paper of their own.
    """
    parent = list(range(len(claims)))

    def root(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    first_with: dict[str, int] = {}
    for index, claim in enumerate(claims):
        doi = canonical_doi(claim.get("doi"))
        claim_id = claim.get("claim_id")
        base = CATEGORY_SUFFIX.sub("", claim_id.strip()) if isinstance(claim_id, str) else ""
        for key in ([f"doi:{doi}"] if doi else []) + ([f"id:{base}"] if base else []):
            if key in first_with:
                parent[root(index)] = root(first_with[key])
            else:
                first_with[key] = index
    return [root(index) for index in range(len(claims))]


def split(
    claims: list[dict], corrections: list[dict], unreadable: int = 0
) -> tuple[list[dict], list[dict]]:
    """
    Divide claims into those for verified papers and those for the rest.

    Args:
        claims: The final iteration's claim records.
        corrections: The final iteration's verdict records.
        unreadable: How many lines of the corrections file were not JSON
            objects.

    Returns:
        Two lists, verified then unverified, each in the claims' order. Each
        unverified claim gains a `verification` field: the reasons its paper
        is unverified, such as "title: fail" or "year: no verdict".
    """
    # Problems that can't be tied to one paper make every paper unverified.
    everywhere: list[str] = []
    if unreadable:
        everywhere.append(f"{unreadable} unreadable line(s) in corrections.jsonl")

    paper = group_papers(claims)  # claim index -> paper number
    reasons: dict[int, list[str]] = {number: [] for number in paper}

    # What each paper's claims say about its identity.
    dois_of_paper: dict[int, set[str]] = {number: set() for number in paper}
    papers_of_id: dict[str, set[int]] = {}
    for index, claim in enumerate(claims):
        doi = canonical_doi(claim.get("doi"))
        if doi:
            dois_of_paper[paper[index]].add(doi)
        else:
            reasons[paper[index]].append("a claim has no doi")
        claim_id = claim.get("claim_id")
        if isinstance(claim_id, str) and claim_id.strip():
            papers_of_id.setdefault(claim_id, set()).add(paper[index])
        else:
            reasons[paper[index]].append("a claim has no claim_id")
    for number, found in dois_of_paper.items():
        if len(found) > 1:
            reasons[number].append("claims that share an identifier name different DOIs")
    paper_of_doi = {doi: number for number, found in dois_of_paper.items() for doi in found}

    # Every verdict, attached to its claim by claim_id.
    statuses_of_id: dict[str, list[str]] = {}
    for record in corrections:
        claim_id = record.get("claim_id")
        status = record.get("status")
        status = status.strip().lower() if isinstance(status, str) else ""
        if not isinstance(claim_id, str) or not claim_id.strip():
            everywhere.append("a verdict has no claim_id")
            continue
        if claim_id == "_legacy":
            everywhere.append("the verifier reported that the proposer emitted no claims")
            continue
        if status not in STATUSES:
            everywhere.append(f"verdict for {claim_id} has an unknown status")
            continue
        if claim_id not in papers_of_id:
            # A pass for a claim nobody made changes nothing. Anything else
            # is a failure that can't be attributed, so it counts everywhere.
            if status != "pass":
                everywhere.append(f"verdict '{status}' for unknown claim {claim_id}")
            continue
        statuses_of_id.setdefault(claim_id, []).append(status)
        doi = canonical_doi(record.get("doi"))
        if doi:
            for number in papers_of_id[claim_id]:
                if doi not in dois_of_paper[number]:
                    reasons[number].append(f"verdict for {claim_id} names another DOI")
                    if doi in paper_of_doi:
                        reasons[paper_of_doi[doi]].append(
                            f"verdict for {claim_id} names this DOI but belongs to another paper"
                        )

    # Every claim needs a verdict, and every verdict must be a pass.
    for index, claim in enumerate(claims):
        claim_id = claim.get("claim_id")
        if not isinstance(claim_id, str) or not claim_id.strip():
            continue
        label = str(claim.get("category") or claim_id)
        found = statuses_of_id.get(claim_id, [])
        if not found:
            reasons[paper[index]].append(f"{label}: no verdict")
        for status in found:
            if status != "pass":
                reasons[paper[index]].append(f"{label}: {status}")

    # A paper is judged as a whole: all of its claims go to the same file.
    verified: list[dict] = []
    unverified: list[dict] = []
    for index, claim in enumerate(claims):
        why = list(dict.fromkeys(reasons[paper[index]] + everywhere))
        if why:
            unverified.append({**claim, "verification": why})
        else:
            verified.append(claim)
    return verified, unverified


def count_papers(claims: list[dict]) -> int:
    """Return how many papers a list of claims covers."""
    return len(set(group_papers(claims)))


def write_jsonl(path: Path, records: list[dict]) -> None:
    """Write records to a JSON Lines file, one object per line."""
    text = "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records)
    path.write_text(text, encoding="utf-8")


def main(argv: list[str]) -> int:
    """Split the run folder's final claims and report the paper counts."""
    if len(argv) != 2:
        print("usage: split_claims.py RUN_FOLDER", file=sys.stderr)
        return 2
    run_folder = Path(argv[1])
    # Remove earlier output first, so that a failure can't leave a stale
    # list behind for an import command to read.
    for name in (VERIFIED_NAME, UNVERIFIED_NAME):
        (run_folder / name).unlink(missing_ok=True)
    try:
        final = final_iteration(run_folder)
        claims, bad_claims = read_jsonl(final / "claims.jsonl")
        if bad_claims:
            raise SplitError(f"{bad_claims} unreadable line(s) in {final.name}/claims.jsonl")
        if not claims:
            raise SplitError(f"{final.name}/claims.jsonl holds no claims")
        corrections, unreadable = read_jsonl(final / "corrections.jsonl")
    except (SplitError, OSError) as error:
        print(f"split_claims: {error}", file=sys.stderr)
        return 2
    verified, unverified = split(claims, corrections, unreadable)
    write_jsonl(run_folder / VERIFIED_NAME, verified)
    write_jsonl(run_folder / UNVERIFIED_NAME, unverified)
    print(
        f"{final.name}: {count_papers(verified)} papers verified, "
        f"{count_papers(unverified)} unverified"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
