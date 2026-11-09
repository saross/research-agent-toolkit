"""Which commits get scanned, and how a remote is classified."""

from __future__ import annotations

import json

import pytest
from conftest import FAKE_SECRET, PERSON, PUBLIC_NAME, assert_blocked, assert_passed


def _private_history(sandbox):
    """Push history holding a private term to the private remote."""
    sandbox.git("remote", "add", "private", str(sandbox.private))
    sha = sandbox.commit("private.txt", f"{PERSON}\n")
    result = sandbox.push("private", "HEAD:refs/heads/main")
    assert result.returncode == 0, result.stderr
    return sha


def test_set_url_from_private_to_public_scans_the_whole_history(sandbox):
    """Stale tracking refs must not make the range empty."""
    sha = _private_history(sandbox)
    sandbox.git("remote", "set-url", "private", str(sandbox.public))
    assert_blocked(sandbox.push("private", "HEAD:refs/heads/main"), sandbox, sha)


def test_tracking_refs_of_a_second_remote_do_not_excuse_commits(sandbox):
    sha = _private_history(sandbox)
    assert sandbox.git("rev-parse", "refs/remotes/private/main").stdout.strip() == sha
    assert_blocked(sandbox.push("origin", "HEAD:refs/heads/main"), sandbox, sha)


def test_stale_tracking_ref_for_a_deleted_remote_branch(sandbox):
    sandbox.seed_public()
    sha = sandbox.commit("a.txt", "clean\n")
    assert_passed(sandbox.push("origin", "HEAD:refs/heads/topic"), sandbox)
    sandbox.git("fetch", "-q", "origin")
    # The server loses the branch; the local tracking ref still names it.
    assert_passed(sandbox.push("origin", ":refs/heads/topic"), sandbox)
    sandbox.git("update-ref", "refs/remotes/origin/topic", sha)
    dirty = sandbox.commit("b.txt", f"{PERSON}\n")
    sandbox.git("update-ref", "refs/remotes/origin/topic", dirty)
    assert_blocked(sandbox.push("origin", "HEAD:refs/heads/main"), sandbox, dirty)


def test_remote_sha_absent_locally_does_not_break_the_scan(sandbox):
    sandbox.seed_public()
    # Someone else advances the remote; this clone doesn't have that commit.
    other = sandbox.root / "other"
    sandbox.git("clone", "-q", str(sandbox.public), str(other))
    sandbox.git("config", "user.name", "Other", cwd=other)
    (other / "o.txt").write_text("other\n")
    sandbox.git("add", "o.txt", cwd=other)
    sandbox.git("commit", "-q", "-m", "other", cwd=other)
    assert_passed(sandbox.push("origin", "HEAD:refs/heads/main", cwd=other), sandbox)
    sha = sandbox.commit("a.txt", f"{PERSON}\n")
    assert_blocked(sandbox.push("--force", "origin", "HEAD:refs/heads/main"), sandbox, sha)


def test_pushurl_differing_from_url_uses_the_real_destination(sandbox):
    sandbox.git("remote", "add", "split", str(sandbox.private))
    sandbox.git("remote", "set-url", "--push", "split", str(sandbox.public))
    sha = sandbox.commit("a.txt", f"{PERSON}\n")
    assert_blocked(sandbox.push("split", "HEAD:refs/heads/main"), sandbox, sha)


def test_push_to_a_literal_url(sandbox):
    sha = sandbox.commit("a.txt", f"{PERSON}\n")
    assert_blocked(sandbox.push(str(sandbox.public), "HEAD:refs/heads/main"), sandbox, sha)


def test_deleting_a_branch_needs_no_scan(sandbox):
    sandbox.seed_public()
    assert_passed(sandbox.push("origin", "HEAD:refs/heads/temp"), sandbox)
    assert_passed(sandbox.push("origin", ":refs/heads/temp"), sandbox)


# ------------------------------------------------------------------ private remotes


def _point_origin_private(sandbox):
    sandbox.git("remote", "set-url", "origin", str(sandbox.private))


def test_private_remote_allows_personal_content_and_warns(sandbox):
    _point_origin_private(sandbox)
    sha = sandbox.commit("a.txt", f"{PERSON}\n")
    result = sandbox.push()
    assert result.returncode == 0, result.stderr
    assert sandbox.remote_has(sha, sandbox.private)
    assert "publish-guard: warning" in result.stderr
    assert PERSON not in result.stderr


def test_never_public_repository_is_quiet_about_personal_content(sandbox):
    sandbox.policy["repos"]["test/private"] = {"label": "never-public"}
    sandbox.save_policy()
    _point_origin_private(sandbox)
    sandbox.commit("a.txt", f"{PERSON}\n")
    result = sandbox.push()
    assert result.returncode == 0, result.stderr
    assert "publish-guard: warning" not in result.stderr


@pytest.mark.parametrize("label", ["never-public", "may-go-public", None])
def test_secret_blocks_on_every_private_label(sandbox, label):
    if label:
        sandbox.policy["repos"]["test/private"] = {"label": label}
        sandbox.save_policy()
    _point_origin_private(sandbox)
    sha = sandbox.commit("a.txt", f"token = {FAKE_SECRET}\n")
    result = sandbox.push()
    assert result.returncode != 0
    assert "publish-guard: BLOCKED" in result.stderr
    assert not sandbox.remote_has(sha, sandbox.private)


