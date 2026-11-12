"""
test_review_paper_workflow.py
=============================

Offline tests of the review-paper workflow (``scripts/review-paper.mjs``).

The workflow's verdict is meant to be computed from finding severities and
never taken from any agent's opinion, and a panel with failed agents must
say its coverage is partial rather than pass as clean. Both are logic in the
script, so they can be tested without a model: ``workflow_harness.mjs``
runs the real script under Node with stand-in agents whose answers each
test chooses. Node is needed; the tests skip without it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "review-paper.mjs"
HARNESS = HERE / "workflow_harness.mjs"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

REPO = "/papers/example"
TARGET = f"{REPO}/sections/methods.tex"
CORE_LENSES = {"source-fidelity", "consistency", "calibration", "completeness"}


def run(tmp_path: Path, args: Any, responses: dict | None = None,
        default: dict | None = None) -> dict:
    """Run the workflow under the harness and return its JSON report."""
    scenario = {"args": args, "responses": responses or {}}
    if default is not None:
        scenario["default"] = default
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(scenario), encoding="utf-8")
    proc = subprocess.run(
        [NODE, str(HARNESS), str(SCRIPT), str(path)],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def base_args(**extra: Any) -> dict:
    """Minimal valid arguments for one section."""
    return {"targets": [TARGET], "repo": REPO, **extra}


def finding(severity: str, evidence: str = "sections/methods.tex:10", **extra: Any) -> dict:
    """One lens finding of the given severity."""
    return {"severity": severity, "dimension": "test", "detail": "a problem",
            "evidence": evidence, **extra}


def adversarial_finding(severity: str, evidence: str = "sections/methods.tex:10") -> dict:
    """A finding carrying the adversarial stance's required fields."""
    return finding(severity, evidence, targetClaim="the claim",
                   counterCondition="if shown X", retractionCondition="evidence Y")


def lens_labels(report: dict) -> set[str]:
    """The lens keys that the panel dispatched."""
    return {c["label"].split(":")[0] for c in report["calls"] if c["phase"] == "Review"}


class TestArguments:
    """Bad arguments stop the run before any agent is dispatched."""

    @pytest.mark.parametrize("args, message", [
        ({"repo": REPO}, "targets"),
        ({"targets": ["sections/methods.tex"], "repo": REPO}, "absolute"),
        ({"targets": [TARGET]}, "repo"),
        (base_args(stance="friendly"), "unknown stance"),
        (base_args(voice=True), "voiceReference"),
        (base_args(lensSet=["constraints"]), "not configured"),
        (base_args(lensSet=["no-such-lens"]), "unknown"),
    ])
    def test_rejected_before_any_agent(self, tmp_path: Path, args: dict, message: str) -> None:
        """Each invalid case fails fast, naming the problem."""
        report = run(tmp_path, args)
        assert not report["ok"]
        assert message in report["error"]
        assert report["calls"] == []

    def test_arguments_as_a_json_string_are_accepted(self, tmp_path: Path) -> None:
        """The harness has been seen to pass args as a JSON string."""
        report = run(tmp_path, json.dumps(base_args()))
        assert report["ok"], report.get("error")


