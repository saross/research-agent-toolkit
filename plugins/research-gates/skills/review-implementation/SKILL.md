---
name: review-implementation
description: "Structured review protocol for catching suboptimal implementations and methodology choices. Use when completing a significant new integration, adopting a new tool or method, or at phase boundaries in a project. Surfaces both 'discovery failures' (capabilities not yet considered) and 'exploitation failures' (capabilities known but underused)."
---

# Implementation and Methodology Review

A structured protocol for making sure a newly implemented approach uses the full capability
envelope, rather than stopping at the first working solution. It applies to an API integration, a
statistical method, a data processing pipeline, an experimental design, or any other significant
technical decision.

## When to Use

- After implementing a significant new integration or methodology
- At phase boundaries, when establishing infrastructure for a new stage of work
- When adopting a new tool, API, library, or analytical technique
- When the user asks for an implementation review
- When you recognise, partway through, that you've made a significant design choice the user may not
  have the domain expertise to evaluate
- Proactively, when the aggregate implications of an approach haven't been stated
- Before lodging a preregistration, launching a study, or committing to an experimental protocol:
  run the review at the commitment boundary, while defects are still free to fix rather than public
  amendments

## Background: The Discovery/Exploitation Pattern

Human–AI collaboration has two distinct failure modes when adopting new approaches:

1. **Discovery failure**: not knowing a capability or method exists. Capability scanning addresses
   it, by broadening the search space before committing.
2. **Exploitation failure**: knowing a capability exists, but implementing it conservatively,
   without using the full configuration space available. This is harder to catch, because the
   implementation works correctly; it's just suboptimal.

Both are especially likely when the human collaborator isn't the primary expert in the domain, such
as programming, statistics, API design, or systems architecture. The first methodologically sound
approach is often accepted without surveying the solution space for strictly better alternatives.

## Protocol

Work through each phase in order. State your findings for each phase explicitly, and don't skip a
phase even if it seems unnecessary.

### Phase 1: Capability Scan (What Else Exists?)

Survey the full solution space for the domain in question. Ask:

- **APIs and services**: are there alternative execution modes (batch, streaming, asynchronous),
  tiers, or features we haven't considered? Check the full API surface, not just the endpoints in
  use.
- **Statistical methods**: are there alternative tests or estimators that are strictly more
  powerful, more appropriate for the data structure, or better suited to the hypothesis? For
  example, paired rather than unpaired tests when observations are naturally paired; Bayesian or
  frequentist approaches; exact rather than asymptotic methods for small samples.
- **Programming patterns**: are there alternative architectures (parallel or serial, batch or
  streaming, lazy or eager) that fit the workload better?
- **General**: what would a domain expert consider standard best practice for this kind of problem,
  and does our approach match it?

Report any alternatives found, with a brief assessment of whether they would be materially better
for this specific use.

### Phase 2: Exploitation Review (Are We Using It Fully?)

Examine the current or proposed implementation against the full capability envelope:

- **Concurrency and parallelism**: are we processing sequentially when parallel execution is
  available? What are the concurrency limits, and how much of that capacity are we using?
- **Batch and bulk operations**: are we making individual calls where batch endpoints exist, and are
  we using the maximum batch size?
- **Configuration space**: have we accepted defaults without checking whether alternatives would be
  better? For example: significance levels, chunk sizes, timeouts, or model hyperparameters.
- **Error handling and resilience**: does the implementation handle partial failures gracefully, or
  does one failure cascade into retrying the whole operation?
- **Cost optimisation**: are there pricing tiers, reserved capacity, or discount modes, such as
  batch pricing or spot instances, that reduce cost for this usage pattern?

For each dimension, state whether the current implementation uses the full capacity or leaves gains
on the table.

### Phase 3: Quantitative Audit (What Does It Actually Cost?)

Compute the total resource implications of the current approach, and compare them with the best
alternative from Phases 1 and 2:

- **Wall-clock time**: total elapsed time from start to finish, including worst-case failure and
  retry scenarios. State the formula: N items × L latency × R expected retries.
- **Monetary cost**: total spend, not per-unit cost, including the cost of failures.
- **Human attention cost**: does the approach need a person to monitor or intervene? How often, and
  what happens if they're unavailable?
