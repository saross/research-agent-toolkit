"""Regression tests for the code audit of 7–8 November 2026 (Lens A, implementation).

Each test started as the auditor's reproduction of a bug, asserting the faulty behaviour. Here each
asserts the safe behaviour instead, so it fails if the bug returns. Finding numbers refer to the
audit report.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import string
import subprocess
from pathlib import Path

import pytest
from conftest import (
    PERSON,
    PRIVATE_IP,
    PRIVATE_NAME,
    PUBLIC_NAME,
    assert_blocked,
    assert_passed,
    blocked_push_id,
)

REAL = Path(os.environ.get("PUBLISH_GUARD_TEST_GITLEAKS",
                           Path.home() / ".config/publish-guard/bin/gitleaks"))
needs_real = pytest.mark.skipif(not REAL.exists(), reason="the real gitleaks isn't installed")


def _token() -> str:
    alphabet = string.ascii_letters + string.digits
    return "ghp" + "_" + "".join(secrets.choice(alphabet) for _ in range(36))


@pytest.fixture
def real(sandbox):
    sandbox.gitleaks.unlink()
    shutil.copy(REAL, sandbox.gitleaks)
    return sandbox


def _never_public(sandbox):
    sandbox.policy["repos"][PRIVATE_NAME] = {"label": "never-public"}
    sandbox.save_policy()
    sandbox.git("remote", "set-url", "origin", str(sandbox.private))


# ------------------------------------------------------------------ C1: file signatures


@needs_real
@pytest.mark.parametrize("magic,offset", [("ustar", 257), ("DICM", 128)])
def test_c1_file_signature_in_a_commit_message_does_not_switch_the_scanner_off(
    real, magic, offset
):
    """Places a file-type signature at the byte offset gitleaks checks, counting the text that
    comes before the commit message in the scanned stream (the ref name and two identities)."""
    _never_public(real)
    before = "refs/heads/main\n" + "Test Person <test@example.invalid>\n" * 2
    subject = "x" * (offset - len(before)) + magic + " notes"
    real.work.joinpath("a.txt").write_text(f'token = "{_token()}"\n')
    real.git("add", "a.txt")
    real.git("commit", "-q", "-m", subject)
    sha = real.head()
    result = real.push()
    assert result.returncode != 0
    assert not real.remote_has(sha, real.private)


@needs_real
def test_c1_audit_still_finds_secrets_when_the_author_starts_like_a_binary(real):
    env = dict(real.env, GIT_AUTHOR_NAME="MZ Person")
    real.commit("a.txt", f'token = "{_token()}"\n', "add config", env=env)
    result = real.engine("audit", "--repo", str(real.work), "--name", "x/y", "--as", "private",
                         "--rev", "HEAD")
    assert "secret:github-pat" in result.stdout, result.stdout


# ------------------------------------------------------------------ C2: URL rewriting


def test_c2_local_url_rewrite_cannot_point_the_range_check_elsewhere(sandbox):
    sandbox.seed_public()
    sha = sandbox.commit("diary.txt", f"{PERSON}\n")
    assert sandbox.push(str(sandbox.private), "HEAD:refs/heads/main").returncode == 0
    sandbox.git("remote", "set-url", "origin", "placeholder:origin")
    sandbox.git("config", f"url.{sandbox.public}.pushInsteadOf", "placeholder:origin")
    sandbox.git("config", f"url.{sandbox.private}.insteadOf", str(sandbox.public))
    assert_blocked(sandbox.push(), sandbox, sha)


def test_c2_global_url_rewrite_of_the_destination_refuses(sandbox):
    """pushInsteadOf sends the push to the public repository; insteadOf would send the guard's
    question to the private one. The guard must notice the mismatch and refuse."""
    sandbox.seed_public()
    sha = sandbox.commit("diary.txt", f"{PERSON}\n")
    assert sandbox.push(str(sandbox.private), "HEAD:refs/heads/main").returncode == 0
    sandbox.git("remote", "set-url", "origin", "placeholder:origin")
    sandbox.git_global(f"url.{sandbox.public}.pushInsteadOf", "placeholder:origin")
    sandbox.git_global(f"url.{sandbox.private}.insteadOf", str(sandbox.public))
    result = sandbox.push()
    assert_blocked(result, sandbox, sha)
    assert "rewrite" in result.stderr


def test_c2_url_rewrite_passed_on_the_command_line_is_ignored(sandbox):
    sandbox.seed_public()
    sha = sandbox.commit("diary.txt", f"{PERSON}\n")
    assert sandbox.push(str(sandbox.private), "HEAD:refs/heads/main").returncode == 0
    result = sandbox.git(
        "-c", f"url.{sandbox.public}.pushInsteadOf=placeholder:origin",
        "-c", f"url.{sandbox.private}.insteadOf={sandbox.public}",
        "push", "placeholder:origin", "HEAD:refs/heads/main", check=False,
    )
    assert result.returncode != 0
    assert "publish-guard: BLOCKED" in result.stderr
    assert not sandbox.remote_has(sha)


# ------------------------------------------------------------------ M1: overlapping tiers


def test_m1_skipping_one_tier_does_not_excuse_a_term_another_tier_lists(sandbox):
    sandbox.deny_add("tier3-private", PERSON)
    sandbox.policy["repos"][PUBLIC_NAME]["skip_tiers"] = ["tier3-private"]
    sandbox.save_policy()
    sandbox.seed_public()
    sha = sandbox.commit("a.txt", f"{PERSON}\n")
    result = sandbox.push()
    assert_blocked(result, sandbox, sha)
    assert "tier2a-people" in result.stderr


# ------------------------------------------------------------------ M2, M3: values in paths


def test_m2_private_address_in_a_path_is_not_printed(sandbox):
    sandbox.seed_public()
    sha = sandbox.commit(f"hosts/{PRIVATE_IP}.md", "plain\n")
    result = sandbox.push()
    assert_blocked(result, sandbox, sha)
    assert "<path hidden>" in result.stderr


@needs_real
def test_m2_token_in_a_path_is_not_printed(real):
    real.policy["repos"][PUBLIC_NAME]["allowed_paths"] = ["README.md"]
    real.save_policy()
    real.seed_public()
    token = _token()
    sha = real.commit(f"{token}.txt", "plain\n")
    result = real.push()
    assert_blocked(result, real, sha)
    assert token not in result.stderr


def test_m3_log_does_not_hold_a_listed_path(sandbox):
    sandbox.policy["repos"][PUBLIC_NAME]["binary_allow"] = ["**"]
    sandbox.save_policy()
    sandbox.seed_public()
    path = sandbox.work / f"{PERSON.replace(' ', '-')}.bin"
    path.write_bytes(b"\x00\x01binary")
    sandbox.git("add", path.name)
    sandbox.git("commit", "-q", "-m", "add binary")
    sandbox.push()
    log = (sandbox.guard / "log" / "guard.jsonl").read_text()
    assert PERSON.replace(" ", "-") not in log


# ------------------------------------------------------------------ M4: binary-looking text


@needs_real
@pytest.mark.parametrize("prefix", ["version https://git-lfs.github.com/spec/v1\n", "\x00\n"],
                         ids=["lfs-header", "nul-byte"])
def test_m4_text_that_looks_binary_still_reaches_the_secret_scan(real, prefix):
    _never_public(real)
    sha = real.commit("notes.txt", prefix + f'token = "{_token()}"\n')
    result = real.push()
    assert result.returncode != 0
    assert not real.remote_has(sha, real.private)


# ------------------------------------------------------------------ M5: time limits


def test_m5_slow_repository_hook_after_the_check_is_not_cut_off(sandbox):
    sandbox.install("--scan-timeout", "2")
    marker = sandbox.root / "finished"
    hook = sandbox.work / ".git" / "hooks" / "pre-push"
    hook.write_text(f"#!/bin/sh\ncat >/dev/null\nsleep 4\ntouch {marker}\nexit 0\n")
    hook.chmod(0o755)
    sha = sandbox.head()
    assert_passed(sandbox.push(), sandbox, sha)
    assert marker.exists()


def test_m5_a_check_that_runs_out_of_time_prints_the_marker(sandbox):
    sandbox.install("--scan-timeout", "2")
    sandbox.gitleaks.write_text("#!/bin/sh\nsleep 6\nexit 0\n")
    result = sandbox.push()
    assert_blocked(result, sandbox, sandbox.head())
    assert "ran out of time" in result.stderr


# ------------------------------------------------------------------ M6: terminal gates


def test_m6_deny_add_does_not_reveal_whether_a_term_was_listed(sandbox):
    listed = sandbox.engine("deny-add", "--tier", "tier2a-people", stdin=f"{PERSON}\n").stdout
    unlisted = sandbox.engine("deny-add", "--tier", "tier2a-people", stdin="gamma delta\n").stdout
    assert listed.replace("tier2a-people", "") == unlisted.replace("tier2a-people", "")


@pytest.mark.parametrize(
    "details",
    [{}, {"reason": ""}, {"reason": "   "}, {"repo": "other/repository"}, {"push": "0" * 32}],
)
def test_m6_a_malformed_override_file_does_not_exempt_a_push(sandbox, details):
    """The file sits exactly where the engine looks, so only its content is under test."""
    import hashlib
    import time

    sandbox.seed_public()
    sha = sandbox.commit("a.txt", f"{PERSON}\n")
    push_id = blocked_push_id(sandbox)
    name = hashlib.sha256("\n".join([PUBLIC_NAME, push_id]).encode()).hexdigest()
    path = sandbox.guard / "overrides" / f"{name}.json"
    assert path.parent.is_dir()
    good = {"repo": PUBLIC_NAME, "push": push_id, "reason": "checked", "created": time.time()}
    if details:
        good.update(details)
        good.setdefault("generation", "will be wrong")
    path.write_text(json.dumps(good if details else {}))
    assert_blocked(sandbox.push(), sandbox, sha)


# ------------------------------------------------------------------ L1, L2, L3


def test_l1_escaping_symlink_made_in_a_merge_blocks(sandbox):
    sandbox.policy["repos"][PUBLIC_NAME]["binary_allow"] = ["**"]
    sandbox.save_policy()
    sandbox.commit("link", "base\n")
    sandbox.seed_public()
    sandbox.git("checkout", "-q", "-b", "side")
    sandbox.commit("link", "side\n")
    sandbox.git("checkout", "-q", "main")
    sandbox.commit("link", "main\n")
    sandbox.git("merge", "-q", "side", check=False)
    (sandbox.work / "link").unlink()
    os.symlink("../../../etc/passwd", sandbox.work / "link")
    sandbox.git("add", "link")
    sandbox.git("commit", "-q", "-m", "merge")
    assert_blocked(sandbox.push(), sandbox, sandbox.head())


def test_l2_listed_term_in_a_tag_name_header_blocks(sandbox):
    sandbox.seed_public()
    raw = (
        f"object {sandbox.head()}\ntype commit\ntag {PERSON.replace(' ', '-')}\n"
        "tagger Test Person <test@example.invalid> 0 +0000\n\nrelease\n"
    )
    tag = subprocess.run(
        ["git", "mktag"], input=raw, text=True, capture_output=True, cwd=sandbox.work,
        env=sandbox.env, check=True,
    ).stdout.strip()
    assert_blocked(sandbox.push("origin", f"{tag}:refs/tags/v1"), sandbox)


def test_l2_listed_term_in_an_extra_commit_header_blocks(sandbox):
    sandbox.seed_public()
    tree = sandbox.git("rev-parse", "HEAD^{tree}").stdout.strip()
    raw = (
        f"tree {tree}\nparent {sandbox.head()}\n"
        "author Test Person <test@example.invalid> 0 +0000\n"
        "committer Test Person <test@example.invalid> 0 +0000\n"
        f"x-note {PERSON}\n\nan ordinary message\n"
    )
    sha = subprocess.run(
        ["git", "hash-object", "-t", "commit", "-w", "--stdin"], input=raw, text=True,
        capture_output=True, cwd=sandbox.work, env=sandbox.env, check=True,
    ).stdout.strip()
    assert_blocked(sandbox.push("origin", f"{sha}:refs/heads/main"), sandbox, sha)


def test_l2_merging_an_annotated_tag_scans_its_message(sandbox):
    sandbox.seed_public()
    sandbox.git("checkout", "-q", "-b", "side")
    sandbox.commit("side.txt", "side work\n")
    sandbox.git("tag", "-a", "-m", f"thanks to {PERSON}", "v-side")
    sandbox.git("checkout", "-q", "main")
    sandbox.commit("main.txt", "main work\n")
    sandbox.git("merge", "-q", "--no-edit", "v-side")
    assert_blocked(sandbox.push(), sandbox, sandbox.head())


def test_l2_signatures_are_not_scanned_as_text(sandbox):
    sandbox.seed_public()
    tree = sandbox.git("rev-parse", "HEAD^{tree}").stdout.strip()
    raw = (
        f"tree {tree}\nparent {sandbox.head()}\n"
        "author Test Person <test@example.invalid> 0 +0000\n"
        "committer Test Person <test@example.invalid> 0 +0000\n"
        "gpgsig -----BEGIN PGP SIGNATURE-----\n \n iQEzBAABCAAdFiEEabc\n"
        " -----END PGP SIGNATURE-----\n\nsigned message\n"
    )
    sha = subprocess.run(
        ["git", "hash-object", "-t", "commit", "-w", "--stdin"], input=raw, text=True,
        capture_output=True, cwd=sandbox.work, env=sandbox.env, check=True,
    ).stdout.strip()
    assert_passed(sandbox.push("origin", f"{sha}:refs/heads/main"), sandbox, sha)


@pytest.mark.parametrize(
    "name,text,encoding",
    [
        (PERSON, "Zéphyrine Quillfeather\n", "latin-1"),
        ("Желязко Петров", "context,finder\n101,Желязко Петров\n", "cp1251"),
    ],
    ids=["latin-1", "cp1251"],
)
def test_l3_listed_name_in_a_legacy_encoding_blocks(sandbox, name, text, encoding):
    sandbox.deny_add("tier2a-people", name)
    sandbox.seed_public()
    path = sandbox.work / "finds.csv"
    path.write_bytes(text.encode(encoding))
    sandbox.git("add", "finds.csv")
    sandbox.git("commit", "-q", "-m", "data")
    assert_blocked(sandbox.push(), sandbox, sandbox.head())


def test_l3_editing_a_legacy_file_reports_only_added_names(sandbox):
    sandbox.deny_add("tier2a-people", "Желязко Петров")
    path = sandbox.work / "finds.csv"
    path.write_bytes("101,Желязко Петров\n".encode("cp1251"))
    sandbox.git("add", "finds.csv")
    sandbox.git("commit", "-q", "-m", "legacy")
    subprocess.run(["git", "push", "-q", "--no-verify", "origin", "HEAD:refs/heads/main"],
                   cwd=sandbox.work, env=sandbox.env, check=True)
    path.write_bytes("101,Желязко Петров\n102,someone else\n".encode("cp1251"))
    sandbox.git("add", "finds.csv")
    sandbox.git("commit", "-q", "-m", "more")
    assert_passed(sandbox.push(), sandbox, sandbox.head())


# ------------------------------------------------------------------ L5, L6, L7, L10


@pytest.mark.parametrize(
    "line,blocks",
    [
        ("    Hostname example.invalid", True),
        ("hostname=example.invalid", True),
        ("  identityfile ~/.ssh/key", True),
        ("Hostname of the server is set in the notes", False),
    ],
)
def test_l5_ssh_settings_in_any_spelling(sandbox, line, blocks):
    sandbox.seed_public()
    sha = sandbox.commit("a.txt", f"{line}\n")
    result = sandbox.push()
    if blocks:
        assert_blocked(result, sandbox, sha)
    else:
        assert_passed(result, sandbox, sha)


def test_l6_doctor_sees_a_conditional_include_that_switches_hooks_off(sandbox):
    off = sandbox.home / "off.gitconfig"
    off.write_text("[core]\n\thooksPath = /dev/null\n")
    with sandbox.gitconfig.open("a") as handle:
        handle.write(f'[includeIf "gitdir:{sandbox.work}/"]\n\tpath = {off}\n')
    result = sandbox.engine("doctor", "--test", "--scan", str(sandbox.root))
    assert "unguarded" in result.stdout, result.stdout


def test_l6_doctor_treats_test_mode_as_a_problem(sandbox):
    result = sandbox.engine("doctor")
    assert result.returncode != 0
    assert "test mode" in result.stdout


def test_l7_relative_home_is_made_absolute(sandbox, tmp_path):
    from conftest import ENGINE

    relative = "relative-guard-home"
    result = subprocess.run(
        [os.sys.executable, "-I", str(ENGINE), "--home", relative, "install",
         "--gitleaks", str(sandbox.gitleaks), "--test-mode"],
        cwd=tmp_path, env=sandbox.env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    stub = (tmp_path / relative / "hooks" / "pre-push").read_text()
    assert str(tmp_path / relative / "engine" / "publish_guard.py") in stub
    (tmp_path / relative / "hooks").chmod(0o755)


def test_l10_malformed_deny_entry_warns_on_a_private_push(sandbox):
    sandbox.git("remote", "set-url", "origin", str(sandbox.private))
    path = sandbox.guard / "deny" / "tier2b-teaching.hashes"
    lines = path.read_text().splitlines()
    count = int(lines[-1].split("=")[1])
    path.write_text("\n".join(lines[:-1] + ["2 abcdef", f"# end count={count + 1}"]) + "\n")
    result = sandbox.push()
    assert result.returncode == 0, result.stderr
    assert "deny-list can't be loaded" in result.stderr


def test_l10_malformed_deny_entry_blocks_a_public_push(sandbox):
    path = sandbox.guard / "deny" / "tier2b-teaching.hashes"
    lines = path.read_text().splitlines()
    count = int(lines[-1].split("=")[1])
    path.write_text("\n".join(lines[:-1] + ["2 abcdef", f"# end count={count + 1}"]) + "\n")
    result = sandbox.push()
    assert_blocked(result, sandbox, sandbox.head())
    assert "internal error" not in result.stderr


# ------------------------------------------------------------------ L9: scanner exceptions


@needs_real
def test_l9_a_citation_key_on_the_same_line_does_not_hide_a_real_key(real):
    real.seed_public()
    value = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(40))
    line = json.dumps({"citationKey": value, "api_key": value})
    sha = real.commit("a.json", line + "\n")
    assert_blocked(real.push(), real, sha)