class TestModelAndLenses:
    """What gets dispatched, and with which model."""

    def test_default_model_is_the_opus_alias_on_every_agent(self, tmp_path: Path) -> None:
        """With no model given, every call names 'opus' and the result echoes it."""
        report = run(tmp_path, base_args(stance="adversarial"))
        assert report["ok"], report.get("error")
        assert {c["model"] for c in report["calls"]} == {"opus"}
        assert report["result"]["model"] == "opus"

    def test_a_given_model_is_pinned_on_every_agent(self, tmp_path: Path) -> None:
        """A full model ID passed in reaches every agent unchanged."""
        report = run(tmp_path, base_args(model="claude-opus-5-5"))
        assert {c["model"] for c in report["calls"]} == {"claude-opus-5-5"}

    def test_core_lenses_run_and_optional_ones_need_configuring(self, tmp_path: Path) -> None:
        """Four core lenses by default; constraints and voice only when set up."""
        assert lens_labels(run(tmp_path, base_args())) == CORE_LENSES
        both = run(tmp_path, base_args(constraints="no first person", voice=True,
                                       voiceReference="/notes/register.md"))
        assert lens_labels(both) == CORE_LENSES | {"constraints", "voice"}

    def test_source_notes_folder_reaches_the_source_fidelity_lens(self, tmp_path: Path) -> None:
        """The lens is told where the notes are, or that there are none."""
        with_notes = run(tmp_path, base_args(sourceNotesDir="/papers/example/notes"))
        prompt = next(c["prompt"] for c in with_notes["calls"]
                      if c["label"].startswith("source-fidelity"))
        assert "/papers/example/notes" in prompt
        without = run(tmp_path, base_args())
        prompt = next(c["prompt"] for c in without["calls"]
                      if c["label"].startswith("source-fidelity"))
        assert "NO source notes supplied" in prompt

    def test_adversarial_findings_must_carry_the_hard_rule_fields(self, tmp_path: Path) -> None:
        """The schema itself requires the target claim and the two conditions."""
        report = run(tmp_path, base_args(stance="adversarial"))
        lens_call = next(c for c in report["calls"] if c["phase"] == "Review")
        assert {"targetClaim", "counterCondition", "retractionCondition"} <= set(
            lens_call["findingRequired"])
        friendly = run(tmp_path, base_args())
        lens_call = next(c for c in friendly["calls"] if c["phase"] == "Review")
        assert "targetClaim" not in lens_call["findingRequired"]


class TestDeterministicVerdict:
    """Severities decide the verdict; an agent's own 'passes' never does."""

    def test_clean_critical_friend_run_is_cleared_with_no_ladder_verdict(
        self, tmp_path: Path,
    ) -> None:
        """Critical-friend has no verdict ladder and no meta-review."""
        result = run(tmp_path, base_args())["result"]
        assert result["cleared"] is True
        assert result["verdict"] is None
        assert result["metaReview"] is None

    def test_a_blocker_challenges_even_when_the_agent_says_it_passes(
        self, tmp_path: Path,
    ) -> None:
        """passes=true with a blocker finding still gives CHALLENGED."""
        report = run(tmp_path, base_args(stance="adversarial"), responses={
            "calibration": {"passes": True, "findings": [adversarial_finding("blocker")],
                            "clean": [], "confidence": "high"},
        })
        result = report["result"]
        assert result["verdict"] == "CHALLENGED"
        assert result["cleared"] is False
        # A panel with a blocker is not unanimous, so no devil's advocate runs.
        assert "unanimous-check" not in {c["label"] for c in report["calls"]}
        assert "meta-reviewer" in {c["label"] for c in report["calls"]}

    def test_a_clean_adversarial_panel_triggers_the_unanimous_check(
        self, tmp_path: Path,
    ) -> None:
        """Its major finding joins the aggregation and qualifies the verdict."""
        report = run(tmp_path, base_args(stance="adversarial"), responses={
            "unanimous-check": {"passes": False, "findings": [adversarial_finding("major")],
                                "clean": [], "confidence": "medium"},
        })
        result = report["result"]
        assert "unanimous-check" in {c["label"] for c in report["calls"]}
        assert result["verdict"] == "QUALIFIED"
        assert any(f["lens"] == "unanimous-check" for f in result["findings"])

    def test_prepass_findings_join_the_verdict_but_not_the_unanimity_trigger(
        self, tmp_path: Path,
    ) -> None:
        """A mechanical blocker challenges; the clean panel is still stress-tested."""
        prepass = [{"check": "inputs", "severity": "blocker", "detail": "target not found",
                    "evidence": "x", "target": "sections/methods.tex"}]
        report = run(tmp_path, base_args(stance="adversarial", prepassFindings=prepass))
        result = report["result"]
        assert result["verdict"] == "CHALLENGED"
        assert "unanimous-check" in {c["label"] for c in report["calls"]}


