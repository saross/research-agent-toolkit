#!/usr/bin/env python3
"""agent_hook: a Claude Code PreToolUse hook that backs up the publish guard from the agent's side.

Purpose
    The pre-push guard runs inside git, so a command that switches git's hooks off, or skips them,
    gets past it. This hook looks at each command or file edit an agent is about to make, and
    refuses the few that would do that by accident:

    - `--no-verify` on a push or commit, `git commit -n`, and overrides of `core.hooksPath`, by
      `-c`, `--config-env`, `git config`, or the environment;
    - a push from a clone where the guard isn't in force;
    - the guard's own administration (exemptions, list changes, and clearing the watcher's
      findings), writes into the guard's folder by shell or by the file tools, and running
      `build-tier1.py`, which reads secrets.

    It never asks the person anything, so it doesn't interrupt autonomous work. Commands that
    publish by other routes (creating a repository, changing its visibility, GitHub API writes,
    gists, releases, `git lfs push`, `git send-pack`, a push run over SSH) go through, and each is
    noted in `log/agent-hook.jsonl` in the guard's folder for the watcher's report. The note names
    the route and the folder, never the command, which could hold a secret.

    It is built against accidents and misled agents, not deliberate evasion (Shawn, 8 November
    2026): it reads commands as text, and a disguised command gets past it.

Wiring (in Claude Code settings, under hooks)
    {"PreToolUse": [{"matcher": "Bash|Write|Edit|MultiEdit|NotebookEdit", "hooks": [{"type":
      "command", "command": "python3 -I ~/.config/publish-guard/engine/agent_hook.py",
      "timeout": 30, "onFailure": "block"}]}]}

Output
    Nothing, when the command is fine. Otherwise a JSON refusal on standard output, in the form
    Claude Code documents for PreToolUse hooks. Any error inside the hook refuses the command,
    because a check that fails silently is worse than none.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_HOME = Path.home() / ".config" / "publish-guard"
SEPARATORS = re.compile(r"\|\||&&|[;|&\n]")
WRAPPERS = {"sudo", "env", "command", "exec", "time", "nohup", "nice", "timeout", "xargs"}
SHELLS = {"bash", "sh", "zsh", "dash"}
HOOKS_PATH = re.compile(r"core\.hookspath", re.I)
INCLUDES = re.compile(r"^include(?:if\..*)?\.path", re.I)
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
FILE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
# Engine commands that only a person at a terminal should run.
ADMIN_COMMANDS = {"override", "deny-add", "deny-rebuild", "deny-remove", "deny-check"}
# Commands that change every path they're given.
WRITERS_ALL = {"rm", "rmdir", "chmod", "chown", "chgrp", "touch", "truncate", "shred", "unlink",
               "mkdir", "setfacl", "chattr", "tee"}
# Commands that copy, move, or link sources to a destination: the last operand, or the value of
# a target-directory option. Each one's short options that take a value (the next word, or the
# rest of the word), so a value isn't read as an operand (Astra re-review, item 1).
COPIERS = {"cp": "tS", "mv": "tS", "ln": "tS", "install": "tSmog", "rsync": "efTB",
           "scp": "cFiJloPS"}
COPIER_VALUE_LONG = {"--suffix", "--mode", "--owner", "--group", "--rsh", "--filter",
                     "--exclude", "--include", "--temp-dir", "--partial-dir", "--compare-dest",
                     "--copy-dest", "--link-dest", "--backup-dir", "--block-size"}
REDIRECT = re.compile(r"^(?:\d*|&)>{1,2}\|?(.*)$")
HEREDOC = re.compile(r"<<(-?)[ \t]*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
# `git commit` options whose value is the next word, or the rest of a cluster such as `-am`.
COMMIT_VALUE_SHORT = set("mFcCt")
COMMIT_VALUE_LONG = {"--message", "--file", "--reuse-message", "--reedit-message", "--template",
                     "--author", "--date", "--cleanup", "--fixup", "--squash", "--trailer",
                     "--pathspec-from-file"}


def decision(reason: str) -> dict:
    """A PreToolUse refusal."""
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"publish guard: {reason}",
        }
    }


def strip_heredocs(command: str) -> str:
    """Remove here-document bodies, which are text for a command to read, not commands.

    Without this, each line of a commit message written with `git commit -F - <<EOF` would be read
    as a command of its own, and a line such as "git push --no-verify skips the guard" refused.
    Quote state carries across lines, so `<<` inside a quoted string isn't taken as a heredoc.
    """
    lines = command.split("\n")
    kept: list[str] = []
    quote = ""
    index = 0
    while index < len(lines):
        line = lines[index]
        kept.append(line)
        index += 1
        pending: list[tuple[bool, str]] = []
        position = 0
        while position < len(line):
            char = line[position]
            if quote:
                if char == quote:
                    quote = ""
                elif char == "\\" and quote == '"':
                    position += 1
            elif char in "'\"":
                quote = char
            elif char == "\\":
                position += 1
            elif char == "#" and (position == 0 or line[position - 1].isspace()):
                break  # a comment runs to the end of the line
            elif line.startswith("<<<", position):
                position += 3
                continue  # a here-string is one word, not a body
            else:
                match = HEREDOC.match(line, position)
                if match:
                    pending.append((match.group(1) == "-", match.group(3)))
                    position = match.end()
                    continue
            position += 1
        for strip_tabs, word in pending:
            while index < len(lines):
                body = lines[index]
                index += 1
                if (body.lstrip("\t") if strip_tabs else body) == word:
                    break
    return "\n".join(kept)


def segments(command: str) -> list[list[str]]:
    """Split a command line into simple commands, each as a list of words.

    Here-document bodies are dropped first, and text inside quotes isn't split on separators.
    Commands passed to a shell with `-c` (also `-lc`, `-ec`, `-o pipefail -c`) are split in turn,
    so a wrapped push is still seen.
    """
    command = strip_heredocs(command)
    pieces: list[str] = []
    current = []
    quote = ""
    index = 0
    while index < len(command):
        char = command[index]
        if quote:
            current.append(char)
            if char == quote:
                quote = ""
            elif char == "\\" and quote == '"' and index + 1 < len(command):
                current.append(command[index + 1])
                index += 1
        elif char in "'\"":
            quote = char
            current.append(char)
        else:
            match = SEPARATORS.match(command, index)
            if match:
                pieces.append("".join(current))
                current = []
                index = match.end()
                continue
            current.append(char)
        index += 1
    pieces.append("".join(current))
    result: list[list[str]] = []
    for piece in pieces:
        piece = piece.strip().lstrip("({").strip()
        if not piece:
            continue
        try:
            words = shlex.split(piece, comments=True)
        except ValueError:
            words = piece.split()
        prefix, words = _split_prefix(words)
        script = _shell_script(words)
        if script is not None:
            for inner in segments(script):
                result.append(prefix + inner)
        elif words or prefix:
            result.append(prefix + words)
    return result


def _shell_script(words: list[str]) -> str | None:
    """The script a shell runs with `-c`, if this command is one."""
    if not words or Path(words[0]).name not in SHELLS:
        return None
    index = 1
    while index < len(words):
        word = words[index]
        if word in ("-o", "+o"):
            index += 2
        elif re.fullmatch(r"-[a-zA-Z]*c[a-zA-Z]*", word):
            return words[index + 1] if index + 1 < len(words) else None
        elif word.startswith(("-", "+")):
            index += 1
        else:
            return None
    return None


def _split_prefix(words: list[str]) -> tuple[list[str], list[str]]:
    """Separate variable assignments and wrapper commands from the real command.

    The prefix is kept, marked with a leading `@`, so a check can see an environment change such
    as `GIT_CONFIG_GLOBAL=...` or `env -i` in front of a push.
    """
    prefix: list[str] = []
    while words:
        first = words[0]
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", first):
            prefix.append("@" + first)
            words = words[1:]
        elif Path(first).name in WRAPPERS:
            prefix.append("@" + Path(first).name)
            words = words[1:]
            while words and words[0].startswith("-"):
                prefix.append("@" + words[0])
                words = words[1:]
            if words and re.fullmatch(r"\d+[smhd]?", words[0]):
                words = words[1:]  # timeout's duration
        else:
            break
    return prefix, words


def git_subcommand(words: list[str]) -> tuple[str | None, list[str], list[str]]:
    """For a git command, return (subcommand, its arguments, the global options before it)."""
    if not words or Path(words[0]).name != "git":
        return None, [], []
    options: list[str] = []
    index = 1
    while index < len(words) and words[index].startswith("-"):
        options.append(words[index])
        if words[index] in ("-c", "-C", "--git-dir", "--work-tree", "--namespace"):
            index += 1
            if index < len(words):
                options.append(words[index])
        index += 1
    if index >= len(words):
        return None, [], options
    return words[index], words[index + 1 :], options


def commit_skips_hooks(args: list[str]) -> bool:
    """Whether a `git commit` asks to skip the hooks, reading only its options.

    A message, a file name, or a pathspec that happens to contain `-n` is not an option.
    """
    index = 0
    while index < len(args):
        word = args[index]
        if word == "--":
            return False
        if word == "--no-verify":
            return True
        if word.startswith("--"):
            if word in COMMIT_VALUE_LONG:
                index += 1  # its value is the next word
        elif word.startswith("-") and len(word) > 1:
            for position, flag in enumerate(word[1:]):
                if flag == "n":
                    return True
                if flag in COMMIT_VALUE_SHORT:
                    if position == len(word) - 2:
                        index += 1  # its value is the next word
                    break  # the rest of the cluster is the value
        index += 1
    return False


def guard_in_force(cwd: str, home: Path) -> str | None:
    """None if the guard will run for pushes from cwd, otherwise the reason it won't."""
    hooks = home / "hooks"
    stub = hooks / "pre-push"
    if not stub.is_file():
        return "the guard isn't installed on this machine"
    result = subprocess.run(
        ["git", "-C", cwd, "config", "--get", "core.hooksPath"], capture_output=True, text=True,
        timeout=20,
    )
    effective = result.stdout.strip()
    if result.returncode != 0 and not effective:
        return "git's hooks path isn't set to the guard's folder"
    if effective == "/dev/null":
        return "this clone has git hooks switched off"
    if Path(os.path.expanduser(effective)).resolve() != hooks.resolve():
        return "this repository's hooks path points away from the guard"
    return None


