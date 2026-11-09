---
name: phase-gate
description: "Experimental phase boundary checkpoint. Use before committing API spend, compute, or time to a new experimental phase — especially when scaling from pilot to production, applying a configuration selected on a subset to a larger dataset, or transitioning between optimisation and evaluation phases. Surfaces under-powered assumptions from prior phases and determines whether cheap validation is needed before proceeding. Trigger phrases: 'ready to run', 'start Phase X', 'scale up', 'production run', 'let's proceed with'. Also trigger PROACTIVELY when recognising a phase boundary, even if the user does not invoke it explicitly."
---

# Phase Gate: Experimental Assumption Checkpoint

A structured protocol for catching under-powered assumptions before they become expensive mistakes.
It complements the `review-implementation` skill, which checks whether the *approach* is optimal, by
checking whether the *decisions feeding the approach* were validated at the power the next phase
needs.

## When to Use

- Before committing API spend or compute to a new experimental phase
- When scaling from a pilot or subset to full-corpus evaluation
- When applying a configuration selected on one dataset to a different or larger dataset
- When moving from parameter optimisation to production runs
- When the user says "let's run this", "ready to proceed", or similar
- **Proactively**, when you recognise a phase boundary, even if the user hasn't invoked this skill

## Why This Exists

Human–AI experimental workflows have a specific failure mode: a decision made on a small sample,
with wide confidence intervals and overlapping alternatives, is carried forward as settled fact into
a larger and more expensive phase. The decision *feels* validated because it was data-driven, but
the data didn't have the statistical power to distinguish between the alternatives.

This is distinct from:

- **Not knowing an alternative exists** (caught by `review-implementation`)
- **Choosing the wrong method** (caught by domain review)
- **Implementation bugs** (caught by testing and audits)

The failure mode here is: **the right question was asked and the right method was used, but the
sample was too small to give a definitive answer, and nobody noticed before scaling up.**

## Protocol

Work through each step in order. Present findings as a table at the end.

### Step 1: Enumerate Assumptions

List every prior result or decision that the upcoming phase depends on. Be exhaustive, and include
decisions that seem obvious.

For each assumption, record:

- **What was decided** (for example, "the adversarial verifier is the best strategy")
- **What evidence supports it** (for example, "F1 = 0.796 on a 60-tile pilot")
- **What alternatives were considered** (for example, "brief, checklist, adversarial")

### Step 2: Power Check

For each assumption from Step 1:

- **Sample size**: how many observations supported the decision?
- **Confidence intervals**: were they narrow enough to exclude the alternatives?
- **Overlap**: did the best option's interval overlap with the runner-up's?

Flag assumptions where:

- the intervals of the chosen option and an alternative overlap;
- the sample was under 100, for proportion-based metrics such as F1;
- the decision was made on a convenience sample or subset.

Mark each assumption as:

- **Validated**: intervals don't overlap, and power is adequate
- **Under-powered**: intervals overlap, or the sample is too small
- **Untested**: no direct comparison was made

### Step 3: Cheapest Validation

For each under-powered or untested assumption:

- What is the **minimum cost** to validate it at full power, in time, money, and API calls?
- What is the **cost of proceeding without validation**: the total spend in the upcoming phase that
  depends on this assumption?
- What is the **cost ratio**: validation cost divided by phase cost?

A validation that costs 1% of the phase budget and takes ten minutes is almost always worth running.

### Step 4: Consequence Check

For each assumption, ask: **if validation shows we chose wrong, what changes?**

- **"Nothing changes."** The assumption isn't load-bearing for this phase, so skip validation even
  if it is under-powered. (Example: blue plots or red plots; the analysis is the same either way.)
- **"We'd need to re-run some experiments."** Partial rework, so validate if it's cheap. (Example:
  three of twenty configurations would need a different parameter.)
- **"We'd need to re-run the entire phase."** Full rework, so validation is mandatory whatever it
  costs. (Example: all twenty experiments used the wrong verifier strategy.)

### Step 5: Decision

Present the summary table and recommend one of:

- **Proceed**: all assumptions are validated or not load-bearing
- **Validate first**: list the specific validations to run, with their cost and time
- **Reconsider**: a fundamental assumption is untested and load-bearing, so the phase design may
  need revision

## Output Format

```text
## Phase Gate: [Phase Name]

| # | Assumption | Source | Status | Validation cost | If wrong... |
|---|------------|--------|--------|-----------------|-------------|
| 1 | ... | ... | Validated | — | — |
| 2 | ... | ... | Under-powered | $X, N min | Re-run phase |
| 3 | ... | ... | Untested | $Y, N min | Partial rework |

**Recommendation**: [Proceed / Validate first / Reconsider]

**Validations to run before proceeding:**
1. [Specific validation, cost, time]
2. [...]
```

## Standards

- Follow the user's language and style conventions, for example from their `CLAUDE.md`
- Be specific and quantitative: state sample sizes, interval widths, and costs
- Present the table even if every assumption is validated, which shows the check was thorough
- Don't skip steps; list even the "obvious" assumptions
- Say when statistical power can't be assessed, for example for a qualitative decision, and record
  what the decision rested on instead
- If the phase spawns LLM agents, confirm the model is pinned explicitly and recorded in the phase's
  outputs, never inherited from the session. In practice, session metadata and commit trailers have
  both mislabelled the executing model after a switch partway through a session