class TestCoverage:
    """Failed agents make coverage partial, and never a clean pass."""

    def test_one_failed_lens_is_reported_and_blocks_the_unanimous_check(
        self, tmp_path: Path,
    ) -> None:
        """partialCoverage counts it; unanimity needs the whole panel."""
        report = run(tmp_path, base_args(stance="adversarial"),
                     responses={"completeness": None})
        result = report["result"]
        assert result["partialCoverage"] == 1
        assert "unanimous-check" not in {c["label"] for c in report["calls"]}
        assert any("PARTIAL" in line for line in report["logs"])

    def test_a_lens_that_throws_counts_as_failed(self, tmp_path: Path) -> None:
        """A thrown error is a null result, counted like a skip."""
        report = run(tmp_path, base_args(), responses={"consistency": "throw"})
        assert report["result"]["partialCoverage"] == 1

    def test_a_panel_with_every_lens_failed_gives_no_verdict(self, tmp_path: Path) -> None:
        """No review was done, so the run fails rather than reading as clean."""
        report = run(tmp_path, base_args(), responses={k: None for k in CORE_LENSES})
        assert not report["ok"]
        assert "no review was performed" in report["error"]


class TestConvergence:
    """Two lenses on the same anchor raise priority, not the verdict."""

    def test_two_lenses_citing_one_line_converge(self, tmp_path: Path) -> None:
        """Both findings are marked converged and grouped by the shared line."""
        report = run(tmp_path, base_args(), responses={
            "consistency": {"passes": False, "findings": [finding("minor", "methods.tex:42")],
                            "clean": [], "confidence": "high"},
            "calibration": {"passes": False, "findings": [finding("minor", "line :42 here")],
                            "clean": [], "confidence": "high"},
        })
        result = report["result"]
        converged = [f for f in result["findings"] if f.get("converged")]
        assert {f["lens"] for f in converged} == {"consistency", "calibration"}
        assert result["cleared"] is True  # minors only: priority, not verdict

    def test_paper_scope_adds_a_cross_section_synthesis(self, tmp_path: Path) -> None:
        """Two targets give paper scope and one synthesis agent."""
        args = {"targets": [TARGET, f"{REPO}/sections/results.tex"], "repo": REPO}
        report = run(tmp_path, args)
        assert report["result"]["scope"] == "paper"
        assert [c["label"] for c in report["calls"]].count("cross-section") == 1
        assert len([c for c in report["calls"] if c["phase"] == "Review"]) == 8


class TestConvergenceAnchors:
    """Line anchors belong to the file they name (found in a real run)."""

    @staticmethod
    def _two(tmp_path: Path, first: str, second: str) -> dict:
        """Run with one minor finding from each of two lenses, evidence as given."""
        return run(tmp_path, base_args(), responses={
            "consistency": {"passes": False, "findings": [finding("minor", first)],
                            "clean": [], "confidence": "high"},
            "calibration": {"passes": False, "findings": [finding("minor", second)],
                            "clean": [], "confidence": "high"},
        })["result"]

    def test_the_same_line_number_in_another_file_does_not_converge(
        self, tmp_path: Path,
    ) -> None:
        """refs.bib:7 is not line 7 of the section."""
        result = self._two(tmp_path, "refs.bib:7", "sections/methods.tex:7")
        assert not any(f.get("converged") for f in result["findings"])

    def test_a_log_line_does_not_converge_with_a_bare_target_line(
        self, tmp_path: Path,
    ) -> None:
        """main.blg:6 against a bare :6, which belongs to the target."""
        result = self._two(tmp_path, "main.blg:6", "see :6")
        assert not any(f.get("converged") for f in result["findings"])

    def test_a_line_inside_a_range_converges(self, tmp_path: Path) -> None:
        """methods.tex:10-12 covers line 11, whatever path form each lens used."""
        result = self._two(tmp_path, "methods.tex:10-12", "/papers/example/sections/methods.tex:11")
        assert all(f.get("converged") for f in result["findings"])
        assert [g["token"] for g in result["convergenceGroups"]] == ["line:sections/methods.tex:11"]

    def test_a_wide_range_counts_only_its_first_line(self, tmp_path: Path) -> None:
        """methods.tex:6-22 says nothing about line 15 in particular."""
        result = self._two(tmp_path, "methods.tex:6-22", "methods.tex:15")
        assert not any(f.get("converged") for f in result["findings"])
        again = self._two(tmp_path, "methods.tex:6-22", "methods.tex:6")
        assert all(f.get("converged") for f in again["findings"])


