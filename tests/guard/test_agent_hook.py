"""The agent-side hook: what it refuses, what it asks about, and what it leaves alone."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[2] / "guard" / "agent_hook.py"


def run(command: str, cwd: Path, home: Path, env: dict | None = None) -> dict | None:
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}
    result = subprocess.run(
        [sys.executable, "-I", str(HOOK), "--home", str(home)], input=json.dumps(payload),
        capture_output=True, text=True, env=env, check=True,
    )
    return json.loads(result.stdout) if result.stdout.strip() else None


def kind(result: dict | None) -> str:
    return result["hookSpecificOutput"]["permissionDecision"] if result else "none"


@pytest.fixture
def world(sandbox):
    """The guard sandbox, with an environment that sees its git configuration."""
    return sandbox


@pytest.mark.parametrize(
    "command",
    [
        "git push --no-verify origin main",
        "git commit --no-verify -m x",
        "git commit -nm x",
        "git -c core.hooksPath=/dev/null push origin main",
        "git -c CORE.HOOKSPATH=/tmp/x commit -m x",
        "git --config-env=core.hooksPath=X push",
        "git config core.hooksPath /dev/null",
        "git config --global --unset core.hooksPath",
        "GIT_CONFIG_GLOBAL=/tmp/empty git push origin main",
        "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=/x git push",
        "HOME=/tmp git push origin main",
        "env -i PATH=/usr/bin git push origin main",
        "cd /tmp && git push --no-verify",
        "bash -c 'git push --no-verify origin main'",
        "echo start; git push --no-verify",
    ],
)
def test_switching_the_guard_off_is_refused(world, command):
    assert kind(run(command, world.work, world.guard, world.env)) == "deny"


@pytest.mark.parametrize(
    "command",
    [
        "gh repo create saross/new --public",
        "gh repo edit saross/thing --visibility public",
        "gh gist create notes.md",
        "gh release create v1 dist.zip",
        "gh api -X PATCH repos/saross/thing -f private=false",
        "gh api repos/saross/thing/contents/a.txt -f message=x -f content=eA==",
        "gh api --method=PUT repos/saross/thing/contents/a.txt",
        "git send-pack https://example.invalid/x.git main",
        "ssh build-host 'cd repo && git push origin main'",
    ],
)
def test_other_publishing_routes_pass_and_are_noted(world, command):
    """No prompts: these go through, and the route (never the command) is logged for the
    watcher (Shawn, 8 November 2026)."""
    assert kind(run(command, world.work, world.guard, world.env)) == "none"
    log = (world.guard / "log" / "agent-hook.jsonl").read_text()
    record = json.loads(log.splitlines()[-1])
    assert set(record) == {"time", "route", "cwd"}
    assert command not in log


@pytest.mark.parametrize(
    "command",
    [
        "git push origin main",
        "git push -n origin main",
        "git commit -m 'mention --no-verify in a message is fine'",
        "git config --get core.hooksPath",
        "git status && git log --oneline -3",
        "gh api repos/saross/thing",
        "gh pr view 54",
        "grep -r core.hooksPath docs/",
        "echo 'git push --no-verify' > notes.txt",
    ],
)
def test_ordinary_commands_pass(world, command):
    assert kind(run(command, world.work, world.guard, world.env)) == "none"


def test_push_from_a_clone_with_hooks_off_is_refused(world):
    world.git("config", "--local", "core.hooksPath", "/dev/null")
    result = run("git push origin main", world.work, world.guard, world.env)
    assert kind(result) == "deny"
    assert "switched off" in result["hookSpecificOutput"]["permissionDecisionReason"]


def test_push_from_a_repository_that_overrides_the_hooks_path_is_refused(world):
    world.git("config", "--local", "core.hooksPath", str(world.work / ".git" / "hooks"))
    assert kind(run("git push origin main", world.work, world.guard, world.env)) == "deny"


def test_push_when_the_guard_is_not_installed_is_refused(world, tmp_path):
    assert kind(run("git push origin main", world.work, tmp_path / "nowhere", world.env)) == "deny"


def test_cd_into_an_unguarded_clone_is_followed(world, tmp_path):
    other = tmp_path / "other"
    world.git("clone", "-q", str(world.public), str(other))
    world.git("config", "--local", "core.hooksPath", "/dev/null", cwd=other)
    command = f"cd {other} && git push origin main"
    assert kind(run(command, world.work, world.guard, world.env)) == "deny"


def test_other_tools_are_ignored(world):
    payload = {"tool_name": "Read", "tool_input": {"file_path": "/etc/hosts"}}
    result = subprocess.run(
        [sys.executable, "-I", str(HOOK), "--home", str(world.guard)], input=json.dumps(payload),
        capture_output=True, text=True, env=world.env, check=True,
    )
    assert result.stdout == ""


def test_malformed_input_is_refused(world):
    result = subprocess.run(
        [sys.executable, "-I", str(HOOK), "--home", str(world.guard)], input="{not json",
        capture_output=True, text=True, env=world.env, check=True,
    )
    assert json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


# ------------------------------------------------------------------ the guard's own administration


def _engine(world, sub):
    return f"python3 -I {world.guard}/engine/publish_guard.py --home {world.guard} {sub}"


@pytest.mark.parametrize(
    "sub", ["override --repo a/b --push 0123", "deny-add --tier tier3-private", "deny-rebuild",
            "deny-remove --tier x", "deny-check"],
)
def test_guard_administration_is_refused(world, sub):
    result = run(_engine(world, sub), world.work, world.guard, world.env)
    assert kind(result) == "deny"


@pytest.mark.parametrize("sub", ["doctor", "deny-stats", "audit --repo . --name a/b --rev=HEAD"])
def test_guard_reports_pass(world, sub):
    assert kind(run(_engine(world, sub), world.work, world.guard, world.env)) == "none"


def test_reinstalling_the_guard_passes(world):
    command = _engine(world, "install --gitleaks /x --gitleaks-sha256 00")
    assert kind(run(command, world.work, world.guard, world.env)) == "none"


def test_building_the_secrets_tier_is_refused(world):
    command = "python3 ~/personal-assistant/data/security/build-tier1.py"
    assert kind(run(command, world.work, world.guard, world.env)) == "deny"


@pytest.mark.parametrize(
    "template",
    [
        "echo '{{}}' > {guard}/overrides/abc.json",
        "echo x >> {guard}/log/guard.jsonl",
        "cp /tmp/fake {guard}/bin/gitleaks",
        "chmod u+w {guard}/hooks",
        "rm -rf {guard}/deny",
        "sed -i s/a/b/ {guard}/install.json",
        "tee {guard}/policy.toml < /tmp/p",
        "cd {guard} && touch overrides/x.json",
        "printf x | dd of={guard}/engine/publish_guard.py",
    ],
)
def test_shell_writes_into_the_guard_folder_are_refused(world, template):
    command = template.format(guard=world.guard)
    assert kind(run(command, world.work, world.guard, world.env)) == "deny", command


@pytest.mark.parametrize(
    "template",
    [
        "cat {guard}/log/guard.jsonl",
        "ls -la {guard}/hooks",
        "sha256sum {guard}/bin/gitleaks",
        "cp {guard}/log/guard.jsonl /tmp/copy.jsonl",
        "python3 -I {guard}/engine/agent_hook.py --home {guard}",
    ],
)
def test_reading_the_guard_folder_passes(world, template):
    command = template.format(guard=world.guard)
    assert kind(run(command, world.work, world.guard, world.env)) == "none", command




def _file_tool(world, tool, path):
    payload = {"tool_name": tool, "tool_input": {"file_path": str(path)}, "cwd": str(world.work)}
    result = subprocess.run(
        [sys.executable, "-I", str(HOOK), "--home", str(world.guard)], input=json.dumps(payload),
        capture_output=True, text=True, env=world.env, check=True,
    )
    return json.loads(result.stdout) if result.stdout.strip() else None


@pytest.mark.parametrize("tool", ["Write", "Edit", "MultiEdit"])
def test_file_tools_writing_into_the_guard_folder_are_refused(world, tool):
    assert kind(_file_tool(world, tool, world.guard / "overrides" / "x.json")) == "deny"


def test_file_tools_elsewhere_pass(world):
    assert kind(_file_tool(world, "Write", world.work / "notes.md")) == "none"


def test_replacing_a_link_in_the_guard_folder_is_refused(world, tmp_path):
    """The live set-up links the policy into a private repository. Removing or replacing the
    link changes the guard, even though the link points elsewhere."""
    store = tmp_path / "private-store" / "security"
    store.mkdir(parents=True)
    policy = world.guard / "policy.toml"
    (store / "policy.toml").write_text(policy.read_text())
    policy.unlink()
    policy.symlink_to(store / "policy.toml")
    for command in (f"rm {policy}", f"ln -sf /tmp/other.toml {policy}"):
        assert kind(run(command, world.work, world.guard, world.env)) == "deny", command
    # Editing the policy where it really lives is ordinary work in that repository.
    assert kind(_file_tool(world, "Edit", store / "policy.toml")) == "none"


# ------------------------------------------------------------------ further publishing routes


@pytest.mark.parametrize(
    "command",
    [
        "gh api graphql -f query='mutation { updateRepository(input: {}) { clientMutationId } }'",
        "git lfs push origin main",
        "git config include.path ~/other.gitconfig",
        "git -c include.path=/tmp/x push origin main",
        "gh api repos/saross/thing/contents/a.txt --field=message=x",
    ],
)
def test_further_publishing_routes_pass_and_are_noted(world, command):
    assert kind(run(command, world.work, world.guard, world.env)) == "none"
    assert (world.guard / "log" / "agent-hook.jsonl").is_file()


# ------------------------------------------------------------------ ordinary work that must pass


@pytest.mark.parametrize(
    "command",
    [
        # A commit message written with a heredoc is text, not commands.
        "git commit -q -F - -- a.txt <<'EOF'\nfix: note that\ngit push --no-verify skips it\nEOF",
        "cat > notes.md <<EOF\nrm -rf {guard}/deny\nEOF",
        "git commit -m 'docs: explain the -n flag'",
        "git commit -am 'mention -n and --no-verify'",
        "git commit --author 'A -n B <a@example.invalid>' -m x",
        "git add security/build-tier1.py",
        "git log -p -- security/build-tier1.py",
        "cat ~/personal-assistant/data/security/build-tier1.py",
        "python3 -c 'print(1)' <<< 'git push --no-verify'",
    ],
)
def test_ordinary_work_mentioning_risky_words_passes(world, command):
    command = command.format(guard=world.guard)
    assert kind(run(command, world.work, world.guard, world.env)) == "none", command


@pytest.mark.parametrize(
    "command",
    [
        "bash -lc 'git push --no-verify origin main'",
        "sh -ec 'git commit -n -m x'",
        "bash -o pipefail -c 'git push --no-verify'",
        "git commit -qn -m x",
        "git commit -m x --no-verify",
        "uv run --with x python {guard}/engine/publish_guard.py deny-check",
        "python3 ~/personal-assistant/data/security/build-tier1.py --env /tmp/e",
    ],
)
def test_wrapped_and_combined_forms_are_still_refused(world, command):
    command = command.format(guard=world.guard)
    assert kind(run(command, world.work, world.guard, world.env)) == "deny", command


# ------------------------------------------------------------------ second audit (test lens)


def test_the_wired_form_without_home_guards_the_default_folder(tmp_path):
    """The settings run the hook with no `--home`, so its default must be the real folder."""
    home = tmp_path / "user"
    guard = home / ".config" / "publish-guard"
    (guard / "overrides").mkdir(parents=True)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(home)}
    for payload in (
        {"tool_name": "Write", "tool_input": {"file_path": str(guard / "overrides" / "x.json")},
         "cwd": str(tmp_path)},
        {"tool_name": "Bash", "tool_input": {"command": "cd $HOME/.config/publish-guard && "
                                             "touch overrides/x.json"}, "cwd": str(tmp_path)},
        {"tool_name": "Bash", "tool_input": {"command": "echo {} > ~/.config/publish-guard/"
                                             "overrides/x.json"}, "cwd": str(tmp_path)},
    ):
        result = subprocess.run(
            [sys.executable, "-I", str(HOOK)], input=json.dumps(payload), capture_output=True,
            text=True, env=env, check=True,
        )
        assert kind(json.loads(result.stdout) if result.stdout.strip() else None) == "deny"


def test_an_engine_command_still_cant_write_into_the_guard_folder(world):
    command = _engine(world, f"deny-stats > {world.guard}/overrides/x.json")
    assert kind(run(command, world.work, world.guard, world.env)) == "deny"


@pytest.mark.parametrize(
    "template",
    [
        "mv /tmp/p.toml {guard}/policy.toml",
        "install -m 644 /tmp/p {guard}/install.json",
        "rsync -a /tmp/x/ {guard}/hooks/",
    ],
)
def test_more_writers_into_the_guard_folder_are_refused(world, template):
    command = template.format(guard=world.guard)
    assert kind(run(command, world.work, world.guard, world.env)) == "deny", command


def test_notebook_edits_into_the_guard_folder_are_refused(world):
    payload = {"tool_name": "NotebookEdit",
               "tool_input": {"notebook_path": str(world.guard / "x.ipynb")},
               "cwd": str(world.work)}
    result = subprocess.run(
        [sys.executable, "-I", str(HOOK), "--home", str(world.guard)], input=json.dumps(payload),
        capture_output=True, text=True, env=world.env, check=True,
    )
    assert kind(json.loads(result.stdout)) == "deny"


# ------------------------------------------------- Astra's reviews: re-review item 1 and W5


@pytest.mark.parametrize(
    "template",
    [
        "install -m 444 -t {guard}/engine /tmp/publish_guard.py",
        "install -m 444 -t{guard}/engine /tmp/publish_guard.py",
        "install --target-directory {guard}/engine /tmp/publish_guard.py",
        "cp --target-directory={guard}/bin /tmp/gitleaks",
        "mv -vt {guard}/bin /tmp/gitleaks",
        "sed -i -es/public/may-go-public/ {guard}/policy.toml",
        "sed -i --expression=s/a/b/ {guard}/policy.toml",
        "sed -ni -e p {guard}/policy.toml",
        "perl -i -pe s/a/b/ {guard}/policy.toml",
        "cp -r /tmp/elsewhere/guard-home {parent}/",
        "cp -r /tmp/elsewhere/guard-home {parent}",
        "mv {guard}/policy.toml /tmp/policy.toml",
    ],
)
def test_write_targets_in_ordinary_option_forms_are_refused(world, template):
    command = template.format(guard=world.guard, parent=world.guard.parent)
    assert kind(run(command, world.work, world.guard, world.env)) == "deny", command


def test_a_contents_copy_onto_a_folder_holding_the_guard_is_refused(world, tmp_path):
    source = tmp_path / "staging"
    (source / world.guard.name).mkdir(parents=True)
    for command in (f"rsync -a {source}/ {world.guard.parent}/",
                    f"cp -r {source}/. {world.guard.parent}"):
        assert kind(run(command, world.work, world.guard, world.env)) == "deny", command


@pytest.mark.parametrize(
    "template",
    [
        "install -m 644 {guard}/engine/publish_guard.py /tmp/copy.py",
        "cp -r /tmp/other {parent}/",
        "cp -t /tmp/out {guard}/log/guard.jsonl",
        "sed -n -e p {guard}/policy.toml",
        "sed -e s/a/b/ {guard}/policy.toml",
        "perl -ne print {guard}/policy.toml",
    ],
)
def test_copies_out_of_and_reads_of_the_guard_folder_pass(world, template):
    command = template.format(guard=world.guard, parent=world.guard.parent)
    assert kind(run(command, world.work, world.guard, world.env)) == "none", command


def test_clearing_the_watchers_findings_is_refused(world):
    for sub in ("watch --clear all", "watch --report /tmp/r.md --clear=test/public"):
        assert kind(run(_engine(world, sub), world.work, world.guard, world.env)) == "deny", sub


@pytest.mark.parametrize("sub", ["watch", "watch --report /tmp/r.md", "watch --rescan all"])
def test_running_the_watcher_passes(world, sub):
    assert kind(run(_engine(world, sub), world.work, world.guard, world.env)) == "none"
