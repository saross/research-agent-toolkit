---
name: audit-config
description: "Pre-launch experimental configuration audit. Use before committing API spend to an experimental run, such as a detection, classification, or evaluation run. Systematically checks every configuration parameter against the preregistered protocol, the project's known failure modes, and the filesystem, and produces a READY TO LAUNCH or BLOCKED verdict. Trigger phrases: 'audit configs', 'check configs', 'ready to run', 'launch the evaluation'. Also trigger PROACTIVELY when the user is about to launch an experimental API run, especially after generating new configs."
---

# Audit Config: Pre-Launch Experimental Configuration Audit

This is a VERIFICATION task, not a review or a suggestion engine. Its goal is a binary verdict,
READY TO LAUNCH or BLOCKED, reached by checking every configuration parameter against the protocol.
Don't suggest improvements to the experimental design; only verify that the implementation matches
the intent.

You are auditing experiment configurations before a run that costs real money. Your job is to catch
configuration errors, deviations from the preregistration, and silent parameter mismatches BEFORE
they waste budget.

**Where it came from.** A map-reading study using vision-language models (`map-reader-llm`) once ran
a pair of image-based conditions with the example images switched off. It cost about US$33 and half
a day of invalid analysis and troubleshooting, and it was exactly the kind of mistake this audit
catches. The failure-mode table in Step 3 starts from that study's list. Replace or extend it with
your own project's.

## Sources of Truth (in priority order)

Find these in the project; ask the user where they are if you can't.

1. **The preregistration or protocol**: the canonical statement of what each condition must do
2. **Errata**: documented deviations that override the preregistration
3. **A decisions log**: decisions that constrain or modify the protocol
4. **The filesystem**: actual file paths, image dimensions, and JSON values, NOT what configuration
   descriptions or comments say

When sources conflict, a higher-numbered source overrides a lower one: errata override the
preregistration, and the filesystem overrides anything a configuration's description claims.

## Inputs

The user provides:

- the hypothesis or condition being tested;
- the configuration files to audit, as paths or a pattern;
- optionally, the specific parameter being varied.

## Scope

**IN SCOPE**: every parameter that reaches the model or API call. For example: the model,
temperature, reasoning or thinking settings, whether examples or images are included, instruction or
prompt files, example lists, input sizes, input manifests, and evaluation bounds.

**OUT OF SCOPE**: code quality, script architecture, the analysis plan, and cost optimisation. These
are valid concerns, but not this audit's job.

## Audit Steps

### Step 1: Extract preregistration requirements (OUTPUT: requirements checklist)

Read the relevant hypothesis section of the preregistration, plus the errata and decisions log for
modifications. Refer to other protocol documents as needed to clarify it.

Extract EVERY testable requirement into a numbered checklist. For each, record:

- the requirement, as the preregistration states it;
- its source: section, line, or errata entry;
- whether it is a HARD constraint or a RECOMMENDED practice.

Don't start Step 2 until this checklist is complete. It is the input for Step 4.

### Step 2: Pairwise configuration diff (OUTPUT: parameter table)

Load ALL condition configurations. For EVERY field in EVERY configuration, check whether it is
IDENTICAL across conditions or DIFFERS. Don't skip fields that "obviously" should be the same; check
them.

Report as a table, for example:

| Field | Identical? | Value(s) | Classification |
| --- | --- | --- | --- |
| model | YES | [model name] | Controlled |
| examples | NO | [differs per pool] | MANIPULATED — expected |
| temperature | YES | 0.7 | Controlled |
| ... | ... | ... | ... |

Check in BOTH directions:

- **Configuration to intent**: for every field that DIFFERS, confirm it is the intended manipulated
  variable or expected metadata. Flag any UNEXPECTED difference as a possible confound.
- **Intent to configuration**: for the factor the hypothesis tests, confirm it actually differs
  between conditions. If the target factor is IDENTICAL across configurations, flag a BLOCKER: the
  experiment tests nothing.

### Step 3: Transmission verification (OUTPUT: pass or fail per configuration)

For EVERY configuration, verify that the manipulated factor will physically reach the model. Check
against the project's known failure modes. This table starts from the map-reading study's; adapt the
rows to your project.

| Failure mode | What to check |
| --- | --- |
| **Input flag off** | A flag that switches on images, examples, or tools is explicitly `true`, not `false`, `null`, or absent |
| **Setting shadowed** | No command-line override contradicts the configuration's value, for example for temperature |
| **Reasoning setting dropped** | Reasoning or thinking settings match the intent, and meet any minimum the chosen model needs |
| **Model version drift** | The model field is identical across all conditions and matches the study's model |
| **Input size mismatch** | Configured input dimensions match the actual files |
| **Wrong input set** | The manifest points to the right set: calibration, evaluation, or full |
| **Wrong instruction file** | The instruction or prompt file matches the intended track |
| **Example paths broken** | EVERY path in the example list resolves to a real file |
| **Example dimensions** | Example files are the expected size for the pipeline |
| **Agent model unpinned** | Any workflow or script that spawns agents pins its model explicitly and records the model and run identity in what it produces. A model inherited from the session is a FAIL: session metadata and commit trailers both go stale when the model is switched partway through a session |