class TestMetaReviewerContext:
    """The meta-reviewer is given what the lenses were given (found in a real run)."""

    def test_brief_notes_and_bibliography_reach_the_meta_reviewer(self, tmp_path: Path) -> None:
        report = run(tmp_path, base_args(
            stance="adversarial", paperBrief="Mounds were sited to be seen.",
            sourceNotesDir="/papers/example/notes", bibPaths=["/papers/example/refs.bib"],
        ))
        meta = next(c["prompt"] for c in report["calls"] if c["label"] == "meta-reviewer")
        assert "Mounds were sited to be seen." in meta
        assert "/papers/example/notes" in meta and "/papers/example/refs.bib" in meta

    def test_without_context_the_prompt_has_no_empty_headings(self, tmp_path: Path) -> None:
        report = run(tmp_path, base_args(stance="adversarial"))
        meta = next(c["prompt"] for c in report["calls"] if c["label"] == "meta-reviewer")
        assert "PAPER BRIEF" not in meta and "Source notes" not in meta


class TestAnchorPathsKeepTheirFolders:
    """Review finding R28: files of the same name in different folders stay apart."""

    def test_same_name_in_two_folders_does_not_converge(self, tmp_path: Path) -> None:
        result = TestConvergenceAnchors._two(
            tmp_path, "sections/methods.tex:42", "appendix/methods.tex:42")
        assert not any(f.get("converged") for f in result["findings"])

    def test_a_bare_name_resolves_to_each_findings_own_target(self, tmp_path: Path) -> None:
        """Two targets named methods.tex: "methods.tex:42" means each lens's own target."""
        args = {"targets": [f"{REPO}/sections/methods.tex", f"{REPO}/appendix/methods.tex"],
                "repo": REPO, "scope": "section"}
        report = run(tmp_path, args, responses={
            "consistency:methods.tex": {"passes": False, "clean": [], "confidence": "high",
                                        "findings": [finding("minor", "methods.tex:42")]},
        })
        assert report["ok"], report.get("error")
        # Each target's own lens resolves "methods.tex" to its own target, so the
        # two findings (one per target) carry different tokens and do not converge.
        assert not report["result"]["convergenceGroups"]


