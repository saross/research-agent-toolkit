"""Regression tests for the peer review of 7 November 2026 (GPT in Codex, reviewing commit 3a691ef).

The reviewer reproduced each problem with ordinary, hooked pushes into local bare repositories.
Each test here rebuilds one reproduction and asserts the safe behaviour, so it fails if the problem
returns. Finding numbers are the reviewer's.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import time

import pytest
from conftest import (
    ENGINE,
    FAKE_SECRET,
    PERSON,
    PRIVATE_NAME,
    PUBLIC_NAME,
    assert_blocked,
    assert_passed,
    blocked_push_id,
)

FIRST, SECOND = PERSON.split()
# A long opaque value, standing in for one taken from a `.env` file.
KNOWN_SECRET = "opaquevalue" + "7f3a9c2e5b81d4"


def _to_private(sandbox, label="may-go-public"):
    sandbox.policy["repos"][PRIVATE_NAME] = {"label": label}
    sandbox.save_policy()
    sandbox.git("remote", "set-url", "origin", str(sandbox.private))


# ------------------------------------------------------------------ 1: a second URL rewrite


def test_1_a_rewrite_of_the_already_rewritten_url_refuses(sandbox):
    """origin is an alias for the public repository, and a second rule maps the public path to
    the private one. The push reaches the public repository; asking the rewritten URL again
    would ask the private one, whose history would then look published."""
    sandbox.seed_public()
    sha = sandbox.commit("diary.txt", f"{PERSON}\n")
    assert sandbox.push(str(sandbox.private), "HEAD:refs/heads/main").returncode == 0
    sandbox.git("remote", "set-url", "origin", "alias:origin")
    sandbox.git_global(f"url.{sandbox.public}.insteadOf", "alias:origin")
    sandbox.git_global(f"url.{sandbox.private}.insteadOf", str(sandbox.public))
    result = sandbox.push()
    assert_blocked(result, sandbox, sha)
    assert not sandbox.remote_has(sha)


# ------------------------------------------------------------------ 2: phrases an edit completes


def test_2_name_finished_on_the_next_line_in_a_later_commit_blocks(sandbox):
    sandbox.seed_public()
    sandbox.commit("notes.md", f"Thanks to {FIRST}\n")
    sha = sandbox.commit("notes.md", f"Thanks to {FIRST}\n{SECOND} for the photographs.\n")
    assert_blocked(sandbox.push(), sandbox, sha)


def test_2_name_joined_by_a_deletion_only_edit_blocks(sandbox):
    sandbox.commit("notes.md", f"{FIRST}\nand\n{SECOND}\n")
    sandbox.seed_public()
    sha = sandbox.commit("notes.md", f"{FIRST}\n{SECOND}\n")
    assert_blocked(sandbox.push(), sandbox, sha)


def test_2_merge_that_completes_a_name_blocks(sandbox):
    """Each parent holds only the first word; the merge result adds the second beside it."""
    sandbox.seed_public()
    sandbox.git("checkout", "-q", "-b", "side")
    sandbox.commit("side.txt", "side work\n")
    sandbox.git("checkout", "-q", "main")
    sandbox.commit("notes.md", f"{FIRST}\n")
    sandbox.git("merge", "-q", "--no-commit", "side")
    (sandbox.work / "notes.md").write_text(f"{FIRST}\n{SECOND}\n")
    sandbox.git("add", "notes.md")
    sandbox.git("commit", "-q", "-m", "merge")
    assert_blocked(sandbox.push(), sandbox, sandbox.head())


def test_2_editing_a_file_that_already_holds_a_published_name_passes(sandbox):
    """The negative: a name the public repository already has isn't new when the file changes."""
    # Publish the name by a route the guard doesn't see, standing in for legacy content.
    sandbox.commit("notes.md", f"{PERSON}\n")
    subprocess.run(
        ["git", "push", "-q", "--no-verify", "origin", "HEAD:refs/heads/main"],
        cwd=sandbox.work, env=sandbox.env, check=True,
    )
    sha = sandbox.commit("notes.md", f"{PERSON}\nan unrelated new line\n")
    assert_passed(sandbox.push(), sandbox, sha)