def test_may_go_public_warnings_count_public_rule_hits(sandbox):
    sandbox.policy["repos"]["test/private"] = {"label": "may-go-public"}
    sandbox.save_policy()
    _point_origin_private(sandbox)
    sandbox.commit("a.txt", f"{PERSON}\n")
    result = sandbox.push()
    assert result.returncode == 0
    assert "publish-guard: warning" in result.stderr


# ------------------------------------------------------------------ classification failures


def test_public_repository_with_no_policy_entry_blocks(sandbox):
    sandbox.visibility[str(sandbox.public)]["name"] = "test/unlisted"
    sandbox.save_visibility()
    assert_blocked(sandbox.push(), sandbox, sandbox.head())


def test_never_public_repository_reading_as_public_blocks_and_alerts(sandbox):
    sandbox.policy["repos"][PUBLIC_NAME] = {"label": "never-public"}
    sandbox.save_policy()
    result = sandbox.push()
    assert_blocked(result, sandbox, sandbox.head())
    assert "ALERT" in result.stderr


def test_may_go_public_repository_reading_as_public_blocks(sandbox):
    sandbox.policy["repos"][PUBLIC_NAME] = {"label": "may-go-public"}
    sandbox.save_policy()
    assert_blocked(sandbox.push(), sandbox, sandbox.head())


def test_unknown_visibility_counts_as_public(sandbox):
    sandbox.visibility[str(sandbox.private)] = {"name": "test/private", "visibility": "unknown"}
    sandbox.save_visibility()
    _point_origin_private(sandbox)
    sha = sandbox.commit("a.txt", "fine\n")
    result = sandbox.push()
    assert result.returncode != 0
    assert not sandbox.remote_has(sha, sandbox.private)


def _engine_module():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "guard" / "publish_guard.py"
    spec = importlib.util.spec_from_file_location("publish_guard", path)
    module = importlib.util.module_from_spec(spec)
    import sys

    sys.modules["publish_guard"] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "url,kind,name",
    [
        ("git@github.com:Owner/Repo.git", "github", "owner/repo"),
        ("git@github.com:owner/repo", "github", "owner/repo"),
        ("ssh://git@github.com/owner/repo.git", "github", "owner/repo"),
        ("https://github.com/owner/repo.git", "github", "owner/repo"),
        ("https://github.com/owner/repo/", "github", "owner/repo"),
        ("https://user:hunter2@github.com/owner/repo.git", "github", "owner/repo"),
        ("https://www.github.com/owner/repo", "github", "owner/repo"),
        ("git@my-alias:owner/repo.git", "other", "my-alias:owner/repo.git"),
        ("https://gitlab.example.invalid/owner/repo.git", "other", None),
        ("https://github.com.evil.invalid/owner/repo.git", "other", None),
        ("https://evil.invalid/github.com/owner/repo", "other", None),
        ("/srv/git/thing.git", "local", None),
        ("../thing.git", "local", None),
        ("file:///srv/git/thing.git", "local", None),
    ],
)
def test_url_parsing(url, kind, name):
    guard = _engine_module()
    parsed = guard.parse_remote_url(url)
    assert parsed.kind == kind
    if name:
        assert parsed.name == name
    assert "hunter2" not in repr(parsed)


@pytest.mark.parametrize(
    "exit_code,payload,visibility,name",
    [
        (0, {"visibility": "private", "private": True, "full_name": "o/r"}, "private", "o/r"),
        (0, {"visibility": "public", "private": False, "full_name": "o/r"}, "public", "o/r"),
        (0, {"visibility": "internal", "private": True, "full_name": "o/r"}, "unknown", "o/r"),
        (0, {"visibility": "private", "private": False, "full_name": "o/r"}, "unknown", "o/r"),
        (0, {"message": "Not Found"}, "unknown", "given/name"),
        (1, {"message": "Not Found", "status": "404"}, "unknown", "given/name"),
        (1, {"visibility": "private", "private": True, "full_name": "o/r"}, "unknown",
         "given/name"),
        (0, {"visibility": "public", "private": False, "full_name": "New/Name"}, "public",
         "new/name"),
    ],
    ids=["private", "public", "internal", "inconsistent", "no-field", "404", "error-exit",
         "renamed"],
)
def test_github_answer_is_only_private_when_unambiguous(tmp_path, exit_code, payload, visibility,
                                                         name):
    guard = _engine_module()
    fake = tmp_path / "gh"
    fake.write_text(
        f"#!/bin/sh\ncat <<'EOF'\n{json.dumps(payload)}\nEOF\nexit {exit_code}\n"
    )
    fake.chmod(0o755)
    result = guard.github_visibility("given/name", str(fake))
    assert result == (visibility, name)


def test_missing_gh_is_unknown(tmp_path):
    guard = _engine_module()
    assert guard.github_visibility("o/r", str(tmp_path / "absent")) == ("unknown", "o/r")


def test_local_path_with_no_mapping_is_not_scanned(sandbox):
    other = sandbox.new_bare("backup.git")
    sandbox.git("remote", "add", "backup", str(other))
    sha = sandbox.commit("a.txt", f"{PERSON} {FAKE_SECRET}\n")
    result = sandbox.push("backup", "HEAD:refs/heads/main")
    assert result.returncode == 0, result.stderr
    assert sandbox.remote_has(sha, other)
