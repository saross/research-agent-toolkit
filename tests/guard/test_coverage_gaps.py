"""Tests for gaps the test-adequacy audit (Lens B, 8 November 2026) found.

Each covers a behaviour a one-line change to the engine could break while every other test stayed
green. Comments name the audit's mutant where there was one.
"""

from __future__ import annotations

import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import (
    ENGINE,
    FAKE_SECRET,
    PERSON,
    PUBLIC_NAME,
    assert_blocked,
    assert_passed,
)

GITHUB_URL = "git@github.com:Test/Public.git"


# ------------------------------------------------------------------ the real GitHub route


def _github_world(sandbox, visibility: str) -> None:
    """Reinstall with no visibility map and a fake `gh`, and serve the GitHub URL locally.

    A fake SSH command answers for github.com from the sandbox's bare repository, so no request
    leaves the machine, and no URL rewriting is involved.
    """
    fake = sandbox.root / "fake-bin"
    fake.mkdir()
    payload = {"visibility": visibility, "private": visibility == "private",
               "full_name": "Test/Public"}
    gh = fake / "gh"
    gh.write_text(f"#!/bin/sh\ncat <<'EOF'\n{json.dumps(payload)}\nEOF\n")
    gh.chmod(0o755)
    ssh = fake / "ssh"
    ssh.write_text(
        "#!/bin/sh\n"
        f'case "$*" in *upload-pack*) exec git upload-pack {sandbox.public};;\n'
        f'  *receive-pack*) exec git receive-pack {sandbox.public};; esac\nexit 1\n'
    )
    ssh.chmod(0o755)
    sandbox.env["PATH"] = f"{fake}:{sandbox.env['PATH']}"
    sandbox.env["GIT_SSH_COMMAND"] = str(ssh)
    hooks = sandbox.guard / "hooks"
    hooks.chmod(0o755)
    result = sandbox.engine("install", "--gitleaks", str(sandbox.gitleaks), "--test-mode")
    assert result.returncode == 0, result.stderr
    recorded = json.loads((sandbox.guard / "install.json").read_text())
    assert recorded["gh"] == str(gh)  # M03: install records gh from PATH
    assert recorded["visibility_map"] is None


def test_public_github_repository_is_classified_through_gh(sandbox):
    _github_world(sandbox, "public")
    sandbox.policy["repos"]["test/public"] = {"label": "public"}
    sandbox.save_policy()
    sha = sandbox.commit("a.txt", f"{PERSON}\n")
    result = sandbox.push(GITHUB_URL, "HEAD:refs/heads/main")
    assert_blocked(result, sandbox, sha)
    assert "test/public (public)" in result.stderr


def test_private_github_repository_only_warns(sandbox):
    _github_world(sandbox, "private")
    sandbox.policy["repos"]["test/public"] = {"label": "may-go-public"}
    sandbox.save_policy()
    sha = sandbox.commit("a.txt", f"{PERSON}\n")
    result = sandbox.push(GITHUB_URL, "HEAD:refs/heads/main")
    assert_passed(result, sandbox, sha)
    assert "publish-guard: warning" in result.stderr


def test_another_host_counts_as_public(sandbox):
    _github_world(sandbox, "private")
    sha = sandbox.commit("a.txt", "fine\n")
    result = sandbox.push("git@gitlab.example.invalid:test/public.git", "HEAD:refs/heads/main")
    assert result.returncode != 0
    assert "has no policy entry" in result.stderr
    assert not sandbox.remote_has(sha)


# ------------------------------------------------------------------ range and content


def test_range_is_asked_of_the_push_url_not_the_fetch_url(sandbox):
    """M04: with history on the fetch side, asking the wrong URL would scan nothing."""
    sha = sandbox.commit("a.txt", f"{PERSON}\n")
    subprocess.run(
        ["git", "push", "-q", "--no-verify", str(sandbox.private), "HEAD:refs/heads/main"],
        cwd=sandbox.work, env=sandbox.env, check=True,
    )
    sandbox.git("remote", "add", "split", str(sandbox.private))
    sandbox.git("remote", "set-url", "--push", "split", str(sandbox.public))
    assert_blocked(sandbox.push("split", "HEAD:refs/heads/main"), sandbox, sha)


