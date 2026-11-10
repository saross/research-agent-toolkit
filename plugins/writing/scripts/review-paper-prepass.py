#!/usr/bin/env python3
"""Mechanical pre-pass for the review-paper skill of the writing plugin.

Deterministic checks, with no language model, that run BEFORE any review
agent is dispatched. Findings feed the review report directly and are merged
into the workflow's deterministic severity aggregation through the
``prepassFindings`` argument of ``scripts/review-paper.mjs`` (beside this
script).

Checks (each degrades gracefully to a ``checks_skipped`` entry if its tool or
input is unavailable):

1.  Spelling — ``aspell`` in TeX mode, in the language given by
    ``--spell-lang`` (for example ``en_GB``), or aspell's own default.
2.  Doubled words ("the the"), including across line breaks and ``~`` ties.
3.  Dash consistency — spaced-hyphen-as-dash, digit ranges with a single
    hyphen, and optional compound tokens (``--dash-token human--AI`` flags
    the single-hyphen variant ``human-AI``).
4.  Brace/paren balance (majors on braces; parens advisory).
5.  Citation resolution — every key used by ANY command whose name contains
    "cite" (the full natbib/biblatex family — a ``\\citealp``-shaped miss
    once produced a false "uncited" finding in a real review) must be
    defined in the supplied ``.bib`` files. Scans the whole text, so
    citations wrapped across lines are still caught.
6.  Word budget — ``texcount -1 -sum`` per target vs ``--word-budget``.
7.  Aux-label sanity — every ``\\ref``-family target read back from the
    ``.aux``; flags missing labels (minor — forthcoming labels are expected
    while drafting) and implausible resolutions (major — three or more
    referenced labels WITH THE SAME PREFIX all resolving to one number, the
    starred-section symptom that once silently broke seven supplement
    refs in a real paper; grouping by prefix avoids false positives from different
    counters, e.g. sec 1 / fig 1 / tab 1).
8.  Guard-comment anchor freshness — ``path:line`` anchors inside comment
    blocks must point at an existing file and an in-range line.
9.  Build-convergence gate (opt-in via ``--build-cmd``) — a failed build is
    a blocker.

The script also extracts each target's settled-rulings register (the
STANDING GUARDS / wording-guards comment block) so the caller can pass it to
the review panel as author-settled context ("do not re-flag").

Output: a single JSON document (stdout, or ``--json-out``) with ``findings``
(``{check, severity, detail, evidence, target}``), ``settled_rulings``
(keyed by the repo-relative ``--target`` path — the workflow also matches
these keys against its absolute target paths), ``word_counts``,
``checks_run``/``checks_skipped``, and severity ``counts``. Severities:
``blocker`` / ``major`` / ``minor`` / ``info`` (``info`` never gates a
verdict).

Known, deliberate limitations: verbatim environments are not special-cased;
nested braces inside citation optional notes and ``\\newlabel`` values are
not parsed; the exit code is 0 even when findings include blockers (callers
consume the JSON, not the exit status).

The script uses only the Python standard library. aspell, texcount, and a
build command are optional: each check that needs one is skipped, and says
so, when it is missing.

Usage:
    python3 review-paper-prepass.py --repo /path/to/paper-repo \\
        --target sections/03-methodology.tex \\
        --bib 'refs/*.bib' --aux main.aux --spell-lang en_GB \\
        --word-budget 660 --dash-token 'human--AI'
"""

from __future__ import annotations

import argparse
import glob as globmod
import json
import pathlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

MAX_SPELLING_WORDS = 40          # cap the word list in a spelling finding
IMPLAUSIBLE_SHARED_NUMBER = 3    # >= this many same-prefix labels sharing one number
SUBPROCESS_TIMEOUT = 120         # seconds, aspell/texcount
BUILD_TIMEOUT_SECONDS = 600

