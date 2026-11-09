---
name: pre-run-review
description: "Interactive pre-run review of a longer-running automated block. Use BEFORE launching any multi-item automated pipeline that will run largely unattended — a recompute queue, a migration, a batch campaign, a multi-session analysis programme. Walks the operator through six structured sections (artefacts, finished states, stop states, dependency structure, partial-completion semantics, verification stack) as a dialogue, capturing hardenings into the block's controlling document. Trigger phrases: 'pre-run review', 'audit this block', 'what will this produce', 'what are the tripwires', 'walk me through the run plan', 'deeper dive before we run'. Also trigger PROACTIVELY when about to start an automated block expected to span more than one session or more than ~5 chained items without human review between them."
---

# Pre-Run Review: Interactive Audit of an Automated Block

A structured dialogue run *before* a longer automated block executes, with two equal purposes:

1. **Hardening**: surface unstated orderings, missing gates, and unverified assumptions while they
   are still cheap to fix.
2. **Operator comprehension**: the person running the project should understand, at this level of
   detail, what is about to happen. That understanding is a deliverable, not a by-product.

**Where it came from.** It was first used before a five-item recompute queue in a map-reading study
(`map-reader-llm`, August 2026). One sitting produced four hardenings:

- a coherence ordering between two overlapping items;
- a one-commit-per-document rule;
- a countable completeness gate against mixed-vintage outputs;
- a layered verification stack calibrated to the project's measured claim-defect rate (619 of 7,894
  decisively recomputable claims mismatched, about 8%).

A review by a separate model the same day added the verifier denominator requirement, the
disagreement rule, cold derivation for answer-shaped claims, and the naive-reviewer stance.

## The Naive-Reviewer Stance

The questions that produce hardenings come from ignorance, not expertise. "Does item 3 depend on
item 2?" can only be asked by someone who doesn't already believe they know. A reviewer with full
project context tends to nod at the dependency structure, which is the one section where nodding is
most expensive.

So **ask the obvious question anyway, including ones you believe you already know the answer to.**
Asking costs one sentence; assuming costs a re-run. When an agent embedded in the project conducts
this review, rather than the human operator, either hand sections 4 and 5 to a fresh-context
reviewer or adopt the stance explicitly and answer each question from the artefacts, not from
familiarity.

## When to Use

- Before starting an automated block expected to run across sessions, or more than about five
  chained items without human review between them
- Before delegating a pipeline to background agents or scheduled runs
- When the user asks what a planned block will produce, or what its stop conditions are
- **Proactively** at the boundary; don't wait to be asked

## The Clean-Context Agent Pass

A standing complement to the operator's review, never a replacement for it. Run it **after** the
operator dialogue, against the **committed** plan, so it audits the hardened text rather than the
draft.

- **Who:** one fresh-context agent from a capable model tier, with full read tools, briefed with the
  naive-reviewer stance and none of the drafting context.
- **What it audits:** the plan's controlling document, plus every artefact the plan makes claims
  about, such as scripts, hooks, schemas, and registries.
  - Tell it to open the code, not to reason from the plan's own assertions.
  - Tell it to prefer live fault-injection probes over reading alone. For example: run the tool on
    an empty input; delete a sidecar file; reconstruct a regex target character for character.
- **Required output:**
  - **a denominator:** files opened with line counts, claims checked, probes actually run, and an
    explicit list of what was NOT checked;
  - **findings** as severity-ranked claims, each with file and line evidence and a concrete failure
    scenario;
  - **clean probes** reported one by one. A clean probe with its denominator is a result; an
    unexamined area is not.
- **Adjudication:**
  - The drafting session proposes a disposition for each finding: fix, accept with rationale, or
    dispute.
  - It lands the mechanical fixes before the go or no-go, and records the audit's outcome and any
    changes to the plan in the controlling document.
  - Judgement calls go to the operator. Findings never land automatically: the disagreement rule
    applies to the auditor too.

**Evidence from two runs, both valuable:**

- **A proof-of-concept run** in a reproducibility study returned 4 blockers, all confirmed. The
  headline was a receipt gate that had "blocked" 39 of 45 agent launches with no downstream effect.
- **A later pre-run audit** returned 19 findings against 17 files and 11 probes, 5 of them blockers
  before any spend, and all 19 were confirmed on adjudication. They included:
  - an empty-set reconciliation that reported clean, found by live execution;
  - a verification agent that matched itself;
  - a spend metric that couldn't be reproduced.

Both runs caught defects that the drafting agent and the operator dialogue had each missed,
precisely because a clean context has no stake in the draft's framing.

## Relationship to Sibling Skills

- **`phase-gate`** asks whether the *decisions feeding* the next phase carry enough statistical
  power. Run it first at experimental phase boundaries.
- **`audit-config`** checks *configuration correctness* against the protocol before API spend.
- **`pre-run-review`** (this skill) checks the *execution structure* of the block itself: what it
  emits, when it is done, when it must halt, and how its claims are verified.

The three chain naturally: `phase-gate`, then `audit-config`, then `pre-run-review`, then launch.

## Protocol: Six Sections

