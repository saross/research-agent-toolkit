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


def write_script(here: Path, manifest: str = GOOD_MANIFEST) -> Path:
    """Write the profile script into the first clone, uncommitted."""
    script = here / "runs" / "p1" / "code" / "profile.py"
    script.parent.mkdir(parents=True)
    script.write_text(PROFILE.format(manifest=manifest))
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
    status = " M README.md\n?? runs/p1/code/profile.py\nA  staged.txt\n"
    assert remote_run.other_changes(status, "runs/p1/code/profile.py") == [
        " M README.md", "A  staged.txt",
    ]
    assert remote_run.read_manifest("a.md\n\n a.md \ntables/b.csv\n") == ["a.md", "tables/b.csv"]
    with pytest.raises(remote_run.Stop):
        remote_run.read_manifest("ok.md\nsub/../../escape\n")


def test_ssh_needs_a_host_that_is_not_an_option(capsys: pytest.CaptureFixture[str]) -> None:
    base = ["--workdir", "/w", "--python", "python3", "--script", "s.py", "--output-dir", "o"]
    for host in ([], ["--host", "-oProxyCommand=x"]):
        with pytest.raises(SystemExit) as stop:
            remote_run.main([*host, *base])
        assert stop.value.code == 2
