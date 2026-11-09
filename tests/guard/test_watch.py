"""The watcher: what it finds after the fact, and what it leaves alone.

GitHub is played by a fake `gh` that answers from a JSON file, and by local bare repositories that
the watcher reads in place of github.com. Content reaches the "public" repository by
`git push --no-verify`, standing in for every route the pre-push check doesn't see.

The second half holds the regression tests for Astra's review of the watcher (W1 to W6, 8
November 2026). Each asserts the safe behaviour, so it fails if the problem returns.
"""

from __future__ import annotations

import fcntl
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from conftest import ENGINE, FAKE_SECRET, PERSON, PUBLIC_NAME

FAKE_GH = textwrap.dedent(
    """\
    #!{python}
    import json, sys
    args = sys.argv[1:]
    world = json.load(open({world!r}))
    if args[:2] == ["repo", "list"] and "list" in world.get("fail", []):
        sys.exit(1)
    if args[:2] == ["repo", "list"] and "badlist" in world.get("fail", []):
        print("{{}}")
        sys.exit(0)
    if args[:1] == ["api"] and "alerts" in world.get("fail", []):
        sys.exit(1)
    if args[:2] == ["repo", "list"]:
        owner = args[2]
        rows = [{{"nameWithOwner": name, "visibility": vis.split(",")[0].upper(),
                  "isArchived": vis.endswith(",archived")}}
                for name, vis in world["repos"].items() if name.split("/")[0] == owner]
        print(json.dumps(rows))
        sys.exit(0)
    if args[:1] == ["api"] and "secret-scanning" in args[1]:
        parts = args[1].split("/")
        print(world.get("alerts", {{}}).get(parts[1] + "/" + parts[2], 0))
        sys.exit(0)
    sys.exit(1)
    """
)


class Watch:
    """A sandbox set up for the watcher."""

    def __init__(self, sandbox) -> None:
        self.sandbox = sandbox
        self.world_file = sandbox.root / "github.json"
        self.world = {"repos": {PUBLIC_NAME: "public"}, "alerts": {}}
        self.save_world()
        gh = sandbox.root / "bin" / "gh"
        gh.write_text(FAKE_GH.format(python=sys.executable, world=str(self.world_file)))
        gh.chmod(0o755)
        record = sandbox.guard / "install.json"
        record.chmod(0o600)
        data = json.loads(record.read_text())
        data["gh"] = str(gh)
        data["watch_urls"] = {PUBLIC_NAME: str(sandbox.public)}
        record.write_text(json.dumps(data))
        self.report = sandbox.root / "report.md"
        self.save_policy()

    def save_world(self) -> None:
        self.world_file.write_text(json.dumps(self.world))

    def save_policy(self) -> None:
        self.sandbox.save_policy()
        path = self.sandbox.guard / "policy.toml"
        text = path.read_text()
        path.write_text('watch_owners = ["test"]\n' + text)

    def run(self, *extra: str):
        return self.sandbox.engine("watch", "--report", str(self.report), *extra)

    def publish_unchecked(self, path: str, text: str) -> str:
        """Commit and push past the pre-push check, as another route would."""
        sha = self.sandbox.commit(path, text)
        subprocess.run(
            ["git", "push", "-q", "--no-verify", "origin", "HEAD:refs/heads/main"],
            cwd=self.sandbox.work, env=self.sandbox.env, check=True,
        )
        return sha


@pytest.fixture
def watch(sandbox):
    return Watch(sandbox)


def test_first_run_records_and_reads_nothing(watch):
    watch.publish_unchecked("a.txt", f"{PERSON}\n")
    result = watch.run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "seen for the first time" in result.stdout
    assert "Nothing needs attention" in watch.report.read_text()


def test_new_content_with_a_listed_name_is_reported_without_the_name(watch):
    watch.publish_unchecked("README.md", "hello again\n")
    assert watch.run().returncode == 0
    watch.publish_unchecked("a.txt", f"{PERSON}\n")
    result = watch.run()
    assert result.returncode == 1, result.stdout + result.stderr
    report = watch.report.read_text()
    assert "tier2a-people" in report
    assert "a.txt:1" in report
    assert PERSON not in report and PERSON not in result.stdout


