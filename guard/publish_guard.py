#!/usr/bin/env python3
"""publish_guard: check what a git push would expose, and refuse if it must not go.

Purpose
    A pre-push check for people and agents who keep private material near public repositories. It
    stops accidents and misdirected agents. It can't stop a determined local user; the aim is that
    getting past it takes a deliberate act.

How it decides
    1. Ask GitHub, with no cache, whether the destination is public. Anything other than an
       unambiguous "private" counts as public.
    2. Find the commits the destination doesn't have, by asking the destination. Local tracking
       refs are never trusted, because a stale one can make a whole private history look published.
    3. Read those commits through git's object store, not through `git log -p`, so that merges,
       `.gitattributes`, replace refs, and local git settings can't hide content.
    4. Run `gitleaks`, and the secrets tier of the deny-list, on every remote. On public remotes
       also apply the rest of the deny-list, narrow topology patterns, and per-repository path
       rules.
    5. Fail closed. If any part of this can't be done, the push doesn't happen.

What it never does
    Print or log a matched value. Findings give a location and a rule. A location that itself holds
    a deny-listed term is shown as `<path hidden>`.

Layout of the guard's home folder (default `~/.config/publish-guard`)
    engine/          the installed copies of this file and `agent_hook.py`, read-only
    hooks/           real-file stubs, read-only; `core.hooksPath` points here
    bin/gitleaks     the pinned scanner (its rules are written from this file on each run)
    install.json     what `install` recorded, read-only
    policy.toml      repository labels and path rules (usually a link into a private repository)
    deny/            keyed hashes of deny-listed terms, one file per tier (likewise)
    deny-sources/    plain-text lists a person reviews and edits, one file per tier (likewise);
                     `secrets/` inside it holds the ones agents are barred from reading
    overrides/       one-time exemptions made by a person at a terminal
    log/guard.jsonl  outcomes, with no values
    log/agent-hook.jsonl  publishing routes the agent hook let through, with no commands
    watch/           the watcher's mirrors of public repositories, and what it has read

Runs on the Python standard library alone, under `python3 -I`, because a hook's working directory is
the repository being checked and must not be able to supply modules.
"""

from __future__ import annotations

import argparse
import bisect
import collections
import contextlib
import dataclasses
import fcntl
import hashlib
import json
import os
import posixpath
import re
import secrets
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import termios
import time
import tomllib
import unicodedata
from collections.abc import Iterable, Iterator
from pathlib import Path

MARKER = "publish-guard: BLOCKED"
WARNING = "publish-guard: warning"
EXIT_BLOCKED = 10
EXIT_INTERNAL = 11
# The watcher's own statuses: 0 means everything was checked and nothing needs attention, 1 that
# something needs attention, and this one that some check couldn't run, so the report is
# incomplete (Astra review W4, 8 November 2026).
EXIT_WATCH_INCOMPLETE = 3
NETWORK_TIMEOUT_SECONDS = 60
MAX_TEXT_BYTES = 64 * 1024 * 1024
BINARY_SNIFF_BYTES = 8000
MAX_LISTED_FINDINGS = 50
# A Git Large File Storage (LFS) pointer, in full. Anything else that merely starts like one is
# read as an ordinary file (Astra review, finding 5, 8 November 2026).
LFS_POINTER = re.compile(
    rb"version https://git-lfs\.github\.com/spec/v1\n"
    rb"(?:ext-\d-[a-z0-9]+ sha256:[0-9a-f]{64}\n)*"
    rb"oid sha256:[0-9a-f]{64}\nsize \d+\n"
)
LFS_POINTER_MAX_BYTES = 1024
# The tier of known secret values. It blocks on every remote, like the secret scan, and no policy
# entry can skip it.
SECRET_TIER = "tier1-exploit"
# Written beside the guard's folders whenever the secrets tier is built, so that losing its file
# later is read as an accident rather than as a tier that was never set up (Astra review W3).
SECRET_TIER_MARKER = "secret-tier-expected"
OVERRIDE_LIFETIME_SECONDS = 3600
MODE_GITLINK = "160000"
MODE_SYMLINK = "120000"
LABELS = ("public", "may-go-public", "never-public")
SCAN_TIMEOUT_SECONDS = 900
# Guard-owned text that opens every stream given to gitleaks, longer than any file-type signature
# offset gitleaks checks (the ISO 9660 signature sits at byte 32769).
SCAN_PREAMBLE = (
    "publish-guard: this opening text is the guard's own; the repository's text follows.\n" * 900
)
# Assembled so that this file doesn't trip its own rule when it is pushed.
INLINE_ALLOW = "gitleaks" + ":allow"
SCANNER_CONFIG_NAMES = (".gitleaks.toml", ".gitleaksignore")

# Rules for the scanner, kept outside any repository. The default rules plus two narrow exceptions,
# found by rehearsing on real history, for fields that look like keys and never are: paging cursors
# in logged URLs, bibliographic citation keys, and values that are file names (a field such as
# "rekeyed" holding an image's name). Only the generic rule is relaxed, and only for the matched
# text itself, so another key on the same line is still caught.
SCANNER_CONFIG = """[extend]
useDefault = true

[[allowlists]]
description = "Identifiers that look like keys and are not secrets"
targetRules = ["generic-api-key"]
regexTarget = "match"
regexes = [
  \'\'\'^pageToken=\'\'\',
  \'\'\'^"?citationKey"?\\s*:\'\'\',
  \'\'\'\\.(?:png|jpe?g|gif|svg|tiff?|webp|pdf|json|jsonl|csv|tsv|txt|md|xml|ya?ml|html?)"?\\s*$\'\'\',
]
"""

# Every hook git can run, so a global hooks folder doesn't silently disable a repository's own.
PASS_THROUGH_HOOKS = (
    "applypatch-msg",
    "pre-applypatch",
    "post-applypatch",
    "pre-commit",
    "pre-merge-commit",
    "prepare-commit-msg",
    "commit-msg",
    "post-commit",
    "pre-rebase",
    "post-checkout",
    "post-merge",
    "pre-auto-gc",
    "post-rewrite",
    "sendemail-validate",
    "post-index-change",
    "reference-transaction",
    "pre-receive",
    "update",
    "post-receive",
    "post-update",
    "push-to-checkout",
    "proc-receive",
    "p4-changelist",
    "p4-prepare-changelist",
    "p4-post-changelist",
    "p4-pre-submit",
)

# Settings that could change what git prints, forced on every read.
LOCKED_GIT_OPTIONS = (
    "--no-replace-objects",
    "--no-pager",
    "-c", "core.quotePath=off",
    "-c", "core.attributesFile=/dev/null",
    "-c", "core.fsmonitor=false",
    "-c", "core.hooksPath=/dev/null",
    "-c", "color.ui=false",
    "-c", "diff.noprefix=false",
    "-c", "diff.mnemonicPrefix=false",
    "-c", "diff.renames=false",
    "-c", "diff.ignoreSubmodules=none",
    "-c", "i18n.logOutputEncoding=UTF-8",
)

# Narrow on purpose. Aliases, usernames, and home paths are assumed discoverable, and blocking them
# would stop daily work: they were nearly all of the hits when measured on real repositories.
TOPOLOGY_PATTERNS = {
    "topology:private-address": re.compile(
        r"(?<![\d.])(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}"
        r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(?!\d)(?!\.\d)"
    ),
    "topology:ssh-port": re.compile(
        r"\bssh\b[^|;&\n]*\s-p\s*\d+|\bscp\b[^|;&\n]*\s-P\s*\d+|ssh://[^/\s]+:\d+"
    ),
    # A keyword with a single value and nothing after it, as in an SSH configuration file, so that
    # ordinary sentences beginning "Hostname ..." don't match.
    "topology:ssh-config": re.compile(
        r"^\s*(?:hostname|identityfile|proxyjump)(?:\s*=\s*|\s+)\S+\s*$", re.I
    ),
    "topology:private-key": re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
}
HOME_PATH_PATTERN = re.compile(r"(?:/home|/Users)/[A-Za-z0-9._-]+/")

