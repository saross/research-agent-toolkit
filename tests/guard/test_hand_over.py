"""The guard must not break the hooks a repository already relies on."""

from __future__ import annotations

from conftest import PERSON, assert_blocked, assert_passed


def _local_hook(sandbox, name, body, repo=None):
    hook = (repo or sandbox.work) / ".git" / "hooks" / name
    hook.parent.mkdir(exist_ok=True)
    hook.write_text("#!/bin/sh\n" + body)
    hook.chmod(0o755)
    return hook


def test_repository_pre_push_runs_after_the_guard_with_the_same_input(sandbox):
    seen = sandbox.root / "seen.txt"
    _local_hook(sandbox, "pre-push", f'echo "$1 $2" > {seen}\ncat >> {seen}\nexit 0\n')
    sha = sandbox.head()
    assert_passed(sandbox.push(), sandbox, sha)
    text = seen.read_text()
    assert str(sandbox.public) in text
    assert f"{sha} " in text


def test_failing_repository_hook_still_blocks_the_push(sandbox):
    _local_hook(sandbox, "pre-push", "exit 1\n")
    result = sandbox.push()
    assert result.returncode != 0
    assert not sandbox.remote_has(sandbox.head())


def test_guard_runs_before_the_repository_hook(sandbox):
    ran = sandbox.root / "ran.txt"
    _local_hook(sandbox, "pre-push", f"touch {ran}\nexit 0\n")
    sha = sandbox.commit("a.txt", f"{PERSON}\n")
    assert_blocked(sandbox.push(), sandbox, sha)
    assert not ran.exists()


def test_other_hooks_still_run_through_the_global_folder(sandbox):
    _local_hook(sandbox, "pre-commit", "echo refused >&2\nexit 1\n")
    (sandbox.work / "b.txt").write_text("x\n")
    sandbox.git("add", "b.txt")
    result = sandbox.git("commit", "-m", "x", check=False)
    assert result.returncode != 0
    assert "refused" in result.stderr


def test_post_commit_hook_receives_control(sandbox):
    ran = sandbox.root / "post.txt"
    _local_hook(sandbox, "post-commit", f"touch {ran}\n")
    sandbox.commit("b.txt", "x\n")
    assert ran.exists()


def test_commit_works_when_a_repository_has_no_hooks(sandbox):
    sha = sandbox.commit("b.txt", "x\n")
    assert len(sha) == 40


def test_linked_worktree_finds_the_shared_hook_and_is_scanned(sandbox):
    seen = sandbox.root / "seen.txt"
    _local_hook(sandbox, "pre-push", f"touch {seen}\n")
    worktree = sandbox.root / "wt"
    sandbox.git("worktree", "add", "-q", "-b", "wt-branch", str(worktree))
    (worktree / "w.txt").write_text("fine\n")
    sandbox.git("add", "w.txt", cwd=worktree)
    sandbox.git("commit", "-q", "-m", "wt", cwd=worktree)
    assert_passed(sandbox.push("origin", "HEAD:refs/heads/wt", cwd=worktree), sandbox)
    assert seen.exists()
    (worktree / "x.txt").write_text(f"{PERSON}\n")
    sandbox.git("add", "x.txt", cwd=worktree)
    sandbox.git("commit", "-q", "-m", "wt2", cwd=worktree)
    assert_blocked(sandbox.push("origin", "HEAD:refs/heads/wt", cwd=worktree), sandbox)


def test_no_hand_over_flag_skips_repository_hooks(sandbox):
    ran = sandbox.root / "ran.txt"
    _local_hook(sandbox, "pre-push", f"touch {ran}\nexit 1\n")
    sandbox.install("--no-hand-over")
    assert_passed(sandbox.push(), sandbox)
    assert not ran.exists()


def test_lfs_repository_without_a_local_hook_calls_lfs_directly(sandbox):
    fake_bin = sandbox.root / "fakebin"
    fake_bin.mkdir()
    marker = sandbox.root / "lfs.txt"
    lfs = fake_bin / "git-lfs"
    lfs.write_text(f'#!/bin/sh\necho "$@" > {marker}\ncat >> {marker}\nexit 0\n')
    lfs.chmod(0o755)
    (sandbox.work / ".git" / "lfs").mkdir()
    sandbox.env["PATH"] = f"{fake_bin}:{sandbox.env['PATH']}"
    assert_passed(sandbox.push(), sandbox)
    assert "pre-push" in marker.read_text()
