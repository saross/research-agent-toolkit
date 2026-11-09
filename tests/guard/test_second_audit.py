"""Regression tests for the second audit of 8 November 2026, of the fixes in abf6d74..3fc91e6.

Lens A (implementation) and Lens B (test adequacy) each ran in a fresh context. Finding labels
are theirs: "A-M1" is Lens A's first medium finding, "B-C1" Lens B's first critical one. Each test
asserts the safe behaviour, so it fails if the problem returns.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from conftest import (
    ENGINE,
    FAKE_SECRET,
    PERSON,
    PRIVATE_NAME,
    PUBLIC_NAME,
    assert_blocked,
    assert_passed,
)

KNOWN_SECRET = "opaquevalue" + "7f3a9c2e5b81d4"


def _audit(sandbox, *revs, cwd=None):
    args = ["audit", "--repo", str(cwd or sandbox.work), "--name", PUBLIC_NAME]
    args += [f"--rev={rev}" for rev in revs]
    return sandbox.engine(*args)


def _to_private(sandbox, label="may-go-public", **extra):
    sandbox.policy["repos"][PRIVATE_NAME] = {"label": label, **extra}
    sandbox.save_policy()
    sandbox.git("remote", "set-url", "origin", str(sandbox.private))


# ------------------------------------------------------------------ the audit command


def test_a_m1_audit_with_not_still_reads_the_new_commits(sandbox):
    base = sandbox.head()
    sandbox.commit("a.txt", f"{PERSON}\n")
    result = _audit(sandbox, "HEAD", "--not", base)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "1 commit(s)" in result.stdout


def test_a_m2_the_readme_audit_example_works(sandbox):
    sandbox.commit("a.txt", f"{PERSON}\n")
    result = _audit(sandbox, "--since=2000-01-01", "HEAD")
    assert "error" not in result.stderr, result.stderr
    assert result.returncode != 0
    assert "tier2a-people" in result.stdout


def test_a_m2_a_revision_naming_several_objects_works(sandbox):
    sandbox.commit("a.txt", f"{PERSON}\n")
    result = _audit(sandbox, "HEAD^!")
    assert "error" not in result.stderr, result.stderr
    assert "tier2a-people" in result.stdout


def test_a_l1_audit_of_all_refs_reads_a_detached_head(sandbox):
    sandbox.git("checkout", "-q", "--detach")
    sandbox.commit("a.txt", f"{PERSON}\n")
    result = _audit(sandbox, "--all")
    assert result.returncode != 0, result.stdout
    assert "tier2a-people" in result.stdout


def test_b_low_audit_of_a_named_tag_reports_the_rule(sandbox):
    sandbox.git("tag", "-a", "-m", f"thanks to {PERSON}", "v1")
    result = _audit(sandbox, "v1")
    assert "tier2a-people" in result.stdout, result.stdout + result.stderr
    assert PERSON not in result.stdout


# ------------------------------------------------------------------ cost of the context check


def test_a_m3_a_one_line_edit_to_a_large_file_reads_only_around_the_edit(sandbox):
    """The deny-list check reads a window around each change, not the whole file."""
    lines = [f"row {n}, an ordinary line of data\n" for n in range(20000)]
    sandbox.commit("big.csv", "".join(lines))
    first = sandbox.head()
    lines[10000] = "row 10000, an edited line\n"
    second = sandbox.commit("big.csv", "".join(lines))
    sys.path.insert(0, str(ENGINE.parent))
    try:
        import publish_guard as engine
    finally:
        sys.path.pop(0)
    git_dir = Path(sandbox.git("rev-parse", "--absolute-git-dir").stdout.strip())
    repo = engine.Repository("git", git_dir)
    deny = engine.DenyList.load(sandbox.guard, ())
    rules = engine.Rules("block", engine.RepoPolicy(), None)
    scanner = engine.Scanner(repo, rules, deny, sandbox.root / "stream.txt")
    try:
        scanner.scan_commit(second)
    finally:
        repo.close()
    assert first != second
    assert scanner.lines_tokenised < 50, scanner.lines_tokenised
    assert not scanner.findings


# ------------------------------------------------------------ the secrets tier when lists break


def test_a_m4_a_damaged_unrelated_tier_doesnt_switch_the_secrets_tier_off(sandbox):
    sandbox.deny_add("tier1-exploit", KNOWN_SECRET)
    (sandbox.guard / "deny" / "tier2b-teaching.hashes").write_text("not a tier file\n")
    _to_private(sandbox, "never-public")
    sha = sandbox.commit("config.txt", f"token = {KNOWN_SECRET}\n")
    result = sandbox.push()
    assert result.returncode != 0, result.stderr
    assert "publish-guard: BLOCKED" in result.stderr
    assert not sandbox.remote_has(sha, sandbox.private)


def test_a_m4_a_damaged_secrets_tier_refuses_a_private_push(sandbox):
    sandbox.deny_add("tier1-exploit", KNOWN_SECRET)
    (sandbox.guard / "deny" / "tier1-exploit.hashes").write_text("not a tier file\n")
    _to_private(sandbox, "never-public")
    sha = sandbox.commit("notes.txt", "ordinary\n")
    result = sandbox.push()
    assert result.returncode != 0
    assert "publish-guard: BLOCKED" in result.stderr
    assert not sandbox.remote_has(sha, sandbox.private)


def test_b_m4_the_secrets_tier_reads_binary_files_on_any_remote(sandbox):
    sandbox.deny_add("tier1-exploit", KNOWN_SECRET)
    _to_private(sandbox, "never-public")
    target = sandbox.work / "blob.bin"
    target.write_bytes(b"\x00\x01\x02 " + KNOWN_SECRET.encode() + b" \x00")
    sandbox.git("add", "blob.bin")
    sandbox.git("commit", "-q", "-m", "binary")
    result = sandbox.push()
    assert result.returncode != 0
    assert "tier1-exploit" in result.stderr
    assert not sandbox.remote_has(sandbox.head(), sandbox.private)


# ------------------------------------------------------------------ an unreadable policy


def test_a_m5_an_unreadable_policy_warns_instead_of_going_quiet(sandbox):
    sandbox.git("remote", "set-url", "origin", str(sandbox.private))
    (sandbox.guard / "policy.toml").write_text("this is [not toml")
    sandbox.commit("a.txt", f"{PERSON}\n")
    result = sandbox.push()
    assert result.returncode == 0, result.stderr
    assert "public rules ran as warnings" in result.stderr
    assert "public-rule hit" in result.stderr


# ------------------------------------------------------------------ withholding paths


def test_a_m6_a_file_name_starting_with_an_angle_bracket_is_withheld(sandbox):
    _to_private(sandbox, "never-public")
    name = f"<{PERSON}> notes.md"
    sha = sandbox.commit(name, f"{FAKE_SECRET}\n")
    result = sandbox.push()
    assert result.returncode != 0
    assert "<path hidden>" in result.stderr
    assert PERSON not in result.stderr
    assert not sandbox.remote_has(sha, sandbox.private)


def test_b_m7_the_log_withholds_binary_paths_when_the_list_cant_load(sandbox):
    _to_private(sandbox, binary_allow=["assets/*"])
    (sandbox.guard / "deny" / "tier2b-teaching.hashes").write_text("not a tier file\n")
    target = sandbox.work / "assets" / f"{PERSON.replace(' ', '-')}.png"
    target.parent.mkdir()
    target.write_bytes(b"\x89PNG\x00\x01")
    sandbox.git("add", "assets")
    sandbox.git("commit", "-q", "-m", "figure")
    sandbox.push()
    log = (sandbox.guard / "log" / "guard.jsonl").read_text()
    record = json.loads(log.splitlines()[-1])
    assert record["binary_allowed"] == ["<path hidden>"], record
    assert PERSON.replace(" ", "-") not in log


# ------------------------------------------------------------------ LFS pointers


def test_b_c1_a_valid_pointer_followed_by_text_is_read_as_text(sandbox):
    sandbox.policy["repos"][PUBLIC_NAME]["binary_allow"] = ["assets/*"]
    sandbox.save_policy()
    sandbox.seed_public()
    pointer = "version https://git-lfs.github.com/spec/v1\noid sha256:" + "a" * 64 + "\nsize 9\n"
    sha = sandbox.commit("assets/data.bin", pointer + f"{PERSON}\n")
    result = sandbox.push()
    assert_blocked(result, sandbox, sha)
    assert "tier2a-people" in result.stderr


# ------------------------------------------------------------------ list commands


def test_a_l7_rebuilding_from_standard_input_refuses_a_tier_with_a_source_file(sandbox):
    sources = sandbox.guard / "deny-sources"
    sources.mkdir()
    (sources / "tier4-commercial.txt").write_text("acme widgets\n")
    assert sandbox.engine("deny-rebuild").returncode == 0
    result = sandbox.engine(
        "deny-rebuild", "--tier", "tier4-commercial", "--stdin", stdin="other terms\n"
    )
    assert result.returncode != 0
    assert "source file" in result.stderr


def test_ordinary_push_still_passes(sandbox):
    """The negative for this file: none of the above fires on clean work."""
    sandbox.deny_add("tier1-exploit", KNOWN_SECRET)
    sandbox.seed_public()
    sha = sandbox.commit("a.txt", "ordinary text\n")
    assert_passed(sandbox.push(), sandbox, sha)
