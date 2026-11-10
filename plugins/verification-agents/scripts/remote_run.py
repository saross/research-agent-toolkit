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

- here: the script is inside a git repository; the branch has an upstream
  branch of the same remote for fetching and pushing; that remote is not a
  mirror; after a fetch, the branch is level with it (nothing unpushed,
  nothing to pull); and the working tree and index hold no change other
  than the script itself;
- there: the folder is a clone on the same branch, tracking the same
  branch name, at the same commit, with a clean working tree and index.

What it then does, checking each step:

1. commits the script alone (a commit limited to that path), and confirms
   the new commit has the starting commit as its only parent and changes
   that one file;
2. pushes that one commit, by its hash, to the one upstream branch;
3. there: fetches that branch, fast-forwards to exactly that commit, and
   runs the script with the given interpreter, from the clone's root;
4. there: confirms the clone is still on the same branch at the script
   commit, so that nobody else's commit has arrived meanwhile; reads the
   manifest the script wrote (`outputs.manifest` in the output folder: one
   path per line, relative to that folder); commits exactly those files and
   the manifest; and confirms the new commit has the script commit as its
   only parent and changes exactly those files;
5. there: pushes that one commit, by its hash, to the one upstream branch;
6. here: fetches that branch, confirms it is at exactly that commit, and
   fast-forwards to it.

**What is published.** Each push names one commit hash and one branch
(`git push REMOTE HASH:refs/heads/BRANCH`), so no other branch, tag, or
configured push rule takes part, and each commit's parent is checked first,
so the push adds that single commit and nothing behind it. Push hooks run
as usual.

**Where it is published.** A push to a remote goes to every push address
the remote has, after git's own address rewriting (`url.*.insteadOf` and
`pushInsteadOf`). The script asks git for the remote's effective addresses,
and requires exactly one, the same for fetching and pushing. It asks again
immediately before each push and stops if the answer has changed since the
start. It pushes to the remote by name, so the address git uses is the one
it reported. (Pushing to the reported address itself would be wrong: git
would apply its rewriting rules to it a second time.) Git's configuration
could still be changed in the instant between that last check and the push;
the script does not guard against that.

**Other writers.** The script does not lock either clone. It checks where
each clone is before and after every step that depends on it, so if another
writer commits or switches branch during the exchange, the next check fails
and the exchange stops before the next push. It reports success only after
confirming both clones are on the branch at the output commit; it cannot
promise to notice a writer who acts between its last check and its exit.

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


def run(argv: list[str], cwd: Path, raw: bool = False) -> str:
    """
    Run a command here and return its standard output.

    Args:
        argv: The command.
        cwd: Where to run it.
        raw: Return the output exactly as printed. Otherwise it is stripped
            of surrounding whitespace, which suits single values such as a
            hash but would damage output whose leading spaces carry meaning.

    Raises:
        Stop: If the command exits with an error; the message carries the
            command and what it printed.
    """
    done = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise Stop(f"`{shlex.join(argv)}` failed here:\n{(done.stderr or done.stdout).strip()}")
    return done.stdout if raw else done.stdout.strip()


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


def changed_paths(status: str) -> list[tuple[str, str]]:
    """
    Parse `git status --porcelain=v1 -z` into (state, path) pairs.

    With `-z`, entries end in a NUL and paths are given as they are, with no
    quoting, so a path with spaces or non-ASCII characters is read exactly.
    Each entry is two state characters, a space, and the path; a rename or
    copy is followed by one more entry holding the path it came from.

    Args:
        status: The command's output, unmodified.

    Returns:
        One pair per changed path. The source of a rename or copy is
        reported as a change of its own, with the state "from".
    """
    found: list[tuple[str, str]] = []
    entries = iter(status.split("\0"))
    for entry in entries:
        if not entry:
            continue
        state, path = entry[:2], entry[3:]
        found.append((state, path))
        if "R" in state or "C" in state:
            found.append(("from", next(entries, "")))
    return found


def other_changes(status: str, allowed: str) -> list[str]:
    """
    Return the changes in a repository other than the one allowed path.

    Args:
        status: Output of `git status --porcelain=v1 -z --untracked-files=all`.
        allowed: The one path, relative to the root, that may be changed.

    Returns:
        A line for every other changed path: its state and the path.
    """
    return [f"{state} {path}" for state, path in changed_paths(status) if path != allowed]