def test_root_commit_of_a_new_repository_is_scanned(sandbox):
    """M59: the first push of a new repository is a root commit."""
    fresh = sandbox.root / "fresh"
    fresh.mkdir()
    sandbox.git("init", "-q", cwd=fresh)
    (fresh / "a.txt").write_text(f"{PERSON}\n")
    sandbox.git("add", "a.txt", cwd=fresh)
    sandbox.git("commit", "-q", "-m", "root", cwd=fresh)
    sha = sandbox.git("rev-parse", "HEAD", cwd=fresh).stdout.strip()
    result = sandbox.push(str(sandbox.public), "HEAD:refs/heads/main", cwd=fresh)
    assert_blocked(result, sandbox, sha)


def test_appending_to_a_file_without_a_final_newline_is_scanned(sandbox):
    """M21b: the diff marks the old last line with a backslash line."""
    sandbox.commit("notes.txt", "first line")
    sandbox.seed_public()
    sha = sandbox.commit("notes.txt", f"first line\n{PERSON}")
    assert_blocked(sandbox.push(), sandbox, sha)


def test_tagger_identity_is_scanned(sandbox):
    """M20."""
    sandbox.seed_public()
    env = dict(sandbox.env, GIT_COMMITTER_NAME=PERSON)
    sandbox.git("tag", "-a", "v1", "-m", "release", env=env)
    assert_blocked(sandbox.push("origin", "refs/tags/v1"), sandbox)


def test_clean_tag_push_passes(sandbox):
    """M104: a check that refused every tag would otherwise go unnoticed."""
    sandbox.seed_public()
    sandbox.git("tag", "-a", "v1", "-m", "release")
    sandbox.git("tag", "light")
    assert_passed(sandbox.push("origin", "refs/tags/v1", "refs/tags/light"), sandbox)


def test_merge_only_path_is_checked_against_allowed_paths(sandbox):
    """M62."""
    sandbox.policy["repos"][PUBLIC_NAME]["allowed_paths"] = ["README.md", "docs/**"]
    sandbox.save_policy()
    base = sandbox.seed_public()
    sandbox.git("checkout", "-q", "-b", "side", base)
    sandbox.commit("docs/side.md", "side\n")
    sandbox.git("checkout", "-q", "-b", "other", base)
    sandbox.commit("docs/other.md", "other\n")
    sandbox.git("merge", "-q", "--no-commit", "side")
    (sandbox.work / "wiki").mkdir()
    (sandbox.work / "wiki" / "notes.md").write_text("only in the merge\n")
    sandbox.git("add", "wiki/notes.md")
    sandbox.git("commit", "-q", "-m", "merge")
    assert_blocked(sandbox.push(), sandbox, sandbox.head())


def test_merge_only_binary_needs_an_allowance(sandbox):
    """M63."""
    base = sandbox.seed_public()
    sandbox.git("checkout", "-q", "-b", "side", base)
    sandbox.commit("side.txt", "side\n")
    sandbox.git("checkout", "-q", "-b", "other", base)
    sandbox.commit("other.txt", "other\n")
    sandbox.git("merge", "-q", "--no-commit", "side")
    (sandbox.work / "scan.pdf").write_bytes(b"\x00\x01binary" * 20)
    sandbox.git("add", "scan.pdf")
    sandbox.git("commit", "-q", "-m", "merge")
    assert_blocked(sandbox.push(), sandbox, sandbox.head())


def test_symlink_to_the_parent_folder_blocks(sandbox):
    """M22."""
    sandbox.seed_public()
    (sandbox.work / "up").symlink_to("..")
    sandbox.git("add", "up")
    sandbox.git("commit", "-q", "-m", "link")
    assert_blocked(sandbox.push(), sandbox, sandbox.head())


def test_private_repository_labelled_public_blocks(sandbox):
    """M08: the label is the stricter of the two."""
    sandbox.policy["repos"]["test/private"] = {"label": "public"}
    sandbox.save_policy()
    sandbox.git("remote", "set-url", "origin", str(sandbox.private))
    sha = sandbox.commit("a.txt", f"{PERSON}\n")
    result = sandbox.push()
    assert result.returncode != 0
    assert not sandbox.remote_has(sha, sandbox.private)


