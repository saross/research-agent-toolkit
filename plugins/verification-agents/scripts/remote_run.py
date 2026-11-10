#!/usr/bin/env python3
"""
remote_run.py
=============

Run a dataset-profile script on another machine, with git as the transport.

The dataset profiler can be asked to run its Python somewhere else, for
example on a machine with more memory. The script travels there, and its
outputs travel back, as commits in the user's own repository: nothing is
copied with rsync or scp, so the research record stays in one place.

That means committing and pushing in someone's repository, twice, on two
machines. Done loosely, it can publish files nobody meant to publish: a plain
`git commit` takes everything already staged, and a plain `git push` takes
every earlier commit that was never pushed. This script does the whole
exchange as one checked transaction, and stops, changing nothing further, at
the first thing that isn't as expected. It never switches branch, cleans,
resets, rebases, or force-pushes, on either machine.

What it checks before it changes anything:

- here: the script is inside a git repository; the branch has an upstream;
  after a fetch, the branch is level with it (nothing unpushed, nothing to
  pull); and the working tree and index hold no change other than the
  script itself;
- there: the folder is a clone of a repository on the same branch, at the
  same commit, with a clean working tree and index.

What it then does, checking each step:

1. commits the script alone (a commit limited to that path) and pushes it;
2. there: fast-forwards, confirms the clone is at exactly that commit, and
   runs the script with the given interpreter, from the clone's root;
3. there: reads the manifest the script wrote (`outputs.manifest` in the
   output folder: one path per line, relative to that folder), confirms
   every listed file exists inside the output folder, commits exactly those
   files and the manifest, and pushes;
4. here: fast-forwards and confirms the branch is at exactly the commit
   made in step 3.

It prints the two commit hashes. Paths are worked out relative to each
clone's root, so the two clones may live in different places.

The remote side is reached with `ssh HOST`, each command a single quoted
string. `--runner local` treats `--workdir` as a second clone on this
machine instead; it exists so the transaction can be tested without SSH.

Uses the standard library only.

Usage:
    python3 remote_run.py --host HOST --workdir REMOTE_CLONE \\
        --python REMOTE_PYTHON --script LOCAL_SCRIPT --output-dir LOCAL_OUTPUT_DIR

Exit status: 0 when the outputs are back and both commits verified; 1 when a
check failed or a step did not do what was expected (the message says which,
and what state things were left in); 2 for a usage error.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path, PurePosixPath

MANIFEST = "outputs.manifest"


class Stop(Exception):
    """A check failed; the message says what, and nothing more is attempted."""


def run(argv: list[str], cwd: Path) -> str:
    """
    Run a command here and return its standard output, stripped.

    Raises:
        Stop: If the command exits with an error; the message carries the
            command and what it printed.
    """
    done = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise Stop(f"`{shlex.join(argv)}` failed here:\n{(done.stderr or done.stdout).strip()}")
    return done.stdout.strip()


class Remote:
    """The other clone: reached over SSH, or a local folder when testing."""

    def __init__(self, runner: str, host: str, workdir: str) -> None:
        self.runner, self.host, self.workdir = runner, host, workdir

    def run(self, argv: list[str]) -> str:
        """
        Run a command in the other clone's root and return its output.

        Every argument is quoted, so no value can be read as shell syntax
        on the other machine.

        Raises:
            Stop: If the command exits with an error.
        """
        if self.runner == "local":
            return run(argv, Path(self.workdir))
        line = f"cd {shlex.quote(self.workdir)} && {shlex.join(argv)}"
        done = subprocess.run(
            ["ssh", "--", self.host, line], capture_output=True, text=True, check=False
        )
        if done.returncode != 0:
            raise Stop(
                f"`{shlex.join(argv)}` failed on {self.host}:\n"
                f"{(done.stderr or done.stdout).strip()}"
            )
        return done.stdout.strip()


def relative_to_root(path: Path, root: Path, what: str) -> str:
    """
    Return a path relative to the repository root, in POSIX form.

    Raises:
        Stop: If the path is not inside the repository.
    """
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise Stop(f"the {what} ({path}) is not inside the repository at {root}") from error


def other_changes(status: str, allowed: str) -> list[str]:
    """
    Return the lines of `git status --porcelain` that are not the allowed path.

    Args:
        status: Output of `git status --porcelain --untracked-files=all`.
        allowed: The one path, relative to the root, that may be changed.

    Returns:
        The status lines for every other path.
    """
    return [line for line in status.splitlines() if line.strip() and line[3:] != allowed]


def read_manifest(text: str) -> list[str]:
    """
    Return the output paths a manifest lists, checked for safety.

    Args:
        text: The manifest's contents: one path per line, relative to the
            output folder.

    Returns:
        The paths, in order, without repeats.

    Raises:
        Stop: If the manifest is empty, or a path is absolute, climbs out of
            the output folder, or is the manifest itself written oddly.
    """
    paths: list[str] = []
    for line in text.splitlines():
        entry = line.strip()
        if not entry:
            continue
        pure = PurePosixPath(entry)
        if pure.is_absolute() or ".." in pure.parts or entry.startswith("-"):
            raise Stop(f"the manifest lists a path outside the output folder: {entry!r}")
        if pure.as_posix() not in paths:
            paths.append(pure.as_posix())
    if not paths:
        raise Stop("the manifest lists no output files")
    return paths


def transact(args: argparse.Namespace) -> tuple[str, str]:
    """
    Carry out the exchange described in the module docstring.

    Returns:
        The script commit and the output commit.

    Raises:
        Stop: At the first check or step that fails.
    """
    script = Path(args.script).resolve()
    if not script.is_file():
        raise Stop(f"no such script: {script}")
    root = Path(run(["git", "rev-parse", "--show-toplevel"], script.parent))
    script_rel = relative_to_root(script, root, "script")
    output_rel = relative_to_root(Path(args.output_dir), root, "output folder")
    remote = Remote(args.runner, args.host, args.workdir)

    # ---- checks here ---------------------------------------------------------
    branch = run(["git", "symbolic-ref", "--short", "HEAD"], root)
    upstream = run(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], root)
    run(["git", "fetch", "--quiet"], root)
    head = run(["git", "rev-parse", "HEAD"], root)
    if run(["git", "rev-parse", "@{u}"], root) != head:
        raise Stop(
            f"branch {branch} is not level with {upstream} here: push or pull first, so that "
            "this run publishes nothing but its own two commits"
        )
    status = run(["git", "status", "--porcelain", "--untracked-files=all"], root)
    extra = other_changes(status, script_rel)
    if extra:
        raise Stop(
            "the repository here has other changes; commit or set them aside first:\n"
            + "\n".join(extra)
        )
    if not status.strip():
        raise Stop(f"{script_rel} has no change to commit; has this script already been run?")

    # ---- checks there --------------------------------------------------------
    there_branch = remote.run(["git", "symbolic-ref", "--short", "HEAD"])
    if there_branch != branch:
        raise Stop(f"the other clone is on branch {there_branch}, not {branch}")
    there_status = remote.run(["git", "status", "--porcelain", "--untracked-files=all"])
    if there_status.strip():
        raise Stop("the other clone has uncommitted changes:\n" + there_status)
    if remote.run(["git", "rev-parse", "HEAD"]) != head:
        raise Stop(f"the other clone is not at {head[:12]}, the commit this one is at")

    # ---- 1. commit the script alone, and push --------------------------------
    run(["git", "add", "--", script_rel], root)
    run(["git", "commit", "--quiet", "-m", f"Add profile script {script_rel}", "--", script_rel],
        root)
    script_commit = run(["git", "rev-parse", "HEAD"], root)
    changed = run(["git", "diff", "--name-only", head, script_commit], root).splitlines()
    if changed != [script_rel]:
        raise Stop(f"the script commit {script_commit[:12]} holds more than the script: {changed}")
    run(["git", "push", "--quiet"], root)

    # ---- 2. run it there, at exactly that commit -----------------------------
    remote.run(["git", "pull", "--quiet", "--ff-only"])
    if remote.run(["git", "rev-parse", "HEAD"]) != script_commit:
        raise Stop(f"the other clone did not arrive at the script commit {script_commit[:12]}")
    remote.run([args.python, script_rel])

    # ---- 3. commit exactly the listed outputs there, and push ----------------
    manifest_rel = f"{output_rel}/{MANIFEST}"
    listed = read_manifest(remote.run(["cat", "--", manifest_rel]))
    outputs = [f"{output_rel}/{path}" for path in listed if path != MANIFEST] + [manifest_rel]
    remote.run(["ls", "-d", "--", *outputs])  # fails if any listed file is missing
    remote.run(["git", "add", "--", *outputs])
    staged = sorted(remote.run(["git", "diff", "--cached", "--name-only"]).splitlines())
    if staged != sorted(outputs):
        raise Stop(
            "what is staged in the other clone is not exactly the listed outputs; nothing was "
            f"committed there.\nstaged: {staged}\nlisted: {sorted(outputs)}"
        )
    remote.run(["git", "commit", "--quiet", "-m", f"Add profile outputs in {output_rel}",
                "--", *outputs])
    output_commit = remote.run(["git", "rev-parse", "HEAD"])
    remote.run(["git", "push", "--quiet"])

    # ---- 4. bring the outputs back -------------------------------------------
    run(["git", "pull", "--quiet", "--ff-only"], root)
    if run(["git", "rev-parse", "HEAD"], root) != output_commit:
        raise Stop(f"this clone did not arrive at the output commit {output_commit[:12]}")
    return script_commit, output_commit


def main(argv: list[str] | None = None) -> int:
    """Parse the arguments, run the exchange, and report the two commits."""
    parser = argparse.ArgumentParser(description="Run a profile script on another machine.")
    parser.add_argument("--host", default="", help="SSH host of the other machine.")
    parser.add_argument("--workdir", required=True, help="The repository's clone there.")
    parser.add_argument("--python", required=True, help="Python interpreter to use there.")
    parser.add_argument("--script", required=True, help="The script, in this clone.")
    parser.add_argument("--output-dir", required=True, help="The output folder, in this clone.")
    parser.add_argument("--runner", choices=("ssh", "local"), default="ssh",
                        help="`local` treats --workdir as a clone on this machine (for tests).")
    args = parser.parse_args(argv)
    if args.runner == "ssh" and (not args.host or args.host.startswith("-")):
        parser.error("--host is required, and may not begin with a dash")
    try:
        script_commit, output_commit = transact(args)
    except Stop as stop:
        print(f"remote_run: stopped. {stop}", file=sys.stderr)
        print(
            "Nothing was switched, cleaned, reset, or force-pushed. Check `git status` and "
            "`git log -3` in both clones before trying again.",
            file=sys.stderr,
        )
        return 1
    print(f"script commit: {script_commit}")
    print(f"output commit: {output_commit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
