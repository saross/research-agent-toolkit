---
name: review-paper
description: >-
  Multi-lens fresh-context review panel for academic paper prose, in LaTeX.
  Two stances: critical-friend (constructive, drafting phase; the default)
  and adversarial ("Reviewer 2", a whole-paper pre-submission gate). Use
  when the user asks to review a paper section or whole manuscript, run an
  adversarial or Reviewer-2 pass, or run a critical-friend pass. Not for
  code review or literature review.
---

# Review paper: fresh-context review panel

**Announce at start:** "I'm using the review-paper skill: mechanical
pre-pass first, then the [stance] panel after the cost gate."

Two files beside this skill do the work:

- the mechanical pre-pass, `${CLAUDE_PLUGIN_ROOT}/scripts/review-paper-prepass.py`
  (Python standard library only; `aspell`, `texcount`, and a build command
  are optional, and each check that needs a missing one is skipped and
  says so);
- the panel, a Claude Code workflow script,
  `${CLAUDE_PLUGIN_ROOT}/scripts/review-paper.mjs`. It needs Claude Code's
  Workflow tool (dynamic workflows), and the session must be able to read
  this plugin's `scripts/` folder (Step 3). If either is missing, say so
  and stop after the pre-pass: don't imitate the panel by hand, because
  its verdict is computed by the script.

