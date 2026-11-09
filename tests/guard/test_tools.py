"""Deny-list handling, overrides, the log, the doctor, and the audit command."""

from __future__ import annotations

import hashlib
import json
import os
import pty
import select
import subprocess
import sys

import pytest
from conftest import (
    ENGINE,
    FAKE_SECRET,
    PERSON,
    TEACHING,
    assert_blocked,
    assert_passed,
    blocked_push_id,
)


def _deny_text(sandbox):
    return "".join(p.read_text() for p in (sandbox.guard / "deny").glob("*.hashes"))


def test_deny_files_hold_no_plain_text(sandbox):
    text = _deny_text(sandbox).lower()
    for word in (PERSON + " " + TEACHING).split():
        assert word not in text


def test_deny_add_never_echoes_terms_and_reports_counts(sandbox):
    result = sandbox.engine("deny-add", "--tier", "tier3-private", stdin="unusual phrase here\n")
    assert result.returncode == 0
    assert "unusual" not in result.stdout + result.stderr
    assert "added" in result.stdout


def test_deny_add_refuses_a_term_too_short_to_be_safe(sandbox):
    result = sandbox.engine("deny-add", "--tier", "tier3-private", stdin="ab\n")
    assert result.returncode != 0


def test_deny_add_from_file(sandbox, tmp_path):
    roster = tmp_path / "roster.txt"
    roster.write_text("first person\n\n# a comment\nsecond person\n")
    result = sandbox.engine("deny-add", "--tier", "tier2b-teaching", "--from-file", str(roster))
    assert result.returncode == 0, result.stderr
    sandbox.seed_public()
    sha = sandbox.commit("a.txt", "second person\n")
    assert_blocked(sandbox.push(), sandbox, sha)


def test_deny_stats_shows_counts_only(sandbox):
    result = sandbox.engine("deny-stats")
    assert result.returncode == 0
    assert "tier2a-people" in result.stdout
    assert PERSON not in result.stdout


def test_skip_tiers_for_one_repository(sandbox):
    sandbox.policy["repos"]["test/public"]["skip_tiers"] = ["tier2a-people"]
    sandbox.save_policy()
    sandbox.seed_public()
    sha = sandbox.commit("a.txt", f"{PERSON}\n")
    assert_passed(sandbox.push(), sandbox, sha)
    dirty = sandbox.commit("b.txt", f"{TEACHING}\n")
    assert_blocked(sandbox.push(), sandbox, dirty)


def test_log_records_outcome_without_values(sandbox):
    sandbox.seed_public()
    sandbox.commit("a.txt", f"{PERSON} {FAKE_SECRET}\n")
    sandbox.push()
    log = (sandbox.guard / "log" / "guard.jsonl").read_text()
    assert PERSON not in log and FAKE_SECRET not in log
    records = [json.loads(line) for line in log.splitlines()]
    assert records[-1]["decision"] == "blocked"
    assert records[-1]["repo"] == "test/public"
    assert records[-1]["counts"]


# ------------------------------------------------------------------ overrides


def _run_in_pty(command, env, cwd, reply, prompt=b"Reason"):
    """Run a command with a real terminal and answer its one prompt."""
    master, slave = pty.openpty()
    process = subprocess.Popen(
        command, stdin=slave, stdout=slave, stderr=slave, env=env, cwd=cwd, close_fds=True
    )
    os.close(slave)
    output = b""
    sent = False
    while True:
        ready, _, _ = select.select([master], [], [], 10)
        if not ready:
            break
        try:
            chunk = os.read(master, 4096)
        except OSError:
            break
        if not chunk:
            break
        output += chunk
        if not sent and prompt in output:
            os.write(master, reply.encode() + b"\n")
            sent = True
    process.wait(timeout=10)
    os.close(master)
    return process.returncode, output.decode()


def _override_command(sandbox, push_id):
    return [
        sys.executable, "-I", str(ENGINE), "--home", str(sandbox.guard), "override",
        "--repo", "test/public", "--push", push_id,
    ]


def test_override_refuses_without_a_terminal(sandbox):
    sandbox.seed_public()
    sha = sandbox.commit("a.txt", f"{PERSON}\n")
    result = subprocess.run(
        _override_command(sandbox, blocked_push_id(sandbox)), input="because\n", text=True,
        capture_output=True, env=sandbox.env, cwd=sandbox.work,
    )
    assert result.returncode != 0
    assert_blocked(sandbox.push(), sandbox, sha)