def test_a_secret_is_reported(watch):
    watch.publish_unchecked("README.md", "hello again\n")
    watch.run()
    watch.publish_unchecked("config.txt", f"key = {FAKE_SECRET}\n")
    result = watch.run()
    assert result.returncode == 1
    assert "secret:fake-rule" in watch.report.read_text()
    assert FAKE_SECRET not in watch.report.read_text()


def test_clean_new_content_passes(watch):
    watch.publish_unchecked("README.md", "hello again\n")
    watch.run()
    watch.publish_unchecked("b.txt", "ordinary text\n")
    result = watch.run()
    assert result.returncode == 0, result.stdout
    assert "Nothing needs attention" in watch.report.read_text()


def test_findings_stay_until_cleared(watch):
    watch.publish_unchecked("README.md", "hello again\n")
    watch.run()
    watch.publish_unchecked("a.txt", f"{PERSON}\n")
    watch.run()
    assert watch.run().returncode == 1  # still listed on the next, quiet run
    assert "cleared 1" in watch.sandbox.engine("watch", "--clear", PUBLIC_NAME).stdout
    assert watch.run().returncode == 0


def test_never_public_repository_that_is_public_raises_an_alert(watch):
    watch.sandbox.policy["repos"]["test/diary"] = {"label": "never-public"}
    watch.save_policy()
    watch.world["repos"]["test/diary"] = "public"
    watch.save_world()
    result = watch.run()
    assert result.returncode == 1
    assert "ALERT test/diary is labelled never-public but is public" in watch.report.read_text()


def test_public_repository_without_a_policy_entry_is_reported(watch):
    watch.world["repos"]["test/brand-new"] = "public"
    watch.save_world()
    result = watch.run()
    assert result.returncode == 1
    assert "test/brand-new is public and has no policy entry" in watch.report.read_text()


def test_archived_public_repository_without_an_entry_is_only_noted(watch):
    watch.world["repos"]["test/old-poster"] = "public,archived"
    watch.save_world()
    result = watch.run()
    assert result.returncode == 0, result.stdout
    assert "archived public repository(ies) have no policy entry: test/old-poster" in result.stdout


def test_private_repository_without_a_policy_entry_is_left_alone(watch):
    watch.world["repos"]["test/working-notes"] = "private"
    watch.save_world()
    assert watch.run().returncode == 0


def test_open_secret_scanning_alerts_are_reported(watch):
    watch.world["alerts"] = {PUBLIC_NAME: 2}
    watch.save_world()
    result = watch.run()
    assert result.returncode == 1
    assert "2 open secret-scanning alert(s)" in watch.report.read_text()


def test_agent_publishing_routes_are_counted_once(watch):
    log = watch.sandbox.guard / "log" / "agent-hook.jsonl"
    log.parent.mkdir(exist_ok=True)
    log.write_text(json.dumps({"time": "t", "route": "gh-repo-create", "cwd": "/x"}) + "\n")
    assert "gh-repo-create 1" in watch.run().stdout
    assert "gh-repo-create" not in watch.run().stdout


def test_a_quiet_run_leaves_the_reports_content_unchanged(watch):
    """A run marks the report as in progress, then restores it: a quiet run leaves the same
    content, so a repository holding the report sees no change."""
    watch.run()  # the first run records the repository, which its report notes
    watch.run()
    first = watch.report.read_bytes()
    watch.run()
    assert watch.report.read_bytes() == first


def test_repositories_of_other_owners_are_not_read_unless_asked(watch):
    """Owners outside watch_owners (an organisation's busy repositories) get visibility checks
    only, unless their entry says watch = true."""
    watch.sandbox.policy["repos"]["other/busy"] = {"label": "public"}
    watch.save_policy()
    watch.world["repos"]["other/busy"] = "public"
    watch.save_world()
    result = watch.run()
    assert "other/busy" not in result.stdout


# ------------------------------------------------------------ Astra's watcher review, W1 to W6

INCOMPLETE = 3


def _engine_module():
    sys.path.insert(0, str(ENGINE.parent))
    try:
        import publish_guard
    finally:
        sys.path.pop(0)
    return publish_guard