def test_deny_file_with_the_wrong_count_blocks(sandbox):
    """M09."""
    path = sandbox.guard / "deny" / "tier2a-people.hashes"
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[:-1] + ["# end count=999"]) + "\n")
    assert_blocked(sandbox.push(), sandbox, sandbox.head())


# ------------------------------------------------------------------ masking on every route


def test_never_public_route_withholds_paths(sandbox):
    sandbox.policy["repos"]["test/private"] = {"label": "never-public"}
    sandbox.save_policy()
    sandbox.git("remote", "set-url", "origin", str(sandbox.private))
    sandbox.commit(f"{PERSON.replace(' ', '-')}/notes.txt", f"token = {FAKE_SECRET}\n")
    result = sandbox.push()
    assert result.returncode != 0
    assert "<path hidden>" in result.stderr


def test_audit_as_private_withholds_paths(sandbox):
    sandbox.commit(f"{PERSON.replace(' ', '-')}.txt", f"token = {FAKE_SECRET}\n")
    result = sandbox.engine("audit", "--repo", str(sandbox.work), "--name", "x/y", "--as",
                            "private", "--rev", "HEAD")
    assert "fake-rule" in result.stdout
    assert PERSON.replace(" ", "-") not in result.stdout


# ------------------------------------------------------------------ gitleaks and reporting


def test_gitleaks_is_asked_to_redact(sandbox):
    """M28."""
    sandbox.commit("a.txt", "fine\n")
    sandbox.push()
    call = json.loads(sandbox.calls.read_text().splitlines()[-1])
    assert "--redact" in call["argv"]


def test_a_leak_reported_with_an_empty_list_blocks(sandbox):
    """M29."""
    sandbox.gitleaks.write_text(
        '#!/bin/sh\nwhile [ "$1" != "--report-path" ]; do shift; done\n'
        'printf "[]" > "$2"\nexit 7\n'
    )
    assert_blocked(sandbox.push(), sandbox, sandbox.head())


def test_findings_give_the_right_file_and_line(sandbox):
    """M26, M27."""
    sandbox.seed_public()
    sha = sandbox.commit("notes/a.txt", "one\ntwo\n" + f"three {PERSON}\n" + f"{FAKE_SECRET}\n")
    result = sandbox.push()
    assert_blocked(result, sandbox, sha)
    assert f"tier2a-people  commit {sha[:12]}  notes/a.txt:3" in result.stderr
    assert f"secret:fake-rule  commit {sha[:12]}  notes/a.txt:4" in result.stderr


def test_audit_runs_the_secret_scan(sandbox):
    """M16."""
    sandbox.commit("a.txt", f"token = {FAKE_SECRET}\n")
    result = sandbox.engine("audit", "--repo", str(sandbox.work), "--name", "x/y", "--as",
                            "private", "--rev", "HEAD")
    assert "secret:fake-rule" in result.stdout


def test_audit_applies_the_repository_policy(sandbox):
    """M77."""
    sandbox.policy["repos"][PUBLIC_NAME]["allowed_paths"] = ["README.md"]
    sandbox.save_policy()
    sandbox.commit("wiki/notes.md", "fine\n")
    result = sandbox.engine("audit", "--repo", str(sandbox.work), "--name", PUBLIC_NAME,
                            "--rev", "HEAD")
    assert "path-not-allowed" in result.stdout


# ------------------------------------------------------------------ topology and paths


@pytest.mark.parametrize(
    "line,blocks",
    [
        ("host " + ".".join(["10", "1", "2", "3"]), True),
        ("host " + ".".join(["172", "16", "0", "1"]), True),
        ("host " + ".".join(["172", "31", "255", "1"]), True),
        ("host " + ".".join(["172", "15", "0", "1"]), False),
        ("host " + ".".join(["172", "32", "0", "1"]), False),
        ("version " + ".".join(["10", "2", "3", "4", "5"]), False),
        ("scp " + "-P " + "2200 a b:", True),
        ("ssh" + "://backup:" + "2200/repo", True),
        ("  IdentityFile ~/.ssh/key", True),
        ("  ProxyJump jumphost", True),
    ],
)
def test_topology_boundaries(sandbox, line, blocks):
    """M33, M43, M50."""
    sandbox.seed_public()
    sha = sandbox.commit("a.txt", f"{line}\n")
    result = sandbox.push()
    if blocks:
        assert_blocked(result, sandbox, sha)
    else:
        assert_passed(result, sandbox, sha)


