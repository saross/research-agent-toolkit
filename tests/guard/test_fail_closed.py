"""The guard must refuse when it can't do its job, on every route."""

from __future__ import annotations

import json
import shutil

import pytest
from conftest import FAKE_SECRET, assert_blocked, assert_passed


def _writable(path):
    path.chmod(path.stat().st_mode | 0o200)


def test_missing_gitleaks_blocks_public(sandbox):
    sandbox.gitleaks.unlink()
    assert_blocked(sandbox.push(), sandbox, sandbox.head())


def test_missing_gitleaks_blocks_private_too(sandbox):
    sandbox.git("remote", "set-url", "origin", str(sandbox.private))
    sandbox.gitleaks.unlink()
    sha = sandbox.head()
    result = sandbox.push()
    assert result.returncode != 0
    assert "publish-guard: BLOCKED" in result.stderr
    assert not sandbox.remote_has(sha, sandbox.private)


def test_crashing_gitleaks_blocks(sandbox):
    sandbox.gitleaks.write_text("#!/bin/sh\nexit 3\n")
    assert_blocked(sandbox.push(), sandbox, sandbox.head())


def test_gitleaks_writing_a_garbled_report_blocks(sandbox):
    sandbox.gitleaks.write_text(
        '#!/bin/sh\nwhile [ "$1" != "--report-path" ]; do shift; done\n'
        'printf "not json" > "$2"\nexit 7\n'
    )
    assert_blocked(sandbox.push(), sandbox, sandbox.head())


def test_scanner_rules_on_disk_have_no_say_in_a_push(sandbox):
    """The rules come from the engine on every push, so a copy planted in the guard's folder
    can't weaken the scan (Astra review, finding 6)."""
    assert not (sandbox.guard / "gitleaks.toml").exists()
    (sandbox.guard / "gitleaks.toml").write_text('[allowlist]\nregexes = [".*"]\n')
    sha = sandbox.commit("a.txt", f"{FAKE_SECRET}\n")
    assert_blocked(sandbox.push(), sandbox, sha)
    calls = [json.loads(line) for line in sandbox.calls.read_text().splitlines()]
    config = calls[-1]["argv"][calls[-1]["argv"].index("--config") + 1]
    assert not config.startswith(str(sandbox.guard))


def test_doctor_reports_a_changed_agent_hook(sandbox):
    hook = sandbox.guard / "engine" / "agent_hook.py"
    hook.chmod(0o644)
    hook.write_text(hook.read_text() + "\n# changed\n")
    result = sandbox.engine("doctor", "--test")
    assert result.returncode != 0
    assert "agent hook" in result.stdout


def test_doctor_reports_an_unpinned_scanner_outside_test_mode(sandbox):
    record = sandbox.guard / "install.json"
    record.chmod(0o600)
    data = json.loads(record.read_text())
    data["test_mode"] = False
    data["gitleaks_sha256"] = None
    record.write_text(json.dumps(data))
    result = sandbox.engine("doctor")
    assert result.returncode != 0
    assert "no pinned checksum" in result.stdout


def test_an_unpinned_scanner_outside_test_mode_refuses_every_push(sandbox):
    """Second audit (test lens), M3: the push-time check, not only the install-time one."""
    record = sandbox.guard / "install.json"
    record.chmod(0o600)
    data = json.loads(record.read_text())
    data["test_mode"] = False
    data["gitleaks_sha256"] = None
    record.write_text(json.dumps(data))
    result = sandbox.push()
    assert_blocked(result, sandbox, sandbox.head())
    assert "pinned checksum" in result.stderr


def test_install_refuses_a_pin_that_doesnt_match_the_scanner(sandbox):
    result = sandbox.engine(
        "install", "--gitleaks", str(sandbox.gitleaks), "--gitleaks-sha256", "0" * 64,
        "--test-mode",
    )
    assert result.returncode != 0
    assert "doesn't match" in result.stderr


def test_missing_policy_blocks_public(sandbox):
    (sandbox.guard / "policy.toml").unlink()
    assert_blocked(sandbox.push(), sandbox, sandbox.head())