def upstream_of(branch: str, get) -> tuple[str, str, str]:
    """
    Return the remote, its one address, and the branch ref that a branch tracks.

    Args:
        branch: The local branch name.
        get: A function that runs a git command (as an argument list after
            `git`) in the clone and returns its stripped output.

    Returns:
        The remote's name, the single address it fetches from and pushes to,
        and the ref on it, such as `refs/heads/main`.

    Raises:
        Stop: If the branch tracks nothing or a local branch, or the remote
            is a mirror, or has more than one address for fetching or for
            pushing, or pushes somewhere other than it fetches from. A push
            to a remote goes to every push address it has, so a second one
            would receive the commits unchecked.
    """
    remote = get(["config", "--get", f"branch.{branch}.remote"])
    ref = get(["config", "--get", f"branch.{branch}.merge"])
    if not remote or remote == "." or not ref.startswith("refs/heads/"):
        raise Stop(f"branch {branch} does not track a branch on a remote")
    if get(["config", "--default", "false", "--get", f"remote.{remote}.mirror"]) == "true":
        raise Stop(f"remote {remote} is a mirror; refusing to push to it")
    fetch_urls = get(["remote", "get-url", "--all", remote]).splitlines()
    push_urls = get(["remote", "get-url", "--push", "--all", remote]).splitlines()
    if len(fetch_urls) != 1 or push_urls != fetch_urls:
        raise Stop(
            f"remote {remote} must have one address, used for both fetching and pushing; "
            f"it fetches from {fetch_urls} and pushes to {push_urls}"
        )
    return remote, fetch_urls[0], ref


def require_position(get, branch: str, commit: str, where: str, when: str) -> None:
    """
    Confirm a clone is on the given branch at exactly the given commit.

    Raises:
        Stop: If it is on another branch or at another commit, which means
            something else moved it.
    """
    at_branch = get(["symbolic-ref", "--short", "HEAD"])
    at_commit = get(["rev-parse", "HEAD"])
    if at_branch != branch or at_commit != commit:
        raise Stop(
            f"{where} is on {at_branch} at {at_commit[:12]} {when}, not on {branch} at "
            f"{commit[:12]}: something else changed it"
        )


def require_single_commit(get, commit: str, parent: str, paths: list[str], where: str) -> None:
    """
    Confirm a commit adds exactly the given paths on top of one given parent.

    Raises:
        Stop: If the commit has another parent, more than one, or changes
            any other path.
    """
    parents = get(["rev-list", "--parents", "-n", "1", commit]).split()[1:]
    if parents != [parent]:
        raise Stop(
            f"{where}: commit {commit[:12]} does not sit directly on {parent[:12]} "
            f"(its parents: {[p[:12] for p in parents]}); something else was committed meanwhile"
        )
    changed = sorted(p for p in get(
        ["diff", "--name-only", "-z", parent, commit]).split("\0") if p)
    if changed != sorted(paths):
        raise Stop(f"{where}: commit {commit[:12]} changes {changed}, expected {sorted(paths)}")


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