def _watch_patched(watch, monkeypatch, patch) -> int:
    """Run the watcher in this process, after `patch(engine)` has replaced what it needs."""
    for key, value in watch.sandbox.env.items():
        monkeypatch.setenv(key, value)
    engine = _engine_module()
    patch(engine)
    args = engine.build_parser().parse_args(
        ["--home", str(watch.sandbox.guard), "watch", "--report", str(watch.report)]
    )
    return engine.command_watch(Path(args.home), args)


def _watch_in_process(watch, monkeypatch, after_listing) -> int:
    """Run the watcher in this process, calling `after_listing` between listing a repository's
    refs and fetching them: the window in which a ref can move."""

    def patch(engine):
        listing = engine.remote_refs

        def listing_then_move(*args, **kwargs):
            refs = listing(*args, **kwargs)
            after_listing()
            return refs

        monkeypatch.setattr(engine, "remote_refs", listing_then_move)

    return _watch_patched(watch, monkeypatch, patch)


def _move_public_main(watch, sha: str) -> None:
    subprocess.run(["git", "update-ref", "refs/heads/main", sha], cwd=watch.sandbox.public,
                   env=watch.sandbox.env, check=True)


def _steady_state(watch) -> str:
    """Baseline, then one ordinary read, so the mirror exists before the race. A first clone
    from a local folder links every object in, unreachable ones too, which GitHub wouldn't send,
    so racing the first clone would test nothing. Returns the clean tip."""
    watch.publish_unchecked("README.md", "hello again\n")
    watch.run()
    clean = watch.publish_unchecked("b.txt", "ordinary text\n")
    assert watch.run().returncode == 0
    assert (watch.sandbox.guard / "watch" / "mirrors" / "test__public.git").is_dir()
    return clean


def _state(watch) -> dict:
    return json.loads((watch.sandbox.guard / "watch" / "state.json").read_text())


def test_w1_a_ref_moved_back_before_the_fetch_is_still_read(watch, monkeypatch):
    clean = _steady_state(watch)
    watch.publish_unchecked("config.txt", f"key = {FAKE_SECRET}\n")
    status = _watch_in_process(watch, monkeypatch, lambda: _move_public_main(watch, clean))
    assert status == 1
    assert "secret:fake-rule" in watch.report.read_text()


def test_w1_an_advertised_object_that_cant_be_fetched_is_never_counted_as_read(
    watch, monkeypatch
):
    clean = _steady_state(watch)
    leaked = watch.publish_unchecked("config.txt", f"key = {FAKE_SECRET}\n")

    def correct_and_collect():
        _move_public_main(watch, clean)
        subprocess.run(["git", "gc", "-q", "--prune=now"], cwd=watch.sandbox.public,
                       env=watch.sandbox.env, check=True)

    assert _watch_in_process(watch, monkeypatch, correct_and_collect) == INCOMPLETE
    report = watch.report.read_text()
    assert "INCOMPLETE" in report and "couldn't be fetched" in report
    assert leaked in {sha for _, sha in _state(watch)["repos"][PUBLIC_NAME]["pending"]}
    # The next run, with nothing moving, still says so.
    result = watch.run()
    assert result.returncode == INCOMPLETE, result.stdout
    # A person can acknowledge it; then the watcher is clean again.
    cleared = watch.sandbox.engine("watch", "--clear", PUBLIC_NAME)
    assert "1 object(s)" in cleared.stdout
    assert watch.run().returncode == 0


def test_w2_a_source_edited_but_not_rebuilt_stops_the_watcher_and_is_read_after(watch):
    sources = watch.sandbox.guard / "deny-sources"
    sources.mkdir()
    (sources / "tier4-commercial.txt").write_text("acme widgets\n")
    assert watch.sandbox.engine("deny-rebuild").returncode == 0
    watch.publish_unchecked("README.md", "hello again\n")
    watch.run()
    (sources / "tier4-commercial.txt").write_text("acme widgets\nzorblat frobnitz\n")
    watch.publish_unchecked("b.txt", "zorblat frobnitz\n")
    result = watch.run()
    assert result.returncode == INCOMPLETE
    assert "edited but not rebuilt" in watch.report.read_text()
    assert watch.sandbox.engine("deny-rebuild").returncode == 0
    result = watch.run()
    assert result.returncode == 1, result.stdout
    assert "tier4-commercial" in watch.report.read_text()


