"""Shared fixtures for the publish guard tests.

Every test builds a throwaway world: its own HOME, git configuration, guard folder, a fake
`gitleaks`, and bare repositories standing in for GitHub. Pushes are real `git push` commands, so
the tests exercise what git actually does with the installed hooks.

Literals that the guard itself would block (private addresses, SSH settings, secrets) are assembled
at run time, so this repository's own files stay clean when it is pushed through the guard.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parents[2] / "guard" / "publish_guard.py"

# Made-up terms for the deny-list. They mean nothing outside these tests.
PERSON = "zephyrine quillfeather"
TEACHING = "ottoline brackenmoor"
FAKE_SECRET = "FAKESECRET" + "0123456789"
PRIVATE_IP = ".".join(["192", "168", "77", "9"])
SSH_PORT_FLAG = "ssh " + "-p " + "2200"
SSH_HOST_LINE = "    Host" + "Name example.invalid"
HOME_PATH = "/" + "/".join(["home", "someone", "project", "file.txt"])
PUBLIC_NAME = "test/public"
PRIVATE_NAME = "test/private"

FAKE_GITLEAKS = textwrap.dedent(
    """\
    #!{python}
    # Stand-in for gitleaks: records how it was called, flags one fixed pattern.
    import json, os, sys
    argv = sys.argv[1:]
    with open({calls!r}, "a") as handle:
        handle.write(json.dumps({{"argv": argv, "cwd": os.getcwd(),
                                  "env": sorted(os.environ)}}) + "\\n")
    report = argv[argv.index("--report-path") + 1]
    code = int(argv[argv.index("--exit-code") + 1])
    found = []
    for number, line in enumerate(sys.stdin, 1):
        if {secret!r} in line:
            found.append({{"RuleID": "fake-rule", "StartLine": number}})
    with open(report, "w") as handle:
        json.dump(found, handle)
    sys.exit(code if found else 0)
    """
)


class Sandbox:
    """A throwaway home, guard installation, working repository, and bare remotes."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.home = root / "home"
        self.home.mkdir()
        self.guard = root / "guard-home"
        self.gitconfig = self.home / ".gitconfig"
        self.env = {
            "PATH": os.environ["PATH"],
            "HOME": str(self.home),
            "LANG": "C.UTF-8",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }
        self.gitconfig.write_text(
            "[user]\n\tname = Test Person\n\temail = test@example.invalid\n"
            "[init]\n\tdefaultBranch = main\n[protocol \"file\"]\n\tallow = always\n"
        )
        self.calls = root / "gitleaks-calls.jsonl"
        self.gitleaks = root / "bin" / "gitleaks"
        self.gitleaks.parent.mkdir()
        self.gitleaks.write_text(
            FAKE_GITLEAKS.format(
                python=sys.executable, calls=str(self.calls), secret=FAKE_SECRET
            )
        )
        self.gitleaks.chmod(0o755)
        self.visibility_map = root / "visibility.json"
        self.public = self.new_bare("public.git")
        self.private = self.new_bare("private.git")
        self.visibility = {
            str(self.public): {"name": PUBLIC_NAME, "visibility": "public"},
            str(self.private): {"name": PRIVATE_NAME, "visibility": "private"},
        }
        self.save_visibility()
        self.install()
        self.git_global("core.hooksPath", str(self.guard / "hooks"))
        self.deny_add("tier2a-people", PERSON)
        self.deny_add("tier2b-teaching", TEACHING)
        self.policy = {
            "required_tiers": ["tier2a-people", "tier2b-teaching"],
            "repos": {PUBLIC_NAME: {"label": "public"}},
        }
        self.save_policy()
        self.work = root / "work"
        self.work.mkdir()
        self.git("init", "-q")
        self.git("remote", "add", "origin", str(self.public))
        self.commit("README.md", "hello\n", "docs: first commit")

    # ------------------------------------------------------------------ set-up helpers
    def new_bare(self, name: str) -> Path:
        path = self.root / name
        subprocess.run(["git", "init", "-q", "--bare", str(path)], check=True, env=self.env)
        return path

    def save_visibility(self) -> None:
        self.visibility_map.write_text(json.dumps(self.visibility))

    def save_policy(self) -> None:
        lines = [f"required_tiers = {json.dumps(self.policy['required_tiers'])}", ""]
        for name, entry in self.policy["repos"].items():
            lines.append(f'[repos."{name}"]')
            for key, value in entry.items():
                lines.append(f"{key} = {json.dumps(value)}")
            lines.append("")
        (self.guard / "policy.toml").write_text("\n".join(lines))

    def git_global(self, key: str, value: str) -> None:
        subprocess.run(["git", "config", "--global", key, value], check=True, env=self.env)

    def engine(self, *args: str, stdin: str | None = None, env: dict | None = None):
        """Run the engine directly, with this sandbox's guard folder."""
        command = [sys.executable, "-I", str(ENGINE), "--home", str(self.guard), *args]
        return subprocess.run(
            command, text=True, capture_output=True, input=stdin, env=env or self.env,
            cwd=self.work if self.root.joinpath("work").exists() else self.root,
        )

    def install(self, *extra: str) -> None:
        result = self.engine(
            "install",
            "--gitleaks", str(self.gitleaks),
            "--visibility-map", str(self.visibility_map),
            "--test-mode",
            *extra,
        )
        assert result.returncode == 0, result.stderr

    def deny_add(self, tier: str, term: str) -> None:
        result = self.engine("deny-add", "--tier", tier, stdin=term + "\n")
        assert result.returncode == 0, result.stderr

    # ------------------------------------------------------------------ git helpers
    def git(self, *args: str, check: bool = True, cwd: Path | None = None, env: dict | None = None):
        return subprocess.run(
            ["git", *args], text=True, capture_output=True, check=check,
            cwd=cwd or self.work, env=env or self.env,
        )

    def commit(self, path: str, text: str, message: str = "change", env: dict | None = None) -> str:
        target = self.work / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        self.git("add", "--", path)
        self.git("commit", "-q", "-m", message, env=env)
        return self.head()

    def head(self) -> str:
        return self.git("rev-parse", "HEAD").stdout.strip()

    def push(self, *args: str, cwd: Path | None = None):
        """Push, by default the current branch to the public remote."""
        return self.git("push", *(args or ("origin", "HEAD:refs/heads/main")), check=False, cwd=cwd)

    def remote_refs(self, remote: Path | None = None) -> str:
        return subprocess.run(
            ["git", "ls-remote", str(remote or self.public)],
            text=True, capture_output=True, env=self.env,
        ).stdout

    def remote_has(self, sha: str, remote: Path | None = None) -> bool:
        return subprocess.run(
            ["git", "cat-file", "-e", sha], cwd=remote or self.public,
            capture_output=True, env=self.env,
        ).returncode == 0

    def seed_public(self) -> str:
        """Push the first commit, so later pushes have a known public starting point."""
        result = self.push()
        assert result.returncode == 0, result.stderr
        return self.head()

    def cleanup(self) -> None:
        """Restore write permission so pytest can remove the read-only hooks folder."""
        hooks = self.guard / "hooks"
        if hooks.exists():
            hooks.chmod(hooks.stat().st_mode | stat.S_IWUSR)


