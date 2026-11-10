"""
Tests for the remote-run transaction (scripts/remote_run.py).

The script commits and pushes in a user's repository on two machines, so
what matters most is what it refuses to do. Each test builds a real bare
repository with two clones in a temporary folder and runs the transaction
with `--runner local`, which treats the second clone as "the other machine".
No SSH, network, or real repository is involved.

The refusals pinned here are the ones a review reproduced or named: other
staged files riding along in the script commit, unpushed commits being
published, a remote clone on another branch or commit or with changes of its
own, and outputs that the manifest does not list or that climb out of the
output folder.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import remote_run  # noqa: E402

PROFILE = '''
from pathlib import Path
out = Path("runs/p1/out")
out.mkdir(parents=True, exist_ok=True)
(out / "summary.md").write_text("summary\\n")
(out / "tables").mkdir(exist_ok=True)
(out / "tables" / "a.csv").write_text("x\\n1\\n")
(out / "scratch.tmp").write_text("not listed\\n")
(out / "outputs.manifest").write_text({manifest!r})
'''
GOOD_MANIFEST = "summary.md\ntables/a.csv\n"


def git(cwd: Path, *argv: str) -> str:
    """Run git in a folder and return its output."""
    done = subprocess.run(["git", *argv], cwd=cwd, capture_output=True, text=True, check=True)
    return done.stdout.strip()


@pytest.fixture(autouse=True)
def identity(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Give git an identity and keep it away from the user's own configuration."""
    for name, value in {
        "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid",
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
        "HOME": str(tmp_path),
    }.items():
        monkeypatch.setenv(name, value)


@pytest.fixture
def clones(tmp_path: Path) -> tuple[Path, Path]:
    """A bare repository with one commit, cloned twice: here and there."""
    bare = tmp_path / "origin.git"
    git(tmp_path, "init", "--quiet", "--bare", "--initial-branch=main", str(bare))
    here, there = tmp_path / "here", tmp_path / "elsewhere" / "there"
    git(tmp_path, "clone", "--quiet", str(bare), str(here))
    (here / "README.md").write_text("project\n")
    git(here, "add", "README.md")
    git(here, "commit", "--quiet", "-m", "first")
    git(here, "push", "--quiet", "-u", "origin", "main")
    there.parent.mkdir()
    git(tmp_path, "clone", "--quiet", str(bare), str(there))
    return here, there


def write_script(here: Path, manifest: str = GOOD_MANIFEST, extra: str = "") -> Path:
    """Write the profile script into the first clone, uncommitted."""
    script = here / "runs" / "p1" / "code" / "profile.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(PROFILE.format(manifest=manifest) + extra)
    return script


def transact(here: Path, there: Path, script: Path) -> int:
    """Run the transaction between the two clones."""
    return remote_run.main([
        "--runner", "local", "--workdir", str(there), "--python", sys.executable,
        "--script", str(script), "--output-dir", str(here / "runs" / "p1" / "out"),
    ])


