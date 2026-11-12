#!/usr/bin/env python3
"""
tally_classifications.py
========================

Tally the per-mention records of an entity-classifier report.

The entity-classifier skill writes one record per mention, in its report
template's exact format: a ``### Mention N:`` heading followed by, among
others, these four lines::

    **Entity:** <the entity's name, written the same way in every mention>
    **Classification:** building | organisation | both
    **Confidence:** high | medium | low
    **Flag:** none | for review: <question> | resolved: <decision>

This script reads those lines and prints what the report's classification
summary needs:

1. **Mention counts** under each label, with percentages of all mentions
   (rounded to one decimal place) and how many under each label still have
   an open flag (``for review:``). Flagged mentions are counted like any
   other.
2. **The per-entity roll-up**, in order of first appearance: the entity's
   label counts and open flags; its *provisional* union, over all its
   mentions; its *supported* union, over the mentions not still for review
   (``unresolved`` when none is left); and the recommendation, which is the
   facet when the two unions agree and ``pending review`` when they differ.
3. **Entities by recommendation**, and the mentions by confidence.

A union is ``both`` if it includes both building and organisation, or any
one mention labelled both; otherwise it is the one label its mentions
share. No flagged record is ever dropped: an open flag only keeps a mention
out of the supported union.

The script fails loudly. A record that lacks one of the four lines, repeats
one, or gives a value outside those above, or two records with the same
number, stop it with an error naming the record and its line, and nothing
is printed to standard output. Fenced code blocks are skipped, so the
template's own examples are not counted, and any other heading ends the
current record.

Usage::

    python3 -I tally_classifications.py REPORT.md          # Markdown tables
    python3 -I tally_classifications.py REPORT.md --json   # the same, as JSON

The Markdown tables use the report template's column headings, so they can
be copied into its classification summary as they stand.

Exit status: 0 on success; 1 if the report cannot be read or a record is
malformed; 2 on a usage error.

Requires Python 3.11 or later; standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# The values the report template allows, in the order the tables list them.
LABELS: tuple[str, ...] = ("building", "organisation", "both")
CONFIDENCES: tuple[str, ...] = ("high", "medium", "low")
REQUIRED: tuple[str, ...] = ("entity", "classification", "confidence", "flag")

# The two non-facet outcomes of the roll-up.
UNRESOLVED = "unresolved"
PENDING = "pending review"
RECOMMENDATIONS: tuple[str, ...] = (*LABELS, PENDING)

# The three states of a Flag line: no flag, an open flag, a settled one.
FLAG_NONE = "none"
FLAG_OPEN = "for review"
FLAG_RESOLVED = "resolved"

MENTION_HEADING = re.compile(r"^###\s+Mention\s+(\d+)\s*:")
# Any heading that starts with "Mention", at any level, case ignored: one that does not
# match MENTION_HEADING exactly is a malformed record, not prose (review finding R42).
MENTION_LIKE = re.compile(r"^#{1,6}\s*mention\b", re.IGNORECASE)
SECTION = re.compile(r"^##\s+(.*?)\s*$")
DETAILED = "detailed analysis"
ANY_HEADING = re.compile(r"^#{1,6}\s")
FIELD = re.compile(r"^\*\*(Entity|Classification|Confidence|Flag):\*\*[ \t]*(.*?)\s*$")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})")

# Column headings, matching the report template's two summary tables.
MENTION_HEADER = "| Mention label | Count | Percentage | Flagged |"
ENTITY_HEADER = (
    "| Entity | Mentions | Building | Org. | Both | Flagged | Provisional | Supported "
    "| Recommendation |"
)


class ReportError(ValueError):
    """A report that cannot be tallied: a missing, repeated, or invalid line."""


@dataclass(frozen=True)
class Mention:
    """One per-mention record, with its values checked and normalised."""

    number: int
    line: int
    entity: str
    classification: str
    confidence: str
    flag: str

    @property
    def is_open(self) -> bool:
        """True if the mention is still for review."""
        return self.flag == FLAG_OPEN


def _flag_state(value: str) -> str | None:
    """Return the state a Flag value names, or None if it names none.

    ``none`` is no flag; ``for review: …`` is an open flag; ``resolved: …``
    is one a reviewer has settled. Case is ignored; the colon is required.
    """
    lowered = value.lower()
    if lowered == FLAG_NONE:
        return FLAG_NONE
    # Both flag forms need text after the colon: an open flag names its
    # question, a settled one its decision (review finding R43). An empty
    # "resolved:" would otherwise turn a pending entity firm with no
    # decision recorded.
    for state in (FLAG_OPEN, FLAG_RESOLVED):
        prefix = state + ":"
        if lowered.startswith(prefix):
            return state if value[len(prefix):].strip() else None
    return None


def _check(raw: dict[str, Any]) -> Mention:
    """Validate one raw record and return it as a Mention.

    Raises ReportError naming the record if a required line is missing or
    holds a value the template does not allow.
    """
    where = f"mention {raw['number']} (line {raw['line']})"
    missing = [key for key in REQUIRED if key not in raw]
    if missing:
        lines = ", ".join(f"**{key.capitalize()}:**" for key in missing)
        raise ReportError(f"{where}: no {lines} line")

    entity = raw["entity"]
    if not entity:
        raise ReportError(f"{where}: the **Entity:** line is empty")
    label = raw["classification"].lower()
    if label not in LABELS:
        raise ReportError(
            f"{where}: classification {raw['classification']!r} is not one of "
            f"{', '.join(LABELS)}"
        )
    confidence = raw["confidence"].lower()
    if confidence not in CONFIDENCES:
        raise ReportError(
            f"{where}: confidence {raw['confidence']!r} is not one of "
            f"{', '.join(CONFIDENCES)}"
        )
    flag = _flag_state(raw["flag"])
    if flag is None:
        raise ReportError(
            f"{where}: flag {raw['flag']!r} is not 'none', 'for review: <question>', "
            "or 'resolved: <decision>'"
        )
    return Mention(raw["number"], raw["line"], entity, label, confidence, flag)


def parse_report(text: str) -> list[Mention]:
    """Return the report's per-mention records, in order.

    A record starts at a ``### Mention N:`` heading and ends at the next
    heading of any level. Fenced code blocks are skipped. Raises ReportError
    if there are no records, if any record is malformed, or if two records
    share a number.
    """
    raw_records: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    fence: str | None = None
    section = ""  # the current level-two heading, lower-cased

    for line_no, line in enumerate(text.splitlines(), 1):
        # Skip fenced blocks: the template's review-block example holds a
        # "### Mention N:" heading that must not be counted.
        opener = FENCE.match(line)
        if fence is not None:
            if opener and opener.group(1)[0] == fence[0] and len(opener.group(1)) >= len(fence):
                fence = None
            continue
        if opener:
            fence = opener.group(1)
            continue

        heading = MENTION_HEADING.match(line)
        if heading:
            current = {"number": int(heading.group(1)), "line": line_no}
            raw_records.append(current)
            continue
        if MENTION_LIKE.match(line):
            raise ReportError(
                f"line {line_no}: malformed mention heading {line.strip()!r}; "
                "expected '### Mention N: …' with N a number"
            )
        level_two = SECTION.match(line)
        if level_two:
            section = level_two.group(1).lower()
        if ANY_HEADING.match(line):
            # Any other heading (Pattern analysis, say) closes the record,
            # so a stray field line further down cannot attach to it.
            current = None
            continue

        field = FIELD.match(line)
        if field and current is None and section.startswith(DETAILED):
            # A record's field line with no record to belong to: its heading
            # was malformed or a sub-heading cut it off (review finding R42).
            raise ReportError(
                f"line {line_no}: a **{field.group(1)}:** line in Detailed analysis "
                "outside any '### Mention N:' record"
            )
        if field and current is not None:
            key = field.group(1).lower()
            if key in current:
                raise ReportError(
                    f"mention {current['number']} (line {current['line']}): "
                    f"a second **{field.group(1)}:** line at line {line_no}"
                )
            current[key] = field.group(2)

    if fence is not None:
        raise ReportError("a fenced code block is never closed")
    if not raw_records:
        raise ReportError("no '### Mention N:' records found")

    mentions = [_check(raw) for raw in raw_records]
    first_line: dict[int, int] = {}
    for mention in mentions:
        if mention.number in first_line:
            raise ReportError(
                f"mention {mention.number} appears twice (lines "
                f"{first_line[mention.number]} and {mention.line})"
            )
        first_line[mention.number] = mention.line
    return mentions


def union(labels: Iterable[str]) -> str:
    """Return the union of mention labels under the skill's roll-up rule.

    ``both`` if the labels include both building and organisation, or any
    ``both``; otherwise the one label they share; ``unresolved`` if there
    are none.
    """
    present = set(labels)
    if not present:
        return UNRESOLVED
    if "both" in present or {"building", "organisation"} <= present:
        return "both"
    (only,) = present
    return only


def tally(mentions: list[Mention]) -> dict[str, Any]:
    """Return every figure the report's summary needs, as plain data."""
    total = len(mentions)
    label_counts = Counter(m.classification for m in mentions)
    label_open = Counter(m.classification for m in mentions if m.is_open)

    # Group by entity, in order of first appearance.
    by_entity: dict[str, list[Mention]] = {}
    for mention in mentions:
        by_entity.setdefault(mention.entity, []).append(mention)

    entities: list[dict[str, Any]] = []
    for name, group in by_entity.items():
        counts = Counter(m.classification for m in group)
        provisional = union(m.classification for m in group)
        supported = union(m.classification for m in group if not m.is_open)
        entities.append({
            "entity": name,
            "mentions": len(group),
            **{label: counts[label] for label in LABELS},
            "flagged": sum(m.is_open for m in group),
            "resolved": sum(m.flag == FLAG_RESOLVED for m in group),
            "provisional": provisional,
            "supported": supported,
            "recommendation": provisional if provisional == supported else PENDING,
            "mention_numbers": [m.number for m in group],
        })

    by_recommendation = Counter(e["recommendation"] for e in entities)
    return {
        "mentions": {
            "total": total,
            "flagged": sum(m.is_open for m in mentions),
            "resolved": sum(m.flag == FLAG_RESOLVED for m in mentions),
            "by_label": {
                label: {
                    "count": label_counts[label],
                    "percentage": round(100 * label_counts[label] / total, 1),
                    "flagged": label_open[label],
                }
                for label in LABELS
            },
            "by_confidence": {c: sum(m.confidence == c for m in mentions)
                              for c in CONFIDENCES},
        },
        "entities": entities,
        "by_recommendation": {r: by_recommendation[r] for r in RECOMMENDATIONS},
    }