def transact(args: argparse.Namespace, progress: dict[str, str]) -> tuple[str, str]:
    """
    Carry out the exchange described in the module docstring.

    Args:
        args: The parsed command line.
        progress: Filled in as each step completes, so that a stop can
            report exactly what had been committed and pushed by then.

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

    def here(argv: list[str]) -> str:
        return run(["git", *argv], root)

    def there(argv: list[str]) -> str:
        return remote.run(["git", *argv])

    # ---- checks here ---------------------------------------------------------
    branch = here(["symbolic-ref", "--short", "HEAD"])
    origin, url, ref = upstream_of(branch, here)
    here(["fetch", "--quiet", origin, ref])
    head = here(["rev-parse", "HEAD"])
    if here(["rev-parse", "FETCH_HEAD"]) != head:
        raise Stop(
            f"branch {branch} is not level with {ref} on {origin} here: push or pull first, "
            "so that this run publishes nothing but its own two commits"
        )
    status = run(["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"], root, raw=True)
    extra = other_changes(status, script_rel)
    if extra:
        raise Stop(
            "the repository here has other changes; commit or set them aside first:\n"
            + "\n".join(extra)
        )
    if not changed_paths(status):
        raise Stop(f"{script_rel} has no change to commit; has this script already been run?")

    # ---- checks there --------------------------------------------------------
    if there(["symbolic-ref", "--short", "HEAD"]) != branch:
        raise Stop(f"the other clone is not on branch {branch}")
    there_origin, there_url, there_ref = upstream_of(branch, there)
    if there_ref != ref:
        raise Stop(f"the other clone's branch tracks {there_ref}, not {ref}")
    if there(["status", "--porcelain=v1", "--untracked-files=all"]):
        raise Stop("the other clone has uncommitted changes; nothing was committed")
    if there(["rev-parse", "HEAD"]) != head:
        raise Stop(f"the other clone is not at {head[:12]}, the commit this one is at")

    # ---- 1. commit the script alone ------------------------------------------
    here(["add", "--", script_rel])
    here(["commit", "--quiet", "-m", f"Add profile script {script_rel}", "--", script_rel])
    script_commit = here(["rev-parse", "HEAD"])
    progress["script commit (here, not yet pushed)"] = script_commit
    require_single_commit(here, script_commit, head, [script_rel], "here")

    # ---- 2. push that one commit to the one branch ---------------------------
    if upstream_of(branch, here) != (origin, url, ref):
        raise Stop("this clone's remote settings changed during the run; nothing was pushed")
    here(["push", "--quiet", "--no-follow-tags", origin, f"{script_commit}:{ref}"])
    del progress["script commit (here, not yet pushed)"]
    progress["script commit (pushed)"] = script_commit

    # ---- 3. run it there, at exactly that commit -----------------------------
    there(["fetch", "--quiet", there_origin, ref])
    if there(["rev-parse", "FETCH_HEAD"]) != script_commit:
        raise Stop(
            f"the other clone's remote does not hold the script commit {script_commit[:12]} "
            f"on {ref}: the two clones do not share a remote, or someone pushed meanwhile"
        )
    require_position(there, branch, head, "the other clone", "before taking the script")
    there(["merge", "--quiet", "--ff-only", script_commit])
    progress["script commit merged there (position not yet confirmed)"] = script_commit
    require_position(there, branch, script_commit, "the other clone", "before the run")
    del progress["script commit merged there (position not yet confirmed)"]
    remote.run([args.python, script_rel])

    # ---- 4. commit exactly the listed outputs there --------------------------
    require_position(there, branch, script_commit, "the other clone", "after the run")
    manifest_rel = f"{output_rel}/{MANIFEST}"
    listed = read_manifest(remote.run(["cat", "--", manifest_rel]))
    outputs = [f"{output_rel}/{path}" for path in listed if path != MANIFEST] + [manifest_rel]
    remote.run(["ls", "-d", "--", *outputs])  # fails if any listed file is missing
    there(["add", "--", *outputs])
    staged = sorted(p for p in there(["diff", "--cached", "--name-only", "-z"]).split("\0") if p)
    if staged != sorted(outputs):
        raise Stop(
            "what is staged in the other clone is not exactly the listed outputs; nothing was "
            f"committed there.\nstaged: {staged}\nlisted: {sorted(outputs)}"
        )
    there(["commit", "--quiet", "-m", f"Add profile outputs in {output_rel}", "--", *outputs])
    output_commit = there(["rev-parse", "HEAD"])
    progress["output commit (there, not yet pushed)"] = output_commit
    require_single_commit(there, output_commit, script_commit, outputs, "the other clone")

    # ---- 5. push that one commit to the one branch ---------------------------
    if upstream_of(branch, there) != (there_origin, there_url, ref):
        raise Stop(
            "the other clone's remote settings changed during the run; "
            "the outputs were not pushed"
        )
    there(["push", "--quiet", "--no-follow-tags", there_origin, f"{output_commit}:{ref}"])
    del progress["output commit (there, not yet pushed)"]
    progress["output commit (pushed)"] = output_commit

    # ---- 6. bring exactly that commit back -----------------------------------
    here(["fetch", "--quiet", origin, ref])
    if here(["rev-parse", "FETCH_HEAD"]) != output_commit:
        raise Stop(
            f"{ref} on {origin} is not at the output commit {output_commit[:12]}; "
            "someone pushed meanwhile, and nothing was merged here"
        )
    require_position(here, branch, script_commit, "this clone", "before taking the outputs")
    here(["merge", "--quiet", "--ff-only", output_commit])
    progress["output commit merged here (final position not yet confirmed)"] = output_commit
    require_position(here, branch, output_commit, "this clone", "after taking the outputs")
    require_position(there, branch, output_commit, "the other clone", "at the end")
    del progress["output commit merged here (final position not yet confirmed)"]
    progress["outputs merged here"] = output_commit
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
    progress: dict[str, str] = {}
    try:
        script_commit, output_commit = transact(args, progress)
    except Stop as stop:
        print(f"remote_run: stopped. {stop}", file=sys.stderr)
        if progress:
            print("Done before the stop:", file=sys.stderr)
            for step, commit in progress.items():
                print(f"  {step}: {commit}", file=sys.stderr)
        else:
            print("Nothing had been committed or pushed.", file=sys.stderr)
        print(
            "Nothing was switched, cleaned, reset, or force-pushed. Check `git status` and "
            "`git log -3` in both clones before trying again.",
            file=sys.stderr,
        )
        return 1
    print(f"script commit: {script_commit}")
    print(f"output commit: {output_commit}")
    print("Both clones were on the branch at the output commit when this finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