# Scripts written without spaces between words, matched character by character.
_NO_SPACE_SCRIPTS = "぀-ヿ㐀-䶿一-鿿豈-﫿가-힯"
_TOKEN = re.compile(rf"[{_NO_SPACE_SCRIPTS}]|[^\W_{_NO_SPACE_SCRIPTS}]+")
_NO_SPACE_CHAR = re.compile(rf"[{_NO_SPACE_SCRIPTS}]")
_TIER_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_HUNK = re.compile(rb"^@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class GuardError(Exception):
    """The guard can't do its job. On a hook, this refuses the push."""


class Blocked(Exception):
    """A decision to refuse, made before any content was read."""

    def __init__(self, reason: str, alert: bool = False) -> None:
        super().__init__(reason)
        self.alert = alert


# ------------------------------------------------------------------ deny-list


def tokenise(text: str) -> list[str]:
    """Reduce text to comparable words: no case, accents, width variants, or punctuation."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _TOKEN.findall(stripped.casefold())


class DenyFiles:
    """Reading and writing the deny folder. Terms are stored only as keyed hashes."""

    def __init__(self, home: Path) -> None:
        self.folder = home / "deny"

    def _secret_value(self, name: str) -> str:
        path = self.folder / name
        if not path.is_file():
            raise GuardError(f"deny-list: {name} file is missing")
        value = path.read_text().strip()
        if not value:
            raise GuardError(f"deny-list: {name} file is empty")
        return value

    def salt(self) -> bytes:
        return bytes.fromhex(self._secret_value("salt"))

    def sentinel(self) -> str:
        return self._secret_value("sentinel")

    def initialise(self) -> None:
        """Create the folder, key, and self-test term if this is the first use."""
        self.folder.mkdir(parents=True, exist_ok=True)
        os.chmod(self.folder, 0o700)
        for name, value in (("salt", secrets.token_hex(32)), ("sentinel", secrets.token_hex(16))):
            path = self.folder / name
            if not path.exists():
                path.write_text(value + "\n")
                os.chmod(path, 0o600)


def _first_key(salt: bytes, token: str) -> str:
    return hashlib.blake2b(token.encode(), key=salt, digest_size=8).hexdigest()


def _full_key(salt: bytes, tokens: Iterable[str]) -> str:
    return hashlib.blake2b(" ".join(tokens).encode(), key=salt, digest_size=16).hexdigest()


def _entry(salt: bytes, tokens: list[str]) -> str:
    return f"{len(tokens)} {_first_key(salt, tokens[0])} {_full_key(salt, tokens)}"


def term_variants(term: str) -> list[list[str]]:
    """The word sequences to store for one term.

    Hyphens, underscores, spaces, and case already reduce to one form. What is left to generate is
    the same words run together, and two-word names in reverse order.
    """
    tokens = tokenise(term)
    if not tokens:
        return []
    variants = [tokens]
    if 2 <= len(tokens) <= 4 and not any(_NO_SPACE_CHAR.fullmatch(t) for t in tokens):
        variants.append(["".join(tokens)])
        if len(tokens) == 2:
            variants.append([tokens[1], tokens[0]])
    return variants


def source_files(home: Path) -> dict[str, Path]:
    """The plain-text list for each tier that has one."""
    folder = home / "deny-sources"
    paths = [*folder.glob("*.txt"), *(folder / "secrets").glob("*.txt")]
    found: dict[str, Path] = {}
    for path in sorted(paths):
        if path.stem in found:
            raise GuardError(f"two source files are both named {path.name}")
        found[path.stem] = path
    return found


def _entries_for_terms(salt: bytes, terms: Iterable[str]) -> tuple[set[str], int]:
    """Hash terms, refusing any that would block ordinary text. Returns (entries, terms used)."""
    entries: set[str] = set()
    used = 0
    for raw in terms:
        term = raw.strip()
        if not term or term.startswith("#"):
            continue
        tokens = tokenise(term)
        if not tokens:
            raise GuardError("a term has no letters or digits to match on")
        if len(tokens) == 1 and len(tokens[0]) < 3:
            raise GuardError("a one-word term under three characters would block ordinary text")
        for variant in term_variants(term):
            entries.add(_entry(salt, variant))
        used += 1
    return entries, used


def _read_entries(path: Path) -> set[str]:
    return {line for line in path.read_text().splitlines() if line and not line.startswith("#")}


def _write_tier(path: Path, tier: str, entries: set[str], source_sha256: str | None = None) -> None:
    """Replace a tier's file in one step, so a failure leaves the old one in place."""
    origin = f" source={source_sha256}" if source_sha256 else ""
    body = "\n".join(sorted(entries))
    text = f"# publish-guard deny tier={tier}{origin}\n{body}\n# end count={len(entries)}\n"
    scratch = path.with_suffix(".tmp")
    scratch.write_text(text)
    os.chmod(scratch, 0o600)
    os.replace(scratch, path)
    if tier == SECRET_TIER:
        (path.parent.parent / SECRET_TIER_MARKER).touch()


def _check_tier_name(tier: str) -> None:
    if not _TIER_NAME.match(tier):
        raise GuardError("tier names use lowercase letters, digits, and hyphens")


def deny_add(home: Path, tier: str, terms: Iterable[str]) -> tuple[int, int]:
    """Add terms to a tier. Returns (terms added, entries now in the tier), never the terms."""
    _check_tier_name(tier)
    if tier in source_files(home):
        raise GuardError(f"{tier} has a source file: edit that, then run deny-rebuild")
    files = DenyFiles(home)
    files.initialise()
    salt, sentinel = files.salt(), files.sentinel()
    path = files.folder / f"{tier}.hashes"
    entries = {_entry(salt, [sentinel])}
    if path.exists():
        entries |= _read_entries(path)
    new, used = _entries_for_terms(salt, terms)
    entries |= new
    _write_tier(path, tier, entries)
    return used, len(entries)


def deny_rebuild(home: Path, tier: str, text: str, keep_source_hash: bool) -> tuple[int, int]:
    """Replace a tier with exactly these terms. Returns (terms, entries)."""
    _check_tier_name(tier)
    files = DenyFiles(home)
    files.initialise()
    salt, sentinel = files.salt(), files.sentinel()
    entries, used = _entries_for_terms(salt, text.splitlines())
    entries.add(_entry(salt, [sentinel]))
    digest = hashlib.sha256(text.encode()).hexdigest() if keep_source_hash else None
    _write_tier(files.folder / f"{tier}.hashes", tier, entries, digest)
    return used, len(entries)


def deny_remove(home: Path, tier: str, term: str) -> int:
    """Remove one term and its variants from a tier. Returns how many entries went."""
    _check_tier_name(tier)
    if tier in source_files(home):
        raise GuardError(f"{tier} has a source file: edit that, then run deny-rebuild")
    files = DenyFiles(home)
    path = files.folder / f"{tier}.hashes"
    if not path.is_file():
        raise GuardError(f"{tier} doesn't exist")
    salt = files.salt()
    entries = _read_entries(path)
    remove = {_entry(salt, variant) for variant in term_variants(term)}
    _write_tier(path, tier, entries - remove)
    return len(entries & remove)


def deny_tiers_holding(home: Path, term: str) -> list[str]:
    """Which tiers list this term."""
    files = DenyFiles(home)
    salt = files.salt()
    variants = term_variants(term)
    if not variants:
        return []
    wanted = _entry(salt, variants[0])
    return [p.stem for p in sorted(files.folder.glob("*.hashes")) if wanted in _read_entries(p)]


def stale_sources(home: Path) -> list[str]:
    """Tiers whose source file has changed since the last rebuild. Names only."""
    stale = []
    folder = DenyFiles(home).folder
    for tier, path in source_files(home).items():
        digest = hashlib.sha256(path.read_text().encode()).hexdigest()
        hashes = folder / f"{tier}.hashes"
        header = hashes.read_text().split("\n", 1)[0] if hashes.is_file() else ""
        if f" source={digest}" not in header:
            stale.append(tier)
    return stale


def secret_tier_expected(home: Path, policy: Policy | None) -> bool:
    """Whether the known-secrets tier should be present.

    It is expected when the policy requires it, when it has a source file, or when it has been
    built here before. A tier that was never set up is left optional; one whose file has gone
    missing since is an accident, and must not quietly switch the check off (Astra review W3).
    """
    return (
        (policy is not None and SECRET_TIER in policy.required_tiers)
        or SECRET_TIER in source_files(home)
        or (home / SECRET_TIER_MARKER).is_file()
    )


def required_tiers(home: Path, policy: Policy | None) -> tuple[str, ...]:
    """The tiers a check must load: the policy's, and the secrets tier when it is expected."""
    tiers = list(policy.required_tiers) if policy is not None else []
    if secret_tier_expected(home, policy) and SECRET_TIER not in tiers:
        tiers.append(SECRET_TIER)
    return tuple(tiers)


class DenyList:
    """Matches word sequences against the stored hashes, across line breaks."""

    def __init__(
        self, salt: bytes, first: dict[str, set[int]], full: dict[str, set[str]]
    ) -> None:
        self.salt = salt
        self.first = first
        self.full = full
        self.tiers: frozenset[str] = frozenset().union(*full.values()) if full else frozenset()
        # A fingerprint of exactly the files this matcher was built from (Astra review H2).
        self.digest = ""
        # The most words any listed term has, which bounds how far a match can reach.
        self.longest = max((n for lengths in first.values() for n in lengths), default=1)
        self._first_cache: dict[str, str] = {}

    @classmethod
    def load(
        cls, home: Path, required: Iterable[str], only: set[str] | None = None
    ) -> DenyList:
        """Load every tier, or `only` those named, refusing anything missing, truncated, or from
        another key."""
        files = DenyFiles(home)
        if not files.folder.is_dir():
            raise GuardError("deny-list: the folder is missing")
        salt, sentinel = files.salt(), files.sentinel()
        expected = _entry(salt, [sentinel])
        paths = sorted(files.folder.glob("*.hashes"))
        if only is not None:
            paths = [path for path in paths if path.stem in only]
        if not paths:
            raise GuardError("deny-list: no tiers are present")
        names = {p.stem for p in paths}
        absent = sorted(set(required) - names)
        if absent:
            raise GuardError(f"deny-list: required tier missing: {', '.join(absent)}")
        first: dict[str, set[int]] = {}
        full: dict[str, set[str]] = {}
        required_tiers = set(required)
        digest = hashlib.sha256()
        for path in paths:
            try:
                text = path.read_text()
            except (OSError, UnicodeDecodeError) as error:
                raise GuardError(f"deny-list: {path.stem} can't be read") from error
            digest.update(path.name.encode() + b"\0" + text.encode() + b"\0")
            lines = text.splitlines()
            if len(lines) < 2 or not lines[0].startswith("# publish-guard deny"):
                raise GuardError(f"deny-list: {path.stem} has no valid header")
            match = re.fullmatch(r"# end count=(\d+)", lines[-1])
            if not match:
                raise GuardError(f"deny-list: {path.stem} is truncated")
            body = [line for line in lines[1:-1] if line]
            if len(body) != int(match.group(1)):
                raise GuardError(f"deny-list: {path.stem} has the wrong number of entries")
            if expected not in body:
                raise GuardError(f"deny-list: {path.stem} fails its self-test")
            if path.stem in required_tiers and len(body) < 2:
                raise GuardError(f"deny-list: required tier {path.stem} holds no terms")
            for line in body:
                try:
                    count, first_key, full_key = line.split()
                    length = int(count)
                except ValueError as error:
                    raise GuardError(f"deny-list: {path.stem} has a malformed entry") from error
                first.setdefault(first_key, set()).add(length)
                # A term may sit in several tiers; skipping one tier mustn't excuse the others.
                full.setdefault(full_key, set()).add(path.stem)
        loaded = cls(salt, first, full)
        loaded.digest = digest.hexdigest()
        if not any(True for _ in loaded.find(tokenise(sentinel))):
            raise GuardError("deny-list: matching fails its self-test")
        return loaded

    def _first(self, token: str) -> str:
        key = self._first_cache.get(token)
        if key is None:
            key = _first_key(self.salt, token)
            self._first_cache[token] = key
        return key

    def matches(
        self, tokens: list[str], skip: frozenset[str] = frozenset()
    ) -> Iterator[tuple[int, int, str]]:
        """Yield (index of first word, number of words, tier) for each match."""
        total = len(tokens)
        for index, token in enumerate(tokens):
            lengths = self.first.get(self._first(token))
            if not lengths:
                continue
            for length in lengths:
                if index + length > total:
                    continue
                tiers = self.full.get(_full_key(self.salt, tokens[index : index + length]))
                for tier in sorted((tiers or set()) - skip):
                    yield index, length, tier

    def find(
        self, tokens: list[str], skip: frozenset[str] = frozenset()
    ) -> Iterator[tuple[int, str]]:
        """Yield (index of first word, tier) for each match."""
        for index, _, tier in self.matches(tokens, skip):
            yield index, tier


# ------------------------------------------------------------------ policy


@dataclasses.dataclass(frozen=True)
class RepoPolicy:
    """What one repository's policy entry says."""

    label: str = "may-go-public"
    allowed_paths: tuple[str, ...] | None = None
    binary_allow: tuple[str, ...] = ()
    skip_tiers: frozenset[str] = frozenset()
    block_home_paths: bool = False
    # Whether the watcher reads this repository's new content; None means the owner rule decides.
    watch: bool | None = None


@dataclasses.dataclass(frozen=True)
class Policy:
    """The private policy file. It lives outside any repository being checked."""

    repos: dict[str, RepoPolicy]
    required_tiers: tuple[str, ...]
    # Owners whose public repositories the watcher reads by default.
    watch_owners: tuple[str, ...] = ()


def load_policy(home: Path) -> Policy:
    """Read the policy, refusing anything missing or malformed."""
    path = home / "policy.toml"
    if not path.is_file():
        raise GuardError("the policy file is missing")
    try:
        data = tomllib.loads(path.read_text())
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as error:
        raise GuardError("the policy file can't be read") from error
    repos: dict[str, RepoPolicy] = {}
    for name, entry in data.get("repos", {}).items():
        label = entry.get("label")
        if label not in LABELS:
            raise GuardError(f"the policy gives {name} an unknown label")
        allowed = entry.get("allowed_paths")
        skip = frozenset(entry.get("skip_tiers", ()))
        if SECRET_TIER in skip:
            raise GuardError(
                f"the policy skips {SECRET_TIER} for {name}, and secrets can't be skipped"
            )
        repos[name.lower()] = RepoPolicy(
            label=label,
            allowed_paths=tuple(allowed) if allowed is not None else None,
            binary_allow=tuple(entry.get("binary_allow", ())),
            skip_tiers=skip,
            block_home_paths=bool(entry.get("block_home_paths", False)),
            watch=entry.get("watch") if isinstance(entry.get("watch"), bool) else None,
        )
    return Policy(
        repos=repos,
        required_tiers=tuple(data.get("required_tiers", ())),
        watch_owners=tuple(owner.lower() for owner in data.get("watch_owners", ())),
    )


def glob_matches(pattern: str, path: str) -> bool:
    """Path globbing: `*` stays within a folder and `**` crosses folders."""
    regex = ""
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            regex += "(?:.*/)?"
            index += 3
        elif pattern.startswith("**", index):
            regex += ".*"
            index += 2
        elif pattern[index] == "*":
            regex += "[^/]*"
            index += 1
        elif pattern[index] == "?":
            regex += "[^/]"
            index += 1
        else:
            regex += re.escape(pattern[index])
            index += 1
    return re.fullmatch(regex, path) is not None


# ------------------------------------------------------------------ remotes


@dataclasses.dataclass(frozen=True)
class RemoteUrl:
    """A push destination with any credentials already removed."""

    kind: str  # github, local, or other
    name: str


_GITHUB_PATTERNS = (
    re.compile(r"^(?:ssh://)?(?:[^@/\s]+@)?github\.com[:/]([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", re.I),
    re.compile(
        r"^https?://(?:[^@/\s]+@)?(?:www\.)?github\.com/([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", re.I
    ),
)


def parse_remote_url(url: str) -> RemoteUrl:
    """Work out what a push URL points at. Anything unrecognised counts as public."""
    for pattern in _GITHUB_PATTERNS:
        match = pattern.match(url)
        if match:
            return RemoteUrl("github", f"{match.group(1)}/{match.group(2)}".lower())
    if url.startswith(("/", "./", "../", "file://")) or url == ".":
        return RemoteUrl("local", url)
    without_scheme = re.sub(r"^[a-z][a-z0-9+.-]*://", "", url, flags=re.I)
    without_user = re.sub(r"^[^@/\s]+@", "", without_scheme)
    if without_scheme == url and ":" not in url:
        return RemoteUrl("local", url)
    return RemoteUrl("other", without_user.lower())


def github_visibility(name: str, gh: str | None) -> tuple[str, str]:
    """Ask GitHub about a repository. Returns (visibility, current name).

    Only an unambiguous answer counts as private: any failure, an `internal` repository, or fields
    that disagree come back as `unknown`, which callers treat as public.
    """
    if not gh:
        return "unknown", name
    env = {k: v for k, v in os.environ.items() if k not in ("GH_HOST", "GH_REPO", "GH_PAGER")}
    try:
        result = subprocess.run(
            [gh, "api", f"repos/{name}"], capture_output=True, text=True, env=env,
            timeout=NETWORK_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown", name
    if result.returncode != 0:
        return "unknown", name
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return "unknown", name
    if not isinstance(payload, dict):
        return "unknown", name
    current = str(payload.get("full_name") or name).lower()
    visibility, private = payload.get("visibility"), payload.get("private")
    if visibility == "private" and private is True:
        return "private", current
    if visibility == "public" and private is False:
        return "public", current
    return "unknown", current


@dataclasses.dataclass(frozen=True)
class Destination:
    """A classified remote."""

    name: str
    visibility: str  # public, private, unknown, or local


def classify_destination(url: str, install: dict) -> Destination:
    """Combine URL parsing with a live visibility check."""
    test_map = install.get("visibility_map")
    if test_map:
        mapping = json.loads(Path(test_map).read_text())
        if url in mapping:
            entry = mapping[url]
            return Destination(entry["name"].lower(), entry["visibility"])
    parsed = parse_remote_url(url)
    if parsed.kind == "local":
        return Destination(parsed.name, "local")
    if parsed.kind == "other":
        return Destination(parsed.name, "unknown")
    visibility, name = github_visibility(parsed.name, install.get("gh"))
    return Destination(name, visibility)


@dataclasses.dataclass(frozen=True)
class Rules:
    """How strictly to treat one push."""

    content: str  # block, warn, or off
    repo: RepoPolicy
    policy: Policy | None


def decide_rules(destination: Destination, home: Path) -> Rules:
    """Turn a destination and the policy into rules, or refuse outright."""
    public_like = destination.visibility != "private"
    try:
        policy = load_policy(home)
    except GuardError as error:
        if public_like:
            raise
        # Not silent, and not off: a private repository labelled public would otherwise get no
        # content checks at all (second audit, M5, 8 November 2026).
        print(f"{WARNING}: {error}; the public rules ran as warnings", file=sys.stderr)
        return Rules("warn", RepoPolicy(), None)
    entry = policy.repos.get(destination.name)
    if not public_like:
        if entry and entry.label == "never-public":
            return Rules("off", entry, policy)
        if entry and entry.label == "public":
            return Rules("block", entry, policy)
        return Rules("warn", entry or RepoPolicy(), policy)
    if entry is None:
        raise Blocked(
            f"{destination.name} reads as {destination.visibility} and has no policy entry. "
            "Add it to the policy before pushing."
        )
    if entry.label == "never-public":
        raise Blocked(
            f"ALERT: {destination.name} is labelled never-public but reads as "
            f"{destination.visibility}. Check its visibility now.",
            alert=True,
        )
    if entry.label == "may-go-public" and destination.visibility == "public":
        raise Blocked(
            f"{destination.name} has changed to public while labelled may-go-public. Review it, "
            "then update its label."
        )
    return Rules("block", entry, policy)


# ------------------------------------------------------------------ reading git


def git_environment(git_dir: Path) -> dict[str, str]:
    """An environment that ignores user and session git settings."""
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/nonexistent"),
        "LANG": "C.UTF-8",
        "GIT_DIR": str(git_dir),
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
    }


class Repository:
    """Locked reads of one repository's objects."""

    def __init__(self, git: str, git_dir: Path) -> None:
        self.git = git
        self.git_dir = git_dir
        self.env = git_environment(git_dir)
        self._batch: subprocess.Popen | None = None
        self._check: subprocess.Popen | None = None

    def run(self, *args: str, stdin: bytes | None = None) -> bytes:
        """Run git and return its output. Any failure refuses the push."""
        result = subprocess.run(
            [self.git, *LOCKED_GIT_OPTIONS, *args], input=stdin, capture_output=True,
            env=self.env, cwd=self.git_dir,
        )
        if result.returncode != 0:
            raise GuardError(f"git {args[0]} failed with status {result.returncode}")
        return result.stdout

    def _process(self, option: str) -> subprocess.Popen:
        return subprocess.Popen(
            [self.git, *LOCKED_GIT_OPTIONS, "cat-file", option], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, env=self.env, cwd=self.git_dir,
        )

    def info(self, sha: str) -> tuple[str, int] | None:
        """Return an object's type and size, or None when this repository doesn't have it."""
        if self._check is None:
            self._check = self._process("--batch-check")
        self._check.stdin.write(sha.encode() + b"\n")
        self._check.stdin.flush()
        parts = self._check.stdout.readline().decode().split()
        if len(parts) != 3:
            return None
        return parts[1], int(parts[2])

    def read(self, sha: str) -> tuple[str, bytes]:
        """Return an object's type and content."""
        if self._batch is None:
            self._batch = self._process("--batch")
        self._batch.stdin.write(sha.encode() + b"\n")
        self._batch.stdin.flush()
        parts = self._batch.stdout.readline().decode().split()
        if len(parts) != 3:
            raise GuardError("git can't read an object in this push")
        size = int(parts[2])
        data = self._batch.stdout.read(size)
        self._batch.stdout.read(1)
        return parts[1], data

    def close(self) -> None:
        for process in (self._batch, self._check):
            if process is not None:
                process.stdin.close()
                process.stdout.close()
                process.wait()

    def changes(self, commit: str, parent: str | None) -> list[Change]:
        """List what changed against one parent, or against nothing for a root commit."""
        range_args = [parent, commit] if parent else ["--root", commit]
        output = self.run(
            "diff-tree", "-r", "-z", "--raw", "--no-abbrev", "--no-renames", "--no-commit-id",
            *range_args,
        )
        fields = output.split(b"\0")
        changes = []
        for index in range(0, len(fields) - 1, 2):
            meta = fields[index].decode().lstrip(":").split()
            path = fields[index + 1].decode("utf-8", "surrogateescape")
            changes.append(Change(meta[0], meta[1], meta[2], meta[3], meta[4][0], path))
        return changes

    def hunks(
        self, old_sha: str, new_sha: str
    ) -> tuple[list[list[tuple[int, str]]], set[int]]:
        """What a blob gains over another: blocks of added (line number, text), and the places
        where a deletion alone joined two lines (see `parse_hunks`)."""
        output = self.run(
            "diff", "-U0", "--text", "--no-color", "--no-ext-diff", "--no-textconv", "--no-renames",
            old_sha, new_sha,
        )
        return parse_hunks(output)


@dataclasses.dataclass(frozen=True)
class Change:
    """One line of `git diff-tree --raw`."""

    old_mode: str
    new_mode: str
    old_sha: str
    new_sha: str
    status: str
    path: str


@dataclasses.dataclass(frozen=True)
class Region:
    """What a change did to a file against one parent, in the new file's line numbers.

    `everything` marks a file that is new against that parent, so all of it is new.
    """

    old_sha: str
    added: frozenset[int] = frozenset()
    junctions: frozenset[int] = frozenset()
    everything: bool = False

    def touched_by(self, first: int, last: int) -> bool:
        """Whether text spanning lines first..last includes any of this change."""
        if self.everything:
            return True
        if any(first <= j and last >= j + 1 for j in self.junctions):
            return True
        return any(n in self.added for n in range(first, last + 1))


def _is_fresh(change: Change) -> bool:
    """Whether a change has no earlier text to compare with: a new file, or a change of type."""
    return set(change.old_sha) == {"0"} or change.old_mode[:2] != change.new_mode[:2]


def _decode_line(raw: bytes) -> str:
    return raw.rstrip(b"\r").decode("utf-8", "replace")


def parse_added_lines(diff: bytes) -> list[list[tuple[int, str]]]:
    """Extract added lines from a zero-context diff."""
    return parse_hunks(diff)[0]


def parse_hunks(diff: bytes) -> tuple[list[list[tuple[int, str]]], set[int]]:
    """Extract added lines, and deletion junctions, from a zero-context diff.

    A junction `n` means a hunk only deleted lines, leaving new lines n and n + 1 side by side,
    where a listed phrase can form without any added line. Hunk lengths come from the `@@`
    header, so file content can't imitate diff syntax.
    """
    blocks: list[list[tuple[int, str]]] = []
    junctions: set[int] = set()
    lines = diff.split(b"\n")
    index = 0
    while index < len(lines):
        match = _HUNK.match(lines[index])
        index += 1
        if not match:
            continue
        old_left = int(match.group(1)) if match.group(1) is not None else 1
        number = int(match.group(2))
        new_left = int(match.group(3)) if match.group(3) is not None else 1
        if new_left == 0:
            junctions.add(number)
        block: list[tuple[int, str]] = []
        while (old_left > 0 or new_left > 0) and index < len(lines):
            line = lines[index]
            index += 1
            if line.startswith(b"+"):
                block.append((number, _decode_line(line[1:])))
                number += 1
                new_left -= 1
            elif line.startswith(b"-"):
                old_left -= 1
            elif line.startswith(b"\\"):
                continue
            else:
                old_left -= 1
                new_left -= 1
                number += 1
        if block:
            blocks.append(block)
    return blocks, junctions


def numbered_lines(data: bytes) -> list[tuple[int, str]]:
    """All of a blob's lines, for a file with nothing to compare against."""
    lines = data.split(b"\n")
    if lines and not lines[-1]:
        lines.pop()
    return [(number, _decode_line(line)) for number, line in enumerate(lines, 1)]


# ------------------------------------------------------------------ scanning


@dataclasses.dataclass(frozen=True)
class Place:
    """Where something was found. `path` may be a label such as `<commit message>`."""

    commit: str
    path: str
    # True for a label such as `<commit message>`, which is the guard's own text, never a path.
    label: bool = False


@dataclasses.dataclass(frozen=True)
class Finding:
    """One rule that fired, with a location and no value."""

    rule: str
    place: Place
    line: int | None
    severity: str  # block or warn


class Scanner:
    """Collects findings and builds the text stream for `gitleaks`."""

    def __init__(self, repo: Repository, rules: Rules, deny: DenyList | None, stream: Path) -> None:
        self.repo = repo
        self.rules = rules
        self.deny = deny
        self.findings: list[Finding] = []
        self._seen: set[Finding] = set()
        self.hidden_paths: set[str] = set()
        self.binary_allowed: list[str] = []
        self._stream = stream.open("w", encoding="utf-8", errors="replace", newline="\n")
        # gitleaks decides from the opening bytes whether its input is a binary file, and if so
        # reads none of it. Text from the repository must never come first, so guard-owned text
        # fills the first stretch of the stream (audit finding C1, 8 November 2026).
        self._stream.write(SCAN_PREAMBLE)
        self._preamble_lines = SCAN_PREAMBLE.count("\n")
        self._stream_lines = self._preamble_lines
        self._starts: list[int] = []
        self._segments: list[tuple[Place, int]] = []
        self._segment_paths: dict[int, str] = {}
        self._checked_paths: set[str] = set()
        self._kinds: dict[str, str] = {}
        self._hits: dict[tuple[str, str], list[tuple[tuple[str, ...], str, int, int]]] = {}
        # How many lines the deny-list check has tokenised, so a test can hold its cost down.
        self.lines_tokenised = 0

    def _record(
        self, rule: str, place: Place, line: int | None, severity: str | None = None
    ) -> None:
        finding = Finding(rule, place, line, severity or self.rules.content)
        if finding not in self._seen:
            self._seen.add(finding)
            self.findings.append(finding)

    @property
    def _content_on(self) -> bool:
        return self.rules.content != "off"

    @property
    def _in_context(self) -> bool:
        """Whether text around each change is checked against the deny-list.

        Pushes that would block read every tier this way. Private pushes read only the secrets
        tier this way, because it blocks on every remote and a listed secret can be completed
        across lines in successive commits (Astra re-review, item 3). Their other tiers only
        warn, so they keep the cheaper check of added lines; the audit before a visibility
        change reads those in full.
        """
        if self.deny is None:
            return False
        return self.rules.content == "block" or SECRET_TIER in self.deny.tiers

    @property
    def _context_covers_all(self) -> bool:
        """Whether the check around changes covers every tier, so added lines needn't be."""
        return self.rules.content == "block"

    @property
    def _context_skip(self) -> frozenset[str]:
        """Tiers the check around changes leaves out."""
        if self._context_covers_all:
            return self._skipped_tiers(False)
        return self.deny.tiers - {SECRET_TIER} if self.deny is not None else frozenset()

    def _skipped_tiers(self, secrets_only: bool) -> frozenset[str]:
        """Tiers not applied to some text. The secrets tier always applies, on every remote."""
        if self.deny is None:
            return frozenset()
        if secrets_only or not self._content_on:
            return self.deny.tiers - {SECRET_TIER}
        return self.rules.repo.skip_tiers - {SECRET_TIER}

    def _record_tier(self, tier: str, place: Place, line: int | None) -> None:
        """Record a deny-list match. Known secrets block wherever they go (Astra review, 7)."""
        self._record(tier, place, line, "block" if tier == SECRET_TIER else None)

    def add_text(
        self,
        place: Place,
        block: list[tuple[int, str]],
        secrets_only: bool = False,
        hides_path: str | None = None,
        deny: bool = True,
    ) -> None:
        """Queue a block of added lines for the secret scan, and check it against local rules.

        `hides_path` names a file path that this text spells out, so that a secret found in it
        keeps the path out of every report. `deny=False` leaves the deny-list to a caller that
        checks the whole file instead.
        """
        if not block:
            return
        self._starts.append(self._stream_lines + 1)
        self._segments.append((place, block[0][0]))
        if hides_path is not None:
            self._segment_paths[len(self._segments) - 1] = hides_path
        for _, text in block:
            self._stream.write(text.replace("\n", " ") + "\n")
        self._stream_lines += len(block)
        if deny:
            self._check_deny(place, block, secrets_only)
        if self._content_on and not secrets_only:
            self._check_patterns(place, block)

    def _check_deny(
        self, place: Place, block: list[tuple[int, str]], secrets_only: bool = False
    ) -> None:
        if self.deny is None:
            return
        tokens: list[str] = []
        owners: list[int] = []
        for number, text in block:
            words = tokenise(text)
            tokens.extend(words)
            owners.extend([number] * len(words))
        for index, tier in self.deny.find(tokens, self._skipped_tiers(secrets_only)):
            self._record_tier(tier, place, owners[index])

    def _lines(self, sha: str, encoding: str) -> list[str]:
        """A blob's lines, decoded, numbered from 1 by position (index 0 is line 1)."""
        _, data = self.repo.read(sha)
        if encoding == "utf-8":
            return [text for _, text in numbered_lines(data)]
        lines = [line.rstrip("\r") for line in data.decode(encoding, "replace").split("\n")]
        if lines and not lines[-1]:
            lines.pop()
        return lines

    def _hits_in(
        self, lines: list[str], first_line: int, last_line: int
    ) -> list[tuple[tuple[str, ...], str, int, int]]:
        """Listed terms in lines first_line..last_line, as (words, tier, first, last line)."""
        tokens: list[str] = []
        owners: list[int] = []
        for number in range(first_line, last_line + 1):
            words = tokenise(lines[number - 1])
            tokens.extend(words)
            owners.extend([number] * len(words))
        self.lines_tokenised += last_line - first_line + 1
        return [
            (tuple(tokens[index : index + length]), tier, owners[index],
             owners[index + length - 1])
            for index, length, tier in self.deny.matches(tokens, self._context_skip)
        ]

    def _deny_hits(
        self, sha: str, encoding: str = "utf-8"
    ) -> list[tuple[tuple[str, ...], str, int, int]]:
        """Every listed term in one whole blob, cached by blob."""
        if self.deny is None or set(sha) == {"0"}:
            return []
        key = (sha, encoding)
        cached = self._hits.get(key)
        if cached is None:
            lines = self._lines(sha, encoding)
            cached = self._hits_in(lines, 1, len(lines)) if lines else []
            self._hits[key] = cached
        return cached

    def _windows(
        self, lines: list[str], regions: list[Region]
    ) -> list[tuple[int, int]]:
        """Line ranges that hold every match able to touch a change, merged.

        Each changed line, and each pair of lines a deletion joined, is widened by enough lines
        to hold the longest listed term's other words on either side.
        """
        total = len(lines)
        spans: set[tuple[int, int]] = set()
        for region in regions:
            spans |= {(n, n) for n in region.added}
            spans |= {(j, j + 1) for j in region.junctions}
        counts: dict[int, int] = {}

        def words_on(number: int) -> int:
            if number not in counts:
                counts[number] = len(tokenise(lines[number - 1]))
            return counts[number]

        reach = self.deny.longest - 1
        widened: list[tuple[int, int]] = []
        for start, end in sorted(spans):
            start, end = max(start, 1), min(end, total)
            if start > end:
                continue
            need, low = reach, start
            while need > 0 and low > 1:
                low -= 1
                need -= words_on(low)
            need, high = reach, end
            while need > 0 and high < total:
                high += 1
                need -= words_on(high)
            if widened and low <= widened[-1][1] + 1:
                widened[-1] = (widened[-1][0], max(widened[-1][1], high))
            else:
                widened.append((low, high))
        return widened

    def _check_deny_near_changes(
        self, place: Place, new_sha: str, regions: list[Region], encoding: str = "utf-8"
    ) -> None:
        """Check the text around a file's changes against the deny-list.

        Checking added lines alone misses a listed phrase that an edit completes without any added
        line holding all of it: a name finished on the next line, or joined up by deleting the
        word between (Astra review, finding 2). So the check reads each change with enough text
        either side to hold any listed term, and keeps the matches that include changed text
        against every parent. Matching only around the changes keeps the matching work in
        proportion to the change (second audit, M3); the file is still read and decoded whole, and
        git still computes the diff, so the total cost isn't bounded by the change (Astra review).

        A match there is new unless the file held that term as often before, in some parent: an
        edit to a line that already held a published name isn't a new exposure. Each parent has
        itself been checked, or is already on the remote. Whole files are counted only in that
        rare case.
        """
        if self.deny is None:
            return
        constraining = [region for region in regions if not region.everything]
        lines = self._lines(new_sha, encoding)
        if not lines:
            return
        if constraining:
            windows = self._windows(lines, constraining)
        else:
            windows = [(1, len(lines))]
        candidates = [
            hit
            for low, high in windows
            for hit in self._hits_in(lines, low, high)
            if all(region.touched_by(hit[2], hit[3]) for region in constraining)
        ]
        if not candidates:
            return
        now = collections.Counter((w, t) for w, t, _, _ in self._deny_hits(new_sha, encoding))
        before: collections.Counter = collections.Counter()
        for region in constraining:
            before |= collections.Counter(
                (w, t) for w, t, _, _ in self._deny_hits(region.old_sha, encoding)
            )
        for words, tier, first, _ in candidates:
            if now[(words, tier)] > before[(words, tier)]:
                self._record_tier(tier, place, first)

    def _check_patterns(self, place: Place, block: list[tuple[int, str]]) -> None:
        for number, text in block:
            for rule, pattern in TOPOLOGY_PATTERNS.items():
                if pattern.search(text):
                    self._record(rule, place, number)
            if self.rules.repo.block_home_paths and HOME_PATH_PATTERN.search(text):
                self._record("topology:home-path", place, number)
            if INLINE_ALLOW in text:
                self._record("scanner-rules-changed", place, number)

    def check_ref(self, ref: str, namespace_rule: bool = True) -> None:
        """Check a ref's name, and, for a push destination, its namespace."""
        place = Place("", "<ref name>", label=True)
        self.add_text(place, [(1, ref)])
        if (
            namespace_rule and self._content_on
            and not ref.startswith(("refs/heads/", "refs/tags/"))
        ):
            self._record("ref-outside-heads-and-tags", place, None)

    def _scan_headers(self, sha: str, header: bytes, label: str) -> list[str]:
        """Scan an object's header lines, and return its parents.

        Identities are scanned as identities. Every other header is scanned as text too, including
        a `mergetag` header, which carries a whole tag object (with its message) inside a merge
        commit. Only the tree, parents, object, type, and signatures are left out: the first four
        are hashes, and signatures are encoded data.
        """
        parents: list[str] = []
        lines = header.split(b"\n")
        skipping_signature = False
        extra: list[tuple[int, str]] = []
        for number, line in enumerate(lines, 1):
            if line.startswith(b" "):
                if not skipping_signature:
                    extra.append((number, _decode_line(line[1:])))
                continue
            skipping_signature = False
            key, _, value = line.partition(b" ")
            if key == b"parent":
                parents.append(value.split()[0].decode())
            elif key in (b"author", b"committer", b"tagger"):
                place = Place(sha, f"<{key.decode()}>", label=True)
                self.add_text(place, [(1, _identity_text(line))])
            elif key in (b"gpgsig", b"gpgsig-sha256"):
                skipping_signature = True
            elif key not in (b"tree", b"object", b"type"):
                extra.append((number, _decode_line(line)))
        self.add_text(Place(sha, label, label=True), extra)
        return parents

    def scan_tag_chain(self, sha: str) -> str | None:
        """Scan any tag objects and return the commit they lead to."""
        current = sha
        while True:
            info = self.repo.info(current)
            if info is None:
                raise GuardError("a pushed ref names an object git can't find")
            kind = info[0]
            if kind == "commit":
                return current
            if kind != "tag":
                target = Place(current, "<ref target>", label=True)
                self._record("non-commit-ref", target, None, "block")
                return None
            _, data = self.repo.read(current)
            header, _, message = data.partition(b"\n\n")
            self._scan_headers(current, header, "<tag header>")
            self.add_text(Place(current, "<tag>", label=True), numbered_lines(message))
            target = re.search(rb"^object ([0-9a-f]+)$", header, re.M)
            if not target:
                raise GuardError("a tag object can't be parsed")
            current = target.group(1).decode()

    def scan_commit(self, sha: str) -> None:
        """Scan a commit's identities, headers, message, and everything it introduces."""
        kind, data = self.repo.read(sha)
        if kind != "commit":
            raise GuardError("the commit list holds something that isn't a commit")
        header, _, message = data.partition(b"\n\n")
        parents = self._scan_headers(sha, header, "<commit header>")
        self.add_text(Place(sha, "<commit message>", label=True), numbered_lines(message))
        if len(parents) <= 1:
            parent = parents[0] if parents else None
            for change in self.repo.changes(sha, parent):
                self._scan_change(sha, change)
        else:
            self._scan_merge(sha, parents)

    def _scan_merge(self, sha: str, parents: list[str]) -> None:
        """Scan only what is new against every parent.

        A merge that brings in already-published work isn't exposing anything new, and content that
        exists only in the merge result still appears here.
        """
        per_parent = [{c.path: c for c in self.repo.changes(sha, p)} for p in parents]
        common = set(per_parent[0]).intersection(*per_parent[1:])
        for path in sorted(common):
            changes = [table[path] for table in per_parent]
            first = changes[0]
            if first.status == "D":
                continue
            self._check_path_rules(sha, first)
            kind = self._kind(first)
            if kind != "text":
                self._scan_non_text(sha, first, kind)
                continue
            place = Place(sha, path)
            counters = []
            blocks = None
            regions: list[Region] = []
            for change in changes:
                current, region = self._changes_for(change)
                regions.append(region)
                counters.append(collections.Counter(t for b in current for _, t in b))
                if blocks is None:
                    blocks = current
            shared = counters[0]
            for counter in counters[1:]:
                shared = shared & counter
            for block in blocks or []:
                kept = []
                for number, text in block:
                    if shared[text] > 0:
                        shared[text] -= 1
                        kept.append((number, text))
                self.add_text(place, kept, deny=not self._context_covers_all)
            if self._in_context:
                self._check_deny_near_changes(place, first.new_sha, regions)
            self._check_other_encodings(sha, first, regions)

    def _changes_for(self, change: Change) -> tuple[list[list[tuple[int, str]]], Region]:
        """A change's added blocks, and its region against the parent it was diffed with."""
        if change.old_sha == change.new_sha:
            return [], Region(change.old_sha)
        if _is_fresh(change):
            _, data = self.repo.read(change.new_sha)
            return [numbered_lines(data)], Region(change.old_sha, everything=True)
        blocks, junctions = self.repo.hunks(change.old_sha, change.new_sha)
        added = frozenset(number for block in blocks for number, _ in block)
        return blocks, Region(change.old_sha, added, frozenset(junctions))

    def _scan_change(self, sha: str, change: Change) -> None:
        if change.status == "D":
            return
        self._check_path_rules(sha, change)
        kind = self._kind(change)
        if kind != "text":
            self._scan_non_text(sha, change, kind)
            return
        place = Place(sha, change.path)
        blocks, region = self._changes_for(change)
        # A new file is all added text, so the ordinary check reads all of it.
        near = self._in_context and not region.everything
        for block in blocks:
            self.add_text(place, block, deny=not (near and self._context_covers_all))
        if near:
            self._check_deny_near_changes(place, change.new_sha, [region])
        self._check_other_encodings(sha, change, [region])

    def _scan_non_text(self, sha: str, change: Change, kind: str) -> None:
        """Submodules, symbolic links, binary files, and LFS pointers, in commits and merges."""
        place = Place(sha, change.path)
        if kind == "gitlink":
            return
        if kind == "symlink":
            _, data = self.repo.read(change.new_sha)
            target = data.decode("utf-8", "replace")
            self.add_text(place, [(1, target)])
            self._check_symlink(place, change.path, target)
            return
        self._scan_binary_for_secrets(place, change)
        self._check_binary(sha, change, kind)

    def _scan_binary_for_secrets(self, place: Place, change: Change) -> None:
        """Put a binary file's readable runs through the secret scan, on every remote.

        Text that begins like an LFS pointer, or holds a NUL byte early on, would otherwise never
        reach the secret scan (audit finding M4).
        """
        info = self.repo.info(change.new_sha)
        if not info or info[1] > MAX_TEXT_BYTES:
            return
        _, data = self.repo.read(change.new_sha)
        if data.startswith((b"\xff\xfe", b"\xfe\xff")):
            text = data.decode("utf-16", "replace")
            self.add_text(place, [(n, t) for n, t in enumerate(text.splitlines(), 1)],
                          secrets_only=True)
        runs = [run.decode("ascii") for run in re.findall(rb"[\x20-\x7e]{8,}", data)]
        self.add_text(place, [(n, run) for n, run in enumerate(runs, 1)], secrets_only=True)

    def _check_other_encodings(self, sha: str, change: Change, regions: list[Region]) -> None:
        """Check a text file that isn't UTF-8 against the deny-list in two legacy encodings.

        Field data exported from older systems is often Windows-1252 or Windows-1251 (Cyrillic),
        and a name in either would otherwise be decoded into replacement characters (audit L3).
        Pushes that would block read around each change, as for UTF-8.
        """
        if not self._content_on or self.deny is None or change.old_sha == change.new_sha:
            return
        _, data = self.repo.read(change.new_sha)
        try:
            data.decode("utf-8")
            return
        except UnicodeDecodeError:
            pass
        place = Place(sha, change.path)
        if self._in_context:
            for encoding in ("cp1252", "cp1251"):
                self._check_deny_near_changes(place, change.new_sha, regions, encoding)
            if self._context_covers_all:
                return
        if set(change.old_sha) != {"0"}:
            # Only the lines this change adds, so legacy content already published isn't
            # re-reported every time the file is edited.
            diff = self.repo.run(
                "diff", "-U0", "--text", "--no-color", "--no-ext-diff", "--no-textconv",
                change.old_sha, change.new_sha,
            )
            data = b"\n".join(
                line[1:] for line in diff.split(b"\n")
                if line.startswith(b"+") and not line.startswith(b"+++")
            )
        for encoding in ("cp1252", "cp1251"):
            words = tokenise(data.decode(encoding, "replace"))
            for _, tier in self.deny.find(words, self._skipped_tiers(False)):
                self._record_tier(tier, place, None)

    def _kind(self, change: Change) -> str:
        if change.new_mode == MODE_GITLINK:
            return "gitlink"
        if change.new_mode == MODE_SYMLINK:
            return "symlink"
        cached = self._kinds.get(change.new_sha)
        if cached:
            return cached
        info = self.repo.info(change.new_sha)
        if info is None:
            raise GuardError("a changed file's content can't be found")
        if info[1] > MAX_TEXT_BYTES:
            kind = "binary"
        else:
            _, data = self.repo.read(change.new_sha)
            if len(data) <= LFS_POINTER_MAX_BYTES and LFS_POINTER.fullmatch(data):
                kind = "lfs"
            elif b"\0" in data[:BINARY_SNIFF_BYTES]:
                kind = "binary"
            else:
                kind = "text"
        self._kinds[change.new_sha] = kind
        return kind

    def _check_path_rules(self, sha: str, change: Change) -> None:
        """Rules that depend on a path or file type, not on content."""
        path = change.path
        place = Place(sha, path)
        # File names reach the secret scan on every remote.
        self.add_text(
            Place(sha, "<file name>", label=True), [(1, path)], secrets_only=True,
            hides_path=path, deny=False,
        )
        if path not in self._checked_paths:
            self._checked_paths.add(path)
            if self.deny is not None:
                tokens = tokenise(path)
                for _, tier in self.deny.find(tokens, self._skipped_tiers(False)):
                    self._record_tier(tier, place, None)
                    self.hidden_paths.add(path)
            if self._content_on:
                for rule, pattern in TOPOLOGY_PATTERNS.items():
                    if pattern.search(path):
                        self._record(rule, place, None)
                        self.hidden_paths.add(path)
        if not self._content_on:
            return
        basename = posixpath.basename(path)
        if basename in SCANNER_CONFIG_NAMES:
            self._record("scanner-rules-changed", place, None)
        if basename == ".gitmodules":
            self._record("submodule", place, None)
        if change.new_mode == MODE_GITLINK:
            self._record("submodule", place, None)
        allowed = self.rules.repo.allowed_paths
        if allowed is not None and not any(glob_matches(p, path) for p in allowed):
            self._record("path-not-allowed", place, None)

    def _check_symlink(self, place: Place, path: str, target: str) -> None:
        if not self._content_on:
            return
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(path), target))
        if target.startswith("/") or resolved == ".." or resolved.startswith("../"):
            self._record("symlink-leaves-repository", place, None)

    def _check_binary(self, sha: str, change: Change, kind: str) -> None:
        """Binary and LFS files aren't read as text, so they need an explicit allowance."""
        if not self._content_on:
            return
        place = Place(sha, change.path)
        allowed = any(glob_matches(p, change.path) for p in self.rules.repo.binary_allow)
        if not allowed:
            self._record(f"{kind}-not-allowed", place, None)
            return
        self.binary_allowed.append(change.path)
        info = self.repo.info(change.new_sha)
        if kind == "binary" and info and info[1] <= MAX_TEXT_BYTES and self.deny is not None:
            _, data = self.repo.read(change.new_sha)
            words = tokenise(data.decode("latin-1"))
            for _, tier in self.deny.find(words, self._skipped_tiers(False)):
                self._record_tier(tier, place, None)

    def _place_for_stream_line(self, line: int) -> tuple[Place, int, int]:
        """Map a stream line to (place, line within it, segment index)."""
        if line <= self._preamble_lines:
            raise GuardError("gitleaks reported a finding inside the guard's own text")
        index = bisect.bisect_right(self._starts, line) - 1
        place, first = self._segments[index]
        return place, first + line - self._starts[index], index

    def run_gitleaks(self, gitleaks: str, config: Path, scratch: Path, stream: Path) -> None:
        """Run the secret scan on the collected text, with no input from the repository."""
        self._stream.close()
        if self._stream_lines == self._preamble_lines:
            return
        empty_folder = scratch / "empty"
        empty_folder.mkdir()
        ignore = scratch / "empty.ignore"
        ignore.touch()
        report = scratch / "report.json"
        env = {"PATH": "/usr/bin:/bin", "HOME": str(empty_folder), "LANG": "C.UTF-8"}
        with stream.open("rb") as handle:
            try:
                result = subprocess.run(
                    [
                        gitleaks, "stdin", "--no-banner", "--log-level", "error",
                        "--config", str(config),
                        "--ignore-gitleaks-allow",
                        "--gitleaks-ignore-path", str(ignore),
                        "--report-format", "json", "--report-path", str(report),
                        "--redact", "--exit-code", "7",
                    ],
                    stdin=handle, capture_output=True, env=env, cwd=empty_folder,
                )
            except OSError as error:
                raise GuardError("gitleaks can't run") from error
        if result.returncode not in (0, 7):
            raise GuardError(f"gitleaks failed with status {result.returncode}")
        if result.returncode == 0:
            return
        try:
            items = json.loads(report.read_text())
            for item in items:
                place, line, index = self._place_for_stream_line(int(item["StartLine"]))
                if index in self._segment_paths:
                    self.hidden_paths.add(self._segment_paths[index])
                self._record(f"secret:{item['RuleID']}", place, line, "block")
        except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
            raise GuardError("gitleaks wrote a report that can't be read") from error
        if not items:
            raise GuardError("gitleaks reported a leak but listed none")