class TestRulingsReachEveryStage:
    """Review finding R29: settled rulings reach synthesis, unanimous check, and meta-review."""

    RULINGS = {"sections/methods.tex": "GUARD-M: mound and tumulus are synonyms.",
               "sections/results.tex": "GUARD-R: the site stays unnamed."}

    def _prompt(self, report: dict, label: str) -> str:
        return next(c["prompt"] for c in report["calls"] if c["label"] == label)

    def test_paper_scope_stages_get_every_register(self, tmp_path: Path) -> None:
        args = {"targets": [TARGET, f"{REPO}/sections/results.tex"], "repo": REPO,
                "stance": "adversarial", "settledRulings": self.RULINGS}
        report = run(tmp_path, args)
        assert report["ok"], report.get("error")
        for label in ("cross-section", "unanimous-check", "meta-reviewer"):
            prompt = self._prompt(report, label)
            assert "GUARD-M" in prompt and "GUARD-R" in prompt, label
        synthesis = self._prompt(report, "cross-section")
        assert "--- sections/methods.tex ---" in synthesis

    def test_one_target_meta_review_gets_its_register(self, tmp_path: Path) -> None:
        args = base_args(stance="adversarial", settledRulings=self.RULINGS,
                         constraints="no first person")
        meta = self._prompt(run(tmp_path, args), "meta-reviewer")
        assert "GUARD-M" in meta and "GUARD-R" not in meta
        assert "no first person" in meta

    def test_a_single_string_register_appears_once(self, tmp_path: Path) -> None:
        args = {"targets": [TARGET, f"{REPO}/sections/results.tex"], "repo": REPO,
                "settledRulings": "GUARD-ALL: one register."}
        synthesis = self._prompt(run(tmp_path, args), "cross-section")
        assert synthesis.count("GUARD-ALL") == 1


class TestGateValidity:
    """Review finding R30: an incomplete review gives no gate verdict."""

    def test_a_complete_run_is_a_valid_gate(self, tmp_path: Path) -> None:
        result = run(tmp_path, base_args(stance="adversarial"))["result"]
        assert result["gateValid"] is True
        assert result["coverage"] == {
            "panel": {"expected": 4, "succeeded": 4}, "crossSection": "not-required",
            "unanimousCheck": "ran", "metaReview": "ran"}
        assert result["verdict"] == "CONFIRMED" and result["cleared"] is True

    def test_a_missing_lens_withholds_the_verdict(self, tmp_path: Path) -> None:
        result = run(tmp_path, base_args(stance="adversarial"),
                     responses={"completeness": None})["result"]
        assert result["gateValid"] is False
        assert result["verdict"] is None and result["cleared"] is None
        assert result["provisional"] == {"verdict": "CONFIRMED", "cleared": True}
        assert result["coverage"]["unanimousCheck"] == "not-triggered"

    @pytest.mark.parametrize("failure", [None, "throw"])
    def test_a_failed_meta_review_withholds_the_verdict(self, tmp_path: Path, failure) -> None:
        report = run(tmp_path, base_args(stance="adversarial"),
                     responses={"meta-reviewer": failure})
        assert report["ok"], report.get("error")  # a throw no longer aborts the run
        result = report["result"]
        assert result["coverage"]["metaReview"] == "failed"
        assert result["gateValid"] is False and result["verdict"] is None

    @pytest.mark.parametrize("failure", [None, "throw"])
    def test_a_failed_unanimous_check_withholds_the_verdict(self, tmp_path: Path, failure) -> None:
        result = run(tmp_path, base_args(stance="adversarial"),
                     responses={"unanimous-check": failure})["result"]
        assert result["coverage"]["unanimousCheck"] == "failed"
        assert result["gateValid"] is False and result["verdict"] is None

    @pytest.mark.parametrize("failure", [None, "throw"])
    def test_a_failed_synthesis_withholds_clearance(self, tmp_path: Path, failure) -> None:
        args = {"targets": [TARGET, f"{REPO}/sections/results.tex"], "repo": REPO}
        result = run(tmp_path, args, responses={"cross-section": failure})["result"]
        assert result["coverage"]["crossSection"] == "failed"
        assert result["gateValid"] is False and result["cleared"] is None
        assert result["provisional"]["cleared"] is True

    def test_critical_friend_section_needs_only_the_panel(self, tmp_path: Path) -> None:
        result = run(tmp_path, base_args())["result"]
        assert result["gateValid"] is True and result["cleared"] is True
        assert result["coverage"]["metaReview"] == "not-required"