For each configuration, report PASS or FAIL per failure mode. A FAIL on any failure mode is a
BLOCKER.

### Step 4: Preregistration cross-check (OUTPUT: alignment table)

Using the checklist from Step 1, check EVERY requirement against the configurations:

| # | Requirement | Config value | Verdict | Notes |
| --- | --- | --- | --- | --- |
| 1 | [for example, pool sizes 20, 40, 80, 160] | [check] | MATCHES / DEVIATION | |
| 2 | ... | ... | ... | |

Verdicts:

- **MATCHES**: the configuration agrees with the preregistration, or with the requirement as errata
  modified it.
- **DELIBERATE DEVIATION**: the configuration differs, and a matching errata entry EXISTS. Cite it.
- **UNDOCUMENTED DEVIATION**: the configuration differs, with NO errata entry. **BLOCKER**: it must
  be corrected, or recorded in the errata, before proceeding.

Also check the reverse direction: is every parameter in the configurations consistent with the
preregistration? This catches parameters the preregistration doesn't mention but the configurations
set to non-default values.

### Step 5: Dry-run validation (OUTPUT: pass or fail)

If the pipeline has a dry-run mode, run it with ONE configuration and check:

- the number of inputs found in the manifest (state expected and actual);
- the number of examples loaded (state expected and actual);
- no warnings about missing reference files or mismatched dimensions;
- any preview of the run's intent confirms the hypothesis, factor, and modality.

Report PASS or FAIL. Any discrepancy is a BLOCKER. If there is no dry-run mode, say so and record it
as a WARNING.

### Step 6: Holdout and evaluation scope (OUTPUT: pass or fail)

Verify that:

- the evaluation set is DISJOINT from any calibration or training inputs (zero overlap);
- the evaluation count matches expectations (state expected and actual);
- the reference or ground-truth file is the right one for this evaluation;
- any bounds or scope file used for scoring matches the evaluation set.

### Step 7: Completeness check

After Steps 1 to 6, review your own audit:

- list any configuration fields you did NOT check, and why;
- list any requirements from Step 1 not verified in Step 4;
- list any failure modes from Step 3 that couldn't be verified, such as checks only possible at run
  time;
- say whether any checks were skipped for lack of information.

Flag anything left unchecked as a WARNING in the final report.

## Output Format

Present the results as a structured audit report. EVERY check MUST have a verdict; "looks fine"
isn't one.

```text
=== PRE-LAUNCH AUDIT: [Hypothesis] ===

1. PREREGISTRATION REQUIREMENTS: [N requirements extracted]
   [numbered list]

2. CONFIG DIFF: [N fields identical, M fields differ]
   Controlled: [list with values]
   Manipulated: [list — EXPECTED or UNEXPECTED per field]
   Confounds: [NONE or list]

3. TRANSMISSION CHECK:
   [table: config × failure mode → PASS/FAIL]
   Blockers: [NONE or list]

4. PREREGISTRATION ALIGNMENT:
   Matches: [count]
   Deliberate deviations: [count, with errata references]
   Undocumented deviations: [count — BLOCKER if more than 0]

5. DRY RUN: PASS / FAIL
   [details if FAIL]

6. EVALUATION SCOPE: PASS / FAIL
   [details if FAIL]

7. COMPLETENESS: [items not checked, if any]

BLOCKERS: [list, or NONE]
WARNINGS: [list, or NONE]

OVERALL: READY TO LAUNCH / BLOCKED ([reasons])
```

## Success Criteria

The audit is complete when:

- [ ] every preregistration requirement has been checked (the Step 1 count equals the Step 4 count);
- [ ] every configuration field has been compared across conditions (the Step 2 table is complete);
- [ ] every failure mode has been checked for every configuration (the Step 3 matrix is full);
- [ ] every deviation is either documented in the errata or flagged as a blocker;
- [ ] a dry run has confirmed input and example counts, or its absence is recorded;
- [ ] the completeness check in Step 7 has been done.

## Critical Rules

DO NOT:

- trust configuration `description` fields: check the ACTUAL values of every parameter;
- declare a parameter "correct" without checking it against the preregistration or errata;
- skip a check because the parameter "obviously" hasn't changed;
- accept `null` or an absent value as equivalent to `true` for a flag the experiment depends on: it
  must be explicitly `true`;
- proceed past an undocumented deviation: it is ALWAYS a blocker until recorded in the errata;
- group several parameters under one "all correct" verdict: each parameter gets its own check.

A configuration with a needed input switched off, while it claims to test that input, is ALWAYS a
blocker. If more parameters differ between conditions than the target factor and metadata fields,
flag a possible confound.