def _identity_text(line: bytes) -> str:
    """The name and address from a raw `author`, `committer`, or `tagger` line."""
    text = line.split(b" ", 1)[1].decode("utf-8", "replace")
    return re.sub(r"\s+\d+\s+[+-]\d{4}$", "", text)


def display_place(finding: Finding, hidden: set[str] | None) -> str:
    """Format a location, withholding any path that itself holds a deny-listed term.

    `hidden` is None when no deny-list was loaded, as on a never-public remote: then nothing can
    tell which paths are safe to show, so every path is withheld.
    """
    place = finding.place
    if place.label:
        path = place.path
    elif hidden is None or place.path in hidden:
        path = "<path hidden>"
    else:
        path = place.path
    commit = f"commit {finding.place.commit[:12]}  " if finding.place.commit else ""
    line = f":{finding.line}" if finding.line else ""
    return f"{commit}{path}{line}"


# ------------------------------------------------------------------ the hook


def read_install(home: Path) -> dict:
    """Read what `install` recorded. Without it, the guard can't run."""
    path = home / "install.json"
    if not path.is_file():
        raise GuardError("the guard isn't installed: install.json is missing")
    return json.loads(path.read_text())


def absolute_git_dir(git: str) -> Path:
    """Find this repository's git folder, ignoring session settings that could mislead it."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_CONFIG")}
    result = subprocess.run(
        [git, "rev-parse", "--absolute-git-dir"], capture_output=True, text=True, env=env
    )
    if result.returncode != 0:
        raise GuardError("this doesn't look like a git repository")
    return Path(result.stdout.strip())


def common_git_dir(git: str) -> Path:
    """The folder shared by linked worktrees, where a repository's own hooks live."""
    result = subprocess.run(
        [git, "rev-parse", "--git-common-dir"], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise GuardError("this doesn't look like a git repository")
    return Path(result.stdout.strip()).resolve()


@dataclasses.dataclass(frozen=True)
class Update:
    """One line of what `git push` passes to a pre-push hook."""

    local_ref: str
    local_sha: str
    remote_ref: str
    remote_sha: str

    @property
    def is_delete(self) -> bool:
        return set(self.local_sha) == {"0"}


def parse_updates(data: bytes) -> list[Update]:
    """Parse the hook's standard input. Anything unexpected refuses the push."""
    updates = []
    for line in data.decode("utf-8", "surrogateescape").splitlines():
        parts = line.split(" ")
        if len(parts) != 4:
            raise GuardError("the pre-push input can't be parsed")
        updates.append(Update(*parts))
    return updates


def _outside_repository_env() -> dict[str, str]:
    """The user's environment, minus anything that would point git at a repository or override
    its configuration for one command."""
    dropped = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
               "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT", "GIT_NAMESPACE")
    return {
        k: v for k, v in os.environ.items()
        if k not in dropped and not k.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))
    }