def test_topology_in_a_path_blocks(sandbox):
    """M34."""
    sandbox.seed_public()
    sha = sandbox.commit("hosts/" + ".".join(["10", "0", "0", "9"]) + ".md", "fine\n")
    assert_blocked(sandbox.push(), sandbox, sha)


def test_topology_warns_on_a_private_repository_that_may_go_public(sandbox):
    """M146."""
    sandbox.git("remote", "set-url", "origin", str(sandbox.private))
    sandbox.commit("a.txt", "host " + ".".join(["10", "1", "2", "3"]) + "\n")
    result = sandbox.push()
    assert result.returncode == 0
    assert "publish-guard: warning" in result.stderr


@pytest.mark.parametrize(
    "allowed,path,blocks",
    [
        (["README.md"], "README.md.bak", True),
        (["docs/*"], "docs/deep/a.md", True),
        (["docs/*"], "docs/a.md", False),
        ([], "README2.md", True),
    ],
)
def test_allowed_path_matching_is_exact(sandbox, allowed, path, blocks):
    """M23, M24, M25."""
    sandbox.policy["repos"][PUBLIC_NAME]["allowed_paths"] = allowed + ["README.md"] * (
        path != "README.md.bak" and allowed != []
    )
    sandbox.save_policy()
    subprocess.run(["git", "push", "-q", "--no-verify", "origin", "HEAD:refs/heads/main"],
                   cwd=sandbox.work, env=sandbox.env, check=True)
    sha = sandbox.commit(path, "fine\n")
    result = sandbox.push()
    if blocks:
        assert_blocked(result, sandbox, sha)
    else:
        assert_passed(result, sandbox, sha)


# ------------------------------------------------------------------ hand-over and stubs


def test_lfs_receives_the_exact_push_lines_and_its_failure_blocks(sandbox):
    """M05, M48."""
    fake = sandbox.root / "lfsbin"
    fake.mkdir()
    seen = sandbox.root / "lfs-seen.txt"
    lfs = fake / "git-lfs"
    lfs.write_text(f'#!/bin/sh\ncat > {seen}\nexit "${{LFS_EXIT:-0}}"\n')
    lfs.chmod(0o755)
    (sandbox.work / ".git" / "lfs").mkdir()
    sandbox.env["PATH"] = f"{fake}:{sandbox.env['PATH']}"
    sha = sandbox.head()
    assert_passed(sandbox.push(), sandbox, sha)
    assert seen.read_text().startswith(f"HEAD {sha} refs/heads/main ")
    sandbox.env["LFS_EXIT"] = "1"
    other = sandbox.commit("b.txt", "fine\n")
    result = sandbox.push()
    assert result.returncode != 0
    assert not sandbox.remote_has(other)


def test_local_destination_still_hands_over(sandbox):
    """M06."""
    seen = sandbox.root / "seen.txt"
    hook = sandbox.work / ".git" / "hooks" / "pre-push"
    hook.write_text(f"#!/bin/sh\ntouch {seen}\n")
    hook.chmod(0o755)
    backup = sandbox.new_bare("backup.git")
    assert_passed(sandbox.push(str(backup), "HEAD:refs/heads/main"), sandbox)
    assert seen.exists()


def test_every_documented_client_hook_has_a_pass_through_stub(sandbox):
    """M19: git's documented hooks, from githooks(5) for git 2.48."""
    documented = {
        "applypatch-msg", "pre-applypatch", "post-applypatch", "pre-commit", "pre-merge-commit",
        "prepare-commit-msg", "commit-msg", "post-commit", "pre-rebase", "post-checkout",
        "post-merge", "pre-push", "pre-receive", "update", "proc-receive", "post-receive",
        "post-update", "reference-transaction", "push-to-checkout", "pre-auto-gc",
        "post-rewrite", "sendemail-validate", "post-index-change", "p4-changelist",
        "p4-prepare-changelist", "p4-post-changelist", "p4-pre-submit",
    }
    installed = {p.name for p in (sandbox.guard / "hooks").iterdir()}
    assert documented <= installed


def test_stub_runs_python_isolated(sandbox):
    """M18."""
    assert " -I " in (sandbox.guard / "hooks" / "pre-push").read_text()