def test_override_lets_one_exact_push_through_once_and_logs_the_reason(sandbox):
    sandbox.seed_public()
    sha = sandbox.commit("a.txt", f"{PERSON}\n")
    code, output = _run_in_pty(
        _override_command(sandbox, blocked_push_id(sandbox)), sandbox.env, sandbox.work,
        "false positive, checked",
    )
    assert code == 0, output
    assert_passed(sandbox.push(), sandbox, sha)
    log = (sandbox.guard / "log" / "guard.jsonl").read_text()
    assert "false positive, checked" in log
    next_sha = sandbox.commit("b.txt", f"{PERSON}\n")
    assert_blocked(sandbox.push(), sandbox, next_sha)


def test_override_cannot_be_used_twice(sandbox):
    sandbox.seed_public()
    sha = sandbox.commit("a.txt", f"{PERSON}\n")
    code, output = _run_in_pty(
        _override_command(sandbox, blocked_push_id(sandbox)), sandbox.env, sandbox.work, "checked"
    )
    assert code == 0, output
    assert_passed(sandbox.push(), sandbox, sha)
    # The same commit, pushed to a second destination under the same repository name.
    second = sandbox.new_bare("second.git")
    sandbox.visibility[str(second)] = {"name": "test/public", "visibility": "public"}
    sandbox.save_visibility()
    result = sandbox.push(str(second), "HEAD:refs/heads/main")
    assert result.returncode != 0
    assert "publish-guard: BLOCKED" in result.stderr


def test_override_does_not_apply_to_a_different_commit(sandbox):
    sandbox.seed_public()
    sandbox.commit("a.txt", f"{PERSON}\n")
    code, output = _run_in_pty(
        _override_command(sandbox, blocked_push_id(sandbox)), sandbox.env, sandbox.work, "checked"
    )
    assert code == 0, output
    other = sandbox.commit("b.txt", f"{PERSON}\n")
    assert_blocked(sandbox.push(), sandbox, other)


def test_override_does_not_excuse_guard_failures(sandbox):
    sandbox.seed_public()
    sha = sandbox.commit("a.txt", "fine\n")
    code, output = _run_in_pty(
        _override_command(sandbox, "0" * 32), sandbox.env, sandbox.work, "checked"
    )
    assert code == 0, output
    (sandbox.guard / "policy.toml").unlink()
    assert_blocked(sandbox.push(), sandbox, sha)


# ------------------------------------------------------------------ reviewing and changing lists


def _source(sandbox, tier, text, secret=False):
    folder = sandbox.guard / "deny-sources"
    if secret:
        folder = folder / "secrets"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{tier}.txt"
    path.write_text(text)
    return path


def _engine_with_terminal(sandbox, command, term, prompt):
    full = [sys.executable, "-I", str(ENGINE), "--home", str(sandbox.guard), *command]
    return _run_in_pty(full, sandbox.env, sandbox.work, term, prompt=prompt)


def test_rebuild_from_a_source_file_adds_and_removes(sandbox):
    source = _source(sandbox, "tier4-commercial", "# clients\nacme widgets\nglobex holdings\n")
    result = sandbox.engine("deny-rebuild")
    assert result.returncode == 0, result.stderr
    assert "acme" not in result.stdout
    sandbox.seed_public()
    sha = sandbox.commit("a.txt", "work for acme widgets\n")
    assert_blocked(sandbox.push(), sandbox, sha)
    # Deleting the line and rebuilding is how an entry gets removed.
    source.write_text("globex holdings\n")
    assert sandbox.engine("deny-rebuild").returncode == 0
    assert_passed(sandbox.push(), sandbox, sha)


def test_rebuild_finds_sources_in_the_secrets_subfolder(sandbox):
    _source(sandbox, "tier3-private", "unusual private phrase\n", secret=True)
    assert sandbox.engine("deny-rebuild").returncode == 0
    sandbox.seed_public()
    sha = sandbox.commit("a.txt", "an unusual private phrase here\n")
    assert_blocked(sandbox.push(), sandbox, sha)


def test_rebuild_of_one_tier_leaves_the_others_alone(sandbox):
    _source(sandbox, "tier4-commercial", "acme widgets\n")
    _source(sandbox, "tier3-private", "unusual private phrase\n")
    assert sandbox.engine("deny-rebuild", "--tier", "tier4-commercial").returncode == 0
    assert not (sandbox.guard / "deny" / "tier3-private.hashes").exists()


