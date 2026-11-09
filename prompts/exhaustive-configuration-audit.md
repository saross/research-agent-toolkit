# Exhaustive Configuration Audit

**Incantation:**

> **This is an exhaustive verification audit, not a spot-check or summary.**
> The goal is to confirm — or disprove — that every production run's actual
> configuration matches both its label and its intended design. You must
> examine every run individually. Do not sample, generalise from a subset,
> or declare groups of runs consistent without checking each one.
>
> **Source of truth hierarchy** (when sources conflict, higher wins):
>
> 1. **Submission payload** (e.g., JSONL request, API call) — what the API
>    actually received. Highest authority.
> 2. **Runtime metadata** (e.g., meta.json, execution log) — runtime snapshot
>    of resolved configuration.
> 3. **Config file** (e.g., JSON/YAML config) — static defaults. Overridable
>    by CLI flags and orchestrator logic.
> 4. **Study/experiment definition** (e.g., study YAML, experiment spec) —
>    intended design. Expresses what SHOULD have happened, not what DID happen.
>
> When any source is missing for a run, flag it as `SOURCE_MISSING` with the
> source name, record reduced confidence for that run, and proceed with
> available sources. Do not skip the run.
>
> **Known error modes — watch specifically for these patterns:**
>
> 1. **Config hardcoding defeats override intent.** [Describe the specific
>    pattern: config file hardcodes a default, override mechanism exists but
>    was never invoked, run label implies the override was applied.]
> 2. **Parameter propagation failure.** [Describe: orchestrator should
>    propagate an override from experiment spec to config, but the code path
>    failed silently, and the config default won.]
> 3. **Silent rejection.** [Describe: the target system rejected a parameter
>    value silently, falling back to a default without error.]
>
> **Phase 1: Inventory.** Before checking anything, enumerate every run.
> Extract the declared and actual values for each audited parameter from
> every available source. Do not assess correctness during this phase.
>
> **Phase 2: Check each run.** For every inventoried run, apply these checks:
>
> - Check 1: Label ↔ metadata (does the name match what was recorded?)
> - Check 2: Intent ↔ metadata (does the experiment spec match what ran?)
> - Check 3: Config propagation chain (trace default → override → resolved
>   value for each parameter — was every override applied?)
> - Check 4: Metadata ↔ submission (does runtime metadata match what was
>   actually sent to the API?)
> - Check 5: Cross-run consistency (within the same condition, are ALL runs
>   identical in configuration?)
> - Check 6: Comparison pair validity (for any two conditions compared
>   statistically, does only the intended variable differ?)
>
> Record each check as PASS, FAIL, or UNVERIFIABLE (with reason).
>
> **Phase 3: Report.** Produce:
>
> 1. Inventory summary table (one row per condition, source availability)
> 2. Discrepancy table (every FAIL, with severity: CRITICAL/HIGH/WARNING/INFO)
> 3. Confound matrix (for each comparison pair, which parameters actually vary)
> 4. Cross-run consistency exceptions
> 5. Recommendations (re-execute, relabel, or accept with caveat)
>
> **DO NOT** declare a condition "consistent" after checking only the first
> run. Check every run. **DO NOT** treat directory names as evidence of
> configuration — they are the hypothesis being tested. **DO NOT** skip runs
> when a source is missing — flag as UNVERIFIABLE and proceed.
>
> **This audit is complete when:** every run with runtime metadata has been
> inventoried, all checks applied, every FAIL recorded with severity, and
> a completeness count confirms "Audited N/N runs across M conditions."

**Effect:** Catches silent configuration mismatches in experiment pipelines
— wrong model, failed parameter overrides, label/metadata drift — that
surface-level checks miss because the results look plausible.

**Mechanism:** Combines 14 anti-satisficing techniques. The critical
structural move is Phase 1 (claims inventory #2): enumerating every run
before checking any forces the model to engage with the full scope rather
than spot-checking. Error mode anchoring (#9) with real past failures
calibrates the suspicion threshold. The source-of-truth hierarchy (#7)
prevents the audited artefacts (labels, metadata) from being treated as
their own evidence. Negative constraints (#10) block the specific
shortcuts that allowed a 3-week-old mislabelling to persist undetected.

**Results:** First deployment (2026-03-25) discovered that
every "Pro" model run in a 50+ run study actually used Flash — affecting
both proposer and verifier stages. The error was in the config file
(hardcoded model name) combined with a never-invoked CLI override. The
audit prompt's error mode anchoring and bidirectional verification caught
it where manual spot-checks had not.

**Source:** Generated via an iterative prompt-hardening process, 2026-03-25.