def _inside(path: str, folder: str) -> bool:
    return path == folder or path.startswith(folder.rstrip("/") + "/")


def _expand_home(word: str) -> str:
    """Expand `~`, `$HOME`, and `${HOME}` as the shell would."""
    user_home = os.path.expanduser("~")
    word = word.replace("${HOME}", user_home).replace("$HOME", user_home)
    return os.path.expanduser(word)


def _in_guard_folder(word: str, cwd: str, home: Path) -> bool:
    """Whether a path names something in the guard's folder, as written or after links.

    Both forms count: removing or replacing a link in the folder changes the guard, even when the
    link points elsewhere.
    """
    path = os.path.join(cwd, _expand_home(word))
    folder = os.path.normpath(home)
    real_folder = os.path.realpath(home)
    if _inside(os.path.normpath(path), folder) or _inside(os.path.normpath(path), real_folder):
        return True
    return _inside(os.path.realpath(path), real_folder)


def _copier_operands(name: str, args: list[str]) -> tuple[list[str], str | None, bool]:
    """A copying command's operands, its target-directory option, and whether it only makes
    directories (`install -d`)."""
    short = COPIERS[name]
    operands: list[str] = []
    target: str | None = None
    makes_dirs = False
    index = 0
    while index < len(args):
        word = args[index]
        redirect = REDIRECT.match(word)
        if word == "--":
            operands.extend(args[index + 1 :])
            break
        if redirect:
            index += 1 if redirect.group(1) else 2
            continue
        if word.startswith("--"):
            key, equals, value = word.partition("=")
            if key == "--target-directory":
                target = value if equals else (args[index + 1] if index + 1 < len(args) else "")
                index += 1 if equals else 2
                continue
            if key == "--directory" and name == "install":
                makes_dirs = True
            index += 2 if key in COPIER_VALUE_LONG and not equals else 1
            continue
        if word.startswith("-") and len(word) > 1:
            takes_next = False
            for position, flag in enumerate(word[1:], 1):
                if flag == "d" and name == "install":
                    makes_dirs = True
                if flag in short:
                    value = word[position + 1 :]
                    if not value:
                        takes_next = True
                        value = args[index + 1] if index + 1 < len(args) else ""
                    if flag == "t":
                        target = value
                    break
            index += 2 if takes_next else 1
            continue
        operands.append(word)
        index += 1
    return operands, target, makes_dirs


