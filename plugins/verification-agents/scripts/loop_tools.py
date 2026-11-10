#!/usr/bin/env python3
"""
loop_tools.py
=============

Two small tools for the closed-loop commands (`lit-scout-iterate` and
`prior-art-scout-iterate`). Each replaces a shell snippet that used to sit in
the command text and went wrong in practice.

    loop_tools.py extract INPUT MARKER OUTPUT
        Copy the machine-readable block out of an agent's Markdown.

    loop_tools.py count CORRECTIONS
        Count the verifier's verdicts by status.

Why they are a script and not shell in the command file:

- Claude Code replaces `$1`, `$2`, and so on in a command file with words
  from the user's request. A shell function written there, with its own
  `$1`, arrived with the query's words in their place.
- The verdicts were counted by searching for the text `"status":"pass"`. A
  verifier that wrote `"status": "pass"`, with a space, was counted as
  having given no verdicts at all, and a run with failed claims would then
  have been reported as a pass. Here every line is parsed as JSON, and a
  line that can't be counted is reported, never ignored.

`extract` looks for the lines `<!-- BEGIN marker -->` and
`<!-- END marker -->` and, between them, a fenced block opened with
```` ```jsonl ````. It writes the block's lines to OUTPUT. Leading
indentation is ignored, since agent output is sometimes relayed indented.

`count` prints one `NAME=value` line for each count, then the failed
claims, for the command to read:

    PASS_CT, PARTIAL_CT, FAIL_CT   verdicts with that status
    UNVER_CT                       `unverifiable`, leaving out the legacy
                                   placeholder
    DOCDEF_CT                      `documentation_defect` (prior-art only)
    LEGACY_CT                      the `_legacy` placeholder
    INVALID_CT                     lines that aren't a verdict: not a JSON
                                   object, no `claim_id`, or an unknown status
    TOTAL_CT                       all non-blank lines; always the sum of
                                   the counts above
    FAIL_SET                       the failed `claim_id`s, sorted, separated
                                   by spaces

Uses the standard library only.

Exit status: `extract` gives 0 when it wrote a block with at least one line,
1 when there was no block or it was empty (OUTPUT is then empty); `count`
gives 0 when every line was a valid verdict, 1 when `INVALID_CT` is above
zero or the file is empty or missing. Both give 2 for a usage error.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

STATUSES = ("pass", "partial", "fail", "unverifiable", "documentation_defect")


def extract_block(text: str, marker: str) -> list[str]:
    """
    Return the lines of the fenced block between a marker's comment lines.

    Args:
        text: An agent's Markdown output.
        marker: The block's name, such as `claims.jsonl`.

    Returns:
        The lines inside the first ```` ```jsonl ```` fence that follows
        `<!-- BEGIN marker -->` and precedes `<!-- END marker -->`, with
        leading and trailing space removed and blank lines dropped. Empty
        when the markers or the fence are missing.
    """
    begin, end = f"<!-- BEGIN {marker} -->", f"<!-- END {marker} -->"
    inside_markers = False
    inside_fence = False
    found: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not inside_markers:
            inside_markers = line == begin
            continue
        if line == end:
            break
        if not inside_fence:
            inside_fence = line.startswith("```jsonl")
            continue
        if line.startswith("```"):
            break
        if line:
            found.append(line)
    return found


def count_verdicts(text: str) -> dict[str, int | str]:
    """
    Count the verdicts in the text of a `corrections.jsonl` file.

    Args:
        text: The file's contents.

    Returns:
        The counts and the failed set described in the module docstring.
        `TOTAL_CT` equals the sum of the other counts by construction.
    """
    counts = {
        "PASS_CT": 0, "PARTIAL_CT": 0, "FAIL_CT": 0, "UNVER_CT": 0,
        "DOCDEF_CT": 0, "LEGACY_CT": 0, "INVALID_CT": 0,
    }
    names = {
        "pass": "PASS_CT", "partial": "PARTIAL_CT", "fail": "FAIL_CT",
        "unverifiable": "UNVER_CT", "documentation_defect": "DOCDEF_CT",
    }
    failed: set[str] = set()
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            record = None
        claim_id = record.get("claim_id") if isinstance(record, dict) else None
        status = record.get("status") if isinstance(record, dict) else None
        if not isinstance(claim_id, str) or not claim_id.strip():
            counts["INVALID_CT"] += 1
        elif claim_id == "_legacy":
            counts["LEGACY_CT"] += 1
        elif not isinstance(status, str) or status.strip().lower() not in STATUSES:
            counts["INVALID_CT"] += 1
        else:
            status = status.strip().lower()
            counts[names[status]] += 1
            if status == "fail":
                failed.add(claim_id.strip())
    result: dict[str, int | str] = dict(counts)
    result["TOTAL_CT"] = sum(counts.values())
    result["FAIL_SET"] = " ".join(sorted(failed))
    return result


def main(argv: list[str]) -> int:
    """Run the `extract` or `count` tool named on the command line."""
    if len(argv) == 5 and argv[1] == "extract":
        source, marker, target = Path(argv[2]), argv[3], Path(argv[4])
        try:
            lines = extract_block(source.read_text(encoding="utf-8", errors="replace"), marker)
        except OSError as error:
            print(f"loop_tools: {error}", file=sys.stderr)
            lines = []
        target.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
        if not lines:
            print(f"loop_tools: no {marker} block found in {source}", file=sys.stderr)
            return 1
        print(f"{len(lines)} line(s) written to {target}")
        return 0
    if len(argv) == 3 and argv[1] == "count":
        path = Path(argv[2])
        text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
        result = count_verdicts(text)
        for name, value in result.items():
            print(f"{name}={value}")
        if result["TOTAL_CT"] == 0:
            print(f"loop_tools: no verdicts in {path}", file=sys.stderr)
            return 1
        if result["INVALID_CT"]:
            print(f"loop_tools: {result['INVALID_CT']} line(s) are not verdicts", file=sys.stderr)
            return 1
        return 0
    print(
        "usage: loop_tools.py extract INPUT MARKER OUTPUT\n"
        "       loop_tools.py count CORRECTIONS",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