def test_2_moving_a_published_name_within_a_file_passes(sandbox):
    sandbox.commit("notes.md", f"intro\n{PERSON}\n")
    subprocess.run(
        ["git", "push", "-q", "--no-verify", "origin", "HEAD:refs/heads/main"],
        cwd=sandbox.work, env=sandbox.env, check=True,
    )
    sha = sandbox.commit("notes.md", f"{PERSON}\nintro\n")
    assert_passed(sandbox.push(), sandbox, sha)


def test_2_a_second_copy_of_a_published_name_blocks(sandbox):
    sandbox.commit("notes.md", f"{PERSON}\n")
    subprocess.run(
        ["git", "push", "-q", "--no-verify", "origin", "HEAD:refs/heads/main"],
        cwd=sandbox.work, env=sandbox.env, check=True,
    )
    sha = sandbox.commit("notes.md", f"{PERSON}\nagain {PERSON}\n")
    result = sandbox.push()
    assert_blocked(result, sandbox, sha)
    assert "notes.md:2" in result.stderr


# ------------------------------------------------------------------ 3: refs and tags in an audit


def _audit(sandbox, *revs):
    args = ["audit", "--repo", str(sandbox.work), "--name", PUBLIC_NAME]
    for rev in revs:
        args.append(f"--rev={rev}")
    return sandbox.engine(*args)


def test_3_audit_of_all_refs_reads_annotated_tag_messages(sandbox):
    sandbox.git("tag", "-a", "-m", f"thanks to {PERSON}", "v1")
    result = _audit(sandbox, "--all")
    assert result.returncode != 0, result.stdout
    assert "tier2a-people" in result.stdout
    assert PERSON not in result.stdout


def test_3_audit_of_all_refs_reads_ref_names(sandbox):
    sandbox.git("branch", PERSON.replace(" ", "-"))
    result = _audit(sandbox, "--all")
    assert result.returncode != 0, result.stdout
    assert "<ref name>" in result.stdout


def test_3_audit_of_a_named_tag_reads_its_message(sandbox):
    sandbox.git("tag", "-a", "-m", f"thanks to {PERSON}", "v1")
    result = _audit(sandbox, "v1")
    assert result.returncode != 0, result.stdout


def test_3_audit_of_clean_refs_passes(sandbox):
    sandbox.git("tag", "-a", "-m", "first release", "v1")
    result = _audit(sandbox, "--all")
    assert result.returncode == 0, result.stdout + result.stderr


# ------------------------------------------------------------------ 5: LFS pointers


def test_5_text_that_only_starts_like_an_lfs_pointer_is_read_as_text(sandbox):
    sandbox.policy["repos"][PUBLIC_NAME]["binary_allow"] = ["assets/*"]
    sandbox.save_policy()
    sandbox.seed_public()
    fake = f"version https://git-lfs.github.com/spec/v1\n{PERSON}\n"
    sha = sandbox.commit("assets/data.bin", fake)
    result = sandbox.push()
    assert_blocked(result, sandbox, sha)
    assert "tier2a-people" in result.stderr


def test_5_a_real_lfs_pointer_on_an_allowed_path_passes(sandbox):
    sandbox.policy["repos"][PUBLIC_NAME]["binary_allow"] = ["assets/*"]
    sandbox.save_policy()
    sandbox.seed_public()
    pointer = "version https://git-lfs.github.com/spec/v1\noid sha256:" + "a" * 64 + "\nsize 9\n"
    sha = sandbox.commit("assets/data.bin", pointer)
    assert_passed(sandbox.push(), sandbox, sha)


# ------------------------------------------------------------------ 6: integrity at push time


