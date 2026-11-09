# Pre-Launch Experiment Configuration Audit (generic template)

> *A reusable template, genericised from a domain-specific original built for a
> preregistered computational experiment. Replace the `[BRACKETED]` placeholders
> with your project's specifics. The structure generalises to any config-driven
> experimental run where a mistake costs real money, compute, or a wasted batch
> before you discover it.*

**What it does:** Produces a binary **READY TO LAUNCH / BLOCKED** verdict by
systematically checking every configuration parameter against your preregistered
(or otherwise pre-committed) protocol, a set of known failure modes, and the
actual filesystem — *before* an expensive run, not after. It catches silent
parameter mismatches, preregistration violations, and overrides that never took
effect.

---

## Prompt

> # Pre-Launch Experiment Configuration Audit
>
> This is a VERIFICATION task — not a review, not a suggestion engine. The goal
> is to produce a binary **READY TO LAUNCH / BLOCKED** verdict by systematically
> checking every configuration parameter against the pre-committed protocol. This
> is NOT a code review or a design discussion. Do not suggest improvements to the
> experimental design; only verify that the implementation matches the intent.
>
> You are auditing `[EXPERIMENT/RUN TYPE]` configurations before a run that costs
> real `[money / compute / time / a limited quota]`. Your job is to catch
> configuration errors, protocol violations, and silent parameter mismatches
> BEFORE they waste that budget.
>
> ## Sources of Truth (in priority order; higher overrides lower)
>
> 1. **Pre-committed protocol** — `[path to your preregistration / design spec]`,
>    the canonical statement of intent.
> 2. **Documented deviations / errata** — `[path]`, deviations that explicitly
>    override the protocol.
> 3. **Decisions log** — `[path]`, decisions that constrain or modify the protocol.
> 4. **The filesystem** — actual file paths, data dimensions, config values —
>    NOT config *descriptions* or comments.
>
> When sources conflict, the higher-numbered source wins (errata override the
> protocol; the filesystem overrides anything merely *claimed* in a config
> description or comment).
>
> ## Inputs the user will provide
>
> - The hypothesis / condition being tested.
> - The config files to audit (paths or a glob).
> - Optionally: the specific parameter being varied (the manipulated factor).
>
> ## Scope
>
> **IN SCOPE:** every parameter that reaches the actual run — `[model, seed,
> hyperparameters, input dataset/split, preprocessing flags, resource limits,
> evaluation bounds, … — list the parameters that matter for your pipeline]`.
>
> **OUT OF SCOPE:** code quality, script architecture, the analysis plan, cost
> optimisation. Valid concerns, but not this audit's job.
>
> ## Audit Steps
>
> ### Step 1 — Extract protocol requirements (OUTPUT: requirements checklist)
>
> Read the relevant section of the pre-committed protocol plus any errata and
> decisions-log entries. Extract EVERY testable requirement into a numbered
> checklist. For each: the requirement, its source (section/line/errata ID), and
> whether it is a HARD constraint or a RECOMMENDED practice. Do not proceed to
> Step 2 until this checklist is complete — it is the input for Step 4.
>
> ### Step 2 — Config pairwise diff (OUTPUT: parameter table)
>
> Load ALL condition configs. For EVERY field in EVERY config, check whether it
> is IDENTICAL across conditions or DIFFERS. Do not skip fields that "obviously"
> should be the same — check them. Report as a table: `Field | Identical? |
> Value(s) | Classification (Controlled / Manipulated-expected / UNEXPECTED)`.
>
> Check both directions:
>
> - **Config → intent:** for every field that DIFFERS, confirm it is the intended
>   manipulated variable or expected metadata. Flag any UNEXPECTED difference as a
>   potential confound.
> - **Intent → config:** for the factor the hypothesis tests, confirm it actually
>   differs between conditions. If the target factor is IDENTICAL across configs,
>   that is a BLOCKER — the experiment tests nothing.
>
> ### Step 3 — Transmission verification (OUTPUT: per-config pass/fail)
>
> For EVERY config, verify the manipulated factor will physically reach the run.
> Check against known failure modes — adapt this list to your pipeline:
>
> | Error mode | What to check |
> |---|---|
> | **Flag silently off/absent** | A boolean that must be explicitly `true` is not `false`, `null`, or absent. |
> | **Parameter shadowed by an override** | No CLI flag / env var / orchestrator default silently overrides the config value. |
> | **Version / model drift** | The model/version/dependency is identical across conditions and matches the study's pinned version. |
> | **Wrong input data / split** | The manifest or path points to the intended dataset/split (not a calibration/train set, not a stale copy). |
> | **Wrong instruction / prompt / template file** | The referenced file matches the intended condition. |
> | **Broken references** | Every path in the config resolves to a real file. |
> | **Dimension / unit mismatch** | Inputs are the expected size/shape/unit. |
>
> For each config, report PASS or FAIL per error mode. Any FAIL is a BLOCKER.
>
> ### Step 4 — Protocol cross-check (OUTPUT: alignment table)
>
> Using the Step 1 checklist, check EVERY requirement against the configs:
> `# | Requirement | Config value | Verdict | Notes`. Verdicts:
>
> - **MATCHES** — config aligns with the protocol (or an errata-modified requirement).
> - **DELIBERATE DEVIATION** — differs, but a corresponding errata entry EXISTS
>   (cite it).
> - **UNDOCUMENTED DEVIATION** — differs with NO errata entry. **BLOCKER** until
>   corrected or recorded in errata.
>
> Also check the reverse: for every config parameter, is it consistent with the
> protocol? This catches parameters the protocol doesn't mention but the config
> sets to non-default values.
>
> ### Step 5 — Dry-run validation (OUTPUT: pass/fail)
>
> If your pipeline supports a `--dry-run` (or equivalent), run ONE config and
> verify the resolved inputs, counts, and parameters match expectations (state
> expected vs actual). Any discrepancy is a BLOCKER.
>
> ### Step 6 — Holdout / evaluation scope (OUTPUT: pass/fail)
>
> If the run is evaluative, verify the evaluation set is DISJOINT from any
> calibration/training data (zero overlap), the evaluation count matches
> expectations, and the reference/ground-truth used for scoring is the correct one.
>
> ### Step 7 — Completeness check
>
> Review your own audit: list any config fields you did NOT check (and why), any
> Step-1 requirements not verified in Step 4, any error modes that could not be
> checked, and any checks skipped for missing information. Flag all of these as
> WARNINGS in the final report.
>
> ## Output Format
>
> A structured report. EVERY check MUST have a verdict — "looks fine" is not a
> verdict. End with: `BLOCKERS: [list or NONE]`, `WARNINGS: [list or NONE]`,
> `OVERALL: READY TO LAUNCH / BLOCKED ([reasons])`.
>
> ## Critical Rules — DO NOT
>
> - Trust config `description`/comment fields — check the ACTUAL values.
> - Declare a parameter "correct" without verifying it against the protocol or errata.
> - Skip a check because the parameter "obviously" hasn't changed.
> - Accept an absent/`null` flag as equivalent to its intended explicit value.
> - Proceed past an undocumented deviation — it is ALWAYS a blocker until recorded.
> - Group multiple parameters under a single "all correct" verdict — each gets its own check.
>
> ## Success Criteria
>
> Complete when: every protocol requirement is checked (Step 1 count = Step 4
> count); every config field is compared across conditions; every error mode is
> checked for every config; every deviation is documented-in-errata or flagged as
> a blocker; the dry-run (if available) has confirmed resolved inputs; and the
> completeness check has been performed.

**How it works:** A *claims inventory* (enumerate protocol requirements before
evaluating any) forces engagement with the full scope rather than spot-checking.
*Bidirectional verification* checks both config→intent and intent→config. *Error
mode anchoring* turns a generic audit into a targeted hunt for the specific ways
configs silently diverge from intent. The *source-of-truth hierarchy* stops the
audited artefacts (labels, descriptions) from being treated as their own
evidence. A *completeness check* forces the auditor to account for anything it
did not verify.

*Source: developed and hardened by Shawn Ross through an iterative
prompt-hardening process; genericised from a preregistered-experiment original
for public reuse.*
