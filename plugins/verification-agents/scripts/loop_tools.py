#!/usr/bin/env python3
"""
loop_tools.py
=============

Two small tools for the closed-loop commands (`lit-scout-iterate` and
`prior-art-scout-iterate`). Each replaces a shell snippet that used to sit in
the command text and went wrong in practice.

    loop_tools.py extract INPUT MARKER OUTPUT
        Copy the machine-readable block out of an agent's Markdown.

    loop_tools.py count LOOP CORRECTIONS
        Count the verifier's verdicts by status and state the outcome.
        LOOP is `lit-scout` or `prior-art`.

Why they are a script and not shell in the command file:

- Claude Code replaces `$1`, `$2`, and so on in a command file with words
  from the user's request. A shell function written there, with its own
  `$1`, arrived with the query's words in their place.
- The verdicts were counted by searching for the text `"status":"pass"`. A
  verifier that wrote `"status": "pass"`, with a space, was counted as
  having given no verdicts at all, and a run with failed claims would then
  have been reported as a pass. Here every line is parsed as JSON, and a
  line that can't be counted is reported, never ignored.

`extract` accepts exactly one shape, and nothing short of it. The text must
hold the line `<!-- BEGIN marker -->` once; the next non-blank line must be
exactly ```` ```jsonl ````; the block's lines follow; then a line that is
exactly ```` ``` ````; then, as the next non-blank line,
`<!-- END marker -->`. A block that is cut short, opened twice, fenced with
another language, or has another marker inside it is refused, because a
truncated report would otherwise pass as a short, clean one. Leading
indentation is ignored, since agent output is sometimes relayed indented.

`count` prints one `NAME=value` line for each of these, for the command to
read:

    PASS_CT, PARTIAL_CT, FAIL_CT   verdicts with that status
    UNVER_CT                       `unverifiable`, leaving out the legacy
                                   placeholder
    DOCDEF_CT                      `documentation_defect` (a status only the
                                   prior-art verifier uses)
    LEGACY_CT                      the `_legacy` placeholder
    INVALID_CT                     lines that aren't a verdict: not a JSON
                                   object, a repeated key, no `claim_id`, a
                                   status this loop doesn't use, or a
                                   `_legacy` record that isn't `unverifiable`
    TOTAL_CT                       all non-blank lines; always the sum of
                                   the counts above
    FAIL_SET                       the failed `claim_id`s, sorted, separated
                                   by spaces
    VERDICT                        the outcome, worked out here so that it
                                   doesn't rest on reading the counts right

`VERDICT` is the first of these that applies: `INVALID` (any invalid line,
or no lines); `LEGACY` (the placeholder is present); `FAIL` (any failed
claim); `PASS` (every verdict is a pass); `UNVERIFIABLE` (lit-scout only:
any claim couldn't be checked); `PARTIAL` (anything else short of a pass).
So `PASS` is never reached by a file with any verdict other than `pass`.

Uses the standard library only.

Exit status: `extract` gives 0 when it wrote a complete block with at least
one line, and 1 otherwise (OUTPUT is then empty); `count` gives 0 unless
`VERDICT` is `INVALID`, when it gives 1. Both give 2 for a usage error.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

#: The statuses each loop's verifier may give.
LOOPS = {
    "lit-scout": ("pass", "partial", "fail", "unverifiable"),
    "prior-art": ("pass", "partial", "fail", "unverifiable", "documentation_defect"),
}
COUNT_NAMES = {
    "pass": "PASS_CT", "partial": "PARTIAL_CT", "fail": "FAIL_CT",
    "unverifiable": "UNVER_CT", "documentation_defect": "DOCDEF_CT",
}


def extract_block(text: str, marker: str) -> list[str] | None:
    """
    Return the lines of a marker's block, if the block is complete.

    Args:
        text: An agent's Markdown output.
        marker: The block's name, such as `claims.jsonl`.

    Returns:
        The non-blank lines of the block, stripped, when the text holds the
        whole shape described in the module docstring. None when anything is
        missing, repeated, out of order, or nested.
    """
    begin, end = f"<!-- BEGIN {marker} -->", f"<!-- END {marker} -->"
    lines = [raw.strip() for raw in text.splitlines()]
    if lines.count(begin) != 1 or lines.count(end) != 1:
        return None
    rest = iter(lines[lines.index(begin) + 1:])
    if next((line for line in rest if line), None) != "```jsonl":
        return None
    found: list[str] = []
    for line in rest:
        if line == "```":
            break
        if line.startswith(("<!-- BEGIN ", "<!-- END ", "```")):
            return None  # another marker or fence inside the block
        if line:
            found.append(line)
    else:
        return None  # the text ended before the closing fence
    if next((line for line in rest if line), None) != end:
        return None
    return found


def parse_record(line: str) -> dict | None:
    """
    Parse one line as a JSON object with no repeated key.

    Python's parser keeps the last of two equal keys, so a record giving
    `status` twice would read as whichever came second. Such a record is
    ambiguous and is refused.

    Args:
        line: One line of a `corrections.jsonl` file.

    Returns:
        The object, or None if the line is not one unambiguous JSON object.
    """
    def no_repeats(pairs: list[tuple[str, object]]) -> dict:
        keys = [key for key, _ in pairs]
        if len(set(keys)) != len(keys):
            raise ValueError("repeated key")
        return dict(pairs)

    try:
        record = json.loads(line, object_pairs_hook=no_repeats)
    except ValueError:  # includes json.JSONDecodeError
        return None
    return record if isinstance(record, dict) else None


def count_verdicts(text: str, loop: str) -> dict[str, int | str]:
    """
    Count the verdicts in the text of a `corrections.jsonl` file.

    Args:
        text: The file's contents.
        loop: `lit-scout` or `prior-art`; decides which statuses are valid.

    Returns:
        The counts, the failed set, and the verdict described in the module
        docstring. `TOTAL_CT` equals the sum of the other counts.
    """
    statuses = LOOPS[loop]
    counts = {name: 0 for name in (*COUNT_NAMES.values(), "LEGACY_CT", "INVALID_CT")}
    failed: set[str] = set()
    for line in text.splitlines():
        if not line.strip():
            continue
        record = parse_record(line) or {}
        claim_id = record.get("claim_id")
        status = record.get("status")
        status = status.strip().lower() if isinstance(status, str) else ""
        if not isinstance(claim_id, str) or not claim_id.strip() or status not in statuses:
            counts["INVALID_CT"] += 1
        elif claim_id.strip() == "_legacy":
            # The placeholder is only ever `unverifiable`; anything else is malformed.
            counts["LEGACY_CT" if status == "unverifiable" else "INVALID_CT"] += 1
        else:
            counts[COUNT_NAMES[status]] += 1
            if status == "fail":
                failed.add(claim_id.strip())
    total = sum(counts.values())
    if counts["INVALID_CT"] or total == 0:
        verdict = "INVALID"
    elif counts["LEGACY_CT"]:
        verdict = "LEGACY"
    elif counts["FAIL_CT"]:
        verdict = "FAIL"
    elif counts["PASS_CT"] == total:
        verdict = "PASS"
    elif loop == "lit-scout" and counts["UNVER_CT"]:
        verdict = "UNVERIFIABLE"
    else:
        verdict = "PARTIAL"
    result: dict[str, int | str] = dict(counts)
    result["TOTAL_CT"] = total
    result["FAIL_SET"] = " ".join(sorted(failed))
    result["VERDICT"] = verdict
    return result


def main(argv: list[str]) -> int:
    """Run the `extract` or `count` tool named on the command line."""
    if len(argv) == 5 and argv[1] == "extract":
        source, marker, target = Path(argv[2]), argv[3], Path(argv[4])
        try:
            lines = extract_block(source.read_text(encoding="utf-8", errors="replace"), marker)
        except OSError as error:
            print(f"loop_tools: {error}", file=sys.stderr)
            lines = None
        target.write_text("".join(line + "\n" for line in lines or []), encoding="utf-8")
        if not lines:
            print(f"loop_tools: no complete {marker} block in {source}", file=sys.stderr)
            return 1
        print(f"{len(lines)} line(s) written to {target}")
        return 0
    if len(argv) == 4 and argv[1] == "count" and argv[2] in LOOPS:
        path = Path(argv[3])
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            print(f"loop_tools: {error}", file=sys.stderr)
            text = ""
        result = count_verdicts(text, argv[2])
        for name, value in result.items():
            print(f"{name}={value}")
        if result["VERDICT"] == "INVALID":
            print(f"loop_tools: the verdicts in {path} can't be relied on", file=sys.stderr)
            return 1
        return 0
    print(
        "usage: loop_tools.py extract INPUT MARKER OUTPUT\n"
        "       loop_tools.py count {lit-scout|prior-art} CORRECTIONS",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