def _pin_scanner(sandbox):
    digest = hashlib.sha256(sandbox.gitleaks.read_bytes()).hexdigest()
    sandbox.install("--gitleaks-sha256", digest)


def test_6_a_replaced_scanner_blocks_the_push(sandbox):
    _pin_scanner(sandbox)
    sandbox.seed_public()
    sandbox.gitleaks.write_text("#!/bin/sh\nexit 0\n")
    sha = sandbox.commit("a.txt", f"{FAKE_SECRET}\n")
    result = sandbox.push()
    assert_blocked(result, sandbox, sha)
    assert "checksum" in result.stderr


def test_6_install_outside_test_mode_needs_a_pinned_scanner(sandbox):
    result = sandbox.engine("install", "--gitleaks", str(sandbox.gitleaks))
    assert result.returncode != 0
    assert "--gitleaks-sha256" in result.stderr


def test_6_a_source_edited_after_rebuilding_blocks_public_pushes(sandbox):
    sources = sandbox.guard / "deny-sources"
    sources.mkdir()
    (sources / "tier4-commercial.txt").write_text("acme widgets\n")
    assert sandbox.engine("deny-rebuild").returncode == 0
    sandbox.seed_public()
    (sources / "tier4-commercial.txt").write_text("acme widgets\nglobex\n")
    sha = sandbox.commit("a.txt", "globex\n")
    result = sandbox.push()
    assert_blocked(result, sandbox, sha)
    assert "edited but not rebuilt" in result.stderr


# ------------------------------------------------------------------ 7: known secrets everywhere


def test_7_known_secret_blocks_on_a_private_remote(sandbox):
    sandbox.deny_add("tier1-exploit", KNOWN_SECRET)
    _to_private(sandbox)
    sha = sandbox.commit("config.txt", f"token = {KNOWN_SECRET}\n")
    result = sandbox.push()
    assert result.returncode != 0
    assert "publish-guard: BLOCKED" in result.stderr
    assert KNOWN_SECRET not in result.stderr
    assert not sandbox.remote_has(sha, sandbox.private)


def test_7_known_secret_blocks_on_a_never_public_remote(sandbox):
    sandbox.deny_add("tier1-exploit", KNOWN_SECRET)
    _to_private(sandbox, "never-public")
    sha = sandbox.commit("config.txt", f"token = {KNOWN_SECRET}\n")
    result = sandbox.push()
    assert result.returncode != 0
    assert "tier1-exploit" in result.stderr
    assert not sandbox.remote_has(sha, sandbox.private)


def test_7_never_public_remote_still_ignores_the_other_tiers(sandbox):
    sandbox.deny_add("tier1-exploit", KNOWN_SECRET)
    _to_private(sandbox, "never-public")
    sha = sandbox.commit("diary.txt", f"{PERSON}\n")
    assert_passed(sandbox.push(), sandbox, None)
    assert sandbox.remote_has(sha, sandbox.private)


def test_7_known_secret_in_a_file_name_blocks_and_hides_paths(sandbox):
    sandbox.deny_add("tier1-exploit", KNOWN_SECRET)
    _to_private(sandbox, "never-public")
    sha = sandbox.commit(f"keys/{KNOWN_SECRET}.txt", "plain\n")
    result = sandbox.push()
    assert result.returncode != 0
    assert KNOWN_SECRET not in result.stderr
    assert not sandbox.remote_has(sha, sandbox.private)


def test_7_the_secrets_tier_cannot_be_skipped(sandbox):
    sandbox.deny_add("tier1-exploit", KNOWN_SECRET)
    sandbox.policy["repos"][PUBLIC_NAME]["skip_tiers"] = ["tier1-exploit"]
    sandbox.save_policy()
    result = sandbox.push()
    assert_blocked(result, sandbox, sandbox.head())
    assert "can't be skipped" in result.stderr


# ------------------------------------------------------------------ overrides