# ------------------------------------------------------------------ doctor tamper checks


def _doctor(sandbox, *extra):
    return sandbox.engine("doctor", "--test", *extra)


def _make_writable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IWUSR)


def test_doctor_finds_a_changed_engine(sandbox):
    """M10."""
    engine = sandbox.guard / "engine" / "publish_guard.py"
    _make_writable(engine)
    engine.write_text(engine.read_text() + "\n# changed\n")
    assert "engine" in _doctor(sandbox).stdout


def test_doctor_finds_a_changed_gitleaks(sandbox, tmp_path):
    """M11."""
    import hashlib

    digest = hashlib.sha256(sandbox.gitleaks.read_bytes()).hexdigest()
    hooks = sandbox.guard / "hooks"
    hooks.chmod(0o755)
    sandbox.install("--gitleaks-sha256", digest)
    assert _doctor(sandbox).returncode == 0
    sandbox.gitleaks.write_text(sandbox.gitleaks.read_text() + "\n# changed\n")
    assert "checksum" in _doctor(sandbox).stdout


def test_doctor_finds_a_writable_or_linked_stub(sandbox):
    """M12, M13."""
    hooks = sandbox.guard / "hooks"
    hooks.chmod(0o755)
    stub = hooks / "pre-commit"
    stub.chmod(0o755)
    assert "writable" in _doctor(sandbox).stdout
    text = stub.read_text()
    stub.unlink()
    real = sandbox.root / "elsewhere"
    real.write_text(text)
    stub.symlink_to(real)
    assert "isn't a real file" in _doctor(sandbox).stdout


def test_doctor_finds_a_missing_policy(sandbox):
    """M35."""
    (sandbox.guard / "policy.toml").unlink()
    result = _doctor(sandbox)
    assert result.returncode != 0
    assert "policy" in result.stdout


def test_doctor_scans_nested_repositories_and_worktrees(sandbox):
    """M14, M15, and the nested-repository probe."""
    deep = sandbox.root / "a" / "b" / "c"
    deep.mkdir(parents=True)
    sandbox.git("init", "-q", cwd=deep)
    sandbox.git("config", "--local", "core.hooksPath", "/dev/null", cwd=deep)
    nested = sandbox.work / "vendor" / "inner"
    nested.mkdir(parents=True)
    sandbox.git("init", "-q", cwd=nested)
    sandbox.git("config", "--local", "core.hooksPath", str(nested / ".git" / "hooks"), cwd=nested)
    worktree = sandbox.root / "wt"
    sandbox.git("worktree", "add", "-q", "-b", "wt-branch", str(worktree))
    sandbox.git("config", "extensions.worktreeConfig", "true")
    sandbox.git("config", "--worktree", "core.hooksPath", "/tmp/elsewhere", cwd=worktree)
    out = _doctor(sandbox, "--scan", str(sandbox.root)).stdout
    assert f"unguarded: hooks are off at {deep}" in out
    assert str(nested) in out
    assert str(worktree) in out


def test_install_activate_global_sets_the_global_hooks_path(sandbox):
    """M17."""
    subprocess.run(["git", "config", "--global", "--unset", "core.hooksPath"], env=sandbox.env,
                   check=True)
    hooks = sandbox.guard / "hooks"
    hooks.chmod(0o755)
    sandbox.install("--activate-global")
    value = subprocess.run(["git", "config", "--global", "--get", "core.hooksPath"],
                           env=sandbox.env, capture_output=True, text=True).stdout.strip()
    assert value == str(hooks)
    local = subprocess.run(["git", "config", "--local", "--get", "core.hooksPath"],
                           cwd=sandbox.work, env=sandbox.env, capture_output=True, text=True)
    assert local.stdout.strip() == ""


def test_the_echo_is_off_before_the_prompt_appears(sandbox):
    """The prompt used to print before echo went off, so a term typed early was shown."""
    from test_tools import _run_in_pty

    full = [sys.executable, "-I", str(ENGINE), "--home", str(sandbox.guard), "deny-check"]
    for _ in range(5):
        code, output = _run_in_pty(full, sandbox.env, sandbox.work, PERSON, prompt=b"Term")
        assert code == 0
        assert PERSON not in output