def test_w2_content_read_under_old_rules_is_read_again_when_they_change(watch):
    watch.publish_unchecked("README.md", "hello again\n")
    watch.run()
    watch.publish_unchecked("b.txt", "zorblat frobnitz\n")
    assert watch.run().returncode == 0  # not listed yet, so clean
    watch.sandbox.deny_add("tier2a-people", "zorblat frobnitz")
    result = watch.run()
    assert result.returncode == 1, result.stdout
    assert "b.txt:1" in watch.report.read_text()


def test_w2_rescan_reads_history_from_before_the_first_sight(watch):
    watch.publish_unchecked("a.txt", f"{PERSON}\n")
    result = watch.run()
    assert "initial audit pending" in result.stdout
    assert watch.run("--rescan", PUBLIC_NAME).returncode == 1
    result = watch.run()
    assert "tier2a-people" in watch.report.read_text()
    assert "initial audit pending" not in result.stdout


def test_w2_a_first_state_file_is_upgraded_with_its_history_marked_unread(watch):
    watch.publish_unchecked("README.md", "hello again\n")
    refs = watch.sandbox.remote_refs().split()
    path = watch.sandbox.guard / "watch" / "state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"repos": {PUBLIC_NAME: {"refs": {refs[1]: refs[0]}}},
                                "findings": []}))
    result = watch.run()
    assert result.returncode == 0, result.stdout
    assert "initial audit pending" in result.stdout


def test_w4_a_failed_owner_listing_is_incomplete_not_clean(watch):
    watch.world["fail"] = ["list"]
    watch.save_world()
    result = watch.run()
    assert result.returncode == INCOMPLETE
    report = watch.report.read_text()
    assert "couldn't list test's repositories" in report
    assert "Status: INCOMPLETE" in report


def test_w4_a_failed_alert_lookup_says_coverage_is_missing(watch):
    watch.world["fail"] = ["alerts"]
    watch.save_world()
    result = watch.run()
    assert result.returncode == INCOMPLETE
    assert "secret-scanning alerts couldn't be read" in watch.report.read_text()


def test_w4_a_broken_prerequisite_still_writes_a_current_report(watch):
    watch.publish_unchecked("README.md", "hello again\n")
    assert watch.run().returncode == 0
    (watch.sandbox.guard / "deny" / "tier2b-teaching.hashes").write_text("not a tier file\n")
    result = watch.run()
    assert result.returncode == INCOMPLETE
    report = watch.report.read_text()
    assert "the watcher couldn't run" in report and "Status: INCOMPLETE" in report


def test_w4_a_broken_prerequisite_keeps_earlier_findings_in_the_report(watch):
    watch.publish_unchecked("README.md", "hello again\n")
    watch.run()
    watch.publish_unchecked("a.txt", f"{PERSON}\n")
    assert watch.run().returncode == 1
    (watch.sandbox.guard / "deny" / "tier2b-teaching.hashes").write_text("not a tier file\n")
    assert watch.run().returncode == INCOMPLETE
    assert "tier2a-people" in watch.report.read_text()


def test_w4_a_second_run_at_once_does_nothing_and_says_so(watch):
    lock_path = watch.sandbox.guard / "watch" / "lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        result = watch.run()
    assert result.returncode == INCOMPLETE
    assert "another watch is running" in result.stderr
    assert not watch.report.exists()


def test_w4_the_service_counts_only_findings_as_success():
    service = (ENGINE.parent / "systemd" / "publish-guard-watch.service").read_text()
    assert "SuccessExitStatus=1\n" in service
    assert "TimeoutStartSec=" in service


def test_w5_cleared_findings_stay_acknowledged_when_read_again(watch):
    watch.publish_unchecked("README.md", "hello again\n")
    watch.run()
    watch.publish_unchecked("a.txt", f"{PERSON}\n")
    watch.run()
    watch.sandbox.engine("watch", "--clear", PUBLIC_NAME)
    watch.sandbox.deny_add("tier2b-teaching", "zorblat frobnitz")  # the rules change, so reread
    result = watch.run()
    assert result.returncode == 0, result.stdout
    assert "acknowledged with `--clear`" in result.stdout