# Any command whose name contains "cite", with its optional-note/key argument
# train. Keys live in the brace groups; bracket/paren groups are pre/post notes.
CITE_COMMAND = re.compile(
    r'\\[A-Za-z]*[cC]ite[A-Za-z]*\*?'
    r'((?:\[[^\]]*\]|\([^)]*\)|\{[^{}]*\})+)'
)
# Commands in the family above whose brace groups are (or include) literal
# text rather than pure citekeys. Excluding them wholesale trades a little
# coverage on rare commands for zero false majors (false majors gate the
# verdict; unchecked rare commands do not).
NON_KEY_CITE_COMMANDS = {'citetext', 'defcitealias', 'citename', 'citefield',
                         'citeurl', 'volcite'}
BRACE_GROUP = re.compile(r'\{([^{}]*)\}')
# Accepts both brace- and paren-delimited entries; skips @string/@comment/@preamble.
BIB_ENTRY = re.compile(r'@(\w+)\s*[{(]\s*([^,\s{}()]+)\s*,')
NON_ENTRY_BIB_TYPES = {'string', 'comment', 'preamble'}
# The \ref family, argument-train style so \crefrange{a}{b} yields both labels.
REF_COMMAND = re.compile(
    r'\\(?:ref|autoref|cref|Cref|crefrange|Crefrange|vref|pageref|eqref'
    r'|nameref|Nameref|labelcref)\*?'
    r'((?:\{[^{}]*\})+)'
)
NEWLABEL = re.compile(r'\\newlabel\{([^{}]*)\}\{\{([^{}]*)\}')
# ``~`` counts as a separator so "the~the" is caught too.
DOUBLED_WORD = re.compile(r'\b([A-Za-z]{2,})[ \t~]+\1\b', re.IGNORECASE)
GUARD_ANCHOR = re.compile(r'([\w./-]+\.(?:tex|md|py|bib|mjs|sty|cls)):(\d+)')
GUARD_BLOCK_MARKER = re.compile(r'STANDING[ -]GUARD|wording[ -]guard', re.IGNORECASE)
ISO_DATE = re.compile(r'\d{4}-\d{2}(-\d{2})?')


def finding(check: str, severity: str, detail: str, evidence: str, target: str) -> dict:
    """Build one finding record in the shape the workflow's aggregation expects."""
    return {
        'check': check,
        'severity': severity,
        'detail': detail,
        'evidence': evidence,
        'target': target,
    }


def add_skip(skipped: list[dict], check: str, reason: str) -> None:
    """Record a skip once — per-target loops would otherwise duplicate entries."""
    entry = {'check': check, 'reason': reason}
    if entry not in skipped:
        skipped.append(entry)


def strip_comments(text: str) -> str:
    """Remove TeX comments (unescaped ``%`` to end of line), preserving line count.

    A ``%`` starts a comment when preceded by an EVEN number of backslashes
    (``\\%`` is an escaped percent; ``\\\\%`` is a line break then a real
    comment). Verbatim environments are not special-cased — an acceptable
    simplification for prose sections.
    """
    out_lines = []
    for line in text.splitlines():
        stripped = re.sub(r'((?:^|[^\\])(?:\\\\)*)%.*$', r'\1', line)
        out_lines.append(stripped)
    return '\n'.join(out_lines)


def line_of_offset(text: str, offset: int) -> int:
    """1-based line number of a character offset (for whole-text regex scans)."""
    return text.count('\n', 0, offset) + 1


def comment_lines(text: str) -> list[tuple[int, str]]:
    """Return (1-based line number, line) for every comment-only line."""
    result = []
    for i, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith('%'):
            result.append((i, line))
    return result


# ---------------------------------------------------------------------------
# Individual checks. Each returns a list of findings; checks with a skip path
# record actual execution in ``ran``.
# ---------------------------------------------------------------------------