def _copier_targets(name: str, args: list[str], cwd: str, home: Path) -> list[str]:
    """Every path a copy, move, or link can write, including what lands inside a destination
    folder: `cp -r S/guard-home P/` writes P/guard-home (Astra re-review, item 1)."""
    operands, target, makes_dirs = _copier_operands(name, args)
    if makes_dirs:
        return operands
    if target is not None:
        destination, sources = target, operands
    elif operands:
        destination, sources = operands[-1], operands[:-1]
    else:
        return []
    targets = [destination]
    if name == "mv":
        targets.extend(sources)  # moving something out of the guard's folder changes it too
    # The guard folder's first name below the destination, if the destination holds the folder.
    below = None
    full = os.path.normpath(os.path.join(cwd, _expand_home(destination)))
    for folder in {os.path.normpath(home), os.path.realpath(home)}:
        if _inside(folder, full) and folder != full:
            below = os.path.relpath(folder, full).split(os.sep)[0]
    for source in sources:
        targets.append(os.path.join(destination, os.path.basename(source.rstrip("/"))))
        # A source ending in "/" or "/." has its contents copied (rsync, `cp -r S/.`).
        if below and source.endswith(("/", "/.")):
            if os.path.lexists(os.path.join(cwd, _expand_home(source), below)):
                targets.append(os.path.join(destination, below))
    return targets