Run it as a conversation, not a lecture. Present each section, invite probing, and capture every
hardening the dialogue produces. Ground every claim in the actual scripts, documents, and data: open
the code and check output paths rather than reciting from memory. A review built on recalled
filenames inherits the roughly one-in-ten error rate it exists to catch.

### 1. Artefact inventory

For each item in the block: which files, records, or registrations it produces, where they land, and
which existing documents it refreshes. Name the cross-cutting artefacts too, such as manifests,
changelogs, and registers that tick over. Verify output paths from the code that emits them.

### 2. Finished states

A countable completion criterion for each item and for the block overall, such as "8 of 8 cells
carry both metrics against the new reference, and the drift check is clean", never "looks done".
State where the finish line sits relative to human sign-off: authored and committed is usually where
the automation finishes, and approval gates belong to the operator.

### 3. Stop states (tripwires)

List the conditions that halt the block and escalate. Common classes:

- **Spend**: any unplanned API or compute cost moves the item to a gated queue. Hard stop; never
  absorb it silently.
- **Invariant breakage**: a gate battery, census test, or lint that must stay green. Red means stop
  before building anything on top.
- **Surprising results**: a rank flip, a headline moving beyond its documented uncertainty band, a
  reversal of direction. Treat it as a finding, not a formality: check the pipeline, then escalate
  to the operator.
- **Missing or ambiguous inputs**: stop rather than substitute a near-enough source, because
  substitution is how reference data gets tainted.
- **Sequencing violations**: downstream items must not start early.
- **Environment**: where compute runs and whether hosts are available. Check; never silently fall
  back.

### 4. Dependency structure

Draw the dependency graph. Distinguish **hard data dependencies** (item B consumes item A's outputs)
from **artefact-coherence orderings** (A and B would each produce a copy of the same artefact, so
order them so that exactly one does). State which items are genuinely safe to run at the same time.
Coherence orderings are the ones nobody writes down, and the first thing parallel execution breaks.

### 5. Partial-completion semantics

What happens if an item stops halfway? Is the computation deterministic, and can it resume from
committed inputs? Is partial state *visible* (missing rows, absent changelog entries) or silent?
Name the mixed-vintage risk, where a downstream item consumes an upstream item that is only partly
refreshed, and gate it with the countable criteria from section 2.

For prose outputs, adopt the one-commit rule: a document's numbers and its changelog entry move in
one commit, so no document is ever left between two states.

### 6. Verification stack

Layers, calibrated to measured error rates at each boundary. Use the project's own figures where
they exist. The synthesis boundary, where numbers flow from computation into prose, typically runs
at about one in ten and deserves the heaviest layer.

- **Layer 0: anchors.** Machine-readable results come first, prose cites them, and every checkable
  specific carries a source anchor. This layer reads like a preliminary, but it is the foundation,
  and the one to protect under time pressure. Without anchors, Layer 2 has nothing to re-derive
  against and Layer 3 has nothing to sweep.
- **Layer 1: code.** Tests, linters, and an audit pass on new scripts.
- **Layer 2: blind verification.** A fresh-context agent that hasn't seen the drafting reasoning
  re-derives every checkable claim from committed artefacts and returns a corrections table. It is
  non-negotiable for the block's item with the most synthesis, and proportionate elsewhere. Three
  requirements keep it verification rather than confirmation:
  - **Report the denominator.** A clean pass and a lazy pass produce the same empty corrections
    table, so the verifier must report what it checked: claims identified, claims re-derived, and
    artefacts opened. "0 corrections across 34 re-derived claims" is evidence; "no corrections
    found" is not. (Precedent: a health check called a command that didn't exist and reported clean.
    Only fault injection showed it was checking nothing.)
  - **Corrections are claims, not verdicts.** The one-in-ten rate applies to the verifier too, and a
    wrong correction that lands automatically carries the verification layer's authority, which
    makes it harder to catch than the original error. State the disagreement rule up front: a
    correction that conflicts with the draft triggers a third derivation from the data, or the
    operator's judgement, and never "the verifier wins" by default.
  - **Ask answer-shaped questions cold.** Put claims about direction or winners to the verifier as
    questions, such as "which configuration wins on each metric?", derive the answers cold from the
    metric files, and then compare them with the prose. Never hand them over as statements to check.
    A verifier anchored on the answer before it starts is confirming, not verifying. The same goes
    for comparison tables: rebuild them independently from the sources, then compare.
- **Layer 3: consistency.** Mechanical cross-document checks, such as drift checks and a sweep of
  every place a changed number is cited.
- **Layer 4: operator gates.** Sign-off fields, accept-edit-or-discard reviews, and slower
  programmes that extract claims for checking.

## Exit

The review ends with three things, or it didn't happen:

1. **Recorded hardenings**: every rule or gate the dialogue produced, written into the block's
   controlling document (the queue register, specification, or plan, not left in chat history), with
   a changelog entry.
2. **An explicit go or no-go** from the operator.
3. **The comprehension check, inverted**: the operator can state the block's stop conditions back.
   If they can't, the review isn't finished, whatever the checklist says. **Run this at every
   review, not once**, because repetition is how the stop-condition classes become second nature.
   The classes, as a mnemonic: **money, breakage, surprises, substitutes, order, environment**.