- **Failure cascade cost**: if one unit fails, what does recovery cost? Serial processing may mean a
  failure at unit 60 of 70 restarts from unit 60, where parallel processing would already have every
  other unit complete.

Present a comparison table where possible:

| Dimension | Current approach | Alternative | Difference |
| --- | --- | --- | --- |
| Wall-clock time | ... | ... | ... |
| Monetary cost | ... | ... | ... |
| Failure resilience | ... | ... | ... |

### Phase 4: Recommendation

Based on the above, give a clear recommendation:

- **No change needed**: the current approach is at or near the optimum for this use. State why.
- **Low-effort improvement**: a configuration change or minor refactor would bring material gains.
  Describe the change and the expected improvement.
- **Significant redesign warranted**: a different approach would be substantially better, but needs
  real implementation effort. Describe the approach, the expected gain, and the implementation cost,
  and let the user decide.

## Domain-Specific Checklists

### API and Service Integrations

- [ ] Checked for batch or bulk endpoints
- [ ] Checked concurrency limits and parallel submission options
- [ ] Checked for different pricing tiers (batch, spot, reserved)
- [ ] Computed total wall-clock time at the aggregate level
- [ ] Checked for asynchronous or webhook options instead of polling
- [ ] Reviewed the rate-limit structure (per request, per minute, or daily)

### Statistical Methodology

- [ ] Checked whether paired tests are available for paired data
- [ ] Checked whether exact tests are appropriate for small samples
- [ ] Checked whether multiple-comparison corrections are needed
- [ ] Verified that the test's assumptions match the data structure
- [ ] Considered whether Bayesian alternatives offer advantages
- [ ] Computed statistical power for the chosen test and sample size

### Data Processing Pipelines

- [ ] Checked whether operations can be parallelised
- [ ] Checked whether intermediate results can be checkpointed
- [ ] Verified that failure handling is granular (per item, not per batch)
- [ ] Checked whether streaming or lazy evaluation would reduce memory use
- [ ] Computed total processing time at the aggregate level

### Experimental Design

- [ ] Checked whether blocking or stratification would improve power
- [ ] Verified that the control condition is appropriate
- [ ] Checked whether adaptive or sequential designs are applicable
- [ ] Computed the sample size needed for the target power
- [ ] Reviewed whether confounds have been adequately controlled

### Study Designs and Preregistrations

Added after a preregistration review in a reproducibility study. The protocol's phases generalised
to study designs, but the most valuable findings (circularity, criterion contamination,
post-treatment conditioning) came from reasoning the protocol hadn't prompted. This checklist
encodes them, so later reviews don't depend on the reviewer re-deriving the defect classes.

- [ ] No definitional circularity: the outcome's definition shares no content with the predictor
      (verdicts, composite scores, and rubrics are the usual offenders)
- [ ] No criterion contamination: measures don't directly reward membership of the grouping variable
      they are tested against
- [ ] Sample restrictions are treatment-invariant: no filtering on variables the intervention or
      policy could itself affect (post-treatment conditioning)
- [ ] Each hypothesis's wording claims only what its test can establish (equivalence and "regardless
      of X" clauses need equivalence-grade designs)
- [ ] Causal language has a counterfactual: a control series, comparison group, or explicit trend
      adjustment, because a before-and-after alone is confounded with time
- [ ] Everything relevant to the analysis is specified in advance: cohort assignment rules,
      missing-data fallbacks, exclusion handling, and denominators, all locked before outcomes are
      observable
- [ ] Blinding or ordering commitments wherever an assessor's knowledge of outcomes could
      contaminate scores (state the pipeline order explicitly)
- [ ] Instruments have a reliability and validation plan, with thresholds and pre-specified
      fallbacks (especially instruments scored by an LLM)
- [ ] Power computed per test with realistic group splits; under-powered tests reframed as
      estimation up front, not excused afterwards
- [ ] An amendment and deviation policy is stated, and the review runs BEFORE the commitment
      boundary (lodgement, launch, spend), while fixes are still free

## Standards

- Follow the user's language and style conventions, for example from their `CLAUDE.md`
- Be specific and quantitative; avoid vague qualitative assessments
- State the aggregate numbers, not just per-unit figures
- Present trade-offs honestly, and don't oversell alternatives
- Say when you lack confidence in a recommendation. For example: "I believe paired permutation tests
  are more appropriate here, but I'd recommend checking with a statistician for this specific
  design"