Core invariants (don't weaken them in orchestration):

- **Fresh-context panel:** each lens reads only the target artefacts;
  never paste the drafting conversation into lens prompts. Agents still
  see the user's `CLAUDE.md` and memory: the prompts keep their standing
  rules but bar personal facts as evidence, and Step 4 checks. This
  reduces contamination; it does not guarantee isolation.
- **Deterministic verdict:** computed from finding severities, including
  the mechanical pre-pass. No agent's opinion, including the
  meta-reviewer's, ever overrides it.
- **Evidence anchors:** no anchor, no finding. This applies to you too,
  when you add or kill findings.
- **Model pinned at dispatch; report stamped at render** (Step 5).

## Step 0: parameters

Gather these before anything runs. Ask only for what you can't infer
from the repository. The panel reviews LaTeX (`.tex`) only; for any other
format, say so and stop.

| Parameter | Default and notes |
| --- | --- |
| `targets` | Section `.tex` file(s), as absolute paths |
| `repo` | The paper repository's root |
| `stance` | `critical-friend`. **`adversarial` is for drafts the author considers done.** Reviewer 2 on still-forming prose is premature; confirm with the user before using it |
| `scope` | `section` (one target) or `paper` (all sections, in the order the main `.tex` file includes them) |
| bibliography and aux | Pre-pass `--bib` and `--aux`, for citation resolution and label sanity. Also pass the `.bib` list to the workflow as `bibPaths` |
| spelling language | Pre-pass `--spell-lang`, an aspell dictionary code. Take it from the user's stated language conventions (for example `en_GB`, `en_AU`, `en_US`); without one, aspell uses its own default |
| word budget, dash tokens | Repository conventions, if any: pre-pass `--word-budget`, and `--dash-token` for a compound that must keep its double hyphen, such as `human--AI` (not workflow arguments) |
| `sourceNotesDir` | Optional. A folder of source notes, one file per cited work, named by its citekey and holding verbatim quotes from that work. The source-fidelity lens checks cited claims against them; without them, it marks every cited claim "unverifiable" at minor severity rather than guess |
| `constraints` | Optional hard constraints (banned words, date rules, citekeys that must stay). Turns on the constraints lens |
| `paperBrief` | Three to six lines on what the paper argues (static context) |
| `model` | `opus`, an alias for the current Opus-class model, unless the user chooses otherwise at the gate. Pass a full model ID to pin one exactly |
| `readOnlyContext` | Optional. Extra paths lenses may consult (supplements, appendices) |
| `lensSet` | Optional. A subset of lens keys to run (`source-fidelity`, `consistency`, `calibration`, `completeness`, `constraints`, `voice`); an unknown or unconfigured key fails at once |
| `voice` and `voiceReference` | Off by default; for final polish only. `voiceReference` is the path to the author's register (the `academic_register` option's file if set, or this plugin's `registers/academic.md`) |

**Settled rulings.** An author can record decisions the panel must not
re-open in a LaTeX comment block in the section itself: a run of `%`
lines containing the words `STANDING GUARDS` or `wording guards`. The
pre-pass extracts each such block, and the lenses are told to report
only drift from those rulings. `path:line` anchors written in comment
blocks are checked for staleness.

## Step 1: mechanical pre-pass (free, deterministic, always first)

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/review-paper-prepass.py" \
  --repo <repo> --target <repo-relative path> [--target ...] \
  [--bib '<glob>'] [--aux <repo-relative .aux>] [--spell-lang en_GB] \
  [--word-budget N] [--dash-token 'human--AI'] [--build-cmd 'latexmk ...'] \
  --json-out <a scratch folder of this session's own>/prepass.json
```

Leave out `--bib` or `--aux` if the paper has none (an `.aux` exists only
after a build); the checks that need them are skipped and say so. Present
its findings to the author at once: they are free, and often actionable
without any agent run. The JSON also yields:

- `findings`: pass these verbatim as `prepassFindings` (they join the
  verdict);
- `settled_rulings`: pass these verbatim as `settledRulings`. Its keys are
  repository-relative target paths; the workflow matches them against
  its absolute targets itself, so no re-keying is needed.

## Step 2: cost gate (mandatory, every run)

Before dispatching, present these and get explicit approval: (1) the
model; (2) that agents run in real time through the Workflow tool; (3)
the agent count; (4) estimated tokens and cost. Approval for one run does
not cover the next.

Measured on one section with four lenses: about 270,000 subagent tokens
and 4–6 minutes wall-clock.

| Run | Agents | Rough tokens |
| --- | --- | --- |
| Section, critical-friend | 4–6 | about 0.3 million |
| Section, adversarial | the lenses, a meta-reviewer, and a devil's advocate if the panel comes back clean | about 0.4–0.5 million |
| Whole paper (8 sections), adversarial | about 34 (8 × 4, plus synthesis, meta-review, and checks) | about 2.5–3 million |

A whole-paper adversarial run is a deliberate pre-submission spend, not
routine. On a subscription plan these tokens draw on the user's usage
limits.

## Step 3: dispatch

The arguments are those the script's header lists, as a JSON object
(not a JSON string). Always pass `model` and `run_date` (today's date:
the workflow sandbox has no clock), plus `prepassFindings` and
`settledRulings` from Step 1.

Call the Workflow tool with `scriptPath` set to
`${CLAUDE_PLUGIN_ROOT}/scripts/review-paper.mjs` and the arguments. The
tool loads a script by path only from the working directory or an added
directory. **If the path is refused**, stop and give the user the exact
folder holding the script: they can add it with `/add-dir`, or list it
(or the plugin cache folder above it, which covers later versions)
under `permissions.additionalDirectories`. Then try the same path again.
Don't change their settings, and don't pass the script inline or copy
it: a copy can't be checked before it runs.

A run that has to be repeated, for any reason, goes back through
Step 2: approval covers one run.

Record the run ID (`wf_…`) from the **Workflow tool's result**, for the
stamp: the script's return value can't know it.

## Step 4: verify contested findings BEFORE presenting

Non-negotiable. In one real run a lens reported that the prose
contradicted a recorded anchor; the anchor was stale, and the obvious
fix would have broken correct text. Before the report ships:

1. Verify every finding named in `metaReview.verifyBeforePresenting`
   (adversarial runs only; `metaReview` is null for critical-friend),
   every finding that contradicts a recorded anchor or ruling, and every
   pair of lenses in contradiction, against **authoritative sources**: re-read
   the target and the source note, or fetch the source. Never check
   against memory.
2. Classify each finding you kill with the hallucinated-objection
   taxonomy (total fabrication, partial corruption, identifier
   hijacking, placeholder, semantic drift; arXiv 2602.05930), and keep the
   kill list in the report. It is the panel's calibration record.
3. Convergence (`converged: true`) raises priority, never the verdict.
   On a short section nearly every finding converges, so the flag
   doesn't discriminate: rank instead by how many lenses raised each
   distinct issue, and tell the author.
4. Drop, and list with the kills, any finding, note, blind spot, or
   strength that draws on the user's own instructions or memory rather
   than the artefacts, or that rests on an unresolved citation or a
   misread line (a wrong strength protects the wrong text).

## Step 5: render the triaged report, with a stamp

Write the report into the paper repository, following its conventions
(for example a `planning/reviews/` folder); if it has none, use
`reviews/review-<stance>-<scope>-<YYYY-MM-DD>.md`. Structure:
verdicts and findings per dimension; then the overall verdict
(`CONFIRMED`, `QUALIFIED`, or `CHALLENGED` for adversarial; the
`cleared` true-or-false for critical-friend); then prioritised
recommendations (the meta-reviewer's priorities, weighted by
convergence). **If `gateValid` is false, there is no verdict and no
clearance:** say so at the top, name the failed stages from `coverage`,
and show the result in `provisional` only under that name, until the
failed stages are re-run. Present what the author must act on in three
tiers:

1. **Mechanical batch:** fixes the author can approve as a group, with
   no per-item review. Nothing is applied until the author says apply.
2. **Rulings needed:** before-and-after snippets with one line of context
   each, reviewable in the conversation without opening the file.
3. **Standing rulings honoured:** re-flagged items already ruled on;
   shown for transparency, not reopened unless the author asks.

**Stamp block (mandatory):** the model requested (from the workflow
result; the transcript remains the record of which model answered), the
run date, the workflow run ID, and this plugin's version (the `version`
in `${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json`).

## Apply phase (only when the author says apply)

- Make batch fixes by **scripted exact-string replacement with an
  assertion per edit** (exact match, count of one; stop on failure), not
  by hand-editing at volume.
- **Re-read the target immediately before applying.** Authors edit
  between the review and the apply.
- **Commit only if the author asks**, and if the repository has a build
  command, only after it succeeds (`&&`, never `;`).

## Calibration gate: the hedging stress test

Language-model reviewers systematically underrate prose with hedging,
risk, and limitation language (LLM-REVal, arXiv 2510.12367), which is
the register careful humanities and social-science writing uses. Every
lens carries a guard against this, which protects calibrated wording but
not a substantive defect the text acknowledges, and admits a request for
more hedging only with cited evidence weaker than the claim. The guard
has to be tested, not trusted.

Before an adversarial run, read the calibration records in the folder
where reviews are written (`calibration-*.md`). Consider only records for
the current panel script (its SHA-256, `sha256sum
${CLAUDE_PLUGIN_ROOT}/scripts/review-paper.mjs`, since the stance
preambles and the calibration lens live there) and the model requested.
Calibration holds only if the most recent of those is a **pass** of
both halves of the test below. A
later failure, no such record, or an order that can't be told leaves it
unresolved; records for another script or model count neither way. So,
for the same script and model, a pass then a later fail is unresolved
and a fail then a later pass is calibrated; a fail for an older script
then a pass for the current one is calibrated. If unresolved, tell the
author, and offer a fresh test. The test is a run like any other, through Step 2's
cost gate; never start it just because a record is missing. If the
author declines, label every adversarial finding about hedging in the
report as uncalibrated.

The test is a pair of adversarial runs over sections the author
nominates, because a guard that suppresses everything would pass a test
of protection alone. **Protection:** a known-good, peer-reviewed,
deliberately hedged section. It passes if no finding treats a calibrated
hedge as a weakness, and any finding about a hedge shows real
mis-calibration with evidence. Count every finding the panel returns,
including any the meta-reviewer rates unsound: the test is of the guard,
not of the meta-reviewer. **Sensitivity:** a cautious section with a
documented substantive defect (one a referee raised, for example) whose
limitation the text openly acknowledges. It passes if at least one
finding identifies that defect and the meta-reviewer does not dismiss it
on hedging or acknowledgement grounds. **Fail (either half):** say that
the plugin's guard needs fixing, and treat hedging findings as
uncalibrated until a later version passes both. **A section used to
diagnose or fix the guard can't confirm the fix:** a pass on it counts
only once the same script and model also pass on a section that played
no part in the fix.
Record which sections a test used, and whether each was held out.
Record each test in a file of its own,
separate from any review report, `calibration-<YYYY-MM-DD>-<run ID>.md`,
with the date and time of the run (UTC), the target, the outcome, the
script's SHA-256, the plugin version, the model requested, and the model
that answered where the transcript shows it (an alias such as `opus`
names a tier, not a fixed model version).

## After the run

Tell the author the run's actual token use beside the Step 2 estimate.