def test_w6_a_repository_name_holding_a_listed_term_is_withheld(watch):
    name = "test/" + PERSON.replace(" ", "-")
    watch.world["repos"][name] = "public"
    watch.save_world()
    result = watch.run()
    assert result.returncode == 1
    assert "<repository withheld" in watch.report.read_text()
    for text in (result.stdout, watch.report.read_text()):
        for word in PERSON.split():
            assert word not in text


# ------------------------------------------------- Astra's hardening review, H1 to H4


def test_h1_a_listed_object_survives_a_failed_fetch_and_a_later_correction(watch, monkeypatch):
    clean = _steady_state(watch)
    leaked = watch.publish_unchecked("config.txt", f"key = {FAKE_SECRET}\n")

    def fetch_fails(engine):
        def refuse(*args, **kwargs):
            raise engine.GuardError("fetching the repository failed")

        monkeypatch.setattr(engine, "refresh_mirror", refuse)

    assert _watch_patched(watch, monkeypatch, fetch_fails) == INCOMPLETE
    assert leaked in {sha for _, sha in _state(watch)["repos"][PUBLIC_NAME]["pending"]}
    monkeypatch.undo()
    _move_public_main(watch, clean)  # corrected before the next run
    result = watch.run()
    assert result.returncode == 1, result.stdout
    assert "secret:fake-rule" in watch.report.read_text()


def test_h2_a_list_rebuilt_during_a_run_doesnt_label_old_reading_as_new(watch, monkeypatch):
    _steady_state(watch)
    watch.publish_unchecked("c.txt", "zorblat frobnitz\n")

    def list_changes_midway(engine):
        listing = engine.owner_listing

        def add_then_list(*args, **kwargs):
            watch.sandbox.deny_add("tier2a-people", "zorblat frobnitz")
            return listing(*args, **kwargs)

        monkeypatch.setattr(engine, "owner_listing", add_then_list)

    assert _watch_patched(watch, monkeypatch, list_changes_midway) == 0  # read under old lists
    monkeypatch.undo()
    result = watch.run()
    assert result.returncode == 1, result.stdout
    assert "c.txt:1" in watch.report.read_text()


def test_h3_a_path_listed_after_its_finding_is_withheld_from_later_reports(watch):
    watch.publish_unchecked("README.md", "hello again\n")
    watch.run()
    watch.publish_unchecked("zorblat-frobnitz.txt", f"key = {FAKE_SECRET}\n")
    assert watch.run().returncode == 1
    assert "zorblat" in watch.report.read_text()  # not listed yet, so shown
    watch.sandbox.deny_add("tier2b-teaching", "zorblat frobnitz")
    result = watch.run()
    assert result.returncode == 1
    for text in (result.stdout, watch.report.read_text()):
        assert "zorblat" not in text
    # A failure report, with no usable list, withholds it too.
    (watch.sandbox.guard / "deny" / "tier2a-people.hashes").write_text("not a tier file\n")
    result = watch.run()
    assert result.returncode == INCOMPLETE
    for text in (result.stdout, watch.report.read_text()):
        assert "zorblat" not in text
        assert "<path hidden>" in text


def test_h3_an_owner_error_never_names_the_owner(watch):
    owner = PERSON.replace(" ", "-")
    watch.sandbox.policy["repos"][f"{owner}/notes"] = {"label": "never-public"}
    watch.save_policy()
    watch.world["fail"] = ["badlist"]
    watch.save_world()
    result = watch.run()
    assert result.returncode == INCOMPLETE
    for text in (result.stdout, watch.report.read_text()):
        for word in PERSON.split():
            assert word not in text


def test_h4_a_run_stopped_from_outside_leaves_the_report_incomplete(watch, monkeypatch):
    _steady_state(watch)
    assert "Status: clean" in watch.report.read_text()
    watch.publish_unchecked("d.txt", "more ordinary text\n")

    def stopped(engine):
        def interrupt(*args, **kwargs):
            raise KeyboardInterrupt  # like a signal: no handler in the watcher runs

        monkeypatch.setattr(engine, "scan_new_content", interrupt)

    with pytest.raises(KeyboardInterrupt):
        _watch_patched(watch, monkeypatch, stopped)
    report = watch.report.read_text()
    assert "Status: INCOMPLETE" in report and "hasn't finished" in report