class TestHarnessChecksItsOwnAnswers:
    """The stand-in rejects answers the real schema would not allow."""

    def test_an_invalid_canned_answer_is_a_test_error(self, tmp_path: Path) -> None:
        report = run(tmp_path, base_args(), responses={"calibration": {"passes": True}})
        assert not report["ok"] and "violates its schema" in report["error"]

    def test_invalid_as_null_models_a_rejected_output(self, tmp_path: Path) -> None:
        path = tmp_path / "scenario.json"
        scenario = {"args": base_args(), "responses": {"calibration": {"passes": True}},
                    "invalidAs": "null"}
        path.write_text(json.dumps(scenario), encoding="utf-8")
        proc = subprocess.run([NODE, str(HARNESS), str(SCRIPT), str(path)],
                              capture_output=True, text=True, timeout=60, check=False)
        result = json.loads(proc.stdout)["result"]
        assert result["partialCoverage"] == 1 and result["gateValid"] is False


class TestAmbiguousAnchorNames:
    """A bare name matching several known files, none the finding's own, gives no token."""

    @staticmethod
    def _run(tmp_path: Path, context: list[str]) -> dict:
        args = base_args(readOnlyContext=context)
        return run(tmp_path, args, responses={
            "consistency": {"passes": False, "clean": [], "confidence": "high",
                            "findings": [finding("minor", "notes.tex:5")]},
            "calibration": {"passes": False, "clean": [], "confidence": "high",
                            "findings": [finding("minor", "notes.tex:5")]},
        })["result"]

    def test_two_known_files_of_that_name_give_no_token(self, tmp_path: Path) -> None:
        result = self._run(tmp_path, [f"{REPO}/a/notes.tex", f"{REPO}/b/notes.tex"])
        assert not result["convergenceGroups"]

    def test_one_known_file_of_that_name_resolves(self, tmp_path: Path) -> None:
        result = self._run(tmp_path, [f"{REPO}/a/notes.tex"])
        assert [g["token"] for g in result["convergenceGroups"]] == ["line:a/notes.tex:5"]


class TestFreshContextPrompts:
    """Found by a real run: standing instructions leaked into a review, and lenses strayed."""

    def test_every_agent_keeps_standing_rules_but_not_personal_facts(
        self, tmp_path: Path,
    ) -> None:
        args = {"targets": [TARGET, f"{REPO}/sections/results.tex"], "repo": REPO,
                "stance": "adversarial"}
        report = run(tmp_path, args)
        for call in report["calls"]:
            assert "are not evidence about this paper" in call["prompt"], call["label"]
            assert "permission, ownership," in call["prompt"], call["label"]

    def test_lenses_read_only_the_files_named(self, tmp_path: Path) -> None:
        lens = next(c for c in run(tmp_path, base_args())["calls"] if c["phase"] == "Review")
        assert "Read ONLY the files named in this prompt" in lens["prompt"]

    def test_consistency_lens_is_not_asked_about_sections_it_cannot_see(
        self, tmp_path: Path,
    ) -> None:
        args = {"targets": [TARGET, f"{REPO}/sections/results.tex"], "repo": REPO}
        report = run(tmp_path, args)
        prompt = next(c["prompt"] for c in report["calls"]
                      if c["label"].startswith("consistency"))
        assert "any other section in the target list" not in prompt

    def test_undefined_labels_depend_on_the_stance(self, tmp_path: Path) -> None:
        def consistency(stance: str) -> str:
            report = run(tmp_path, base_args(stance=stance))
            return next(c["prompt"] for c in report["calls"]
                        if c["label"].startswith("consistency"))
        assert "undefined label IS a defect" in consistency("adversarial")
        assert "EXPECTED while drafting" in consistency("critical-friend")

    def test_the_meta_reviewer_reads_only_the_files_named(self, tmp_path: Path) -> None:
        report = run(tmp_path, base_args(stance="adversarial"))
        meta = next(c["prompt"] for c in report["calls"] if c["label"] == "meta-reviewer")
        assert "Read ONLY\nthe target file(s) and the files named below" in meta