def check_spelling(raw_text: str, rel: str, skipped: list[dict],
                   ran: set[str], lang: str | None = None) -> list[dict]:
    """Run aspell in TeX mode and report unknown words as one minor finding.

    ``lang`` is an aspell dictionary code such as ``en_GB``; with none, aspell
    uses its own default, which follows the system locale.
    """
    if shutil.which('aspell') is None:
        add_skip(skipped, 'spelling', 'aspell not installed')
        return []
    lang_args = [f'--lang={lang}'] if lang else []
    try:
        proc = subprocess.run(
            ['aspell', '--mode=tex', *lang_args, 'list'],
            input=raw_text,
            capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        add_skip(skipped, 'spelling', f'aspell timed out after {SUBPROCESS_TIMEOUT}s')
        return []
    if proc.returncode != 0:
        add_skip(skipped, 'spelling', f'aspell failed: {proc.stderr.strip()}')
        return []
    ran.add('spelling')
    # aspell's TeX filter does not skip citation arguments, so citekey fragments
    # surface as "misspellings". Suppress words that are TOKENS of a citekey
    # used in this file (tokenised, not substring — substring matching would
    # let "theory_2020" mask a genuine "the the" typo word).
    citekey_text = ' '.join(
        group for m in CITE_COMMAND.finditer(raw_text)
        for group in BRACE_GROUP.findall(m.group(1))
    )
    citekey_tokens = {t for t in re.split(r'[^A-Za-z]+', citekey_text.lower()) if t}
    words = sorted({
        w for w in proc.stdout.split()
        # Acronyms, single letters, and anything with a digit are triage noise.
        if not w.isupper() and len(w) > 1 and not any(c.isdigit() for c in w)
        and w.lower() not in citekey_tokens
    })
    if not words:
        return []
    shown = words[:MAX_SPELLING_WORDS]
    overflow = f' (+{len(words) - len(shown)} more)' if len(words) > len(shown) else ''
    dictionary = lang or "aspell's default dictionary"
    return [finding(
        'spelling', 'minor',
        f'{len(words)} words unknown to aspell, {dictionary} (author triage — '
        f'includes proper nouns and jargon): {", ".join(shown)}{overflow}',
        f'aspell --mode=tex {" ".join(lang_args) + " " if lang_args else ""}list < {rel}',
        rel,
    )]


def check_doubled_words(text: str, rel: str) -> list[dict]:
    """Flag immediately repeated words, including pairs split across a line break."""
    found = []
    lines = text.splitlines()
    for i, line in enumerate(lines, start=1):
        for m in DOUBLED_WORD.finditer(line):
            found.append(finding(
                'doubled-words', 'minor',
                f'doubled word "{m.group(1)}" (may be legitimate — e.g. "had had")',
                f'{rel}:{i}', rel,
            ))
    # Across line boundaries: last word of one line == first word of the next.
    for i in range(len(lines) - 1):
        tail = re.search(r'([A-Za-z]{2,})\s*$', lines[i])
        head = re.match(r'\s*([A-Za-z]{2,})\b', lines[i + 1])
        if tail and head and tail.group(1).lower() == head.group(1).lower():
            found.append(finding(
                'doubled-words', 'minor',
                f'doubled word "{tail.group(1)}" across the line break',
                f'{rel}:{i + 1}-{i + 2}', rel,
            ))
    return found


def check_dashes(text: str, rel: str, dash_tokens: list[str]) -> list[dict]:
    """Dash-convention checks: spaced hyphens, digit ranges, compound tokens."""
    found = []
    lines = text.splitlines()
    for i, line in enumerate(lines, start=1):
        if re.search(r'[A-Za-z\d,)] - [A-Za-z\d(]', line):
            found.append(finding(
                'dash-consistency', 'minor',
                'spaced hyphen used as a dash (house style wants "---" or "--")',
                f'{rel}:{i}', rel,
            ))
        # Digit ranges want an en dash. Suppress the noisiest false-positive
        # classes: ISO dates, and lines whose hyphenated digits live inside
        # \label/\cite/\url-style arguments rather than prose.
        if re.search(r'(?<=\d)-(?=\d)', line):
            prose = ISO_DATE.sub('', line)
            if (re.search(r'(?<=\d)-(?=\d)', prose)
                    and not re.search(r'\\(?:label|url|href|path|[A-Za-z]*[cC]ite)', line)):
                found.append(finding(
                    'dash-consistency', 'minor',
                    'digit range with a single hyphen — ranges want an en dash ("--")',
                    f'{rel}:{i}', rel,
                ))
    for token in dash_tokens:
        if '--' not in token:
            continue
        single = token.replace('--', '-')
        # Word-boundary match so "superhuman-AI" does not trip token "human--AI".
        single_re = re.compile(rf'(?<![\w-]){re.escape(single)}(?![\w-])')
        for i, line in enumerate(lines, start=1):
            if single_re.search(line):
                found.append(finding(
                    'dash-consistency', 'minor',
                    f'"{single}" should be "{token}" per the declared dash token',
                    f'{rel}:{i}', rel,
                ))
    return found


def check_balance(text: str, rel: str) -> list[dict]:
    """Report unbalanced braces (major) and parens (minor) on comment-stripped text."""
    found = []
    for open_c, close_c, severity in (('{', '}', 'major'), ('(', ')', 'minor')):
        depth = 0
        first_negative = None
        for i, line in enumerate(text.splitlines(), start=1):
            j = 0
            while j < len(line):
                ch = line[j]
                if ch == '\\':          # skip escaped characters (\{, \}, \%, ...)
                    j += 2
                    continue
                if ch == open_c:
                    depth += 1
                elif ch == close_c:
                    depth -= 1
                    if depth < 0 and first_negative is None:
                        first_negative = i
                j += 1
        if depth != 0 or first_negative is not None:
            where = (f'first goes negative at {rel}:{first_negative}'
                     if first_negative is not None else f'net imbalance {depth:+d}')
            found.append(finding(
                'balance', severity,
                f'unbalanced "{open_c}{close_c}" ({where})',
                where, rel,
            ))
    return found


def collect_bib_keys(bib_paths: list[Path]) -> set[str]:
    """Extract every entry key defined across the supplied .bib files."""
    keys: set[str] = set()
    for bib in bib_paths:
        for m in BIB_ENTRY.finditer(bib.read_text(encoding='utf-8', errors='replace')):
            if m.group(1).lower() not in NON_ENTRY_BIB_TYPES:
                keys.add(m.group(2))
    return keys


def check_citations(text: str, rel: str, bib_keys: set[str], skipped: list[dict],
                    have_bibs: bool, ran: set[str]) -> list[dict]:
    """Every citekey used by any \\...cite... command must resolve in the bibs.

    Scans the WHOLE text (not per line) so citations wrapped across lines —
    standard at 80-column wrap — are still checked.
    """
    if not have_bibs:
        add_skip(skipped, 'citation-resolution', 'no .bib files supplied')
        return []
    ran.add('citation-resolution')
    found = []
    for m in CITE_COMMAND.finditer(text):
        command = m.group(0).split('[')[0].split('{')[0].split('(')[0].lstrip('\\').rstrip('*')
        if command.lower() in NON_KEY_CITE_COMMANDS:
            continue
        line_no = line_of_offset(text, m.start())
        for group in BRACE_GROUP.findall(m.group(1)):
            for key in (k.strip() for k in group.split(',')):
                if key == '*':          # \nocite{*} — include-everything idiom
                    continue
                if key and key not in bib_keys:
                    found.append(finding(
                        'citation-resolution', 'major',
                        f'citekey "{key}" (via \\{command}) is not defined in the '
                        'supplied .bib files',
                        f'{rel}:{line_no}', rel,
                    ))
    return found


def check_word_budget(target: Path, rel: str, budget: int | None, skipped: list[dict],
                      word_counts: dict[str, int], ran: set[str]) -> list[dict]:
    """Count words with texcount; flag (major) if over the declared budget."""
    if shutil.which('texcount') is None:
        add_skip(skipped, 'word-budget', 'texcount not installed')
        return []
    try:
        proc = subprocess.run(
            ['texcount', '-1', '-sum', '-q', str(target)],
            capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        add_skip(skipped, 'word-budget', f'texcount timed out after {SUBPROCESS_TIMEOUT}s')
        return []
    # With -1 -sum -q the count is a line that is EXACTLY an integer (usually
    # the last, but "(errors:N)" trails it when the TeX has problems — and a
    # loose \d+ search would swallow that N as the count). Scan from the end
    # for the integer-only line.
    count_line = next(
        (ln for ln in reversed(proc.stdout.strip().splitlines())
         if re.fullmatch(r'\s*\d+\s*', ln)),
        None)
    if proc.returncode != 0 or count_line is None:
        add_skip(skipped, 'word-budget',
                 f'texcount failed: {(proc.stderr or proc.stdout).strip()}')
        return []
    ran.add('word-budget')
    count = int(count_line)
    word_counts[rel] = count
    if budget is not None and count > budget:
        return [finding(
            'word-budget', 'major',
            f'{count} words exceeds the {budget}-word budget',
            f'texcount -1 -sum {rel} -> {count}', rel,
        )]
    return []


def label_prefix(label: str) -> str:
    """Label family for grouping: the part before the first colon (or the label)."""
    return label.split(':', 1)[0] if ':' in label else label


def check_aux_labels(text: str, rel: str, aux_labels: dict[str, str] | None,
                     skipped: list[dict], ran: set[str]) -> list[dict]:
    """Read every \\ref-family target back from the .aux and flag implausible cases.

    The real-paper catch this encodes: labels on starred sections never step the
    counter, so many labels silently resolve to the SAME number while every
    build looks clean. Grouping is per label PREFIX (``sec:``, ``supp:``, ...)
    because different counters legitimately share numbers (section 1, figure
    1, table 1). Missing labels are only minor — undefined-but-forthcoming
    targets are expected while drafting.
    """
    if aux_labels is None:
        add_skip(skipped, 'aux-labels', 'no .aux file supplied/found')
        return []
    ran.add('aux-labels')
    found = []
    referenced: dict[str, str] = {}
    empty_flagged: set[str] = set()
    for i, line in enumerate(text.splitlines(), start=1):
        for m in REF_COMMAND.finditer(line):
            for label in (g.strip() for g in BRACE_GROUP.findall(m.group(1))):
                if not label:
                    continue
                if label not in aux_labels:
                    found.append(finding(
                        'aux-labels', 'minor',
                        f'\\ref target "{label}" not in the .aux (expected if '
                        'forthcoming; a defect if the label should exist)',
                        f'{rel}:{i}', rel,
                    ))
                    continue
                referenced[label] = aux_labels[label]
                if aux_labels[label].strip() == '' and label not in empty_flagged:
                    empty_flagged.add(label)          # one finding per label, not per use
                    found.append(finding(
                        'aux-labels', 'major',
                        f'label "{label}" resolves to an EMPTY number — likely attached '
                        'to a starred (uncounted) sectioning command',
                        f'\\newlabel{{{label}}} in .aux', rel,
                    ))
    by_group: dict[tuple[str, str], list[str]] = {}
    for label, number in referenced.items():
        by_group.setdefault((label_prefix(label), number), []).append(label)
    for (prefix, number), labels in by_group.items():
        if len(labels) >= IMPLAUSIBLE_SHARED_NUMBER:
            found.append(finding(
                'aux-labels', 'major',
                f'{len(labels)} referenced "{prefix}:" labels all resolve to "{number}" '
                f'({", ".join(sorted(labels))}) — the starred-section symptom; '
                'check the labels sit on numbered commands',
                '.aux \\newlabel values', rel,
            ))
    return found


def _contained_candidates(
    anchor_path: str, repo: Path, target: Path
) -> list[Path]:
    """Resolve an anchor path, discarding anything outside ``repo``.

    Audit round 4d (E17): the anchor text comes from a comment inside the
    manuscript, and nothing constrained it. ``../../.ssh/config`` or an
    absolute path resolved happily, and the "stale anchor" finding then
    reported whether that file exists and how many lines it has — a small
    read-only probe of the filesystem, driven by text in a .tex file. An
    anchor is by definition a pointer into the repository, so anything
    that escapes it is simply not a candidate.

    Args:
        anchor_path: The path as written in the comment.
        repo: Repository root the run is scoped to.
        target: The file the anchor was written in.

    Returns:
        Existing-or-not candidate paths that stay inside ``repo``.
    """
    if pathlib.PurePosixPath(anchor_path).is_absolute():
        return []
    repo_root = repo.resolve()
    contained = []
    for base in (repo, target.parent):
        candidate = (base / anchor_path).resolve()
        if candidate == repo_root or repo_root in candidate.parents:
            contained.append(candidate)
    return contained


def check_guard_anchors(raw_text: str, rel: str, repo: Path, target: Path) -> list[dict]:
    """Verify path:line anchors inside comment blocks still point at real lines."""
    found = []
    for line_no, line in comment_lines(raw_text):
        for m in GUARD_ANCHOR.finditer(line):
            anchor_path, anchor_line = m.group(1), int(m.group(2))
            candidates = _contained_candidates(anchor_path, repo, target)
            existing = next((c for c in candidates if c.is_file()), None)
            if existing is None:
                found.append(finding(
                    'guard-anchors', 'minor',
                    f'comment anchor "{anchor_path}:{anchor_line}" points at a file '
                    'that does not exist (stale anchor)',
                    f'{rel}:{line_no}', rel,
                ))
                continue
            n_lines = len(existing.read_text(encoding='utf-8', errors='replace').splitlines())
            if not 1 <= anchor_line <= n_lines:
                found.append(finding(
                    'guard-anchors', 'minor',
                    f'comment anchor "{anchor_path}:{anchor_line}" is out of range '
                    f'(file has {n_lines} lines) — stale anchor',
                    f'{rel}:{line_no}', rel,
                ))
    return found


def extract_settled_rulings(raw_text: str) -> str | None:
    """Extract the STANDING GUARDS / wording-guards comment block(s), verbatim.

    Contiguous runs of comment lines are treated as one block; every block
    containing a guard marker is returned (joined) so the caller can hand the
    register to review agents as author-settled context.
    """
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in raw_text.splitlines():
        if line.lstrip().startswith('%'):
            current.append(line)
        else:
            if current:
                blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    guard_blocks = ['\n'.join(b) for b in blocks if GUARD_BLOCK_MARKER.search('\n'.join(b))]
    return '\n\n'.join(guard_blocks) if guard_blocks else None


def run_build_gate(build_cmd: str, repo: Path) -> list[dict]:
    """Opt-in build-convergence gate: a failing build is a blocker."""
    try:
        proc = subprocess.run(
            build_cmd, shell=True, cwd=repo,
            capture_output=True, text=True, timeout=BUILD_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return [finding('build-gate', 'blocker',
                        f'build command timed out after {BUILD_TIMEOUT_SECONDS}s',
                        build_cmd, str(repo))]
    if proc.returncode != 0:
        tail = '\n'.join((proc.stdout + proc.stderr).splitlines()[-15:])
        return [finding('build-gate', 'blocker',
                        f'build command failed (exit {proc.returncode}): ...{tail}',
                        build_cmd, str(repo))]
    return []


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description='Deterministic mechanical pre-pass for the review-paper skill.')
    parser.add_argument('--repo', required=True, type=Path,
                        help='paper repository root (checks resolve paths against it)')
    parser.add_argument('--target', action='append', required=True, dest='targets',
                        help='target .tex file, relative to --repo (repeatable)')
    parser.add_argument('--bib', action='append', default=[], dest='bibs',
                        help='.bib path or glob, relative to --repo or absolute '
                             '(repeatable)')
    parser.add_argument('--aux', type=Path, default=None,
                        help='.aux file for label sanity (relative to --repo)')
    parser.add_argument('--spell-lang', default=None,
                        help='aspell dictionary for the spelling check, e.g. en_GB, '
                             'en_AU, or en_US (default: aspell\'s own default)')
    parser.add_argument('--word-budget', type=int, default=None,
                        help='per-target word budget (texcount)')
    parser.add_argument('--dash-token', action='append', default=[], dest='dash_tokens',
                        help='compound token whose en-dash form is canonical, '
                             'e.g. "human--AI" (repeatable)')
    parser.add_argument('--build-cmd', default=None,
                        help='opt-in build-convergence gate command, run in --repo')
    parser.add_argument('--json-out', type=Path, default=None,
                        help='write the JSON report here instead of stdout')
    args = parser.parse_args()

    repo: Path = args.repo.resolve()
    if not repo.is_dir():
        print(f'error: --repo {repo} is not a directory', file=sys.stderr)
        return 2

    findings: list[dict] = []
    skipped: list[dict] = []
    ran: set[str] = set()
    settled_rulings: dict[str, str] = {}
    word_counts: dict[str, int] = {}

    bib_paths: list[Path] = []
    for pattern in args.bibs:
        # Path.glob rejects absolute patterns — route those through glob.glob.
        if Path(pattern).is_absolute():
            matches = sorted(Path(p) for p in globmod.glob(pattern))
        else:
            matches = sorted(repo.glob(pattern))
        if not matches:
            add_skip(skipped, 'citation-resolution',
                     f'--bib pattern matched nothing: {pattern}')
        bib_paths.extend(p for p in matches if p.is_file())
    bib_keys = collect_bib_keys(bib_paths)

    aux_labels: dict[str, str] | None = None
    if args.aux is not None:
        aux_path = (repo / args.aux).resolve()
        if aux_path.is_file():
            aux_labels = {m.group(1): m.group(2)
                          for m in NEWLABEL.finditer(
                              aux_path.read_text(encoding='utf-8', errors='replace'))}
        else:
            add_skip(skipped, 'aux-labels', f'.aux not found: {aux_path}')

    for rel in args.targets:
        target = (repo / rel).resolve()
        if not target.is_file():
            findings.append(finding('inputs', 'blocker',
                                    f'target not found: {rel}', str(target), rel))
            continue
        # errors='replace' so a stray non-UTF-8 byte degrades to a mangled
        # character instead of killing the whole run with a traceback.
        raw = target.read_text(encoding='utf-8', errors='replace')
        text = strip_comments(raw)
        ran.update({'doubled-words', 'dash-consistency', 'balance', 'guard-anchors'})

        findings += check_spelling(raw, rel, skipped, ran, args.spell_lang)
        findings += check_doubled_words(text, rel)
        findings += check_dashes(text, rel, args.dash_tokens)
        findings += check_balance(text, rel)
        findings += check_citations(text, rel, bib_keys, skipped, bool(bib_paths), ran)
        findings += check_word_budget(target, rel, args.word_budget, skipped,
                                      word_counts, ran)
        findings += check_aux_labels(text, rel, aux_labels, skipped, ran)
        findings += check_guard_anchors(raw, rel, repo, target)

        rulings = extract_settled_rulings(raw)
        if rulings:
            settled_rulings[rel] = rulings

    if args.build_cmd:
        ran.add('build-gate')
        findings += run_build_gate(args.build_cmd, repo)
    else:
        add_skip(skipped, 'build-gate', 'opt-in (--build-cmd) not requested')

    counts = {s: sum(1 for f in findings if f['severity'] == s)
              for s in ('blocker', 'major', 'minor', 'info')}
    checks_all = ['spelling', 'doubled-words', 'dash-consistency', 'balance',
                  'citation-resolution', 'word-budget', 'aux-labels', 'guard-anchors',
                  'build-gate']

    report = {
        'generated_by': 'review-paper-prepass.py (writing plugin)',
        'spell_lang': args.spell_lang,
        'repo': str(repo),
        'targets': args.targets,
        # checks_run = executed at least once; a check can also carry skip
        # entries (e.g. one of two --bib patterns matched nothing).
        'checks_run': [c for c in checks_all if c in ran],
        'checks_skipped': skipped,
        'bib_files': [str(p) for p in bib_paths],
        'bib_key_count': len(bib_keys),
        'word_counts': word_counts,
        'counts': counts,
        'findings': findings,
        'settled_rulings': settled_rulings,
    }
    payload = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(payload + '\n', encoding='utf-8')
        print(f'wrote {args.json_out} ({counts})')
    else:
        print(payload)
    return 0


if __name__ == '__main__':
    sys.exit(main())