def test_rebuild_from_standard_input_stores_nothing_in_plain_text(sandbox):
    result = sandbox.engine(
        "deny-rebuild", "--tier", "tier1-exploit", "--stdin", stdin="generated value one\n"
    )
    assert result.returncode == 0, result.stderr
    assert "generated" not in _deny_text(sandbox)
    sandbox.seed_public()
    sha = sandbox.commit("a.txt", "generated value one\n")
    assert_blocked(sandbox.push(), sandbox, sha)


def test_failed_rebuild_keeps_the_existing_tier(sandbox):
    _source(sandbox, "tier4-commercial", "acme widgets\n")
    assert sandbox.engine("deny-rebuild").returncode == 0
    _source(sandbox, "tier4-commercial", "ab\n")
    assert sandbox.engine("deny-rebuild").returncode != 0
    # While the source differs from what was built, public pushes are refused outright.
    result = sandbox.push()
    assert_blocked(result, sandbox, sandbox.head())
    assert "edited but not rebuilt" in result.stderr
    # Put the source back as it was built: the old tier is still there, and still blocks.
    _source(sandbox, "tier4-commercial", "acme widgets\n")
    sandbox.seed_public()
    sha = sandbox.commit("a.txt", "acme widgets\n")
    assert_blocked(sandbox.push(), sandbox, sha)


def test_rebuild_with_no_sources_says_so(sandbox):
    result = sandbox.engine("deny-rebuild")
    assert result.returncode != 0
    assert "no source" in result.stderr


def test_deny_add_refuses_a_tier_that_has_a_source_file(sandbox):
    _source(sandbox, "tier4-commercial", "acme widgets\n")
    result = sandbox.engine("deny-add", "--tier", "tier4-commercial", stdin="other term\n")
    assert result.returncode != 0


def test_required_tier_with_no_terms_blocks_public(sandbox):
    _source(sandbox, "tier3-private", "# nothing yet\n")
    assert sandbox.engine("deny-rebuild").returncode == 0
    sandbox.policy["required_tiers"].append("tier3-private")
    sandbox.save_policy()
    assert_blocked(sandbox.push(), sandbox, sandbox.head())
    assert "tier3-private" in _doctor(sandbox).stdout


def test_doctor_notices_a_source_edited_but_not_rebuilt(sandbox):
    source = _source(sandbox, "tier4-commercial", "acme widgets\n")
    assert sandbox.engine("deny-rebuild").returncode == 0
    assert _doctor(sandbox).returncode == 0
    source.write_text("acme widgets\nglobex holdings\n")
    result = _doctor(sandbox)
    assert result.returncode != 0
    assert "tier4-commercial" in result.stdout
    assert "globex" not in result.stdout


def without_test_mode(sandbox):
    """Switch off the test install's relaxed terminal checks."""
    record = sandbox.guard / "install.json"
    record.chmod(0o600)
    data = json.loads(record.read_text())
    data["test_mode"] = False
    # Outside test mode every push checks the scanner against a pinned checksum.
    data["gitleaks_sha256"] = hashlib.sha256(sandbox.gitleaks.read_bytes()).hexdigest()
    record.write_text(json.dumps(data))
    record.chmod(0o444)


@pytest.mark.parametrize("command", ["deny-check", "deny-remove", "deny-add", "deny-rebuild"])
def test_list_commands_need_a_terminal(sandbox, command):
    without_test_mode(sandbox)
    args = [command] + (["--tier", "tier2a-people"] if command in ("deny-remove", "deny-add")
                        else [])
    if command == "deny-rebuild":
        args += ["--tier", "tier2a-people", "--stdin"]
    result = sandbox.engine(*args, stdin=f"{PERSON}\n")
    assert result.returncode != 0
    assert "terminal" in result.stderr
    sandbox.seed_public()
    sha = sandbox.commit("a.txt", f"{PERSON}\n")
    assert_blocked(sandbox.push(), sandbox, sha)


def test_deny_check_reports_tier_for_a_listed_term(sandbox):
    code, output = _engine_with_terminal(sandbox, ["deny-check"], PERSON, b"Term")
    assert code == 0, output
    assert "tier2a-people" in output
    code, output = _engine_with_terminal(sandbox, ["deny-check"], "not listed anywhere", b"Term")
    assert code == 0, output
    assert "not on" in output


def test_deny_check_does_not_echo_the_term(sandbox):
    _, output = _engine_with_terminal(sandbox, ["deny-check"], PERSON, b"Term")
    assert PERSON not in output


