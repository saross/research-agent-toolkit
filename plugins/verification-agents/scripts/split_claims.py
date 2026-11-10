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

    verified-claims.jsonl    claims for papers whose every check passed
    unverified-claims.jsonl  claims for all other papers, each with a
                             `verification` field listing what didn't pass

An import script that reads only `verified-claims.jsonl` can't import an
unverified reference by accident.

A paper counts as verified only when the verifier's `corrections.jsonl` has
at least one verdict for it and every verdict is `pass`. A paper with a
`partial`, `fail`, or `unverifiable` verdict, or with no verdict at all, is
unverified: absence of a check is not a pass. If `corrections.jsonl` is
missing or empty, or has a line that can't be read, every paper is
unverified: an unreadable verdict might have been a failure.

Papers are matched by the `doi` field, compared case-insensitively, falling
back to the `claim_id` with its category suffix removed for records that
have no `doi`.

Uses the standard library only.

Usage:
    python3 split_claims.py RUN_FOLDER

Exit status: 0 on success; 2 when the run folder has no final claims.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

CATEGORY_SUFFIX = re.compile(r"-(authors|year|title|citation_count|doi_resolves)$")


def load_jsonl(path: Path) -> list[dict]:
    """
    Read a JSON Lines file, skipping blank and unparseable lines.

    Args:
        path: The file to read. A missing file gives an empty list.

    Returns:
        The records that parsed as JSON objects, in file order.
    """
    if not path.is_file():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def unreadable_lines(path: Path) -> int:
    """
    Count the non-blank lines of a JSON Lines file that are not JSON objects.

    Args:
        path: The file to check. A missing file counts as zero.

    Returns:
        The number of lines that `load_jsonl` would skip.
    """
    if not path.is_file():
        return 0
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return len(lines) - len(load_jsonl(path))


def paper_key(record: dict) -> str:
    """
    Return the key that groups a claim or a verdict with its paper.

    Args:
        record: One claim or correction record.

    Returns:
        The lower-cased DOI when the record has one; otherwise the
        `claim_id` without its category suffix. Empty when it has neither.
    """
    doi = str(record.get("doi") or "").strip().lower()
    if doi:
        return doi
    return CATEGORY_SUFFIX.sub("", str(record.get("claim_id") or "").strip().lower())


def final_iteration(run_folder: Path) -> Path | None:
    """
    Return the highest-numbered `iter-N` folder that has a non-empty `claims.jsonl`.

    Args:
        run_folder: The lit-scout-iterate run folder.

    Returns:
        The folder, or None when no iteration has claims.
    """
    numbered = []
    for path in run_folder.glob("iter-*"):
        suffix = path.name.removeprefix("iter-")
        if path.is_dir() and suffix.isdigit():
            numbered.append((int(suffix), path))
    for _, path in sorted(numbered, reverse=True):
        claims = path / "claims.jsonl"
        if claims.is_file() and claims.stat().st_size > 0:
            return path
    return None


def split(claims: list[dict], corrections: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Divide claims into those for verified papers and those for the rest.

    Args:
        claims: The final iteration's claim records.
        corrections: The final iteration's verdict records.

    Returns:
        Two lists, verified then unverified, each in the claims' order. Each
        unverified claim gains a `verification` field: the paper's verdicts
        that were not `pass`, as "category: status", or "not checked" when
        the verifier gave no verdict for the paper.
    """
    verdicts: dict[str, list[tuple[str, str]]] = {}
    for record in corrections:
        key = paper_key(record)
        if key:
            status = str(record.get("status") or "").strip().lower()
            verdicts.setdefault(key, []).append((str(record.get("category") or "?"), status))

    verified: list[dict] = []
    unverified: list[dict] = []
    for claim in claims:
        found = verdicts.get(paper_key(claim), [])
        problems = [f"{category}: {status or 'no status'}"
                    for category, status in found if status != "pass"]
        if found and not problems:
            verified.append(claim)
        else:
            unverified.append({**claim, "verification": problems or ["not checked"]})
    return verified, unverified


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
    final = final_iteration(run_folder)
    if final is None:
        print(f"split_claims: no iter-N/claims.jsonl under {run_folder}", file=sys.stderr)
        return 2
    claims = load_jsonl(final / "claims.jsonl")
    corrections = load_jsonl(final / "corrections.jsonl")
    unreadable = unreadable_lines(final / "corrections.jsonl")
    if unreadable:
        # A verdict that can't be read might have been a failure, so no
        # paper can be called verified on the strength of the rest.
        print(
            f"split_claims: {unreadable} unreadable line(s) in corrections.jsonl; "
            "treating every paper as unverified",
            file=sys.stderr,
        )
        corrections = []
    verified, unverified = split(claims, corrections)
    write_jsonl(run_folder / "verified-claims.jsonl", verified)
    write_jsonl(run_folder / "unverified-claims.jsonl", unverified)
    print(
        f"{final.name}: {len({paper_key(c) for c in verified})} verified papers, "
        f"{len({paper_key(c) for c in unverified})} unverified"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