def test_the_script_goes_out_and_only_the_listed_outputs_come_back(
    clones: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    here, there = clones
    start = git(here, "rev-parse", "HEAD")
    assert transact(here, there, write_script(here)) == 0

    log = git(here, "log", "--format=%s", f"{start}..HEAD").splitlines()
    assert len(log) == 2  # exactly the script commit and the output commit
    script_commit, output_commit = git(here, "rev-parse", "HEAD~1"), git(here, "rev-parse", "HEAD")
    assert git(here, "diff", "--name-only", start, script_commit) == "runs/p1/code/profile.py"
    assert sorted(git(here, "diff", "--name-only", script_commit, output_commit).splitlines()) == [
        "runs/p1/out/outputs.manifest", "runs/p1/out/summary.md", "runs/p1/out/tables/a.csv",
    ]
    assert (here / "runs/p1/out/summary.md").read_text() == "summary\n"
    assert not (here / "runs/p1/out/scratch.tmp").exists()  # unlisted: never committed
    out = capsys.readouterr().out
    assert script_commit in out and output_commit in out
    assert git(here, "rev-parse", "origin/main") == output_commit


def test_a_file_staged_beforehand_stops_everything(clones: tuple[Path, Path]) -> None:
    """The reproduced fault: `git commit` would have taken unrelated.txt too."""
    here, there = clones
    script = write_script(here)
    (here / "unrelated.txt").write_text("private\n")
    git(here, "add", "unrelated.txt")
    start = git(here, "rev-parse", "HEAD")
    assert transact(here, there, script) == 1
    assert git(here, "rev-parse", "HEAD") == start
    assert git(here, "rev-parse", "origin/main") == start
    assert "unrelated.txt" in git(here, "diff", "--cached", "--name-only")  # left as it was


def test_an_untracked_or_modified_file_elsewhere_stops_everything(
    clones: tuple[Path, Path]
) -> None:
    here, there = clones
    script = write_script(here)
    (here / "README.md").write_text("edited\n")
    start = git(here, "rev-parse", "HEAD")
    assert transact(here, there, script) == 1
    assert git(here, "rev-parse", "HEAD") == start


def test_an_unpushed_commit_here_stops_everything(clones: tuple[Path, Path]) -> None:
    """A plain push would have published it along with the script."""
    here, there = clones
    (here / "draft.md").write_text("not ready\n")
    git(here, "add", "draft.md")
    git(here, "commit", "--quiet", "-m", "local only")
    script = write_script(here)
    origin = git(here, "rev-parse", "origin/main")
    assert transact(here, there, script) == 1
    assert git(here, "rev-parse", "origin/main") == origin
    assert git(here, "ls-remote", "origin", "main").split()[0] == origin


@pytest.mark.parametrize("fault", ["branch", "dirty", "behind"])
def test_a_remote_clone_in_the_wrong_state_stops_before_any_commit(
    clones: tuple[Path, Path], fault: str
) -> None:
    here, there = clones
    if fault == "branch":
        git(there, "checkout", "--quiet", "-b", "other")
    elif fault == "dirty":
        (there / "notes.txt").write_text("left over\n")
    else:
        (here / "more.md").write_text("more\n")
        git(here, "add", "more.md")
        git(here, "commit", "--quiet", "-m", "second")
        git(here, "push", "--quiet")
    script = write_script(here)
    start = git(here, "rev-parse", "HEAD")
    assert transact(here, there, script) == 1
    assert git(here, "rev-parse", "HEAD") == start  # no script commit was made
    status = git(here, "status", "--porcelain", "--untracked-files=all")
    assert status.strip().endswith("profile.py")


@pytest.mark.parametrize("manifest", ["../../../README.md\n", "/etc/passwd\n", "", "missing.md\n",
                                      "--force\n"])
def test_a_bad_manifest_commits_no_outputs(clones: tuple[Path, Path], manifest: str) -> None:
    here, there = clones
    assert transact(here, there, write_script(here, manifest)) == 1
    # The script commit went out, as it must before the script can run there;
    # no output commit followed it on either side.
    assert git(there, "log", "--format=%s", "-1") == "Add profile script runs/p1/code/profile.py"
    assert git(here, "ls-remote", "origin", "main").split()[0] == git(here, "rev-parse", "HEAD")


def test_a_script_outside_the_repository_is_refused(
    clones: tuple[Path, Path], tmp_path: Path
) -> None:
    here, there = clones
    outside = tmp_path / "loose.py"
    outside.write_text("print('x')\n")
    assert transact(here, there, outside) == 1


def test_helpers_for_status_and_manifest() -> None:
    status = " M README.md\0?? runs/p1/code/profile.py\0A  staged.txt\0R  new name.md\0old.md\0"
    assert remote_run.other_changes(status, "runs/p1/code/profile.py") == [
        " M README.md", "A  staged.txt", "R  new name.md", "from old.md",
    ]
    # A sole modified, tracked script: its leading space must survive.
    assert remote_run.other_changes(" M runs/p1/code/profile.py\0", "runs/p1/code/profile.py") == []
    assert remote_run.read_manifest("a.md\n\n a.md \ntables/b.csv\n") == ["a.md", "tables/b.csv"]
    with pytest.raises(remote_run.Stop):
        remote_run.read_manifest("ok.md\nsub/../../escape\n")


def test_ssh_needs_a_host_that_is_not_an_option(capsys: pytest.CaptureFixture[str]) -> None:
    base = ["--workdir", "/w", "--python", "python3", "--script", "s.py", "--output-dir", "o"]
    for host in ([], ["--host", "-oProxyCommand=x"]):
        with pytest.raises(SystemExit) as stop:
            remote_run.main([*host, *base])
        assert stop.value.code == 2


# ---------------------------------------------------------------------------
# Second review round: what a push may carry, and who else may be writing
# ---------------------------------------------------------------------------


def origin_refs(clone: Path) -> dict[str, str]:
    """Return every ref the shared remote holds, by name."""
    lines = git(clone, "ls-remote", "origin").splitlines()
    return {name: commit for commit, name in (line.split("\t") for line in lines)}


def test_a_configured_push_rule_cannot_publish_another_branch(clones: tuple[Path, Path]) -> None:
    """`remote.origin.push` naming a side branch used to ride along on a plain push."""
    here, there = clones
    git(here, "checkout", "--quiet", "-b", "side")
    (here / "private.txt").write_text("not for publication\n")
    git(here, "add", "private.txt")
    git(here, "commit", "--quiet", "-m", "side work")
    git(here, "checkout", "--quiet", "main")
    git(here, "config", "remote.origin.push", "refs/heads/side:refs/heads/side")

    assert transact(here, there, write_script(here)) == 0
    refs = origin_refs(here)
    assert "refs/heads/side" not in refs
    assert set(refs) == {"HEAD", "refs/heads/main"}


def test_a_tag_is_not_pushed_along(clones: tuple[Path, Path]) -> None:
    here, there = clones
    git(here, "tag", "-a", "draft-1", "-m", "local tag")
    git(here, "config", "push.followTags", "true")
    assert transact(here, there, write_script(here)) == 0
    assert not any(name.startswith("refs/tags/") for name in origin_refs(here))


@pytest.mark.parametrize("fault", ["push-url", "mirror", "no-upstream"])
def test_an_unsafe_remote_set_up_stops_before_any_commit(
    clones: tuple[Path, Path], tmp_path: Path, fault: str
) -> None:
    here, there = clones
    if fault == "push-url":
        elsewhere = tmp_path / "elsewhere.git"
        git(tmp_path, "init", "--quiet", "--bare", str(elsewhere))
        git(here, "remote", "set-url", "--push", "origin", str(elsewhere))
    elif fault == "mirror":
        git(here, "config", "remote.origin.mirror", "true")
    else:
        git(here, "branch", "--unset-upstream")
    start = git(here, "rev-parse", "HEAD")
    assert transact(here, there, write_script(here)) == 1
    assert git(here, "rev-parse", "HEAD") == start


def test_a_commit_made_in_the_other_clone_during_the_run_stops_the_exchange(
    clones: tuple[Path, Path], capfd: pytest.CaptureFixture[str]
) -> None:
    """A second writer commits while the script runs; its work must not be pushed."""
    here, there = clones
    interfere = (
        "import subprocess\n"
        "Path('intruder.txt').write_text('someone else\\n')\n"
        "subprocess.run(['git', 'add', 'intruder.txt'], check=True)\n"
        "subprocess.run(['git', 'commit', '--quiet', '-m', 'unrelated'], check=True)\n"
    )
    script = write_script(here, extra=interfere)
    assert transact(here, there, script) == 1
    script_commit = git(here, "rev-parse", "HEAD")
    # The remote branch holds the script commit and nothing after it.
    assert origin_refs(here)["refs/heads/main"] == script_commit
    assert not (here / "intruder.txt").exists()
    err = capfd.readouterr().err
    assert "after the run" in err and "something else changed it" in err
    assert f"script commit (pushed): {script_commit}" in err
    assert "output commit" not in err


def test_a_push_by_someone_else_before_the_outputs_return_is_not_merged(
    clones: tuple[Path, Path], tmp_path: Path
) -> None:
    """If the branch moves on the remote after the outputs, nothing extra is merged here."""
    here, there = clones
    third = tmp_path / "third"
    bare = git(here, "remote", "get-url", "origin")
    # The script, running in the other clone, has a third clone push a commit
    # that lands on top of the script commit before the outputs are pushed.
    interfere = (
        "import subprocess\n"
        f"subprocess.run(['git', 'clone', '--quiet', {bare!r}, {str(third)!r}], check=True)\n"
        f"(Path({str(third)!r}) / 'late.txt').write_text('late\\n')\n"
        f"subprocess.run(['git', 'add', 'late.txt'], cwd={str(third)!r}, check=True)\n"
        f"subprocess.run(['git', 'commit', '--quiet', '-m', 'late'], cwd={str(third)!r},"
        " check=True)\n"
        f"subprocess.run(['git', 'push', '--quiet'], cwd={str(third)!r}, check=True)\n"
    )
    assert transact(here, there, write_script(here, extra=interfere)) == 1
    assert not (here / "late.txt").exists()
    assert not (here / "runs/p1/out/summary.md").exists()  # the outputs were never pushed


def test_a_tracked_script_that_was_only_modified_is_accepted(clones: tuple[Path, Path]) -> None:
    """Review finding R19: revising a script that is already committed."""
    here, there = clones
    assert transact(here, there, write_script(here)) == 0
    script = write_script(here, manifest="summary.md\n", extra="# revised\n")
    (here / "runs/p1/out/summary.md").unlink()  # make the rerun's output differ
    git(here, "commit", "--quiet", "-am", "clear old output")
    git(here, "push", "--quiet")
    git(there, "pull", "--quiet", "--ff-only")
    # The first run left an unlisted file in the other clone, which would
    # rightly stop the next run; a careful script lists everything it writes.
    (there / "runs/p1/out/scratch.tmp").unlink()
    script.write_text(script.read_text().replace('"summary\\n"', '"summary, revised\\n"'))
    # Modified, tracked, unstaged: " M path" (the helper strips the leading space).
    assert git(here, "status", "--porcelain") == "M runs/p1/code/profile.py"
    assert transact(here, there, script) == 0
    assert (here / "runs/p1/out/summary.md").read_text() == "summary, revised\n"


def test_paths_with_spaces_and_non_ascii_characters_work(clones: tuple[Path, Path]) -> None:
    here, there = clones
    script = here / "runs" / "p1" / "code" / "profil \u00e9t\u00e9.py"
    script.parent.mkdir(parents=True)
    script.write_text(PROFILE.format(manifest="summary.md\n"))
    assert transact(here, there, script) == 0
    assert (here / "runs/p1/out/summary.md").exists()


def test_a_stop_before_any_commit_says_nothing_was_committed(
    clones: tuple[Path, Path], capfd: pytest.CaptureFixture[str]
) -> None:
    here, there = clones
    (there / "notes.txt").write_text("left over\n")
    assert transact(here, there, write_script(here)) == 1
    assert "Nothing had been committed or pushed." in capfd.readouterr().err


# ---------------------------------------------------------------------------
# Third review round: every destination, and where each clone ends up
# ---------------------------------------------------------------------------


def is_empty(bare: Path) -> bool:
    """Report whether a bare repository holds no refs at all."""
    return git(bare, "for-each-ref") == ""


@pytest.mark.parametrize("clone_with_extra", ["here", "there"])
def test_a_second_push_address_is_refused_and_receives_nothing(
    clones: tuple[Path, Path], tmp_path: Path, clone_with_extra: str
) -> None:
    """A push to a remote goes to every push address; the first one matching is not enough."""
    here, there = clones
    extra = tmp_path / "extra.git"
    git(tmp_path, "init", "--quiet", "--bare", str(extra))
    clone = here if clone_with_extra == "here" else there
    first = git(clone, "remote", "get-url", "origin")
    git(clone, "remote", "set-url", "--add", "--push", "origin", first)
    git(clone, "remote", "set-url", "--add", "--push", "origin", str(extra))
    # Asked for one push address, git gives the first, which hides the second.
    assert git(clone, "remote", "get-url", "--push", "origin") == first

    start = git(here, "rev-parse", "HEAD")
    assert transact(here, there, write_script(here)) == 1
    assert git(here, "rev-parse", "HEAD") == start  # stopped before the script commit
    assert is_empty(extra)


def test_a_commit_made_here_during_the_run_is_noticed_before_the_outputs_are_taken(
    clones: tuple[Path, Path], capfd: pytest.CaptureFixture[str]
) -> None:
    """A second writer moves this clone on; success must not be claimed."""
    here, there = clones
    interfere = (
        "import subprocess\n"
        f"HERE = {str(here)!r}\n"
        "(Path(HERE) / 'meanwhile.txt').write_text('other work\\n')\n"
        "subprocess.run(['git', 'add', 'meanwhile.txt'], cwd=HERE, check=True)\n"
        "subprocess.run(['git', 'commit', '--quiet', '-m', 'meanwhile'], cwd=HERE, check=True)\n"
    )
    assert transact(here, there, write_script(here, extra=interfere)) == 1
    captured = capfd.readouterr()
    assert "before taking the outputs" in captured.err
    assert "output commit (pushed)" in captured.err  # what really happened is reported
    assert "outputs merged here" not in captured.err
    assert "output commit:" not in captured.out


def test_success_is_reported_only_with_both_clones_at_the_output_commit(
    clones: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    here, there = clones
    assert transact(here, there, write_script(here)) == 0
    assert git(here, "rev-parse", "HEAD") == git(there, "rev-parse", "HEAD")
    assert "Both clones were on the branch at the output commit" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Fourth review round: git's own address rewriting
# ---------------------------------------------------------------------------


def test_address_rewriting_cannot_send_a_push_somewhere_else(
    clones: tuple[Path, Path], tmp_path: Path
) -> None:
    """A `pushInsteadOf` rule keyed on the expanded address must not be applied to it.

    The remote is an alias that `insteadOf` expands to the real address; a
    `pushInsteadOf` rule would rewrite that real address to another
    repository if it were pushed to directly. Pushing to the remote by name
    uses the address git reports, and the other repository gets nothing.
    """
    here, there = clones
    real = git(here, "remote", "get-url", "origin")
    other = tmp_path / "other.git"
    git(tmp_path, "init", "--quiet", "--bare", str(other))
    git(here, "config", "remote.origin.url", "fixture-alias:")
    git(here, "config", f"url.{real}.insteadOf", "fixture-alias:")
    git(here, "config", f"url.{other}.pushInsteadOf", real)
    assert git(here, "remote", "get-url", "--push", "--all", "origin") == real

    assert transact(here, there, write_script(here)) == 0
    assert is_empty(other)
    assert origin_refs(there)["refs/heads/main"] == git(here, "rev-parse", "HEAD")


def test_a_push_rewrite_that_changes_the_destination_is_refused(
    clones: tuple[Path, Path], tmp_path: Path
) -> None:
    """A rule that does redirect pushes shows in the effective address, and stops the run."""
    here, there = clones
    real = git(here, "remote", "get-url", "origin")
    other = tmp_path / "other.git"
    git(tmp_path, "init", "--quiet", "--bare", str(other))
    git(here, "config", f"url.{other}.pushInsteadOf", real)
    start = git(here, "rev-parse", "HEAD")
    assert transact(here, there, write_script(here)) == 1
    assert git(here, "rev-parse", "HEAD") == start and is_empty(other)


def test_remote_settings_changed_during_the_run_stop_the_output_push(
    clones: tuple[Path, Path], tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    """The script (standing in for anyone) adds a push address in the other clone mid-run."""
    here, there = clones
    extra = tmp_path / "extra.git"
    git(tmp_path, "init", "--quiet", "--bare", str(extra))
    interfere = (
        "import subprocess\n"
        f"subprocess.run(['git', 'remote', 'set-url', '--add', '--push', 'origin', {str(extra)!r}],"
        " check=True)\n"
    )
    assert transact(here, there, write_script(here, extra=interfere)) == 1
    assert is_empty(extra)
    err = capfd.readouterr().err
    assert "must have one address" in err  # found by the check made just before the push
    assert "output commit (there, not yet pushed)" in err