def test_deny_remove_takes_out_a_term_and_its_variants(sandbox):
    sandbox.deny_add("tier2a-people", "another listed person")
    code, output = _engine_with_terminal(
        sandbox, ["deny-remove", "--tier", "tier2a-people"], PERSON, b"Term"
    )
    assert code == 0, output
    assert "removed" in output
    sandbox.seed_public()
    first = sandbox.commit("a.txt", f"{PERSON}\n")
    assert_passed(sandbox.push(), sandbox, first)
    second = sandbox.commit("b.txt", f"{PERSON.replace(' ', '')}\n")
    assert_passed(sandbox.push(), sandbox, second)


def test_deny_remove_refuses_a_tier_with_a_source_file(sandbox):
    _source(sandbox, "tier4-commercial", "acme widgets\n")
    assert sandbox.engine("deny-rebuild").returncode == 0
    code, output = _engine_with_terminal(
        sandbox, ["deny-remove", "--tier", "tier4-commercial"], "acme widgets", b"Term"
    )
    assert code != 0
    assert "source" in output


# ------------------------------------------------------------------ doctor


def _doctor(sandbox, *extra):
    return sandbox.engine("doctor", "--test", *extra)


def test_doctor_passes_on_a_good_installation(sandbox):
    result = _doctor(sandbox)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("name", ["pre-push", "pre-commit"])
def test_doctor_finds_a_modified_stub(sandbox, name):
    hooks = sandbox.guard / "hooks"
    hooks.chmod(0o755)
    hook = hooks / name
    hook.chmod(0o755)
    hook.write_text("#!/bin/sh\nexit 0\n")
    hook.chmod(0o555)
    hooks.chmod(0o555)
    result = _doctor(sandbox)
    assert result.returncode != 0
    assert name in result.stdout


def test_doctor_finds_a_missing_stub_and_a_writable_folder(sandbox):
    hooks = sandbox.guard / "hooks"
    hooks.chmod(0o755)
    (hooks / "pre-push").unlink()
    result = _doctor(sandbox)
    assert result.returncode != 0
    assert "pre-push" in result.stdout
    assert "writable" in result.stdout


def test_doctor_finds_global_hooks_path_unset(sandbox):
    subprocess.run(
        ["git", "config", "--global", "--unset", "core.hooksPath"], env=sandbox.env, check=True
    )
    result = _doctor(sandbox)
    assert result.returncode != 0
    assert "core.hooksPath" in result.stdout


def test_doctor_reports_repository_overrides(sandbox):
    sandbox.git("config", "--local", "core.hooksPath", str(sandbox.work / ".git" / "hooks"))
    result = _doctor(sandbox, "--scan", str(sandbox.root))
    assert result.returncode != 0
    assert str(sandbox.work) in result.stdout


def test_doctor_names_hooks_off_lanes_as_unguarded(sandbox):
    sandbox.git("config", "--local", "core.hooksPath", "/dev/null")
    result = _doctor(sandbox, "--scan", str(sandbox.root))
    assert "unguarded" in result.stdout


def test_doctor_reports_a_missing_gitleaks(sandbox):
    sandbox.gitleaks.unlink()
    result = _doctor(sandbox)
    assert result.returncode != 0
    assert "gitleaks" in result.stdout


def test_doctor_reports_a_broken_deny_list(sandbox):
    (sandbox.guard / "deny" / "tier2a-people.hashes").write_text("")
    result = _doctor(sandbox)
    assert result.returncode != 0
    assert "deny" in result.stdout


def test_doctor_does_not_print_terms(sandbox):
    result = _doctor(sandbox)
    assert PERSON not in result.stdout


# ------------------------------------------------------------------ audit


def test_audit_reports_masked_findings_across_history(sandbox):
    sandbox.commit("a.txt", f"{PERSON}\n")
    sandbox.commit("b.txt", "fine\n")
    result = sandbox.engine(
        "audit", "--repo", str(sandbox.work), "--name", "test/public", "--as", "public",
        "--rev", "HEAD",
    )
    assert result.returncode == 1, result.stderr
    assert "tier2a-people" in result.stdout
    assert PERSON not in result.stdout


def test_audit_is_clean_on_clean_history(sandbox):
    result = sandbox.engine(
        "audit", "--repo", str(sandbox.work), "--name", "test/public", "--as", "public",
        "--rev", "HEAD",
    )
    assert result.returncode == 0, result.stdout + result.stderr