def _in_place_files(name: str, args: list[str]) -> list[str]:
    """The files `sed` or `perl` edits in place, or none when it doesn't edit in place.

    The programme can be the first operand or the value of `-e`, `-f`, or `--expression`, given
    as the next word or attached (`-es/a/b/`); only in the first case is the first operand not a
    file (Astra re-review, item 1).
    """
    script_flags = "ef" if name == "sed" else "eE"
    value_flags = "efl" if name == "sed" else "eE"
    # Flags whose value, if any, is the rest of the word; `-i` takes a backup suffix this way.
    rest_flags = "i" if name == "sed" else "iIlMm0xdDC"
    in_place = script_given = False
    files: list[str] = []
    index = 0
    while index < len(args):
        word = args[index]
        redirect = REDIRECT.match(word)
        if word == "--":
            files.extend(args[index + 1 :])
            break
        if redirect:
            index += 1 if redirect.group(1) else 2
            continue
        if word.startswith("--"):
            key, equals, _ = word.partition("=")
            if key == "--in-place":
                in_place = True
            elif key in ("--expression", "--file", "--line-length"):
                script_given = script_given or key != "--line-length"
                index += 0 if equals else 1
            index += 1
            continue
        if word.startswith("-") and len(word) > 1:
            takes_next = False
            for position, flag in enumerate(word[1:], 1):
                if flag == "i":
                    in_place = True
                if flag in value_flags:
                    script_given = script_given or flag in script_flags
                    takes_next = position == len(word) - 1
                    break
                if flag in rest_flags:
                    break
            index += 2 if takes_next else 1
            continue
        files.append(word)
        index += 1
    if not in_place:
        return []
    return files if script_given else files[1:]


