"""
test_user_config.py
===================

Checks that each plugin's option references and its manifest agree.

A plugin's agents and commands name an option as ``${user_config.KEY}``,
which Claude Code replaces with the user's saved value. ``claude plugin
validate`` checks those references in server configuration only, so a
misspelt key in an agent or command file would go unnoticed and reach the
model as an unfilled placeholder. These tests catch that, and the reverse
case of an option that nothing uses.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

PLUGINS = Path(__file__).resolve().parents[2] / "plugins"
REFERENCE = re.compile(r"\$\{user_config\.([A-Za-z_][A-Za-z0-9_]*)\}")


def _plugin_dirs() -> list[Path]:
    """Return every plugin folder that has a manifest."""
    return sorted(p.parent.parent for p in PLUGINS.glob("*/.claude-plugin/plugin.json"))


def _declared(plugin: Path) -> dict[str, dict]:
    """Return the plugin's declared options, keyed by name."""
    manifest = json.loads((plugin / ".claude-plugin" / "plugin.json").read_text())
    return manifest.get("userConfig", {})


def _referenced(plugin: Path) -> dict[str, list[str]]:
    """Return each referenced option name with the files that reference it."""
    found: dict[str, list[str]] = {}
    for folder in ("agents", "commands", "skills"):
        for path in sorted((plugin / folder).rglob("*.md")):
            for key in REFERENCE.findall(path.read_text()):
                found.setdefault(key, []).append(str(path.relative_to(plugin)))
    return found


@pytest.mark.parametrize("plugin", _plugin_dirs(), ids=lambda p: p.name)
def test_every_reference_is_declared(plugin: Path) -> None:
    """An option named in an agent, command, or skill exists in the manifest."""
    declared = _declared(plugin)
    undeclared = {k: v for k, v in _referenced(plugin).items() if k not in declared}
    assert not undeclared, f"referenced but not declared: {undeclared}"


@pytest.mark.parametrize("plugin", _plugin_dirs(), ids=lambda p: p.name)
def test_every_option_is_used_and_optional(plugin: Path) -> None:
    """A declared option is used somewhere, is not secret, and is not required."""
    referenced = _referenced(plugin)
    for key, spec in _declared(plugin).items():
        assert key in referenced, f"{key} is declared but never referenced"
        # Sensitive values are not substituted into agent or command text.
        assert not spec.get("sensitive"), f"{key} must not be sensitive"
        # The plugin must work with nothing configured.
        assert not spec.get("required"), f"{key} must stay optional"


def test_verification_agents_declares_its_three_commands() -> None:
    """The options exist under the names the documentation gives."""
    declared = _declared(PLUGINS / "verification-agents")
    assert set(declared) == {
        "library_check_command", "library_import_command", "verification_log_command",
    }
    assert all(spec["type"] == "string" for spec in declared.values())


POSITIONAL = re.compile(r"\$(?:[0-9]|\{[0-9]+\})")


@pytest.mark.parametrize(
    "command",
    sorted(PLUGINS.glob("*/commands/*.md")),
    ids=lambda p: f"{p.parent.parent.name}/{p.name}",
)
def test_command_files_hold_no_positional_placeholders(command: Path) -> None:
    """A `$1` in a command file is replaced with a word of the user's request.

    Claude Code substitutes `$1`, `$2`, and so on in command files, so shell
    written there with its own positional parameters arrives broken. Shell
    that needs arguments belongs in a script under the plugin's `scripts/`.
    """
    found = POSITIONAL.findall(command.read_text())
    assert not found, f"positional placeholders in {command.name}: {sorted(set(found))}"