def remote_commits(git: str, url: str, repo: Repository, outside: Path) -> list[str]:
    """What the destination already has, asked of the destination.

    Tracking refs are never used. After `git remote set-url`, they describe a different repository,
    which would make a private history look already published. Only SHAs this repository also has
    can be excluded; a remote commit this clone hasn't fetched is ignored.

    The question is asked from outside the repository, so its own settings can't redirect it, and
    the guard refuses if the user's settings would rewrite the URL. Otherwise a local `insteadOf`
    could send the question to a private repository, whose history would then look published
    (audit finding C2, 8 November 2026).
    """
    env = _outside_repository_env()
    try:
        resolved = subprocess.run(
            [git, "ls-remote", "--get-url", "--", url], capture_output=True, text=True,
            env=env, cwd=outside, timeout=NETWORK_TIMEOUT_SECONDS,
        )
        if resolved.returncode != 0 or resolved.stdout.strip() != url:
            raise GuardError(
                "git settings rewrite this push's URL, so the guard can't be sure which "
                "repository it would be asking; remove the url rewriting rule, then push again"
            )
        # This call needs the user's credentials and transport settings, so it isn't locked.
        result = subprocess.run(
            [git, "ls-remote", "--", url], capture_output=True, text=True, env=env,
            cwd=outside, timeout=NETWORK_TIMEOUT_SECONDS,
        )
    except subprocess.SubprocessError as error:
        raise GuardError("asking the remote what it has timed out") from error
    if result.returncode != 0:
        raise GuardError("asking the remote what it has failed")
    known = []
    for line in result.stdout.splitlines():
        sha = line.split("\t")[0]
        info = repo.info(sha)
        if info and info[0] in ("commit", "tag"):
            known.append(sha)
    return known


def commits_to_scan(repo: Repository, tips: list[str], known: list[str]) -> list[str]:
    """Every commit reachable from the tips and not from what the remote has."""
    if not tips:
        return []
    stdin = "\n".join([*tips, *(f"^{sha}" for sha in known)]) + "\n"
    return repo.run("rev-list", "--stdin", stdin=stdin.encode()).decode().split()


def override_path(home: Path, repo: str, push_id: str) -> Path:
    joined = "\n".join([repo.lower(), push_id])
    return home / "overrides" / f"{hashlib.sha256(joined.encode()).hexdigest()}.json"


def push_fingerprint(updates: Iterable[Update], findings: Iterable[Finding] = ()) -> str:
    """An identifier for exactly these ref updates and findings, which an exemption is bound to.

    It covers every destination ref and the commit pushed to it, and every finding, so a push
    that has grown since the person looked (the remote moved, or a ref was added) isn't covered.
    It is printed in place of the refs themselves, because a ref name can be what was blocked.
    """
    keys = sorted({f"{u.remote_ref}={u.local_sha}" for u in updates if not u.is_delete})
    found = sorted({f"{f.rule}|{f.place.commit}|{f.place.path}|{f.line}" for f in findings})
    joined = "\n".join([*keys, "--", *found])
    # A path that isn't valid UTF-8 is kept as git gave it.
    return hashlib.sha256(joined.encode("utf-8", "surrogateescape")).hexdigest()[:32]


def policy_generation(home: Path) -> str:
    """A fingerprint of the policy and deny-lists, so an exemption lapses when either changes."""
    digest = hashlib.sha256()
    for path in [home / "policy.toml", *sorted((home / "deny").glob("*.hashes"))]:
        digest.update(path.name.encode() + b"\0")
        digest.update(path.read_bytes() if path.is_file() else b"<absent>")
        digest.update(b"\0")
    return digest.hexdigest()