def test_clean_says_so_when_history_is_still_unread(watch):
    watch.publish_unchecked("README.md", "hello again\n")
    watch.run()
    report = watch.report.read_text()
    assert "Status: clean" in report and "Some history isn't read yet" in report


# ------------------------------------------------- Astra's follow-up review, R1 and R2


@pytest.mark.parametrize("damage", ["undecodable-list", "malformed-finding"])
def test_r1_damaged_input_at_start_leaves_an_incomplete_report_not_a_clean_one(watch, damage):
    _steady_state(watch)
    assert "Status: clean" in watch.report.read_text()
    if damage == "undecodable-list":
        (watch.sandbox.guard / "deny" / "tier2a-people.hashes").write_bytes(b"\xff\xfe\xfa\x00")
    else:
        path = watch.sandbox.guard / "watch" / "state.json"
        state = json.loads(path.read_text())
        state["findings"] = [{}]
        path.write_text(json.dumps(state))
    result = watch.run()
    assert result.returncode == INCOMPLETE, result.stdout + result.stderr
    report = watch.report.read_text()
    assert "Status: INCOMPLETE" in report and "Status: clean" not in report


def test_r2_repositories_failing_or_cut_off_dont_starve_the_rest(watch, monkeypatch):
    for name in ("test/aaa", "test/aab", "test/aac", "test/zzz"):
        watch.sandbox.policy["repos"][name] = {"label": "public"}
        watch.world["repos"][name] = "public"
    watch.save_policy()
    watch.save_world()
    visits: list[list[str]] = []

    def patch(engine):
        listing = engine.remote_refs

        def listing_with_trouble(git, url, outside):
            name = next((n for n in ("aaa", "aab", "aac", "zzz") if url.endswith(n + ".git")),
                        "public")
            visits[-1].append(name)
            if name in ("aaa", "aab"):
                raise engine.GuardError("asking the remote what it has failed")
            if name == "aac":
                raise KeyboardInterrupt  # the outer time limit stops the run here
            if name == "zzz":
                return {}
            return listing(git, url, outside)

        monkeypatch.setattr(engine, "remote_refs", listing_with_trouble)

    for _ in range(2):
        visits.append([])
        with pytest.raises(KeyboardInterrupt):
            _watch_patched(watch, monkeypatch, patch)
        monkeypatch.undo()  # so the next run's patch wraps the real listing, not this one
    assert "zzz" not in visits[0]
    assert visits[1][:2] == ["public", "zzz"], visits


# ------------------------------------------------- Astra's review of 546298b, R3


def test_r3_an_unwritable_report_still_ends_in_the_failure_status(watch):
    folder = watch.sandbox.root / "reports"
    folder.mkdir()
    report = folder / "watch.md"
    watch.publish_unchecked("README.md", "hello again\n")
    assert watch.sandbox.engine("watch", "--report", str(report)).returncode == 0
    folder.chmod(0o500)
    try:
        result = watch.sandbox.engine("watch", "--report", str(report))
    finally:
        folder.chmod(0o700)
    assert result.returncode == INCOMPLETE, result.stdout + result.stderr
    assert "treat this run as incomplete" in result.stderr


def test_r3_a_report_that_fails_after_the_scan_isnt_an_accepted_status(watch, monkeypatch):
    _steady_state(watch)
    watch.publish_unchecked("e.txt", "ordinary text again\n")
    calls = []

    def patch(engine):
        writer = engine.write_watch_report

        def fails_after_the_markers(path, body):
            calls.append(path)
            if len(calls) > 2:  # the two in-progress markers succeed; the real report doesn't
                raise OSError("disk full")
            writer(path, body)

        monkeypatch.setattr(engine, "write_watch_report", fails_after_the_markers)

    assert _watch_patched(watch, monkeypatch, patch) == INCOMPLETE
    assert "Status: INCOMPLETE" in watch.report.read_text()  # the marker stays