def test_corrupt_policy_blocks_public(sandbox):
    (sandbox.guard / "policy.toml").write_text("this is [not toml")
    assert_blocked(sandbox.push(), sandbox, sandbox.head())


def test_unknown_label_in_policy_blocks(sandbox):
    sandbox.policy["repos"]["test/public"]["label"] = "publik"
    sandbox.save_policy()
    assert_blocked(sandbox.push(), sandbox, sandbox.head())


def test_missing_policy_on_private_still_scans_secrets(sandbox):
    (sandbox.guard / "policy.toml").unlink()
    sandbox.git("remote", "set-url", "origin", str(sandbox.private))
    sha = sandbox.head()
    result = sandbox.push()
    assert result.returncode == 0, result.stderr
    assert sandbox.remote_has(sha, sandbox.private)


def test_missing_deny_folder_blocks_public(sandbox):
    shutil.rmtree(sandbox.guard / "deny")
    assert_blocked(sandbox.push(), sandbox, sandbox.head())


def test_missing_required_tier_blocks_public(sandbox):
    (sandbox.guard / "deny" / "tier2b-teaching.hashes").unlink()
    assert_blocked(sandbox.push(), sandbox, sandbox.head())


def test_truncated_deny_file_blocks_public(sandbox):
    path = sandbox.guard / "deny" / "tier2a-people.hashes"
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[:-1]) + "\n")
    assert_blocked(sandbox.push(), sandbox, sandbox.head())


def test_emptied_deny_file_blocks_public(sandbox):
    (sandbox.guard / "deny" / "tier2a-people.hashes").write_text("")
    assert_blocked(sandbox.push(), sandbox, sandbox.head())


def test_deny_file_without_the_sentinel_blocks_public(sandbox):
    path = sandbox.guard / "deny" / "tier2a-people.hashes"
    lines = [line for line in path.read_text().splitlines() if line.startswith("#")]
    head, foot = lines[0], "# end count=0"
    path.write_text(f"{head}\n{foot}\n")
    assert_blocked(sandbox.push(), sandbox, sandbox.head())


def test_changed_salt_blocks_public(sandbox):
    (sandbox.guard / "deny" / "salt").write_text("00" * 32 + "\n")
    assert_blocked(sandbox.push(), sandbox, sandbox.head())


@pytest.mark.parametrize("breakage", ["engine-missing", "engine-broken"])
def test_broken_engine_blocks_through_the_stub(sandbox, breakage):
    engine = sandbox.guard / "engine" / "publish_guard.py"
    _writable(engine)
    if breakage == "engine-missing":
        engine.unlink()
    else:
        engine.write_text("1 / 0\n")
    result = sandbox.push()
    assert result.returncode != 0
    assert not sandbox.remote_has(sandbox.head())


def test_missing_install_record_blocks(sandbox):
    record = sandbox.guard / "install.json"
    _writable(record)
    record.unlink()
    assert_blocked(sandbox.push(), sandbox, sandbox.head())


def test_unexpected_engine_error_blocks_with_the_marker(sandbox):
    # A malformed visibility map makes the engine's own start-up fail.
    sandbox.visibility_map.write_text("{not json")
    assert_blocked(sandbox.push(), sandbox, sandbox.head())


def test_stub_is_a_real_file_not_a_symlink_and_read_only(sandbox):
    hook = sandbox.guard / "hooks" / "pre-push"
    assert hook.is_file() and not hook.is_symlink()
    assert not hook.stat().st_mode & 0o222
    assert not (sandbox.guard / "hooks").stat().st_mode & 0o222
    assert hook.read_text().startswith("#!/bin/sh\n")
    # The time limit lives inside the engine, so a slow LFS upload after the check isn't cut off.
    assert "timeout" not in hook.read_text()


def test_policy_inside_the_repository_is_ignored(sandbox):
    (sandbox.work / "policy.toml").write_text('[repos."test/public"]\nlabel = "may-go-public"\n')
    assert_passed(sandbox.push(), sandbox)