def test_the_script_has_no_inline_prepare_route() -> None:
    """Review finding R27: a copy can't vouch for itself, so no prepare flag exists."""
    assert "prepareOnly" not in SCRIPT.read_text()


class TestHedgingGuardEverywhere:
    """The calibration test failed when only the calibration lens carried the guard."""

    def test_every_lens_and_stage_carries_the_hedging_guard(self, tmp_path: Path) -> None:
        args = {"targets": [TARGET, f"{REPO}/sections/results.tex"], "repo": REPO,
                "stance": "adversarial"}
        report = run(tmp_path, args)
        for call in report["calls"]:
            assert "HEDGING GUARD" in call["prompt"], call["label"]

    def test_the_meta_reviewer_checks_hedge_findings_first(self, tmp_path: Path) -> None:
        report = run(tmp_path, base_args(stance="adversarial"))
        meta = next(c["prompt"] for c in report["calls"] if c["label"] == "meta-reviewer")
        assert "already meets the finding's retraction condition" in meta

    def test_critical_friend_lenses_carry_it_too(self, tmp_path: Path) -> None:
        report = run(tmp_path, base_args())
        assert all("HEDGING GUARD" in c["prompt"] for c in report["calls"])



class TestMetaReviewerGetsEachFindingsConditions:
    """Review finding R35: the meta-reviewer is told to test each finding against its
    retraction condition, so each finding's own conditions must reach it, attached to it."""

    @staticmethod
    def _entries(meta: str) -> list[str]:
        """The digest's entries, one per finding, from the meta-reviewer's prompt."""
        digest = meta.split("PANEL FINDINGS:", 1)[1].split("MECHANICAL PRE-PASS", 1)[0]
        return ["[" + part for part in digest.split("\n[") if part.strip()]

    def test_each_findings_conditions_travel_with_it(self, tmp_path: Path) -> None:
        def sentinel_finding(tag: str) -> dict:
            return finding("major", detail=f"detail-{tag}", targetClaim=f"claim-{tag}",
                           counterCondition=f"COUNTER-{tag}",
                           retractionCondition=f"RETRACT-{tag}")

        report = run(tmp_path, base_args(stance="adversarial"), responses={
            "calibration": {"passes": False, "findings": [sentinel_finding("A")],
                            "clean": [], "confidence": "high"},
            "source-fidelity": {"passes": False, "findings": [sentinel_finding("B")],
                                "clean": [], "confidence": "high"},
        })
        meta = next(c["prompt"] for c in report["calls"] if c["label"] == "meta-reviewer")
        entries = self._entries(meta)
        for tag in ("A", "B"):
            mine = [e for e in entries if f"detail-{tag}" in e]
            assert len(mine) == 1, entries
            assert f"counter-condition: COUNTER-{tag}" in mine[0]
            assert f"retraction condition: RETRACT-{tag}" in mine[0]
            other = "B" if tag == "A" else "A"
            assert f"RETRACT-{other}" not in mine[0]

    def test_a_finding_without_conditions_says_so(self, tmp_path: Path) -> None:
        report = run(tmp_path, base_args(stance="adversarial"), responses={
            "calibration": {"passes": False, "findings": [finding("minor", detail="bare")],
                            "clean": [], "confidence": "high"},
        })
        meta = next(c["prompt"] for c in report["calls"] if c["label"] == "meta-reviewer")
        bare = next(e for e in self._entries(meta) if "bare" in e)
        assert "retraction condition: (none stated)" in bare