def assert_blocked(result, sandbox: Sandbox, sha: str | None = None) -> None:
    """A push must fail, say so with the marker, and deliver nothing."""
    assert result.returncode != 0, result.stdout + result.stderr
    assert "publish-guard: BLOCKED" in result.stderr, result.stderr
    if sha is not None:
        assert not sandbox.remote_has(sha), "the blocked commit reached the remote"
    # Findings must never repeat what they matched, in any of the forms the matcher accepts.
    output = result.stderr.lower()
    for term in (PERSON, TEACHING, FAKE_SECRET, PRIVATE_IP):
        words = term.lower().split()
        forms = set()
        for order in (words, list(reversed(words))):
            for joiner in (" ", "-", "_", "", "/", "."):
                forms.add(joiner.join(order))
        for form in forms:
            if len(form) >= 4:
                assert form not in output, form


def blocked_push_id(sandbox: Sandbox, *push_args: str) -> str:
    """Push, expect a block, and return the identifier the block message gives for exemptions."""
    result = sandbox.push(*push_args)
    assert_blocked(result, sandbox)
    match = re.search(r"--push ([0-9a-f]{32})", result.stderr)
    assert match, result.stderr
    return match.group(1)


def assert_passed(result, sandbox: Sandbox, sha: str | None = None) -> None:
    assert result.returncode == 0, result.stderr
    if sha is not None:
        assert sandbox.remote_has(sha)


@pytest.fixture
def sandbox(tmp_path):
    world = Sandbox(tmp_path)
    yield world
    world.cleanup()