def write_log(home: Path, record: dict) -> None:
    """Append an outcome. A logging failure never decides a push."""
    try:
        folder = home / "log"
        folder.mkdir(parents=True, exist_ok=True)
        record = {"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **record}
        with (folder / "guard.jsonl").open("a") as handle:
            handle.write(json.dumps(record) + "\n")
    except OSError:
        pass


def hand_over(install: dict, remote: str, url: str, stdin: bytes) -> int:
    """Run the repository's own pre-push step, passing along the same input.

    The guard goes first because Git Large File Storage (LFS) uploads during its own hook.
    """
    if install.get("no_hand_over"):
        return 0
    git = install["git"]
    common = common_git_dir(git)
    local = common / "hooks" / "pre-push"
    if local.is_file() and os.access(local, os.X_OK):
        return subprocess.run([str(local), remote, url], input=stdin).returncode
    if (common / "lfs").is_dir():
        return subprocess.run([git, "lfs", "pre-push", remote, url], input=stdin).returncode
    return 0


def _scan_timed_out(_signum: int, _frame: object) -> None:
    raise GuardError("the check ran out of time, so the push was refused")


def _read_override(path: Path, repo: str, push_id: str, generation: str) -> dict | None:
    """An exemption, if one exists for exactly this push, is well formed, and is still current.

    It must name the same repository and the same ref updates, be under an hour old, and have been
    made under the same policy and deny-lists. Reading it consumes it, by renaming it first, so two
    pushes can't both use one exemption.
    """
    if not path.is_file():
        return None
    claimed = path.with_suffix(".claimed")
    try:
        os.replace(path, claimed)
        details = json.loads(claimed.read_text())
        claimed.unlink()
    except (OSError, ValueError):
        return None
    try:
        age = time.time() - float(details.get("created", 0))
    except (TypeError, ValueError, AttributeError):
        return None
    if (
        not isinstance(details, dict)
        or str(details.get("repo", "")).lower() != repo.lower()
        or details.get("push") != push_id
        or details.get("generation") != generation
        or not 0 <= age <= OVERRIDE_LIFETIME_SECONDS
        or not str(details.get("reason", "")).strip()
    ):
        return None
    return details


def summarise(findings: list[Finding]) -> dict[str, int]:
    """Count findings by rule."""
    return dict(collections.Counter(f.rule for f in findings))


def report_block(
    destination: Destination,
    findings: list[Finding],
    hidden: set[str] | None,
    push_id: str,
    home: Path,
) -> None:
    """Print what blocked a push, with locations and no values."""
    print(
        f"{MARKER}: {len(findings)} finding(s) pushing to {destination.name} "
        f"({destination.visibility}). Nothing was pushed.",
        file=sys.stderr,
    )
    for finding in findings[:MAX_LISTED_FINDINGS]:
        print(f"  {finding.rule}  {display_place(finding, hidden)}", file=sys.stderr)
    if len(findings) > MAX_LISTED_FINDINGS:
        print(f"  ... and {len(findings) - MAX_LISTED_FINDINGS} more", file=sys.stderr)
    print(
        "  Matched text isn't shown. Fix the commits, or, if this is a false positive, a person "
        "can exempt this exact push, within the hour, from their own terminal:\n"
        f"  python3 -I {home / 'engine' / 'publish_guard.py'} --home {home} override "
        f"--repo {destination.name} --push {push_id}",
        file=sys.stderr,
    )


def verified_gitleaks(install: dict) -> str:
    """The secret scanner, checked against its pinned checksum on every push (Astra review, 6)."""
    gitleaks = install.get("gitleaks")
    if not gitleaks or not os.access(gitleaks, os.X_OK):
        raise GuardError("gitleaks is missing")
    pinned = install.get("gitleaks_sha256")
    if pinned and _sha256(Path(gitleaks)) != pinned:
        raise GuardError("gitleaks doesn't match its pinned checksum")
    if not pinned and not install.get("test_mode"):
        raise GuardError("gitleaks has no pinned checksum; reinstall with --gitleaks-sha256")
    return gitleaks


def write_scanner_config(scratch: Path) -> Path:
    """Write the scanner's rules from the engine itself, so a changed copy on disk has no effect."""
    config = scratch / "gitleaks.toml"
    config.write_text(SCANNER_CONFIG)
    return config


def load_for_private_push(home: Path, policy: Policy | None) -> tuple[DenyList | None, bool]:
    """The deny-list for a private push, and whether all of it loaded.

    The other tiers only warn there, so a broken list is a warning. The secrets tier blocks on
    every remote, so if its file exists and can't be read, the push is refused rather than sent
    unchecked (second audit, M4, 8 November 2026). The same holds when its file is missing but
    the tier is expected (Astra review W3).
    """
    expected = secret_tier_expected(home, policy)
    try:
        return DenyList.load(home, (SECRET_TIER,) if expected else ()), True
    except GuardError:
        print(f"{WARNING}: the deny-list can't be loaded, so it wasn't read", file=sys.stderr)
    if expected or (DenyFiles(home).folder / f"{SECRET_TIER}.hashes").is_file():
        return DenyList.load(home, (SECRET_TIER,), only={SECRET_TIER}), False
    return None, False


def run_hook(home: Path, remote: str, url: str) -> int:
    """The pre-push hook itself. Returns the status for git."""
    stdin = sys.stdin.buffer.read()
    install = read_install(home)
    destination = classify_destination(url, install)
    if destination.visibility == "local":
        write_log(home, {"repo": "<local path>", "visibility": "local", "decision": "not-scanned"})
        return hand_over(install, remote, url, stdin)
    record = {"repo": destination.name, "visibility": destination.visibility}
    try:
        rules = decide_rules(destination, home)
    except (Blocked, GuardError) as error:
        write_log(home, {**record, "decision": "blocked", "reason": type(error).__name__,
                         "alert": getattr(error, "alert", False)})
        raise
    gitleaks = verified_gitleaks(install)
    deny = None
    complete = True
    if rules.content == "block":
        deny = DenyList.load(home, required_tiers(home, rules.policy))
        stale = stale_sources(home)
        if stale:
            raise GuardError(
                f"deny-list: {', '.join(stale)} edited but not rebuilt; run deny-rebuild"
            )
    else:
        deny, complete = load_for_private_push(home, rules.policy)
        if rules.content == "warn" and complete and stale_sources(home):
            print(f"{WARNING}: a deny-list source was edited but not rebuilt", file=sys.stderr)
    # Without the full deny-list applied, the guard can't tell which paths are safe to show, so
    # it shows none, in the report or the log.
    full = deny is not None and complete and rules.content != "off"
    updates = parse_updates(stdin)
    pushes = [u for u in updates if not u.is_delete]
    git = install["git"]
    repo = Repository(git, absolute_git_dir(git))
    # The scan has a time limit; the hand-over to the repository's own hook, such as an LFS
    # upload, runs afterwards without one (audit finding M5).
    limit = int(install.get("scan_timeout") or SCAN_TIMEOUT_SECONDS)
    previous = signal.signal(signal.SIGALRM, _scan_timed_out)
    signal.alarm(limit)
    try:
        with tempfile.TemporaryDirectory(prefix="publish-guard-") as scratch_name:
            scratch = Path(scratch_name)
            stream = scratch / "added.txt"
            outside = scratch / "outside"
            outside.mkdir()
            scanner = Scanner(repo, rules, deny, stream)
            tips: list[str] = []
            for update in pushes:
                scanner.check_ref(update.remote_ref)
                tip = scanner.scan_tag_chain(update.local_sha)
                if tip:
                    tips.append(tip)
            known = remote_commits(git, url, repo, outside) if pushes else []
            commits = commits_to_scan(repo, tips, known)
            for sha in commits:
                scanner.scan_commit(sha)
            scanner.run_gitleaks(gitleaks, write_scanner_config(scratch), scratch, stream)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
        repo.close()
    blocking = [f for f in scanner.findings if f.severity == "block"]
    warnings = [f for f in scanner.findings if f.severity == "warn"]
    push_id = push_fingerprint(pushes, blocking)
    record.update(
        commits=len(commits), counts=summarise(scanner.findings),
        binary_allowed=sorted(
            {p if full and p not in scanner.hidden_paths else "<path hidden>"
             for p in scanner.binary_allowed}
        ),
    )
    if blocking:
        exemption = override_path(home, destination.name, push_id)
        details = _read_override(exemption, destination.name, push_id, policy_generation(home))
        if details is not None:
            write_log(home, {**record, "decision": "overridden", "reason": details["reason"]})
            print(f"{WARNING}: exempted by a person: {len(blocking)} finding(s)", file=sys.stderr)
        else:
            write_log(home, {**record, "decision": "blocked"})
            hidden = scanner.hidden_paths if full else None
            report_block(destination, blocking, hidden, push_id, home)
            return EXIT_BLOCKED
    else:
        write_log(home, {**record, "decision": "passed"})
    if warnings:
        print(
            f"{WARNING}: {len(warnings)} public-rule hit(s) in a private repository; they would "
            "block if it went public. Counts are in the guard's log.",
            file=sys.stderr,
        )
    return hand_over(install, remote, url, stdin)


# ------------------------------------------------------------------ installation


def render_pre_push_stub(install: dict, home: Path) -> str:
    """The stub for the check itself. Any failure to run means git refuses the push, and the
    refusal carries the same marker as the engine's own."""
    engine = str(home / "engine" / "publish_guard.py")
    command = shlex.join([install["python"], "-I", engine, "--home", str(home), "hook-pre-push"])
    return (
        "#!/bin/sh\n# Generated by publish_guard.py install. `doctor` checks this file.\n"
        f"if [ ! -x {shlex.quote(install['python'])} ] || [ ! -r {shlex.quote(engine)} ]; then\n"
        f'  echo "{MARKER}: the guard can\'t run (its engine or Python is missing), so '
        'refusing." >&2\n'
        "  exit 1\n"
        "fi\n"
        f'exec {command} "$@"\n'
    )


def render_pass_through_stub(name: str) -> str:
    """A stub that only restores the repository's own hook of the same name."""
    return (
        "#!/bin/sh\n# Generated by publish_guard.py install. `doctor` checks this file.\n"
        'dir=$(git rev-parse --git-common-dir 2>/dev/null) || exit 0\n'
        f'hook="$dir/hooks/{name}"\n'
        'if [ -x "$hook" ]; then exec "$hook" "$@"; fi\n'
        "exit 0\n"
    )


def expected_stubs(install: dict, home: Path) -> dict[str, str]:
    stubs = {name: render_pass_through_stub(name) for name in PASS_THROUGH_HOOKS}
    stubs["pre-push"] = render_pre_push_stub(install, home)
    return stubs


def _require_tool(name: str, given: str | None = None) -> str:
    found = given or shutil.which(name)
    if not found:
        raise GuardError(f"{name} wasn't found")
    return found


def command_install(home: Path, args: argparse.Namespace) -> int:
    """Install the engine copy and stubs. Activating them globally is a separate, explicit step."""
    home.mkdir(parents=True, exist_ok=True)
    os.chmod(home, 0o700)
    install = {
        "git": _require_tool("git"),
        "python": _require_tool("python3", "/usr/bin/python3" if Path("/usr/bin/python3").exists()
                                else sys.executable),
        "gh": shutil.which("gh"),
        "gitleaks": args.gitleaks or str(home / "bin" / "gitleaks"),
        "gitleaks_sha256": args.gitleaks_sha256,
        "visibility_map": args.visibility_map,
        "no_hand_over": args.no_hand_over,
        "test_mode": args.test_mode,
        "scan_timeout": args.scan_timeout,
    }
    if (args.visibility_map or args.scan_timeout) and not args.test_mode:
        raise GuardError("--visibility-map and --scan-timeout are for tests, with --test-mode")
    if not args.gitleaks_sha256 and not args.test_mode:
        raise GuardError("--gitleaks-sha256 is needed, so every push can check the scanner")
    if args.gitleaks_sha256:
        candidate = Path(install["gitleaks"])
        if not candidate.is_file() or _sha256(candidate) != args.gitleaks_sha256.lower():
            # The checksum to give is the binary's, not the release archive's (second audit, L8).
            raise GuardError(
                "gitleaks doesn't match --gitleaks-sha256 (give the binary's checksum)"
            )
        install["gitleaks_sha256"] = args.gitleaks_sha256.lower()
    engine_folder = home / "engine"
    engine_folder.mkdir(exist_ok=True)
    engine = engine_folder / "publish_guard.py"
    if engine.exists():
        engine.chmod(0o600)
    shutil.copyfile(Path(__file__).resolve(), engine)
    engine.chmod(0o444)
    install["engine_sha256"] = _sha256(engine)
    agent_hook = Path(__file__).resolve().with_name("agent_hook.py")
    if agent_hook.is_file():
        target = engine_folder / "agent_hook.py"
        if target.exists():
            target.chmod(0o600)
        shutil.copyfile(agent_hook, target)
        target.chmod(0o444)
        install["agent_hook_sha256"] = _sha256(target)
    record = home / "install.json"
    if record.exists():
        record.chmod(0o600)
    record.write_text(json.dumps(install, indent=2) + "\n")
    record.chmod(0o444)
    # The scanner's rules are written from the engine on every run, so no copy is kept here.
    stale_rules = home / "gitleaks.toml"
    if stale_rules.exists():
        stale_rules.unlink()
    (home / "overrides").mkdir(exist_ok=True)
    (home / "log").mkdir(exist_ok=True)
    hooks = home / "hooks"
    hooks.mkdir(exist_ok=True)
    hooks.chmod(0o700)
    for stale in hooks.iterdir():
        stale.chmod(0o700)
        stale.unlink()
    for name, text in expected_stubs(install, home).items():
        path = hooks / name
        path.write_text(text)
        path.chmod(0o555)
    hooks.chmod(0o555)
    if args.activate_global:
        subprocess.run(
            [install["git"], "config", "--global", "core.hooksPath", str(hooks)], check=True
        )
    print(f"installed at {home}" + (" and activated globally" if args.activate_global else ""))
    return 0


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ------------------------------------------------------------------ other commands


def command_deny_add(home: Path, args: argparse.Namespace) -> int:
    """Add terms from a file or standard input.

    The output doesn't say whether a term was already listed, so it can't be used to test guesses.
    """
    _require_terminal("deny-add", home, reads_input=False)
    source = Path(args.from_file).read_text() if args.from_file else sys.stdin.read()
    added, _ = deny_add(home, args.tier, source.splitlines())
    print(f"added {added} term(s) to {args.tier}")
    return 0


def command_deny_rebuild(home: Path, args: argparse.Namespace) -> int:
    """Replace tiers from their source files, or one tier from standard input. Counts only."""
    _require_terminal("deny-rebuild", home, reads_input=False)
    if args.stdin:
        if not args.tier:
            raise GuardError("--stdin needs --tier")
        if args.tier in source_files(home):
            # Rebuilding such a tier from standard input would leave it permanently stale, and
            # every public push refused (second audit, L7).
            raise GuardError(f"{args.tier} has a source file: edit that, then run deny-rebuild")
        used, total = deny_rebuild(home, args.tier, sys.stdin.read(), keep_source_hash=False)
        print(f"{args.tier}: rebuilt from {used} term(s), {total} entries")
        return 0
    sources = source_files(home)
    if args.tier:
        sources = {k: v for k, v in sources.items() if k == args.tier}
    if not sources:
        raise GuardError("no source file to rebuild from")
    for tier, path in sources.items():
        used, total = deny_rebuild(home, tier, path.read_text(), keep_source_hash=True)
        print(f"{tier}: rebuilt from {used} term(s), {total} entries")
    return 0


def _test_mode(home: Path) -> bool:
    try:
        return bool(read_install(home).get("test_mode"))
    except (GuardError, OSError, ValueError):
        return False


def _require_terminal(what: str, home: Path, reads_input: bool = True) -> None:
    """Keep list changes, look-ups, and exemptions to a person at a terminal.

    An agent's shell has no terminal, so this stops an agent probing or shrinking the lists, or
    granting an exemption, by mistake. It can be faked deliberately, for example with script(1),
    so it isn't protection against a determined agent; the agent-side hook adds a second check.
    Commands that only report counts need a terminal for output; those that prompt need one for
    input as well.
    """
    if _test_mode(home):
        return
    if not (os.isatty(1) or os.isatty(2)) or (reads_input and not os.isatty(0)):
        raise GuardError(f"{what} needs a person at a terminal")


def _prompt_hidden(prompt: str) -> str:
    """Read a line from the terminal without showing it. Echo goes off before the prompt shows."""
    settings = termios.tcgetattr(0)
    quiet = list(settings)
    quiet[3] = quiet[3] & ~termios.ECHO
    termios.tcsetattr(0, termios.TCSAFLUSH, quiet)
    try:
        print(prompt, end="", flush=True)
        return sys.stdin.readline().strip()
    finally:
        termios.tcsetattr(0, termios.TCSANOW, settings)
        print()


def command_deny_check(home: Path, _args: argparse.Namespace) -> int:
    """Say whether a term is listed, and where."""
    _require_terminal("deny-check", home)
    tiers = deny_tiers_holding(home, _prompt_hidden("Term to look up (not shown): "))
    print(f"listed in: {', '.join(tiers)}" if tiers else "not on any list")
    return 0


def command_deny_remove(home: Path, args: argparse.Namespace) -> int:
    """Remove a term from a tier that has no source file, such as frozen teaching."""
    _require_terminal("deny-remove", home)
    removed = deny_remove(home, args.tier, _prompt_hidden("Term to remove (not shown): "))
    print(f"removed {removed} entries" if removed else "nothing matched, so nothing changed")
    return 0


def command_deny_stats(home: Path, _args: argparse.Namespace) -> int:
    """Show how many entries each tier holds."""
    folder = DenyFiles(home).folder
    for path in sorted(folder.glob("*.hashes")):
        lines = [x for x in path.read_text().splitlines() if x and not x.startswith("#")]
        print(f"{path.stem}: {max(len(lines) - 1, 0)} entries")
    return 0


def command_override(home: Path, args: argparse.Namespace) -> int:
    """Exempt one exact push. Needs a person at a terminal, and it is logged."""
    if not (os.isatty(0) and os.isatty(1)):
        print("publish-guard: an override needs a person at a terminal.", file=sys.stderr)
        return 1
    reason = input("Reason for this exemption (logged): ").strip()  # shown, so it can be checked
    if not reason:
        print("publish-guard: an override needs a reason.", file=sys.stderr)
        return 1
    if not re.fullmatch(r"[0-9a-f]{32}", args.push):
        print("publish-guard: --push takes the identifier the blocked push printed.",
              file=sys.stderr)
        return 1
    path = override_path(home, args.repo, args.push)
    path.parent.mkdir(parents=True, exist_ok=True)
    details = {
        "repo": args.repo, "push": args.push, "reason": reason,
        "created": time.time(), "generation": policy_generation(home),
    }
    path.write_text(json.dumps(details))
    write_log(home, {"repo": args.repo.lower(), "decision": "override-created", "reason": reason})
    print("exemption recorded for this exact push; it works once, within the hour")
    return 0


def _single_object(repo: Repository, rev: str) -> str | None:
    """The object a revision names, or None if it names none or several (such as `HEAD^!`)."""
    try:
        return repo.run("rev-parse", "--verify", "--end-of-options", rev).decode().strip()
    except GuardError:
        return None


def audit_tips(repo: Repository, scanner: Scanner, revs: list[str]) -> tuple[int, list[str]]:
    """Scan the refs an audit covers, and return (refs read, commits they lead to).

    With `--all`, every ref is read: its name, and any tag objects it points through, which
    commits alone don't show (Astra review, finding 3, 8 November 2026), and a detached HEAD too.
    Each other revision that names a single object has its tag chain read, unless it comes after
    `--not`. Anything else, such as a range, `HEAD^!`, or an option like `--since=`, is left to
    rev-list, which receives every revision as given (second audit, M1 and M2).
    """
    tips: list[str] = []
    count = 0
    named: list[tuple[str, str | None]] = []
    if "--all" in revs:
        listing = repo.run("for-each-ref", "--format=%(objectname) %(refname)").decode()
        for line in listing.splitlines():
            sha, _, ref = line.partition(" ")
            named.append((sha, ref))
        head = _single_object(repo, "HEAD")
        if head:
            named.append((head, None))
    excluding = False
    for rev in revs:
        if rev == "--not":
            excluding = not excluding
            continue
        if excluding or rev.startswith(("-", "^")) or ".." in rev:
            continue
        sha = _single_object(repo, rev)
        if sha:
            named.append((sha, None))
    for sha, ref in named:
        count += 1
        if ref is not None:
            scanner.check_ref(ref, namespace_rule=False)
        tip = scanner.scan_tag_chain(sha)
        if tip:
            tips.append(tip)
    return count, tips


def command_audit(home: Path, args: argparse.Namespace) -> int:
    """Apply the same rules to existing history. Reports locations and counts, never values."""
    install = read_install(home)
    gitleaks = verified_gitleaks(install)
    entry = RepoPolicy()
    policy = None
    try:
        policy = load_policy(home)
        entry = policy.repos.get(args.name.lower(), RepoPolicy())
    except GuardError:
        pass
    content = "block" if args.treat_as == "public" else "off"
    rules = Rules(content, entry, policy)
    deny = None
    if content == "block":
        deny = DenyList.load(home, required_tiers(home, policy))
    else:
        try:
            deny = DenyList.load(home, ())
        except GuardError:
            print(f"{WARNING}: the deny-list can't be loaded, so it wasn't read", file=sys.stderr)
    git = install["git"]
    git_dir = Path(
        subprocess.run(
            [git, "-C", args.repo, "rev-parse", "--absolute-git-dir"], capture_output=True,
            text=True, check=True,
        ).stdout.strip()
    )
    repo = Repository(git, git_dir)
    try:
        with tempfile.TemporaryDirectory(prefix="publish-guard-") as scratch_name:
            scratch = Path(scratch_name)
            stream = scratch / "added.txt"
            scanner = Scanner(repo, rules, deny, stream)
            refs, tips = audit_tips(repo, scanner, args.rev)
            # The tag-peeled tips go first, so a `--not` among the given revisions can't negate
            # them. Revisions go as arguments, because rev-list's --stdin rejects options.
            commits = repo.run("rev-list", *tips, *args.rev).decode().split()
            for sha in commits:
                scanner.scan_commit(sha)
            scanner.run_gitleaks(gitleaks, write_scanner_config(scratch), scratch, stream)
    finally:
        repo.close()
    print(f"{args.name}: {refs} ref(s) and {len(commits)} commit(s) read as {args.treat_as}")
    for rule, count in sorted(summarise(scanner.findings).items()):
        print(f"  {count:6d}  {rule}")
    hidden = scanner.hidden_paths if deny is not None and content != "off" else None
    for finding in scanner.findings[: args.list]:
        print(f"  {finding.rule}  {display_place(finding, hidden)}")
    return 1 if scanner.findings else 0


def _git_folders(roots: Iterable[str], depth: int = 4) -> Iterator[Path]:
    for root in roots:
        for folder, subfolders, files in os.walk(root):
            current = Path(folder)
            if len(current.relative_to(root).parts) >= depth:
                subfolders.clear()
                continue
            if ".git" in subfolders or ".git" in files:
                yield current
            # Keep going: nested repositories, such as submodules, need checking too.
            if ".git" in subfolders:
                subfolders.remove(".git")


def _effective_hooks_path(git: str, folder: Path) -> str | None:
    """The hooks setting git will actually use in a repository.

    This reads the full configuration, so a conditional include in the user's settings that
    switches hooks off for some folders is seen too (audit finding L6).
    """
    result = subprocess.run(
        [git, "-C", str(folder), "config", "--get", "core.hooksPath"], capture_output=True,
        text=True,
    )
    return result.stdout.strip() or None


def command_doctor(home: Path, args: argparse.Namespace) -> int:
    """Check that the guard is really in force on this machine. Prints no deny-listed values."""
    issues: list[str] = []
    notices: list[str] = []
    try:
        install = read_install(home)
    except GuardError as error:
        print(f"PROBLEM: {error}")
        return 1
    git = install["git"]
    hooks = home / "hooks"
    current = subprocess.run(
        [git, "config", "--global", "--get", "core.hooksPath"], capture_output=True, text=True
    ).stdout.strip()
    if current != str(hooks):
        found = current or "unset"
        issues.append(f"global core.hooksPath isn't the guard's folder (found: {found})")
    if hooks.is_dir() and hooks.stat().st_mode & stat.S_IWUSR:
        issues.append("the hooks folder is writable")
    for name, expected in expected_stubs(install, home).items():
        path = hooks / name
        if path.is_symlink() or not path.is_file():
            issues.append(f"stub {name} is missing or isn't a real file")
        elif path.read_text() != expected:
            issues.append(f"stub {name} has been changed")
        elif path.stat().st_mode & stat.S_IWUSR:
            issues.append(f"stub {name} is writable")
        elif not os.access(path, os.X_OK):
            issues.append(f"stub {name} isn't executable, so git would skip it")
    engine = home / "engine" / "publish_guard.py"
    if not engine.is_file() or _sha256(engine) != install.get("engine_sha256"):
        issues.append("the installed engine is missing or has been changed")
    hook = home / "engine" / "agent_hook.py"
    if install.get("agent_hook_sha256") and (
        not hook.is_file() or _sha256(hook) != install["agent_hook_sha256"]
    ):
        issues.append("the installed agent hook is missing or has been changed")
    gitleaks = install.get("gitleaks")
    if not gitleaks or not os.access(gitleaks, os.X_OK):
        issues.append("gitleaks is missing")
    elif not install.get("gitleaks_sha256"):
        if not install.get("test_mode"):
            issues.append("gitleaks has no pinned checksum, so every push is refused")
    elif _sha256(Path(gitleaks)) != install["gitleaks_sha256"]:
        issues.append("gitleaks doesn't match its pinned checksum")
    if install.get("test_mode") and not args.test:
        issues.append("the guard is installed in test mode, which relaxes its checks")
    policy: Policy | None = None
    try:
        policy = load_policy(home)
    except GuardError as error:
        issues.append(str(error))
    try:
        DenyList.load(home, required_tiers(home, policy))
    except (GuardError, ValueError) as error:
        issues.append(str(error))
    for tier in stale_sources(home):
        issues.append(f"deny-list: {tier} was edited but not rebuilt; run deny-rebuild")
    for folder in _git_folders(args.scan or ()):
        effective = _effective_hooks_path(git, folder)
        if effective == "/dev/null":
            notices.append(f"unguarded: hooks are off at {folder}")
        elif effective != str(hooks):
            issues.append(f"git won't use the guard's hooks in {folder}")
    for notice in notices:
        print(f"note: {notice}")
    for issue in issues:
        print(f"PROBLEM: {issue}")
    if not issues:
        print("the guard is in force")
    return 1 if issues else 0


# ------------------------------------------------------------------ the watcher


def _gh_json(gh: str, *args: str) -> object:
    """Run the GitHub CLI and parse its JSON output, or raise GuardError."""
    env = {k: v for k, v in os.environ.items() if k not in ("GH_HOST", "GH_REPO", "GH_PAGER")}
    try:
        result = subprocess.run(
            [gh, *args], capture_output=True, text=True, env=env,
            timeout=NETWORK_TIMEOUT_SECONDS * 3,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise GuardError(f"gh {args[0]} couldn't run") from error
    if result.returncode != 0:
        raise GuardError(f"gh {args[0]} failed")
    try:
        return json.loads(result.stdout or "null")
    except json.JSONDecodeError as error:
        raise GuardError(f"gh {args[0]} gave output that isn't JSON") from error


def owner_listing(gh: str, owner: str) -> dict[str, tuple[str, bool]]:
    """Every repository an owner has that this account can see: (visibility, archived)."""
    rows = _gh_json(gh, "repo", "list", owner, "--limit", "5000", "--json",
                    "nameWithOwner,visibility,isArchived")
    if not isinstance(rows, list):
        raise GuardError("gh repo list gave an unexpected answer")
    return {
        str(r["nameWithOwner"]).lower(): (str(r["visibility"]).lower(), bool(r.get("isArchived")))
        for r in rows
    }


def is_watched(name: str, entry: RepoPolicy, policy: Policy) -> bool:
    """Whether the watcher reads a public repository's new content."""
    if entry.watch is not None:
        return entry.watch
    return entry.label == "public" and name.split("/", 1)[0] in policy.watch_owners


def remote_refs(git: str, url: str, outside: Path) -> dict[str, str]:
    """A remote's refs, asked of the remote, without peeled tag lines."""
    try:
        result = subprocess.run(
            [git, "ls-remote", "--", url], capture_output=True, text=True,
            env={**_outside_repository_env(), "GIT_TERMINAL_PROMPT": "0"}, cwd=outside,
            timeout=NETWORK_TIMEOUT_SECONDS,
        )
    except subprocess.SubprocessError as error:
        raise GuardError("asking the remote what it has timed out") from error
    if result.returncode != 0:
        raise GuardError("asking the remote what it has failed")
    refs = {}
    for line in result.stdout.splitlines():
        sha, _, ref = line.partition("\t")
        if ref and not ref.endswith("^{}") and ref != "HEAD":
            refs[ref] = sha
    return refs


def refresh_mirror(git: str, url: str, mirror: Path, outside: Path) -> None:
    """Bring a bare mirror of a public repository up to date, cloning it the first time.

    Hooks are off for these reads: nothing here pushes, and a mirror has no hooks of its own.
    """
    env = {**_outside_repository_env(), "GIT_TERMINAL_PROMPT": "0"}
    base = [git, "-c", "core.hooksPath=/dev/null"]
    if (mirror / "HEAD").is_file():
        command = [*base, "-C", str(mirror), "fetch", "--quiet", "--prune", "--", url,
                   "+refs/*:refs/*"]
    else:
        mirror.parent.mkdir(parents=True, exist_ok=True)
        command = [*base, "clone", "--quiet", "--mirror", "--", url, str(mirror)]
    try:
        result = subprocess.run(command, capture_output=True, env=env, cwd=outside,
                                timeout=NETWORK_TIMEOUT_SECONDS * 20)
    except subprocess.SubprocessError as error:
        raise GuardError("fetching the repository timed out") from error
    if result.returncode != 0:
        raise GuardError("fetching the repository failed")


def watch_url(name: str, install: dict) -> str:
    """Where to read a repository from. Tests may map names to local folders."""
    test_urls = install.get("watch_urls") if install.get("test_mode") else None
    if test_urls and name in test_urls:
        return str(test_urls[name])
    return f"https://github.com/{name}.git"


def mirror_refs(repo: Repository) -> dict[str, str]:
    """The refs a mirror holds after a fetch: what a scan of it can actually cover."""
    output = repo.run("for-each-ref", "--format=%(objectname) %(refname)").decode()
    refs = {}
    for line in output.splitlines():
        sha, _, ref = line.partition(" ")
        if ref:
            refs[ref] = sha
    return refs


def fetch_objects(git: str, url: str, mirror: Path, outside: Path, shas: list[str]) -> None:
    """Ask the remote for objects by identifier: ones it advertised that the mirror lacks.

    A ref can move between listing and fetching, so the fetch can miss what the listing showed.
    GitHub serves such objects by identifier for a while afterwards. This is best effort; the
    caller reports whatever is still missing (Astra review W1).
    """
    env = {**_outside_repository_env(), "GIT_TERMINAL_PROMPT": "0"}
    for sha in shas[:MAX_LISTED_FINDINGS]:
        command = [git, "-c", "core.hooksPath=/dev/null", "-C", str(mirror), "fetch", "--quiet",
                   "--no-write-fetch-head", "--", url, sha]
        try:
            subprocess.run(command, capture_output=True, env=env, cwd=outside,
                           timeout=NETWORK_TIMEOUT_SECONDS)
        except subprocess.SubprocessError:
            continue


def scan_new_content(
    home: Path, install: dict, name: str, entry: RepoPolicy, policy: Policy, deny: DenyList,
    gitleaks: str, record: dict, wanted: list[tuple[str, str]], full: bool, scratch: Path,
) -> tuple[list[dict], dict[str, str], list[tuple[str, str]]]:
    """Read what a public repository gained since its checkpoint.

    `record` is the repository's saved state, and `wanted` every ref and object pair the watcher
    has seen listed and not yet read: this run's listing and any left pending by earlier runs.
    With `full`, everything above the history left unread at first sight is read again, as when
    the rules have changed since the last check. Returns the findings, as records; the refs the
    scan covered (the new checkpoint); and the pairs whose objects couldn't be retrieved, which
    are never counted as read (Astra review W1).
    """
    git = install["git"]
    url = watch_url(name, install)
    # Each repository gets its own scratch folder, because the secret scan expects a fresh one.
    scratch = scratch / hashlib.sha256(name.encode()).hexdigest()[:16]
    scratch.mkdir()
    outside = scratch / "outside"
    outside.mkdir()
    mirror = home / "watch" / "mirrors" / f"{name.replace('/', '__')}.git"
    refresh_mirror(git, url, mirror, outside)
    repo = Repository(git, mirror)
    try:
        absent = sorted({sha for _, sha in wanted if repo.info(sha) is None})
    finally:
        repo.close()
    if absent:
        fetch_objects(git, url, mirror, outside, absent)
    repo = Repository(git, mirror)
    try:
        covered = mirror_refs(repo)
        still = sorted((ref, sha) for ref, sha in wanted if repo.info(sha) is None)
        unreadable = {sha for _, sha in still}
        checkpoint = record.get("refs", {})
        unread_below = record.get("unread_below", {})
        stream = scratch / "added.txt"
        scanner = Scanner(repo, Rules("block", entry, policy), deny, stream)
        tips: list[str] = []
        candidates = {*covered.items(), *((r, s) for r, s in wanted if s not in unreadable)}
        for ref, sha in sorted(candidates):
            if not full and checkpoint.get(ref) == sha:
                continue
            scanner.check_ref(ref, namespace_rule=False)
            tip = scanner.scan_tag_chain(sha)
            if tip:
                tips.append(tip)
        floor = set(unread_below.values()) if full else {*checkpoint.values(),
                                                         *unread_below.values()}
        known = [sha for sha in floor if repo.info(sha)]
        for sha in commits_to_scan(repo, tips, known):
            scanner.scan_commit(sha)
        scanner.run_gitleaks(gitleaks, write_scanner_config(scratch), scratch, stream)
    finally:
        repo.close()
    records = [finding_record(name, f, scanner.hidden_paths)
               for f in scanner.findings[:MAX_LISTED_FINDINGS]]
    if len(scanner.findings) > MAX_LISTED_FINDINGS:
        records.append({"repo": name.lower(), "rule": "more",
                        "count": len(scanner.findings) - MAX_LISTED_FINDINGS})
    return records, covered, still


def finding_record(name: str, finding: Finding, hidden: set[str]) -> dict:
    """A finding as the watcher stores it: what and where, never how it is shown.

    Display is decided when a report is written, under the lists then in force, so a name or
    path listed later is withheld from every later report (Astra review H3).
    """
    return {
        "repo": name.lower(), "rule": finding.rule, "commit": finding.place.commit,
        "path": finding.place.path, "label": finding.place.label, "line": finding.line,
        "hidden": finding.place.path in hidden,
    }


def finding_key(record: dict) -> str:
    """A finding's identity, which acknowledgement refers to."""
    return json.dumps(record, sort_keys=True)


def _names_listed(text: str, deny: DenyList) -> bool:
    return any(True for _ in deny.find(tokenise(text)))


def render_finding(record: dict, deny: DenyList | None) -> str:
    """One finding as a report line, withholding what the current lists say to withhold.

    Without a deny-list, nothing can be told safe: names and paths are all withheld.
    """
    if "legacy" in record:
        text = record["legacy"]
        if deny is None or _names_listed(text, deny):
            return "<an earlier finding, withheld>"
        return text
    repo = watch_display_name(record["repo"], deny)
    if record["rule"] == "more":
        return f"{repo}: and {record['count']} more"
    path = record["path"]
    if not record["label"] and (
        record.get("hidden") or deny is None or _names_listed(path, deny)
    ):
        path = "<path hidden>"
    commit = f"commit {record['commit'][:12]}  " if record["commit"] else ""
    line = f":{record['line']}" if record["line"] else ""
    return f"{repo}: {record['rule']}  {commit}{path}{line}"


_REPOSITORY_SHAPED = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


def safe_text(text: str, deny: DenyList | None) -> str:
    """An error message fit for the report: none that names a listed term (Astra review H3).

    Without a deny-list, anything shaped like a repository name is withheld.
    """
    if deny is None:
        return _REPOSITORY_SHAPED.sub(lambda match: withheld_name(match.group()), text)
    if _names_listed(text, deny):
        return "details withheld, because they name a listed term"
    return text


def open_secret_alerts(gh: str, name: str) -> int | None:
    """How many open secret-scanning alerts GitHub has for a repository (up to 100), or None if
    it won't say.

    Only the count is read; the alerts' secret values never leave the GitHub CLI.
    """
    try:
        count = _gh_json(gh, "api", f"repos/{name}/secret-scanning/alerts?state=open&per_page=100",
                         "--jq", "length")
    except GuardError:
        return None
    return count if isinstance(count, int) else None


def agent_routes_since(home: Path, offset: int) -> tuple[collections.Counter, int]:
    """Publishing routes the agent hook noted since a byte offset in its log."""
    path = home / "log" / "agent-hook.jsonl"
    counts: collections.Counter = collections.Counter()
    if not path.is_file():
        return counts, 0
    data = path.read_bytes()
    if offset > len(data):
        offset = 0  # the log was rotated or replaced
    for line in data[offset:].decode("utf-8", "replace").splitlines():
        try:
            counts[str(json.loads(line).get("route", "unknown"))] += 1
        except (ValueError, AttributeError):
            counts["unreadable"] += 1
    return counts, len(data)


def withheld_name(name: str) -> str:
    """A stable stand-in for a repository name that can't be shown."""
    return f"<repository withheld {hashlib.sha256(name.lower().encode()).hexdigest()[:10]}>"


def watch_display_name(name: str, deny: DenyList | None) -> str:
    """A repository or owner name as the watcher shows it.

    A name that itself holds a listed term is replaced by a stand-in, as file paths are, so the
    report and the service's log never spell the term out (Astra review W6). Without a deny-list
    nothing can be told safe, so every name is withheld.
    """
    if deny is not None and not any(True for _ in deny.find(tokenise(name))):
        return name
    return withheld_name(name)


def scan_generation(
    install: dict, entry: RepoPolicy, tiers: Iterable[str], deny: DenyList
) -> str:
    """A fingerprint of everything that decides what a scan of one repository finds.

    It covers the repository's policy entry, the required tiers, the deny-lists, and the secret
    scanner's checksum. A checkpoint holds only for the generation that made it: when any of these
    changes, what the watcher has read is read again under the new rules (Astra review W2). The
    lists are fingerprinted from the very bytes the matcher was built from, so a list rebuilt
    during a run labels nothing with rules the run didn't use, and the next run rereads under the
    new ones (Astra review H2). The engine's own code isn't covered; after updating it,
    `watch --rescan all` rereads everything.
    """
    digest = hashlib.sha256()
    digest.update(json.dumps(dataclasses.asdict(entry), sort_keys=True, default=sorted).encode())
    digest.update(json.dumps(sorted(tiers)).encode())
    digest.update(str(install.get("gitleaks_sha256") or install.get("gitleaks")).encode())
    digest.update(deny.digest.encode())
    return digest.hexdigest()[:32]


WATCH_STATE_VERSION = 2


def load_watch_state(path: Path) -> dict:
    """The watcher's saved state, upgraded from the first version if need be.

    Per repository it holds the refs last read (`refs`), the refs below which history was never
    read because the repository was first seen without `--full` (`unread_below`), the rules
    that read it (`generation`), the day of the last complete check (`checked`), and every ref
    and object pair seen listed but not yet read (`pending`). Findings are records, and
    acknowledgements their keys.
    """
    if not path.is_file():
        state: dict = {}
    else:
        try:
            state = json.loads(path.read_text())
        except (OSError, ValueError) as error:
            raise GuardError("the watcher's state file can't be read") from error
        if not isinstance(state, dict) or not isinstance(state.get("repos", {}), dict):
            raise GuardError("the watcher's state file isn't in the expected form")
    if state and state.get("version", 1) < WATCH_STATE_VERSION:
        # The first version kept only the refs last seen, not whether the history below them
        # was ever read, so that history counts as unread, and the rules that read it as unknown.
        for record in state.get("repos", {}).values():
            record.setdefault("unread_below", dict(record.get("refs", {})))
    state["version"] = WATCH_STATE_VERSION
    for key, empty in (("repos", {}), ("findings", []), ("acknowledged", []), ("listed", {})):
        state.setdefault(key, empty)
    _check_watch_state(state)
    for record in state["repos"].values():
        # Objects an earlier form of this version couldn't fetch are pending pairs now.
        missing = record.pop("missing", None)
        if missing:
            record["pending"] = sorted({*map(tuple, record.get("pending", [])),
                                        *((ref, sha) for sha, ref in missing.items())})
    # Findings stored as text by earlier code are kept, and shown only when safe.
    state["findings"] = [f if isinstance(f, dict) else {"legacy": str(f)}
                         for f in state["findings"]]
    return state


_FINDING_FIELDS = {"repo": str, "rule": str, "commit": str, "path": str, "label": bool}


def valid_finding(record: object) -> bool:
    """Whether a stored finding has the shape `render_finding` needs."""
    if isinstance(record, str):
        return True  # text from earlier code, kept as a legacy record
    if not isinstance(record, dict):
        return False
    if "legacy" in record:
        return isinstance(record["legacy"], str)
    if record.get("rule") == "more":
        return isinstance(record.get("repo"), str) and isinstance(record.get("count"), int)
    return all(isinstance(record.get(key), kind) for key, kind in _FINDING_FIELDS.items()) and (
        record.get("line") is None or isinstance(record.get("line"), int)
    )


def _check_watch_state(state: dict) -> None:
    """Refuse a state file whose parts aren't the shapes the watcher reads (Astra review R1)."""
    repos, findings = state["repos"], state["findings"]
    acknowledged, listed = state["acknowledged"], state["listed"]
    if not (isinstance(repos, dict) and all(isinstance(r, dict) for r in repos.values())
            and isinstance(findings, list) and all(valid_finding(f) for f in findings)
            and isinstance(acknowledged, list) and isinstance(listed, dict)
            and isinstance(state.get("attempted", {}), dict)):
        raise GuardError("the watcher's state file isn't in the expected form")
    for record in repos.values():
        for key in ("refs", "unread_below"):
            if not isinstance(record.get(key, {}), dict):
                raise GuardError("the watcher's state file isn't in the expected form")
        pending = record.get("pending", [])
        if not (isinstance(pending, list)
                and all(isinstance(p, list | tuple) and len(p) == 2 for p in pending)):
            raise GuardError("the watcher's state file isn't in the expected form")


def save_watch_state(path: Path, state: dict) -> None:
    """Replace the state in one step, so an interrupted run leaves the previous state whole."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=1, sort_keys=True))
    os.replace(temporary, path)


def _watch_timed_out(_signum: int, _frame: object) -> None:
    raise GuardError("reading it ran out of time")


@contextlib.contextmanager
def time_limit(seconds: int) -> Iterator[None]:
    """Bound one repository's check, so one slow repository can't stall the rest."""
    previous = signal.signal(signal.SIGALRM, _watch_timed_out)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


@dataclasses.dataclass
class WatchRun:
    """What one run of the watcher has to say, by how much it matters."""

    incomplete: list[str] = dataclasses.field(default_factory=list)
    attention: list[str] = dataclasses.field(default_factory=list)
    notes: list[str] = dataclasses.field(default_factory=list)
    # Whether some history is unread or some findings acknowledged, which "clean" mustn't hide.
    caveat: bool = False

    @property
    def status(self) -> int:
        if self.incomplete:
            return EXIT_WATCH_INCOMPLETE
        return 1 if self.attention else 0


def command_watch(home: Path, args: argparse.Namespace) -> int:
    """Check what has already reached GitHub, after the fact.

    The pre-push check stops accidents on this machine. The watcher looks afterwards at what
    other routes put in the watched repositories: other machines, agent lanes with hooks off,
    collaborators, web edits, and API writes (Shawn, 8 November 2026). It reads Git content
    only; the README's coverage table says what that leaves out. Each run:

    - compares every listed repository's visibility with its label, and lists public
      repositories of the watched owners that have no policy entry;
    - reads the new commits, refs, and tags of each watched public repository with the same
      scanner and rules as a public push, and reads again what it has read before if those rules
      have changed since;
    - counts GitHub's open secret-scanning alerts for those repositories;
    - counts the publishing routes the agent hook noted.

    A repository seen for the first time is recorded, not read, unless `--full`; its earlier
    history stays listed as unread until `--rescan` reads it. Findings stay in the report until a
    person clears them with `--clear`. The report gives locations and counts, never values, and
    says plainly when a check couldn't run: it then exits with EXIT_WATCH_INCOMPLETE, and still
    writes its report (Astra review W4). One run at a time holds a lock.
    """
    report = Path(args.report).expanduser() if args.report else None
    lock_path = home / "watch" / "lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("publish-guard: another watch is running, so this one checked nothing",
                  file=sys.stderr)
            return EXIT_WATCH_INCOMPLETE
        if args.clear:
            return watch_clear(home, args.clear)
        # Until this run finishes, the report says so; a run stopped from outside, which can't
        # clean up, leaves it saying so (Astra review H4). This first marker needs no list or
        # saved state, so damaged ones can't keep it from being written (Astra review R1).
        started = WatchRun(incomplete=[f"a run started on {time.strftime('%Y-%m-%d')} hasn't "
                                       "finished; if this stays, it was stopped (a time limit, "
                                       "a shutdown, or a fault) before it could report"])
        if report is not None:
            write_watch_report(report, render_watch_report(started))
        try:
            if report is not None:
                started.attention, problem = recorded_findings(home)
                started.incomplete += problem
                write_watch_report(report, render_watch_report(started))
            return _watch(home, args, report)
        except GuardError as error:
            return _watch_failed(home, report, str(error))
        except Exception as error:  # noqa: BLE001 - a fault in the watcher must reach its report
            return _watch_failed(home, report, f"internal error ({type(error).__name__})")


def watch_clear(home: Path, which: str) -> int:
    """Acknowledge recorded findings, and objects that couldn't be fetched, for one repository
    or all.

    Acknowledged findings leave the report and aren't raised again when the same content is read
    again; they don't make that content clean. This is for a person: an agent's hook refuses it
    (Astra review W5).
    """
    _require_terminal("clearing the watcher's findings", home, reads_input=False)
    state_path = home / "watch" / "state.json"
    state = load_watch_state(state_path)
    if which == "all":
        names = set(state["repos"])
        cleared = list(state["findings"])
    else:
        names = {which.lower()} & set(state["repos"])
        prefixes = (which.lower() + ":", withheld_name(which) + ":")
        cleared = [f for f in state["findings"]
                   if f.get("repo") == which.lower() or f.get("legacy", "").startswith(prefixes)]
    state["findings"] = [f for f in state["findings"] if f not in cleared]
    state["acknowledged"] = sorted(set(state["acknowledged"]) | {finding_key(f) for f in cleared})
    objects = sum(len({sha for _, sha in state["repos"][name].pop("pending", [])})
                  for name in names)
    save_watch_state(state_path, state)
    extra = f" and {objects} object(s) that couldn't be fetched" if objects else ""
    print(f"cleared {len(cleared)} finding(s){extra}")
    return 0


def recorded_findings(home: Path) -> tuple[list[str], list[str]]:
    """The findings already recorded, rendered under whatever lists can be loaded now, and any
    problem reading them. This needs no policy, so it works when a run can't."""
    try:
        deny: DenyList | None = DenyList.load(home, ())
    except Exception:  # noqa: BLE001 - best effort: without a list, everything is withheld
        deny = None
    try:
        state = load_watch_state(home / "watch" / "state.json")
        return [f"finding: {render_finding(f, deny)}" for f in state["findings"]], []
    except Exception:  # noqa: BLE001 - best effort, never a reason to skip the report
        return [], ["the watcher's state can't be read, so earlier findings aren't shown"]


def _watch_failed(home: Path, report: Path | None, reason: str) -> int:
    """Report a run that couldn't check anything, with the findings already recorded."""
    try:
        deny: DenyList | None = DenyList.load(home, ())
    except Exception:  # noqa: BLE001 - best effort: without a list, everything is withheld
        deny = None
    try:
        run = WatchRun(incomplete=[f"the watcher couldn't run: {safe_text(reason, deny)}"])
        run.attention, problem = recorded_findings(home)
        run.incomplete += problem
    except Exception:  # noqa: BLE001 - fixed wording, from nothing that can be broken
        run = WatchRun(incomplete=["the watcher couldn't run, and its reason can't be shown"])
    try:
        finish_watch(home, report, run)
    except Exception:  # noqa: BLE001 - the status below is the signal that must survive
        _watch_last_resort()
    return EXIT_WATCH_INCOMPLETE


def _watch_last_resort() -> None:
    """Say, in fixed words, that a run failed without a report. Needs nothing that can break:
    no report, log, list, or state (Astra review R3)."""
    try:
        print("publish-guard: the watcher failed and couldn't write its report; treat this "
              "run as incomplete", file=sys.stderr)
    except Exception:  # noqa: BLE001 - nothing more can be done; the exit status remains
        pass


def finish_watch(home: Path, report: Path | None, run: WatchRun) -> None:
    """Log, print, and write the report."""
    write_log(home, {"watch": True, "status": run.status, "incomplete": len(run.incomplete),
                     "attention": len(run.attention), "notes": len(run.notes)})
    body = render_watch_report(run)
    print(body)
    if report is not None:
        write_watch_report(report, body)


def _watch(home: Path, args: argparse.Namespace, report: Path | None) -> int:
    """One run of the watcher, once it holds the lock. Prerequisites raise GuardError."""
    install = read_install(home)
    gitleaks = verified_gitleaks(install)
    policy = load_policy(home)
    tiers = required_tiers(home, policy)
    deny = DenyList.load(home, tiers)
    # The same freshness rule as a public push: a list edited but not rebuilt would read new
    # content under old rules and then never read it again (Astra review W2).
    stale = stale_sources(home)
    if stale:
        raise GuardError(f"deny-list: {', '.join(stale)} edited but not rebuilt; run deny-rebuild")
    gh = install.get("gh")
    if not gh:
        raise GuardError("the GitHub CLI isn't installed, so the watcher can't ask GitHub")
    state_path = home / "watch" / "state.json"
    state = load_watch_state(state_path)
    repos_state: dict = state["repos"]
    findings: list[dict] = state["findings"]
    known_findings = {finding_key(f) for f in findings} | set(state["acknowledged"])
    today = time.strftime("%Y-%m-%d")
    rescan = {name.lower() for name in args.rescan or ()}
    if "all" in rescan:
        rescan = set(policy.repos)
    run = WatchRun()

    def show(name: str) -> str:
        return watch_display_name(name, deny)

    owners = sorted({name.split("/", 1)[0] for name in policy.repos} | set(policy.watch_owners))
    listed: dict[str, tuple[str, bool]] = {}
    unlisted: set[str] = set()
    for owner in owners:
        try:
            listed.update(owner_listing(gh, owner))
            state["listed"][owner] = today
        except GuardError as error:
            unlisted.add(owner)
            run.incomplete.append(f"couldn't list {show(owner)}'s repositories "
                                  f"({safe_text(str(error), deny)}); last listed "
                                  f"{state['listed'].get(owner, 'never')}")
    visible = {name: visibility for name, (visibility, _) in listed.items()}
    for name, entry in sorted(policy.repos.items()):
        visibility = visible.get(name)
        if visibility is None:
            if name.split("/", 1)[0] not in unlisted:
                run.notes.append(f"{show(name)} is in the policy but not on GitHub "
                                 "(renamed or deleted?)")
        elif visibility == "public" and entry.label == "never-public":
            run.attention.append(f"ALERT {show(name)} is labelled never-public but is public")
        elif visibility == "public" and entry.label == "may-go-public":
            run.attention.append(f"{show(name)} has become public while labelled may-go-public")
    archived_unlisted = []
    for name, (visibility, archived) in sorted(listed.items()):
        owner = name.split("/", 1)[0]
        if visibility == "public" and owner in policy.watch_owners and name not in policy.repos:
            if archived:
                archived_unlisted.append(show(name))
            else:
                run.attention.append(f"{show(name)} is public and has no policy entry")
    if archived_unlisted:
        # Archived repositories can't change until unarchived, so they wait for the one-time
        # audit of what is already public rather than needing attention now.
        run.notes.append(f"{len(archived_unlisted)} archived public repository(ies) have no "
                         "policy entry: " + ", ".join(archived_unlisted))

    baselined = 0
    watched: list[str] = []
    limit = int(install.get("scan_timeout") or SCAN_TIMEOUT_SECONDS)
    with tempfile.TemporaryDirectory(prefix="publish-guard-watch-") as scratch_name:
        scratch = Path(scratch_name)
        outside = scratch / "outside"
        outside.mkdir()
        # Least recently attempted first, with each attempt saved before it starts, so a run
        # cut short, or failing on the same repositories, doesn't keep starving the rest
        # (Astra review R2). Last success is kept apart, as `checked`, for the report.
        attempted: dict = state.setdefault("attempted", {})
        order = sorted(policy.repos.items(),
                       key=lambda item: (attempted.get(item[0], 0), item[0]))
        for name, entry in order:
            if visible.get(name) != "public" or not is_watched(name, entry, policy):
                continue
            watched.append(name)
            attempted[name] = time.time()
            save_watch_state(state_path, state)
            shown = show(name)
            alerts = open_secret_alerts(gh, name)
            if alerts is None:
                run.incomplete.append(f"{shown}: GitHub's secret-scanning alerts couldn't be read")
            elif alerts:
                link = f" (https://github.com/{name}/security/secret-scanning)" if (
                    shown == name) else ""
                run.attention.append(f"{shown}: {alerts} open secret-scanning alert(s){link}")
            record = repos_state.get(name)
            generation = scan_generation(install, entry, tiers, deny)
            last = (record or {}).get("checked", "never")
            try:
                with time_limit(limit):
                    observed = remote_refs(install["git"], watch_url(name, install), outside)
                    if record is None and not args.full and name not in rescan:
                        repos_state[name] = {"refs": observed, "unread_below": observed,
                                             "generation": generation, "checked": today}
                        baselined += 1
                        save_watch_state(state_path, state)
                        continue
                    record = dict(record or {"refs": {}, "unread_below": {}})
                    pending = {tuple(pair) for pair in record.get("pending", [])}
                    checkpoint = record.get("refs", {})
                    seen = {(ref, sha) for ref, sha in observed.items()
                            if checkpoint.get(ref) != sha}
                    full = name in rescan or record.get("generation") != generation
                    if not seen and not full and not pending:
                        record["checked"] = today
                        repos_state[name] = record
                        continue
                    # What this listing showed is saved as pending before anything that can
                    # fail, so a failed fetch or read can't forget it (Astra review H1).
                    wanted = sorted(pending | seen)
                    repos_state[name] = {**record, "pending": [list(p) for p in wanted]}
                    save_watch_state(state_path, state)
                    if name in rescan:
                        record["unread_below"] = {}
                    found, covered, still = scan_new_content(
                        home, install, name, entry, policy, deny, gitleaks, record, wanted,
                        full, scratch,
                    )
            except GuardError as error:
                run.incomplete.append(f"couldn't read {shown} ({safe_text(str(error), deny)}); "
                                      f"last complete check {last}")
                continue
            for item in found:
                if finding_key(item) not in known_findings:
                    known_findings.add(finding_key(item))
                    findings.append(item)
            record.update(refs=covered, generation=generation)
            record.pop("pending", None)
            if still:
                record["pending"] = [list(p) for p in still]
                run.incomplete.append(
                    f"{shown}: {len({sha for _, sha in still})} object(s) GitHub listed couldn't "
                    "be fetched, so weren't read (a ref moved during the check, or the object is "
                    f"gone); last complete check {last}"
                )
            else:
                record["checked"] = today
            repos_state[name] = record
            save_watch_state(state_path, state)
    routes, offset = agent_routes_since(home, int(state.get("hook_log_offset", 0)))
    state["hook_log_offset"] = offset
    save_watch_state(state_path, state)

    if baselined:
        run.notes.append(f"{baselined} repository(ies) seen for the first time and recorded")
    unread = [show(n) for n in watched if repos_state.get(n, {}).get("unread_below")]
    run.caveat = bool(unread or state["acknowledged"])
    if unread:
        run.notes.append(
            f"initial audit pending: the watcher hasn't read the history of {len(unread)} "
            f"repository(ies) from before it first saw them ({', '.join(unread)}); "
            "`watch --rescan NAME` reads it"
        )
    if routes:
        run.notes.append("agent publishing routes since the last run: " + ", ".join(
            f"{route} {count}" for route, count in sorted(routes.items())))
    if state["acknowledged"]:
        run.notes.append(f"{len(state['acknowledged'])} finding(s) acknowledged with `--clear` "
                         "aren't listed")
    run.attention += [f"finding: {render_finding(f, deny)}" for f in findings]
    finish_watch(home, report, run)
    return run.status


def render_watch_report(run: WatchRun) -> str:
    """The watcher's report, in Markdown, dated by day so it changes at most daily when quiet."""
    clean = "clean: every check ran, and nothing needs attention."
    if run.caveat:
        clean += " Some history isn't read yet, or some findings were acknowledged (see Notes)."
    status = {
        0: clean,
        1: "something needs attention.",
        EXIT_WATCH_INCOMPLETE: "INCOMPLETE: some checks couldn't run (see below).",
    }[run.status]
    lines = ["# Publication watch", "",
             f"Checked on {time.strftime('%Y-%m-%d')} by the publish guard's watcher. Locations "
             "and counts only, never values.", "", f"Status: {status}", ""]
    if run.incomplete:
        lines += ["## Couldn't check", ""] + [f"- {item}" for item in run.incomplete] + [""]
    lines += ["## Needs attention", ""]
    if run.attention:
        lines += [f"- {item}" for item in run.attention]
    elif run.incomplete:
        lines += ["Nothing needs attention in what could be checked."]
    else:
        lines += ["Nothing needs attention."]
    if run.notes:
        lines += ["", "## Notes", ""] + [f"- {note}" for note in run.notes]
    return "\n".join(lines) + "\n"


def write_watch_report(path: Path, body: str) -> None:
    """Write the report only when it has changed, so a quiet watcher makes one change a day."""
    if path.is_file() and path.read_text() == body:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(body)
    os.replace(temporary, path)


# ------------------------------------------------------------------ command line


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check what a git push would expose.")
    parser.add_argument("--home", default=str(Path.home() / ".config" / "publish-guard"))
    commands = parser.add_subparsers(dest="command", required=True)

    hook = commands.add_parser("hook-pre-push", help="run as git's pre-push hook")
    hook.add_argument("remote")
    hook.add_argument("url")

    install = commands.add_parser("install", help="install the engine and hook stubs")
    install.add_argument("--gitleaks", help="path to the gitleaks binary")
    install.add_argument("--gitleaks-sha256", help="checksum `doctor` verifies gitleaks against")
    install.add_argument("--visibility-map", help="for tests only: stand-in for asking GitHub")
    install.add_argument("--no-hand-over", action="store_true",
                         help="never run a repository's own pre-push hook")
    install.add_argument("--activate-global", action="store_true",
                         help="also set the global core.hooksPath")
    install.add_argument("--test-mode", action="store_true",
                         help="for tests only: allow a visibility map and skip terminal checks")
    install.add_argument("--scan-timeout", type=int, help="for tests only: the scan's time limit")
    install.set_defaults(handler=command_install)

    add = commands.add_parser("deny-add", help="add terms to a tier, from a file or standard input")
    add.add_argument("--tier", required=True)
    add.add_argument("--from-file")
    add.set_defaults(handler=command_deny_add)

    rebuild = commands.add_parser("deny-rebuild", help="replace tiers from their source files")
    rebuild.add_argument("--tier", help="just this tier")
    rebuild.add_argument("--stdin", action="store_true", help="read terms from standard input")
    rebuild.set_defaults(handler=command_deny_rebuild)

    check = commands.add_parser("deny-check", help="look up one term, at a terminal")
    check.set_defaults(handler=command_deny_check)

    remove = commands.add_parser("deny-remove", help="remove one term, at a terminal")
    remove.add_argument("--tier", required=True)
    remove.set_defaults(handler=command_deny_remove)

    stats = commands.add_parser("deny-stats", help="count the entries in each tier")
    stats.set_defaults(handler=command_deny_stats)

    override = commands.add_parser("override", help="exempt one exact push, at a terminal")
    override.add_argument("--repo", required=True)
    override.add_argument("--push", required=True,
                          help="the identifier of the blocked push, as it printed it")
    override.set_defaults(handler=command_override)

    audit = commands.add_parser("audit", help="apply the rules to existing history")
    audit.add_argument("--repo", required=True)
    audit.add_argument("--name", required=True)
    audit.add_argument("--as", dest="treat_as", choices=("public", "private"), default="public")
    audit.add_argument("--rev", action="append", required=True, help="an argument for git rev-list")
    audit.add_argument("--list", type=int, default=200, help="how many locations to print")
    audit.set_defaults(handler=command_audit)

    watch = commands.add_parser("watch", help="check what has already reached GitHub")
    watch.add_argument("--report", help="also write the report to this Markdown file")
    watch.add_argument("--full", action="store_true",
                       help="read the whole history of repositories seen for the first time")
    watch.add_argument("--rescan", action="append", metavar="NAME",
                       help="read this repository's whole history again (repeatable)")
    watch.add_argument("--clear", help="acknowledge recorded findings for one repository, or "
                       "'all', at a terminal")
    watch.set_defaults(handler=command_watch)

    doctor = commands.add_parser("doctor", help="check the guard is in force on this machine")
    doctor.add_argument("--scan", action="append", help="also check repositories under this folder")
    doctor.add_argument("--test", action="store_true", help="for tests: accept test mode")
    doctor.set_defaults(handler=command_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    # A path that isn't valid UTF-8 must not turn a useful report into a crash.
    sys.stderr.reconfigure(errors="backslashreplace")
    sys.stdout.reconfigure(errors="backslashreplace")
    args = build_parser().parse_args(argv)
    # A relative home would be written into the stubs as relative, and git runs hooks from the
    # repository, so it must be made absolute here (audit finding L7).
    home = Path(args.home).expanduser().resolve()
    if args.command == "hook-pre-push":
        # Everything here fails closed: an error of any kind refuses the push.
        try:
            return run_hook(home, args.remote, args.url)
        except (Blocked, GuardError) as error:
            print(f"{MARKER}: {error}", file=sys.stderr)
            return EXIT_BLOCKED
        except Exception as error:  # noqa: BLE001
            name = type(error).__name__
            print(f"{MARKER}: internal error ({name}), so refusing.", file=sys.stderr)
            return EXIT_INTERNAL
    if args.command == "watch":
        # Whatever goes wrong, the watcher ends with its own failure status, never 1, which the
        # service counts as success because it means findings (Astra review R3). Signals keep
        # their usual meaning, since only Exception is caught here.
        try:
            return args.handler(home, args)
        except GuardError as error:
            try:
                print(f"publish-guard: error: {error}", file=sys.stderr)
            except Exception:  # noqa: BLE001
                pass
            return EXIT_WATCH_INCOMPLETE
        except Exception:  # noqa: BLE001
            _watch_last_resort()
            return EXIT_WATCH_INCOMPLETE
    try:
        return args.handler(home, args)
    except GuardError as error:
        print(f"publish-guard: error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