def _write_targets(words: list[str], cwd: str, home: Path) -> list[str]:
    """The paths a command writes, as far as can be read from its words."""
    name = Path(words[0]).name
    args = words[1:]
    targets: list[str] = []
    for index, word in enumerate(words):
        match = REDIRECT.match(word)
        if match:
            targets.append(match.group(1) or (words[index + 1] if index + 1 < len(words) else ""))
    if name in WRITERS_ALL:
        targets.extend(w for w in args if not w.startswith("-") and not REDIRECT.match(w))
    elif name in COPIERS:
        targets.extend(_copier_targets(name, args, cwd, home))
    elif name in ("sed", "perl"):
        targets.extend(_in_place_files(name, args))
    elif name == "dd":
        targets.extend(w[3:] for w in args if w.startswith("of="))
    return [t for t in targets if t]


def _script_run(words: list[str], script: str) -> list[str] | None:
    """If a command runs the named script, the words after it; otherwise None.

    Only running counts, directly or through Python or `uv run`, so reading, staging, or diffing
    the script is fine.
    """
    runner = Path(words[0]).name
    if runner == script:
        return words[1:]
    if runner.startswith("python") or runner == "uv":
        for index, word in enumerate(words[1:], 1):
            if not word.startswith("-") and "=" not in word and Path(word).name == script:
                return words[index + 1 :]
    return None


def _engine_subcommand(rest: list[str]) -> str:
    position = 0
    while position < len(rest):
        if rest[position] == "--home":
            position += 2
        elif rest[position].startswith("-"):
            position += 1
        else:
            return rest[position]
    return ""


