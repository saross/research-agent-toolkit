"""Checks against the real gitleaks binary. Skipped where it isn't installed."""

from __future__ import annotations

import os
import random
import secrets
import shutil
import string
import subprocess
from pathlib import Path

import pytest
from conftest import assert_blocked, assert_passed

REAL = Path(os.environ.get("PUBLISH_GUARD_TEST_GITLEAKS",
                           Path.home() / ".config/publish-guard/bin/gitleaks"))

pytestmark = pytest.mark.skipif(not REAL.exists(), reason="the real gitleaks isn't installed")


def _token():
    """A correctly shaped token, made at run time and never stored."""
    alphabet = string.ascii_letters + string.digits
    return "ghp" + "_" + "".join(secrets.choice(alphabet) for _ in range(36))


@pytest.fixture
def real(sandbox):
    sandbox.gitleaks.unlink()
    shutil.copy(REAL, sandbox.gitleaks)
    return sandbox


def test_clean_push_passes(real):
    assert_passed(real.push(), real, real.head())


def test_real_token_blocks_and_stays_hidden(real):
    real.seed_public()
    token = _token()
    sha = real.commit("a.txt", f'token = "{token}"\n')
    result = real.push()
    assert_blocked(result, real, sha)
    assert token not in result.stderr
    assert "github-pat" in result.stderr


def test_inline_allow_does_not_excuse_a_real_token_on_private(real):
    real.git("remote", "set-url", "origin", str(real.private))
    sha = real.commit("a.txt", f'token = "{_token()}" # ' + "gitleaks" + ":allow\n")
    result = real.push()
    assert result.returncode != 0
    assert not real.remote_has(sha, real.private)


def test_repository_config_does_not_excuse_a_real_token_on_private(real):
    real.git("remote", "set-url", "origin", str(real.private))
    (real.work / (".gitleaks" + ".toml")).write_text(
        '[allowlist]\npaths = [".*"]\nregexes = [".*"]\n'
    )
    real.git("add", ".")
    real.git("commit", "-q", "-m", "add scanner config")
    sha = real.commit("a.txt", f'token = "{_token()}"\n')
    result = real.push()
    assert result.returncode != 0
    assert not real.remote_has(sha, real.private)


def test_ignore_file_does_not_excuse_a_real_token_on_private(real):
    real.git("remote", "set-url", "origin", str(real.private))
    (real.work / ".gitleaksignore").write_text("*\n")
    real.git("add", ".")
    real.git("commit", "-q", "-m", "add ignore")
    sha = real.commit("a.txt", f'token = "{_token()}"\n')
    result = real.push()
    assert result.returncode != 0
    assert not real.remote_has(sha, real.private)


def test_environment_config_does_not_excuse_a_real_token(real, tmp_path):
    planted = tmp_path / "planted.toml"
    planted.write_text('[allowlist]\nregexes = [".*"]\n')
    real.seed_public()
    sha = real.commit("a.txt", f'token = "{_token()}"\n')
    env = dict(real.env, GITLEAKS_CONFIG=str(planted))
    result = subprocess.run(
        ["git", "push", "origin", "HEAD:refs/heads/main"], env=env, cwd=real.work,
        capture_output=True, text=True,
    )
    assert_blocked(result, real, sha)


def _alphanumeric(length, seed=20261108):
    """A fixed random-looking value. A fresh one each run made a test flaky: gitleaks' generic
    rule skips values that happen to contain a common word, so now and then one wasn't flagged.
    """
    alphabet = string.ascii_letters + string.digits
    chooser = random.Random(seed)
    return "".join(chooser.choice(alphabet) for _ in range(length))


@pytest.mark.parametrize(
    "line",
    [
        'GET https://example.invalid/v1/files?pageSize=100&pageToken={value} "HTTP/1.1 200 OK"',
        '    "citationKey": "{value}",',
        '    "rekeyed": "{value}.png",',
    ],
    ids=["paging-cursor", "citation-key", "file-name-value"],
)
def test_known_lookalikes_do_not_block(real, line):
    real.seed_public()
    sha = real.commit("a.txt", line.format(value=_alphanumeric(40)) + "\n")
    assert_passed(real.push(), real, sha)


def test_generic_key_still_blocks(real):
    real.seed_public()
    sha = real.commit("a.txt", f'api_key = "{_alphanumeric(40)}"\n')
    assert_blocked(real.push(), real, sha)


def test_exception_does_not_excuse_a_recognised_credential_on_the_same_line(real):
    real.seed_public()
    line = f'url?pageToken=abc token = "{_token()}"\n'
    sha = real.commit("a.txt", line)
    assert_blocked(real.push(), real, sha)
