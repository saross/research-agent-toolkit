# Adversarial Results Audit (generic template)

> *A reusable template, genericised from a domain-specific original built to
> stress-test a surprisingly-high benchmark result in a detection pipeline.
> Replace the `[BRACKETED]` placeholders with your project's specifics. Use it
> whenever a quantitative result is good enough that you suspect an error is
> inflating it — and you want an evidence-cited audit trail rather than a vibe
> check.*

**What it does:** Produces a structured, evidence-cited, layer-by-layer audit of
a results pipeline's headline metric. It forces the auditor to assume the result
is wrong until proven otherwise, enumerate every verifiable claim before
evaluating any, verify in both directions (code→claim and claim→code), and apply
indirect verification when a check is blocked rather than silently skipping it.

---

## Prompt

> # Adversarial Results Audit
>
> ## Task Declaration
>
> This is an ADVERSARIAL VERIFICATION task. Your goal is to find the error that
> inflates (or deflates) the reported `[HEADLINE METRIC]` — or to demonstrate,
> with evidence, that no such error exists. **Assume the result is wrong until
> proven otherwise.**
>
> This is NOT a code review, not a general assessment, and not a suggestions
> exercise. Do not comment on code quality, propose improvements, or note "minor
> issues" unless they directly affect the reported metric. Every finding must
> connect to a metric impact.
>
> ## Source of Truth (in order of authority)
>
> 1. **The codebase itself** — scripts, configs, and pipeline code as they exist
>    on disk.
> 2. **The reference / ground-truth data** — `[gold labels, annotations,
>    expected outputs]`.
> 3. **The raw output archives** — the system's actual recorded outputs.
> 4. **Output metadata** — version strings, timestamps, parameter logs, counts.
>
> When code behaviour contradicts documentation, comments, or commit messages,
> the code is authoritative. When output metadata contradicts input
> configuration, flag the mismatch.
>
> ## Framing
>
> `[State the result and why it is surprising — e.g. "Our pipeline reports
> [METRIC] = [VALUE], which exceeds the best published/expected result of
> [BASELINE]. If correct, this is remarkable; remarkable results are the ones
> most worth auditing."]`
>
> **We assume this result contains an error.** Your task is to find it. The error
> may be small or large, subtle or obvious — in the data, code, pipeline,
> configuration, metric calculation, or evaluation methodology. Small errors can
> mask larger ones, so investigate every anomaly, not only those that would
> directly inflate the metric.
>
> ## Audit Protocol — three explicit phases, do not combine them
>
> ### Phase 1 — Inventory (enumerate before evaluating)
>
> For each layer below, enumerate every verifiable claim or assumption the
> pipeline makes. Do not assess correctness yet. Produce a numbered checklist of
> claims per layer. (Example claims: "the reference set contains N items"; "the
> matching tolerance of X equals Y in the working units"; "no calibration items
> appear in the evaluation set".)
>
> ### Phase 2 — Verify (check each claim with evidence, both directions)
>
> For every claim: (1) restate it precisely; (2) locate where it is implemented
> (cite file + function/line); (3) state evidence FOR it being correct; (4) state
> evidence AGAINST; (5) verdict PASS / CONCERN / FAIL with the weight of
> evidence. Check both **code/data → claim** and **claim → code/data**. A check
> that "looks obviously fine" is the most likely place for an error to hide.
>
> ### Phase 3 — Synthesise
>
> Aggregate layer verdicts. Identify the single most likely source of metric
> inflation. If no error was found, state your confidence level and identify the
> weakest link — the layer where an undetected error is most plausible.
>
> ## Audit Layers (adapt to your pipeline; keep the "enumerate-then-verify" shape)
>
> 1. **Reference / ground-truth integrity** — count every reference item; check
>    for duplicates; confirm the reference total is consistent across every
>    report, script, and output that cites it; spot-check that reference items
>    align with the data they describe.
> 2. **Data preparation & coverage** — verify the input data covers the intended
>    scope with no silent gaps or losses; identify every item excluded from
>    evaluation (calibration/training/holdout) and confirm none leak into the
>    evaluated set; report exact counts: total / excluded / evaluated.
> 3. **Processing & parsing** — confirm raw outputs are archived; read the
>    parsing code and identify every path that could silently drop or duplicate a
>    record (swallowed exceptions, regex misses, empty-default returns); compare
>    items-in vs items-out and account for every difference.
> 4. **Matching / aggregation logic** — verify how predictions are matched to
>    references (or how records are aggregated). Confirm one-to-one assignment
>    where intended (no double-counting). If a tolerance/threshold governs
>    matching, verify its value and units, and sweep it across a range to confirm
>    the result curve behaves sensibly (monotonic where expected; inflection
>    point plausible).
> 5. **Metric calculation** — recompute the headline metric from raw counts; show
>    the arithmetic. Confirm the counts sum to the totals they should. Check how
>    edge cases (empty inputs, ties, missing values) are handled and whether they
>    inflate the metric. Spot-check a handful of units by hand against the
>    pipeline output.
> 6. **Configuration & pipeline integrity** — identify the EXACT configuration
>    that produced the result; list every parameter. Check for cached/stale/
>    intermediate files that could contaminate the evaluation (verify timestamps
>    and version metadata). Confirm the run used the model/version/inputs claimed.
> 7. **Cross-condition consistency** — compare the headline configuration against
>    several worse-performing ones; for each pair, confirm the performance
>    difference is directionally consistent with the parameter that differs. An
>    inexplicable gap is a red flag.
> 8. **Statistical validity** — how many independent runs contribute? Are they
>    truly independent (not cached copies)? Verify the confidence-interval method
>    and resampling unit. Enumerate how many comparisons the full study implies;
>    is multiple-comparison correction applied, and does it change which results
>    are significant?
>
> ## Specific Failure Hypotheses — test each explicitly (evidence for/against → verdict)
>
> 1. **Reference leakage** — are any ground-truth values visible to the system
>    (baked into filenames, embedded in prompts/metadata, passed in the request)?
> 2. **Tolerance / threshold inflation** — is the matching tolerance or decision
>    threshold actually what's claimed, or has a unit/conversion error made it
>    looser than intended? Show the arithmetic.
> 3. **Double-counting** — could one prediction satisfy multiple references (or
>    vice versa)? Confirm one-to-one assignment.
> 4. **Selective exclusion** — are poorly-performing items being silently dropped?
>    Compare the set submitted against the set evaluated; account for every difference.
> 5. **Inter-stage contamination** — in any multi-stage pipeline, does a later
>    stage see information from an earlier one that biases it toward agreement?
>    Trace the exact data passed between stages.
> 6. **Empty / trivial-case inflation** — are trivial cases (no signal, no
>    prediction) counted as perfect performance and inflating the aggregate?
> 7. **Train/eval overlap** — list evaluation-set IDs and calibration/training
>    IDs; confirm zero overlap.
> 8. **Stale results** — were the output files used for the metric actually
>    produced by the claimed configuration? Check timestamps and version metadata.
> 9. **Configuration mismatch** — does every input config used in the run match
>    the parameters recorded in the output metadata?
>
> ## When Blocked
>
> Some checks can't be run directly (re-running costs money; some inspection
> needs human eyes). When blocked: (1) mark the check BLOCKED — do not silently
> skip it; (2) check input configs against output metadata (mismatches are a
> common silent-failure mode); (3) compare with adjacent runs that differ by
> exactly one factor and confirm directional consistency; (4) state what would be
> needed to convert BLOCKED to PASS/FAIL.
>
> ## Output Format
>
> Per layer: `Claims inventoried: [count]`, then a table
> `# | Claim | Evidence checked | Verdict | Impact on metric`, then a layer
> verdict (PASS / CONCERN / FAIL) with 2–3 sentences citing evidence. For the
> failure hypotheses: `# | Hypothesis | Evidence FOR | Evidence AGAINST | Verdict
> (REJECTED / PLAUSIBLE / CONFIRMED)`.
>
> ## Prohibitions — DO NOT
>
> - Declare a check PASS without citing the specific file, line, or data point.
> - Accept a plausible explanation for an anomaly without verifying it against the
>   code — "this is probably because…" is not evidence.
> - Skip a check because it "appears straightforward" — that's where errors hide.
> - Group multiple checks under one verdict — each gets its own status.
> - Propose fixes or improvements — this is verification, not development.
>
> ## Completeness Check (mandatory final step)
>
> List every layer and confirm it received a verdict; same for every failure
> hypothesis. Confirm every BLOCKED check applied the indirect-verification
> protocol. Identify the layer you spent the LEAST time on and re-check it. Ask:
> "If the error is in the one place I didn't look carefully, where would that be?"
> — and check there.
>
> ## Overall Assessment
>
> Conclude with: (1) confidence that the result is genuine (percentage +
> justification); (2) most likely error source, if found, with estimated impact;
> (3) the weakest link even if no error was confirmed; (4) specific additional
> checks that would raise confidence on any BLOCKED items.

**How it works:** The three-phase protocol (inventory → verify → synthesise)
prevents jumping to "looks fine" without enumeration. *Bidirectional
verification* catches errors visible from only one direction. The *adversarial
framing* ("assume it's wrong") counters the confirmation bias that makes a
flattering result feel trustworthy. The *when-blocked protocol* converts skipped
checks into indirect verifications instead of silent gaps. *Negative constraints*
close the common satisficing shortcuts (accepting plausible explanations,
grouping checks, skipping "obvious" items).

*Source: developed and hardened by Shawn Ross through an iterative
prompt-hardening process; genericised from a detection-benchmark original for
public reuse.*