def _override(sandbox, push_id, created=None, generation=None):
    """Write an exemption as the override command would, with chosen age and generation."""
    sys_path = [str(ENGINE.parent)]
    code = (
        "import json, sys, time\n"
        f"sys.path[:0] = {sys_path!r}\n"
        "import publish_guard as g\n"
        "from pathlib import Path\n"
        f"home = Path({str(sandbox.guard)!r})\n"
        f"path = g.override_path(home, {PUBLIC_NAME!r}, {push_id!r})\n"
        "path.parent.mkdir(parents=True, exist_ok=True)\n"
        f"created = {created!r} if {created!r} is not None else time.time()\n"
        f"generation = {generation!r} or g.policy_generation(home)\n"
        f"path.write_text(json.dumps({{'repo': {PUBLIC_NAME!r}, 'push': {push_id!r}, "
        "'reason': 'checked', 'created': created, 'generation': generation}))\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True, env=sandbox.env)


def test_override_is_bound_to_the_destination_ref(sandbox):
    sandbox.seed_public()
    sha = sandbox.commit("a.txt", f"{PERSON}\n")
    _override(sandbox, blocked_push_id(sandbox))
    assert_blocked(sandbox.push("origin", "HEAD:refs/heads/other"), sandbox, sha)


def test_override_doesnt_cover_an_extra_ref_pushed_with_it(sandbox):
    """Second audit (test lens), C2: every ref in the push is bound, not just the first."""
    sandbox.seed_public()
    sha = sandbox.commit("a.txt", f"{PERSON}\n")
    _override(sandbox, blocked_push_id(sandbox))
    branch = "refs/heads/" + PERSON.replace(" ", "-")
    result = sandbox.push("origin", "HEAD:refs/heads/main", f"HEAD:{branch}")
    assert_blocked(result, sandbox, sha)


def test_override_lapses_after_an_hour(sandbox):
    sandbox.seed_public()
    sha = sandbox.commit("a.txt", f"{PERSON}\n")
    _override(sandbox, blocked_push_id(sandbox), created=time.time() - 7200)
    assert_blocked(sandbox.push(), sandbox, sha)


def test_override_from_the_future_is_refused(sandbox):
    sandbox.seed_public()
    sha = sandbox.commit("a.txt", f"{PERSON}\n")
    _override(sandbox, blocked_push_id(sandbox), created=time.time() + 600)
    assert_blocked(sandbox.push(), sandbox, sha)


def test_override_lapses_when_the_policy_file_changes(sandbox):
    """Second audit (test lens), M2: change the policy itself, not the stored fingerprint."""
    sandbox.seed_public()
    sha = sandbox.commit("a.txt", f"{PERSON}\n")
    _override(sandbox, blocked_push_id(sandbox))
    sandbox.policy["repos"]["unrelated/repository"] = {"label": "never-public"}
    sandbox.save_policy()
    assert_blocked(sandbox.push(), sandbox, sha)


def test_override_lapses_when_a_deny_list_changes(sandbox):
    sandbox.seed_public()
    sha = sandbox.commit("a.txt", f"{PERSON}\n")
    _override(sandbox, blocked_push_id(sandbox))
    sandbox.deny_add("tier2a-people", "another listed person")
    assert_blocked(sandbox.push(), sandbox, sha)


def test_override_written_correctly_lets_the_push_through_once(sandbox):
    sandbox.seed_public()
    sha = sandbox.commit("a.txt", f"{PERSON}\n")
    _override(sandbox, blocked_push_id(sandbox))
    assert_passed(sandbox.push(), sandbox, sha)
    assert not list((sandbox.guard / "overrides").iterdir())


def test_blocked_push_prints_an_identifier_not_the_ref_name(sandbox):
    sandbox.seed_public()
    sha = sandbox.commit("a.txt", "fine\n")
    branch = PERSON.replace(" ", "-")
    result = sandbox.push("origin", f"HEAD:refs/heads/{branch}")
    assert_blocked(result, sandbox, sha)
    assert re.search(r"--push [0-9a-f]{32}", result.stderr)


# ------------------------------------------------------------------ the stub and doctor


def test_stub_prints_the_marker_when_the_engine_is_missing(sandbox):
    (sandbox.guard / "engine" / "publish_guard.py").unlink()
    result = sandbox.push()
    assert result.returncode != 0
    assert "publish-guard: BLOCKED" in result.stderr
    assert not sandbox.remote_has(sandbox.head())


def test_doctor_reports_a_stub_that_isnt_executable(sandbox):
    (sandbox.guard / "hooks" / "pre-push").chmod(0o444)
    result = sandbox.engine("doctor", "--test")
    assert result.returncode != 0
    assert "isn't executable" in result.stdout


def test_log_never_holds_a_known_secret(sandbox):
    sandbox.deny_add("tier1-exploit", KNOWN_SECRET)
    _to_private(sandbox)
    sandbox.commit(f"{KNOWN_SECRET}.txt", f"{KNOWN_SECRET}\n")
    sandbox.push()
    log = (sandbox.guard / "log" / "guard.jsonl").read_text()
    assert KNOWN_SECRET not in log
    assert json.loads(log.splitlines()[-1])["decision"] == "blocked"


# ------------------------------------------- Astra's reviews of 8 November: W3 and item 3


def _private_with_secret(sandbox, label="never-public"):
    sandbox.deny_add("tier1-exploit", KNOWN_SECRET)
    sandbox.policy["repos"][PRIVATE_NAME] = {"label": label}
    sandbox.save_policy()
    sandbox.git("remote", "set-url", "origin", str(sandbox.private))


def test_w3_a_missing_secrets_tier_file_refuses_a_private_push(sandbox):
    _private_with_secret(sandbox)
    (sandbox.guard / "deny" / "tier1-exploit.hashes").unlink()
    sha = sandbox.commit("config.txt", f"token = {KNOWN_SECRET}\n")
    result = sandbox.push()
    assert result.returncode != 0, result.stderr
    assert "publish-guard: BLOCKED" in result.stderr
    assert not sandbox.remote_has(sha, sandbox.private)


def test_w3_a_required_secrets_tier_is_required_on_private_pushes_too(sandbox):
    _private_with_secret(sandbox)
    sandbox.policy["required_tiers"].append("tier1-exploit")
    sandbox.save_policy()
    (sandbox.guard / "deny" / "tier1-exploit.hashes").unlink()
    (sandbox.guard / "secret-tier-expected").unlink()
    sha = sandbox.commit("notes.txt", "ordinary\n")
    result = sandbox.push()
    assert result.returncode != 0
    assert not sandbox.remote_has(sha, sandbox.private)


def test_w3_a_secrets_tier_never_set_up_stays_optional(sandbox):
    sandbox.policy["repos"][PRIVATE_NAME] = {"label": "never-public"}
    sandbox.save_policy()
    sandbox.git("remote", "set-url", "origin", str(sandbox.private))
    sha = sandbox.commit("notes.txt", "ordinary\n")
    assert sandbox.push().returncode == 0
    assert sandbox.remote_has(sha, sandbox.private)


@pytest.mark.parametrize("label", ["never-public", "may-go-public"])
def test_item3_a_secret_completed_across_commits_on_a_private_push_is_blocked(sandbox, label):
    _private_with_secret(sandbox, label)
    sandbox.deny_add("tier1-exploit", "syntheticopaque passphrasecomponent")
    sandbox.commit("keys.txt", "syntheticopaque\n")
    assert sandbox.push().returncode == 0
    sha = sandbox.commit("keys.txt", "syntheticopaque\npassphrasecomponent\n")
    result = sandbox.push()
    assert result.returncode != 0, result.stderr
    assert "tier1-exploit" in result.stderr
    assert not sandbox.remote_has(sha, sandbox.private)