class TestHedgingGuardIsNarrow:
    """Review finding R36: calibrated wording protects only a hedging objection, never a
    substantive defect the text happens to acknowledge. These pin the wording; whether a
    model honours it is for the paired calibration run."""

    def test_every_prompt_keeps_substantive_defects_reportable(self, tmp_path: Path) -> None:
        report = run(tmp_path, base_args(stance="adversarial"))
        for call in report["calls"]:
            prompt = call["prompt"]
            assert "covers one kind of objection only" in prompt, call["label"]
            assert "does NOT protect a substantive defect" in prompt, call["label"]

    def test_the_meta_reviewer_treats_the_two_kinds_differently(self, tmp_path: Path) -> None:
        report = run(tmp_path, base_args(stance="adversarial"))
        meta = next(c["prompt"] for c in report["calls"] if c["label"] == "meta-reviewer")
        assert "(a) A finding whose sole objection is the presence or degree of hedging" in meta
        assert "calibrated wording is no answer to it" in meta
        assert "quote what satisfies it in the note" in meta


def flat(text: str) -> str:
    """The text with every run of whitespace made one space, so a test pins the
    wording of a prompt and not where its lines happen to wrap."""
    return " ".join(text.split())


class TestMoreHedgingNeedsWeakerEvidence:
    """Three calibration tests failed the same way: the calibration lens asked for more
    hedging on prose that was already calibrated, arguing from caution elsewhere in the
    text or by analogy with a nearby hedge. A request for more hedging must now cite
    evidence weaker than the claim as worded. These pin the wording; whether a model
    honours it is for the calibration test."""

    @pytest.mark.parametrize("stance", ["adversarial", "critical-friend"])
    def test_every_lens_and_stage_carries_the_rule(self, tmp_path: Path, stance: str) -> None:
        """Paper scope, so the synthesis (and, adversarially, both checks) run too."""
        args = {"targets": [TARGET, f"{REPO}/sections/results.tex"], "repo": REPO,
                "stance": stance}
        report = run(tmp_path, args)
        assert report["ok"], report.get("error")
        labels = {c["label"] for c in report["calls"]}
        assert "cross-section" in labels
        if stance == "adversarial":
            assert {"unanimous-check", "meta-reviewer"} <= labels
        for call in report["calls"]:
            prompt = flat(call["prompt"])
            assert ("A finding that asks for more hedging, a weaker verb, or a softer claim "
                    "must cite evidence that is weaker than the claim as worded") in prompt, \
                call["label"]
            assert ("A hedge elsewhere in the text, an argument from consistency of tone, a "
                    "general preference for caution, or the claim's directness alone is not "
                    "such evidence; without it, there is no finding.") in prompt, call["label"]

    def test_the_calibration_lens_states_it_under_hedges(self, tmp_path: Path) -> None:
        """Dimension (2), on mis-calibrated hedges, repeats the rule in brief."""
        report = run(tmp_path, base_args(stance="adversarial"))
        lens = next(c["prompt"] for c in report["calls"] if c["label"].startswith("calibration"))
        dimension = flat(lens.split("(2) Mis-calibrated hedges", 1)[1].split("(3) Altitude", 1)[0])
        assert ("To ask for more hedging, a weaker verb, or a softer claim, cite the evidence "
                "that is weaker than the claim as worded") in dimension
        assert ("a hedge elsewhere in the text, consistency of tone, or a general preference "
                "for caution is not that evidence") in dimension
        # Both directions of mis-calibration stay reportable.
        assert "a hedge on a strongly-evidenced claim undersells" in dimension

    def test_the_meta_reviewer_rejects_a_request_without_weaker_evidence(
        self, tmp_path: Path,
    ) -> None:
        """Branch (a), for hedging-only findings, calls such a request not sound."""
        report = run(tmp_path, base_args(stance="adversarial"))
        meta = next(c["prompt"] for c in report["calls"] if c["label"] == "meta-reviewer")
        branch = flat(meta.split("(a) A finding whose sole objection", 1)[1]
                      .split("(b) A finding about a substantive defect", 1)[0])
        assert ("A finding that asks for more hedging, a weaker verb, or a softer claim shows "
                "this only by citing evidence weaker than the claim as worded") in branch
        assert ("If the hedge is calibrated, if such a request cites no weaker evidence, or if "
                "the text already meets the finding's retraction condition, the finding is not "
                "sound: classify it semantic-drift") in branch
