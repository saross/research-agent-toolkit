"""
test_bundled_paths.py
=====================

Checks that what a plugin's text points at is really in the plugin.

Skill, agent, and command files name their own bundled files as
``${CLAUDE_PLUGIN_ROOT}/<path>``, which Claude Code replaces with the
installed plugin's folder. A misspelt or moved path is not caught by
``claude plugin validate``; the model would be sent to a file that does not
exist. These tests resolve every such reference, and check that each skill's
front matter names the skill as its folder does.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PLUGINS = Path(__file__).resolve().parents[2] / "plugins"
# A path after the root variable: stops at whitespace, quotes, backticks, or brackets.
REFERENCE = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/([^\s\"'`)\]>]+)")


def _texts() -> list[Path]:
    """Every Markdown file that Claude Code reads as plugin content."""
    return sorted(
        p for folder in ("agents", "commands", "skills")
        for p in PLUGINS.glob(f"*/{folder}/**/*.md")
    )


@pytest.mark.parametrize(
    "text", _texts(), ids=lambda p: str(p.relative_to(PLUGINS)),
)
def test_every_bundled_reference_exists(text: Path) -> None:
    """Each referenced path exists inside the plugin that names it."""
    plugin = text.relative_to(PLUGINS).parts[0]
    root = PLUGINS / plugin
    missing = []
    for ref in REFERENCE.findall(text.read_text()):
        target = ref.rstrip(".,;:")
        if not (root / target).exists():
            missing.append(target)
    assert not missing, f"missing in {plugin}: {missing}"


@pytest.mark.parametrize(
    "skill", sorted(PLUGINS.glob("*/skills/*/SKILL.md")),
    ids=lambda p: f"{p.parent.parent.parent.name}/{p.parent.name}",
)
def test_skill_front_matter_names_its_folder(skill: Path) -> None:
    """A skill's front matter has a name equal to its folder, and a description."""
    text = skill.read_text()
    assert text.startswith("---\n"), "no front matter"
    front = text.split("---\n", 2)[1]
    name = re.search(r"^name:\s*(\S+)\s*$", front, re.MULTILINE)
    assert name and name.group(1) == skill.parent.name
    assert re.search(r"^description:", front, re.MULTILINE)