def note(home: Path, route: str, cwd: str) -> None:
    """Record a publishing route the hook let through. A logging failure never decides."""
    try:
        folder = home / "log"
        folder.mkdir(parents=True, exist_ok=True)
        record = {"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "route": route, "cwd": cwd}
        with (folder / "agent-hook.jsonl").open("a") as handle:
            handle.write(json.dumps(record) + "\n")
    except OSError:
        pass


def check_file_tool(payload: dict, home: Path) -> dict | None:
    """Writes by the file tools into the guard's folder are refused."""
    tool_input = payload.get("tool_input") or {}
    target = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
    if target and _in_guard_folder(target, str(payload.get("cwd") or os.getcwd()), home):
        return decision("the guard's own folder is changed by a person, not an agent")
    return None


def check(payload: dict, home: Path) -> dict | None:
    """Return a refusal for one tool call, or None to let it through."""
    if payload.get("tool_name") in FILE_TOOLS:
        return check_file_tool(payload, home)
    if payload.get("tool_name") != "Bash":
        return None
    command = str((payload.get("tool_input") or {}).get("command", ""))
    cwd = str(payload.get("cwd") or os.getcwd())
    routes: list[str] = []
    for full in segments(command):
        prefix = [w[1:] for w in full if w.startswith("@")]
        words = [w for w in full if not w.startswith("@")]
        if not words:
            continue
        name = Path(words[0]).name
        if name == "cd" and len(words) > 1:
            cwd = os.path.join(cwd, _expand_home(words[1]))
            continue
        if any(_in_guard_folder(t, cwd, home) for t in _write_targets(words, cwd, home)):
            return decision("the guard's own folder is changed by a person, not an agent")
        engine = _script_run(words, "publish_guard.py")
        if engine is not None:
            sub = _engine_subcommand(engine)
            if sub in ADMIN_COMMANDS:
                return decision(f"`{sub}` is for a person at their own terminal, not an agent")
            if sub == "watch" and any(w == "--clear" or w.startswith("--clear=") for w in engine):
                # Clearing acknowledges findings; it never shows that the content is clean
                # (Astra review W5).
                return decision("`watch --clear` is for a person at their own terminal, not an "
                                "agent")
            continue
        if _script_run(words, "build-tier1.py") is not None:
            return decision("build-tier1 reads secrets and rebuilds a list; a person runs it")
        sub, args, options = git_subcommand(words)
        if sub is not None and any(
            HOOKS_PATH.search(p) or p.startswith(("GIT_CONFIG", "HOME="))
            or p in ("-i", "-u", "--ignore-environment", "--unset")
            for p in prefix
        ):
            return decision("changing git's configuration environment is refused")
        if sub is not None:
            if any(HOOKS_PATH.search(o) for o in options):
                return decision("overriding core.hooksPath on a git command is refused")
            reading = any(a in ("--get", "--get-all", "--list", "-l", "--get-regexp") for a in args)
            if sub == "config" and any(HOOKS_PATH.search(a) for a in args) and not reading:
                return decision("changing core.hooksPath is refused")
            if sub == "push" and "--no-verify" in args:
                return decision("git push --no-verify skips the guard")
            if sub == "commit" and commit_skips_hooks(args):
                return decision("git commit --no-verify or -n skips the repository's checks")
            if sub == "push":
                where = cwd
                if "-C" in options:
                    where = os.path.join(cwd, options[options.index("-C") + 1])
                reason = guard_in_force(where, home)
                if reason:
                    return decision(f"{reason}, so this push wouldn't be checked")
            if any(INCLUDES.match(o.split("=", 1)[0]) for o in options) or (
                sub == "config" and not reading and any(INCLUDES.match(a) for a in args)
            ):
                routes.append("git-include")
            if sub == "lfs" and args[:1] == ["push"]:
                routes.append("git-lfs-push")
            if sub in ("send-pack", "http-push"):
                routes.append(f"git-{sub}")
        elif name == "gh":
            routes.extend(gh_routes(words[1:]))
        elif name == "ssh" and re.search(r"\bgit\b.*\bpush\b", " ".join(words[1:])):
            routes.append("ssh-push")
    for route in routes:
        note(home, route, cwd)
    return None


def gh_routes(args: list[str]) -> list[str]:
    """Publishing routes a GitHub CLI command takes that the pre-push check doesn't see."""
    if not args:
        return []
    group, rest = args[0], args[1:]
    action = rest[0] if rest else ""
    if group == "repo" and action == "create":
        return ["gh-repo-create"]
    if group == "repo" and action == "edit" and any(a.startswith("--visibility") for a in rest):
        return ["gh-repo-visibility"]
    if group == "gist" and action in ("create", "edit"):
        return ["gh-gist"]
    if group == "release" and action in ("create", "upload", "edit"):
        return ["gh-release"]
    if group == "api":
        method = None
        for index, word in enumerate(rest):
            if word in ("-X", "--method") and index + 1 < len(rest):
                method = rest[index + 1].upper()
            elif word.startswith("--method="):
                method = word.split("=", 1)[1].upper()
        fields = any(
            w in ("-f", "-F", "--field", "--raw-field", "--input")
            or w.startswith(("--field=", "--raw-field=", "--input="))
            for w in rest
        )
        if "graphql" in rest:
            return ["gh-api-graphql"] if fields or method else []
        if (method in WRITE_METHODS or (method is None and fields)) and "repos/" in " ".join(rest):
            return ["gh-api-write"]
    return []


def main() -> int:
    home = DEFAULT_HOME
    if len(sys.argv) == 3 and sys.argv[1] == "--home":
        home = Path(sys.argv[2])
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        result = check(payload, home)
    except Exception as error:  # noqa: BLE001
        result = decision(f"the agent hook failed ({type(error).__name__})")
    if result:
        print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
