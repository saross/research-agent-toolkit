"""What a push to a public repository may and may not carry."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from conftest import (
    FAKE_SECRET,
    HOME_PATH,
    PERSON,
    PRIVATE_IP,
    SSH_HOST_LINE,
    SSH_PORT_FLAG,
    TEACHING,
    assert_blocked,
    assert_passed,
)


def test_clean_push_passes(sandbox):
    assert_passed(sandbox.push(), sandbox, sandbox.head())


def test_block_message_has_a_stable_marker_even_though_git_hides_exit_codes(sandbox):
    sandbox.seed_public()
    sandbox.commit("a.txt", f"{PERSON}\n")
    result = sandbox.push()
    assert result.returncode == 1  # git's own status, whatever the hook returned
    assert "publish-guard: BLOCKED" in result.stderr


@pytest.mark.parametrize(
    "text",
    [
        f"note about {PERSON} here\n",
        f"{PERSON.upper()}\n",
        f"{PERSON.replace(' ', '-')}\n",
        f"{PERSON.replace(' ', '_')}\n",
        f"{PERSON.replace(' ', '')}\n",
        " ".join(reversed(PERSON.split())) + "\n",
        f"{TEACHING}\n",
    ],
    ids=["plain", "upper", "hyphen", "underscore", "joined", "reversed", "frozen-teaching-tier"],
)
def test_deny_term_in_a_line(sandbox, text):
    sandbox.seed_public()
    sha = sandbox.commit("a.txt", text)
    assert_blocked(sandbox.push(), sandbox, sha)


def test_deny_term_split_across_a_line_wrap(sandbox):
    first, second = PERSON.split()
    sandbox.seed_public()
    sha = sandbox.commit("a.txt", f"written by {first}\n{second} last year\n")
    assert_blocked(sandbox.push(), sandbox, sha)


def test_accented_and_fullwidth_forms_match(sandbox):
    sandbox.deny_add("tier2a-people", "rene zoltan")
    sandbox.seed_public()
    sha = sandbox.commit("a.txt", "René ｚｏｌｔａｎ\n")
    assert_blocked(sandbox.push(), sandbox, sha)


def test_cjk_name_matches_inside_a_longer_run(sandbox):
    sandbox.deny_add("tier2b-teaching", "王小明")
    sandbox.seed_public()
    sha = sandbox.commit("a.txt", "作者是王小明同学\n")
    assert_blocked(sandbox.push(), sandbox, sha)


def test_deny_term_in_commit_message(sandbox):
    sandbox.seed_public()
    sha = sandbox.commit("a.txt", "fine\n", f"docs: thanks to {PERSON}")
    assert_blocked(sandbox.push(), sandbox, sha)


def test_deny_term_in_filename_is_masked(sandbox):
    sandbox.seed_public()
    sha = sandbox.commit(PERSON.replace(" ", "-") + ".md", "fine\n")
    result = sandbox.push()
    assert_blocked(result, sandbox, sha)
    assert "<path hidden>" in result.stderr


@pytest.mark.parametrize("who", ["AUTHOR", "COMMITTER"])
def test_deny_term_in_identity(sandbox, who):
    sandbox.seed_public()
    env = dict(sandbox.env)
    env[f"GIT_{who}_NAME"] = PERSON
    env[f"GIT_{who}_EMAIL"] = "someone@example.invalid"
    sha = sandbox.commit("a.txt", "fine\n", env=env)
    assert_blocked(sandbox.push(), sandbox, sha)


def test_deny_term_in_branch_name(sandbox):
    sandbox.seed_public()
    sandbox.commit("a.txt", "fine\n")
    branch = PERSON.replace(" ", "-")
    assert_blocked(sandbox.push("origin", f"HEAD:refs/heads/{branch}"), sandbox)


def test_term_added_then_reverted_in_the_range(sandbox):
    sandbox.seed_public()
    first = sandbox.commit("a.txt", f"{PERSON}\n")
    sandbox.commit("a.txt", "clean again\n")
    assert_blocked(sandbox.push(), sandbox, first)


def test_preexisting_public_content_does_not_block(sandbox):
    # Legacy content reached the remote before the guard existed.
    sandbox.commit("legacy.txt", f"{PERSON}\n")
    subprocess.run(
        ["git", "push", "-q", "--no-verify", "origin", "HEAD:refs/heads/main"],
        cwd=sandbox.work, env=sandbox.env, check=True,
    )
    sha = sandbox.commit("new.txt", "fine\n")
    assert_passed(sandbox.push(), sandbox, sha)


def test_editing_near_legacy_content_scans_only_added_lines(sandbox):
    sandbox.commit("legacy.txt", f"{PERSON}\nline two\n")
    subprocess.run(
        ["git", "push", "-q", "--no-verify", "origin", "HEAD:refs/heads/main"],
        cwd=sandbox.work, env=sandbox.env, check=True,
    )
    sha = sandbox.commit("legacy.txt", f"{PERSON}\nline two changed\n")
    assert_passed(sandbox.push(), sandbox, sha)


def test_changing_a_file_mode_adds_no_content(sandbox):
    sandbox.commit("legacy.sh", f"# {PERSON}\n")
    subprocess.run(
        ["git", "push", "-q", "--no-verify", "origin", "HEAD:refs/heads/main"],
        cwd=sandbox.work, env=sandbox.env, check=True,
    )
    (sandbox.work / "legacy.sh").chmod(0o755)
    sandbox.git("add", "legacy.sh")
    sandbox.git("commit", "-q", "-m", "make it executable")
    assert_passed(sandbox.push(), sandbox, sandbox.head())


def test_a_path_that_is_not_utf8_still_gives_a_useful_report(sandbox):
    sandbox.seed_public()
    process = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"], input=f"{PERSON}\n", text=True,
        capture_output=True, cwd=sandbox.work, env=sandbox.env, check=True,
    )
    name = b"caf\xe9.txt"
    subprocess.run(
        [b"git", b"update-index", b"--add", b"--cacheinfo",
         b"100644," + process.stdout.strip().encode() + b"," + name],
        cwd=sandbox.work, env=sandbox.env, check=True,
    )
    sandbox.git("commit", "-q", "-m", "odd name")
    result = sandbox.push()
    assert_blocked(result, sandbox, sandbox.head())
    assert "internal error" not in result.stderr


# ------------------------------------------------------------------ topology


@pytest.mark.parametrize(
    "text",
    [f"host is {PRIVATE_IP}\n", f"run {SSH_PORT_FLAG} backup-host\n", f"{SSH_HOST_LINE}\n"],
    ids=["private-address", "ssh-port-flag", "ssh-config-block"],
)
def test_topology_patterns_block(sandbox, text):
    sandbox.seed_public()
    sha = sandbox.commit("a.txt", text)
    assert_blocked(sandbox.push(), sandbox, sha)


def test_private_key_header_blocks(sandbox):
    sandbox.seed_public()
    sha = sandbox.commit("a.txt", "-----BEGIN " + "OPENSSH PRIVATE KEY-----\n")
    assert_blocked(sandbox.push(), sandbox, sha)


def test_aliases_and_home_paths_do_not_block_by_default(sandbox):
    sandbox.seed_public()
    sha = sandbox.commit("a.txt", f"ssh backup-host\nsee {HOME_PATH}\n")
    assert_passed(sandbox.push(), sandbox, sha)


def test_home_paths_block_where_the_repository_asks(sandbox):
    sandbox.policy["repos"]["test/public"]["block_home_paths"] = True
    sandbox.save_policy()
    sandbox.seed_public()
    sha = sandbox.commit("a.txt", f"see {HOME_PATH}\n")
    assert_blocked(sandbox.push(), sandbox, sha)


# ------------------------------------------------------------------ secrets


def test_secret_blocks(sandbox):
    sandbox.seed_public()
    sha = sandbox.commit("a.txt", f"token = {FAKE_SECRET}\n")
    result = sandbox.push()
    assert_blocked(result, sandbox, sha)
    assert "fake-rule" in result.stderr


def test_secret_in_commit_message_blocks(sandbox):
    sandbox.seed_public()
    sha = sandbox.commit("a.txt", "fine\n", f"fix: rotate {FAKE_SECRET}")
    assert_blocked(sandbox.push(), sandbox, sha)


def test_gitleaks_runs_locked_from_an_empty_folder_with_a_clean_environment(sandbox):
    sandbox.seed_public()
    (sandbox.work / ".gitleaks.toml").write_text("title = 'planted'\n")
    env_marker = dict(sandbox.env, GITLEAKS_CONFIG="/planted", GITLEAKS_CONFIG_TOML="planted")
    sandbox.commit("a.txt", "fine\n")
    sandbox.calls.write_text("")
    subprocess.run(
        ["git", "push", "origin", "HEAD:refs/heads/main"],
        cwd=sandbox.work, env=env_marker, capture_output=True,
    )
    call = json.loads(sandbox.calls.read_text().splitlines()[-1])
    assert "--ignore-gitleaks-allow" in call["argv"]
    assert "--gitleaks-ignore-path" in call["argv"]
    assert call["argv"][call["argv"].index("--gitleaks-ignore-path") + 1] != "."
    # The rules are written fresh from the engine for each push, outside the repository and
    # outside the guard's folder, where a changed copy could otherwise be read.
    config = call["argv"][call["argv"].index("--config") + 1]
    assert Path(config).name == "gitleaks.toml"
    assert not config.startswith((str(sandbox.guard), str(sandbox.work)))
    assert not [name for name in call["env"] if name.startswith("GITLEAKS")]
    assert os.path.realpath(call["cwd"]) != os.path.realpath(sandbox.work)


@pytest.mark.parametrize(
    "path,text",
    [
        (".gitleaks.toml", "title = 'x'\n"),
        (".gitleaksignore", "abc\n"),
        ("a.txt", "x = 1 # " + "gitleaks" + ":allow\n"),
    ],
    ids=["config-file", "ignore-file", "inline-allow"],
)
def test_changing_the_scanners_rules_blocks_on_public(sandbox, path, text):
    sandbox.seed_public()
    sha = sandbox.commit(path, text)
    assert_blocked(sandbox.push(), sandbox, sha)


# ------------------------------------------------------------------ git mechanics


def test_content_only_in_a_merge_result_blocks(sandbox):
    base = sandbox.seed_public()
    sandbox.git("checkout", "-q", "-b", "side", base)
    sandbox.commit("side.txt", "side\n")
    sandbox.git("checkout", "-q", "-b", "other", base)
    sandbox.commit("other.txt", "other\n")
    sandbox.git("merge", "-q", "--no-commit", "side")
    (sandbox.work / "README.md").write_text(f"hello\n{PERSON}\n")
    sandbox.git("add", "README.md")
    sandbox.git("commit", "-q", "-m", "merge side")
    assert_blocked(sandbox.push(), sandbox, sandbox.head())


def test_ordinary_merge_of_legacy_content_does_not_block(sandbox):
    # Main already holds a legacy term. Merging it into a branch adds nothing new.
    base = sandbox.seed_public()
    sandbox.commit("legacy.txt", f"{PERSON}\n")
    subprocess.run(
        ["git", "push", "-q", "--no-verify", "origin", "HEAD:refs/heads/main"],
        cwd=sandbox.work, env=sandbox.env, check=True,
    )
    main_tip = sandbox.head()
    sandbox.git("checkout", "-q", "-b", "feature", base)
    sandbox.commit("feature.txt", "feature\n")
    sandbox.git("merge", "-q", "--no-edit", main_tip)
    assert_passed(sandbox.push("origin", "HEAD:refs/heads/feature"), sandbox, sandbox.head())


def test_merge_scans_only_what_is_new_against_every_parent(sandbox):
    # Both sides change one file, and main's side carries a legacy term that is already public.
    base = sandbox.seed_public()
    original = (sandbox.work / "README.md").read_text()
    sandbox.commit("README.md", f"{PERSON}\n\n\n\n{original}")
    subprocess.run(
        ["git", "push", "-q", "--no-verify", "origin", "HEAD:refs/heads/main"],
        cwd=sandbox.work, env=sandbox.env, check=True,
    )
    main_tip = sandbox.head()
    sandbox.git("checkout", "-q", "-b", "feature", base)
    sandbox.commit("README.md", f"{original}\n\n\nfeature line\n")
    sandbox.git("merge", "-q", "--no-edit", main_tip)
    assert_passed(sandbox.push("origin", "HEAD:refs/heads/feature"), sandbox, sandbox.head())


@pytest.mark.parametrize("where", ["tracked", "info"])
def test_text_marked_binary_is_still_read(sandbox, where):
    sandbox.seed_public()
    if where == "tracked":
        sandbox.commit(".gitattributes", "*.jsonl -diff\n*.ipynb binary\n")
        sandbox.seed_public()
    else:
        info = sandbox.work / ".git" / "info"
        info.mkdir(exist_ok=True)
        (info / "attributes").write_text("*.jsonl -diff\n")
    sha = sandbox.commit("log.jsonl", f'{{"name": "{PERSON}"}}\n')
    assert_blocked(sandbox.push(), sandbox, sha)


def test_replace_refs_do_not_hide_content(sandbox):
    sandbox.seed_public()
    dirty = sandbox.commit("a.txt", f"{PERSON}\n")
    sandbox.git("reset", "-q", "--hard", "HEAD~1")
    clean = sandbox.commit("a.txt", "clean\n")
    sandbox.git("reset", "-q", "--hard", dirty)
    sandbox.git("replace", dirty, clean)
    assert_blocked(sandbox.push(), sandbox, dirty)


def test_plumbing_commit_is_checked(sandbox):
    sandbox.seed_public()
    process = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"], input=f"{PERSON}\n", text=True,
        capture_output=True, cwd=sandbox.work, env=sandbox.env, check=True,
    )
    index = sandbox.root / "index"
    env = dict(sandbox.env, GIT_INDEX_FILE=str(index))
    sandbox.git("read-tree", "HEAD", env=env)
    sandbox.git(
        "update-index", "--add", "--cacheinfo", f"100644,{process.stdout.strip()},p.txt", env=env
    )
    tree = sandbox.git("write-tree", env=env).stdout.strip()
    sha = sandbox.git("commit-tree", tree, "-p", "HEAD", "-m", "plumbing").stdout.strip()
    assert_blocked(sandbox.push("origin", f"{sha}:refs/heads/main"), sandbox, sha)


def test_new_branch_is_checked_in_full(sandbox):
    sandbox.seed_public()
    first = sandbox.commit("a.txt", f"{PERSON}\n")
    sandbox.commit("b.txt", "fine\n")
    assert_blocked(sandbox.push("origin", "HEAD:refs/heads/topic"), sandbox, first)


def test_force_push_is_checked(sandbox):
    base = sandbox.seed_public()
    sandbox.commit("a.txt", "one\n")
    assert_passed(sandbox.push(), sandbox)
    sandbox.git("reset", "-q", "--hard", base)
    sha = sandbox.commit("a.txt", f"{PERSON}\n")
    assert_blocked(sandbox.push("--force", "origin", "HEAD:refs/heads/main"), sandbox, sha)


def test_annotated_tag_message_on_an_old_commit(sandbox):
    sandbox.seed_public()
    sandbox.git("tag", "-a", "v1", "-m", f"thanks to {PERSON}")
    assert_blocked(sandbox.push("origin", "refs/tags/v1"), sandbox)


def test_tag_on_a_blob_is_refused(sandbox):
    sandbox.seed_public()
    process = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"], input="anything\n", text=True,
        capture_output=True, cwd=sandbox.work, env=sandbox.env, check=True,
    )
    blob = process.stdout.strip()
    sandbox.git("tag", "blobtag", blob)
    assert_blocked(sandbox.push("origin", "refs/tags/blobtag"), sandbox, blob)


def test_refs_outside_heads_and_tags_are_refused_on_public(sandbox):
    sandbox.seed_public()
    sandbox.git("notes", "add", "-m", "a note")
    assert_blocked(sandbox.push("origin", "refs/notes/commits"), sandbox)


def test_submodule_blocks(sandbox):
    sandbox.seed_public()
    sandbox.git(
        "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(sandbox.private), "sub",
        check=False,
    )
    sandbox.git("update-index", "--add", "--cacheinfo", f"160000,{sandbox.head()},vendored")
    sandbox.git("commit", "-q", "-m", "add submodule")
    assert_blocked(sandbox.push(), sandbox, sandbox.head())


def test_gitmodules_file_blocks(sandbox):
    sandbox.seed_public()
    sha = sandbox.commit(".gitmodules", '[submodule "x"]\n\tpath = x\n')
    assert_blocked(sandbox.push(), sandbox, sha)


@pytest.mark.parametrize("target", ["/etc/hostname", "../../outside"], ids=["absolute", "escaping"])
def test_symlink_leaving_the_repository_blocks(sandbox, target):
    sandbox.seed_public()
    (sandbox.work / "link").symlink_to(target)
    sandbox.git("add", "link")
    sandbox.git("commit", "-q", "-m", "link")
    assert_blocked(sandbox.push(), sandbox, sandbox.head())


def test_symlink_inside_the_repository_passes(sandbox):
    sandbox.seed_public()
    (sandbox.work / "link").symlink_to("README.md")
    sandbox.git("add", "link")
    sandbox.git("commit", "-q", "-m", "link")
    assert_passed(sandbox.push(), sandbox, sandbox.head())


def test_symlink_target_is_scanned(sandbox):
    sandbox.seed_public()
    (sandbox.work / "link").symlink_to(PERSON.replace(" ", "-") + ".md")
    sandbox.git("add", "link")
    sandbox.git("commit", "-q", "-m", "link")
    assert_blocked(sandbox.push(), sandbox, sandbox.head())


# ------------------------------------------------------------------ allowed paths and binaries


def test_allowed_paths(sandbox):
    sandbox.policy["repos"]["test/public"]["allowed_paths"] = ["README.md", "docs/**"]
    sandbox.save_policy()
    assert_passed(sandbox.push(), sandbox)
    assert_passed(_commit_and_push(sandbox, "docs/deep/note.md"), sandbox)
    sha = sandbox.commit("wiki/continuity.md", "a perfectly clean line\n")
    assert_blocked(sandbox.push(), sandbox, sha)


def _commit_and_push(sandbox, path):
    sandbox.commit(path, "fine\n")
    return sandbox.push()


def test_rename_to_a_disallowed_path_blocks(sandbox):
    sandbox.policy["repos"]["test/public"]["allowed_paths"] = ["README.md", "docs/**"]
    sandbox.save_policy()
    sandbox.commit("docs/a.md", "fine\n")
    assert_passed(sandbox.push(), sandbox)
    sandbox.git("mv", "docs/a.md", "a.md")
    sandbox.git("commit", "-q", "-m", "move")
    assert_blocked(sandbox.push(), sandbox, sandbox.head())


def _binary_commit(sandbox, path):
    target = sandbox.work / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"\x00\x01binary" * 50)
    sandbox.git("add", "--", path)
    sandbox.git("commit", "-q", "-m", "binary")
    return sandbox.head()


def test_binary_blocks_without_an_allowance(sandbox):
    sandbox.seed_public()
    sha = _binary_commit(sandbox, "scan.pdf")
    assert_blocked(sandbox.push(), sandbox, sha)


def test_binary_passes_on_an_allowed_path_and_is_logged(sandbox):
    sandbox.policy["repos"]["test/public"]["binary_allow"] = ["docs/images/*"]
    sandbox.save_policy()
    sandbox.seed_public()
    sha = _binary_commit(sandbox, "docs/images/plot.png")
    assert_passed(sandbox.push(), sandbox, sha)
    log = (sandbox.guard / "log" / "guard.jsonl").read_text()
    assert "docs/images/plot.png" in log


def test_allowed_binary_is_still_searched_for_terms(sandbox):
    sandbox.policy["repos"]["test/public"]["binary_allow"] = ["docs/images/*"]
    sandbox.save_policy()
    sandbox.seed_public()
    target = sandbox.work / "docs/images/plot.png"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"\x00\x01" + PERSON.encode() + b"\x00")
    sandbox.git("add", "docs/images/plot.png")
    sandbox.git("commit", "-q", "-m", "binary")
    assert_blocked(sandbox.push(), sandbox, sandbox.head())


def test_lfs_pointer_blocks_without_an_allowance(sandbox):
    sandbox.seed_public()
    pointer = (
        "version https://git-lfs.github.com/spec/v1\n"
        "oid sha256:" + "a" * 64 + "\nsize 12345\n"
    )
    sha = sandbox.commit("big.bin", pointer)
    assert_blocked(sandbox.push(), sandbox, sha)


def test_large_text_is_not_a_way_around_the_scan(sandbox):
    sandbox.seed_public()
    sha = sandbox.commit("a.txt", ("padding line\n" * 2000) + f"{PERSON}\n")
    assert_blocked(sandbox.push(), sandbox, sha)