def near_duplicate_entities(mentions: list[Mention]) -> list[list[str]]:
    """Return groups of entity names that differ only in case or spacing.

    The skill asks for each entity's name to be written the same way in
    every mention; names that differ only so are probably one entity
    counted as two.
    """
    groups: dict[str, set[str]] = {}
    for mention in mentions:
        key = " ".join(mention.entity.split()).casefold()
        groups.setdefault(key, set()).add(mention.entity)
    return [sorted(names) for names in groups.values() if len(names) > 1]


def _cell(text: str) -> str:
    """Escape a value for a Markdown table cell."""
    return text.replace("|", "\\|")


def render_markdown(summary: dict[str, Any]) -> str:
    """Render the tally as the report template's two tables and two lines."""
    m = summary["mentions"]
    out = [f"Mentions: {m['total']} ({m['flagged']} flagged, {m['resolved']} resolved)",
           f"Entities: {len(summary['entities'])}", "",
           MENTION_HEADER, "| --- | --- | --- | --- |"]
    for label in LABELS:
        row = m["by_label"][label]
        out.append(f"| {label.capitalize()} | {row['count']} | {row['percentage']:.1f}% "
                   f"| {row['flagged']} |")
    out += [f"| **Total** | **{m['total']}** | **100%** | **{m['flagged']}** |", "",
            ENTITY_HEADER, "| --- " * 9 + "|"]
    for e in summary["entities"]:
        out.append(
            f"| {_cell(e['entity'])} | {e['mentions']} | {e['building']} | "
            f"{e['organisation']} | {e['both']} | {e['flagged']} | {e['provisional']} | "
            f"{e['supported']} | {e['recommendation']} |"
        )
    r = summary["by_recommendation"]
    c = m["by_confidence"]
    out += ["",
            f"**Entities by recommendation:** {r['building']} building only, "
            f"{r['organisation']} business or organisation only, {r['both']} both, "
            f"and {r[PENDING]} pending review.",
            "",
            f"**Mentions by confidence:** {c['high']} high, {c['medium']} medium, "
            f"and {c['low']} low."]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Read the report named on the command line and print its tally."""
    parser = argparse.ArgumentParser(
        prog="tally_classifications.py",
        description="Tally the per-mention records of an entity-classifier report.",
    )
    parser.add_argument("report", type=Path, help="the classification report (Markdown)")
    parser.add_argument("--json", action="store_true", help="print JSON, not Markdown")
    args = parser.parse_args(argv)

    try:
        mentions = parse_report(args.report.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ReportError) as error:
        print(f"{parser.prog}: error: {args.report}: {error}", file=sys.stderr)
        return 1

    for names in near_duplicate_entities(mentions):
        print(f"{parser.prog}: warning: entity names differ only in case or spacing, "
              f"so are counted apart: {names}", file=sys.stderr)

    summary = tally(mentions)
    if args.json:
        print(json.dumps({"report": str(args.report), **summary}, indent=2))
    else:
        print(render_markdown(summary), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
