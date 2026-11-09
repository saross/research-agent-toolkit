---
title: "Anti-confabulation apparatus — inventory, evidence, and open questions"
tags: [anti-confabulation, llm-craft, audit-pattern]
created: 2026-09-24
updated: 2026-11-09
status: reviewed
reviewed: 2026-11-09
---

# Anti-confabulation apparatus — inventory, evidence, and open questions

A living reference to the guards this system uses against confabulation. Here,
confabulation means a large language model (LLM) stating an invented or stale
specific (a number, file path, identifier, citation, quotation, or commit hash)
with the same fluency as a true one. The guards accumulated between April and
September 2026. They were built one incident at a time and have never been
described in one place.

**This document is descriptive.** Nothing in the apparatus changes because of
it. The apparatus is working, on the evidence of what it catches; nothing yet
measures what escapes it (see [Evidence](#4-evidence-that-it-works)). So any
rationalisation starts from the [open questions](#7-open-questions-for-review)
at the end and goes through review, not through this page.

**Anchors.** Every specific below carries a re-verifiable anchor: a path with a
line number, or a commit hash. The anchors point into the author's private
working repository, with line numbers as at its commit `61b37e7`, so they don't
resolve here. They are kept so that the evidence trail stays explicit. Two other
sources are private repositories, described but not linked: an applications
repository with its own claim registers, and the working repository for Paper B.
Paper B's submitted manuscript is public at
[osf.io/m376w](https://osf.io/m376w/), and it is cited here by section.

## 1. The two failure shapes the apparatus exists for

1. **Fragment welding.** When many identifiers sit in context together, the
   model composites adjacent fragments into new ones that look plausible, and
   then cites them with conviction. Cutting the volume of surfaced memories
   "reduced incidents but did not eliminate them"
   (`wiki/planning/vector-2-design.md:106-111`). The rule that anchors this
   whole apparatus was introduced in response (`40f58a9`, 2026-04-24).
2. **A record read as a source.** The model trusts a derived artefact (its own
   summary, a continuity line, a stale plan row) in place of the thing it
   describes. Each restatement compresses further, until a plan reads as a slip.
   The lesson "a record is not a source" is recorded as having "fired six times"
   in three days (`wiki/continuity.md:2481`). `claude-obs 88` records the same
   shape three times in one week (`wiki/claude-observations.md:1703`).

## 2. Design principles the guards share

- **Stored context is "pointers, not authorities."** The read-side rule
  (`global-agent-guidance/common.md:13`): re-read the source before citing a
  specific.
- **The read side is only as good as the write side.** Every specific that gets
  saved must carry an anchor (a path, commit, or Zotero key). If a specific
  cannot be anchored, reword it to drop the false precision
  (`global-agent-guidance/common.md:15`; `85c832a`).
- **Anchors over confidence.** A self-reported confidence label is "decorative
  if it is not bound to an objective condition". When a check fails, the memory
  still lands, but flagged: **"Fail soft, never silent"**
  (`wiki/planning/memory-system-v2-design.md:41-47`).
- **Independence has to be structural.** "A same-context self-check cannot catch
  this ... The guard has to be in a fresh context window"
  (`wiki/reflections/abductive-reasoning.md:79-86`).
- **Procedure beats exhortation.** "The original prompt-level 'never fabricate'
  constraint failed; its procedural replacement succeeded"
  (`wiki/reflections/abductive-reasoning.md:160-162`).
- **More copies of one model are not independent checks.** "*N* Claude verifiers
  approximate one verifier with sampling variance, not *N* independent checks"
  (`wiki/planning/cross-model-verification-plan-2026-07-27.md:17-19`).

## 3. Inventory, by layer

"Enforced" means code or a hook runs regardless of whether the working model
cooperates. "Procedure" means a command or an agent contract sets out the steps,
and the working model carries them out: a separate agent's check is independent
once it runs, but whether it runs depends on the model following the command.
"Instruction" means it holds only if the model follows a written rule.

### 3.1 Instruction rules

<!-- markdownlint-disable MD013 -->
| Guard | What it does | Type | Since | Anchor |
| --- | --- | --- | --- | --- |
| Read-side rule | Re-read the source before citing a number, path, identifier, hash, config value, or quotation | Instruction | 2026-04-24 | `global-agent-guidance/common.md:13`; `40f58a9` |
| Write-side rule | Every saved specific carries an anchor; `session_id` is not one | Instruction | 2026-05-15 | `global-agent-guidance/common.md:15`; `85c832a` |
| Local restatements | The same rules, repeated in the handoff, session-start, and scratchpad protocols, the observation-writer agent, and the academic-prose "anchor test" | Instruction | various | e.g. `agents/obs-writer.md:34` |
<!-- markdownlint-enable MD013 -->

### 3.2 Memory and anchor layer

<!-- markdownlint-disable MD013 -->
| Guard | What it does | Type | Checks against | Anchor |
| --- | --- | --- | --- | --- |
| Anchor shape gate | Drops malformed anchors before a memory is written | Enforced | Anchor syntax | `scripts/anchor_verify.py:808`; `b6f85c1` |
| Anchor verification | A memory is "verified-true" only if every well-formed anchor resolves; one `false` makes the memory `false` | Enforced, at write time | Working tree and git history | `scripts/anchor_verify.py:889`; `50e663b` |
| Confidence binding | Overwrites the extractor's self-rated confidence with the verification result. The audit had found 93.1% of records self-rated "high", including every confabulation | Enforced | The verification result | `scripts/anchor_verify.py:955`; `wiki/planning/memory-system-v2-design.md:185` |
| Session-start digest | Surfaces verified-true entries first, within a 1,500-byte budget. Any unverified top-up is labelled "Unverified", and refuted entries are excluded | Enforced | The stored `verified` flag | `scripts/digest.py:74`, `:614` |
| Drift sweep | Re-resolves every anchor across the corpus and logs the result | Enforced when run; optional in the weekly review | Working tree and git history | `commands/weekly-review.md:125-131` |
<!-- markdownlint-enable MD013 -->

### 3.3 Separate-agent verification

<!-- markdownlint-disable MD013 -->
| Guard | What it does | Type | Checks against | Anchor |
| --- | --- | --- | --- | --- |
| lit-scout → lit-scout-verifier | A fresh-context verifier re-queries every cited DOI. Hand-off is "**Pure transfer**": no hints, no summary | Procedure (command); independent once it runs | CrossRef, Semantic Scholar, OpenAlex | `commands/lit-scout.md:65-69`; `965bbce` |
| Iterate loops | Proposer–verifier rounds, capped at five. "Always runs the verifier ... There is no bypass" (the command has no option to skip it). A row is removed only on an authoritative negative | Procedure (command) | As above | `commands/lit-scout-iterate.md:7-13` |
| prior-art and data-profile verifiers | Same pattern, for software and for dataset statistics | Procedure (command); independent once it runs | GitHub, PyPI, npm, Hugging Face; the dataset itself | `agents/prior-art-scout-verifier.md`; `agents/data-profile-verifier.md` |
| `VERIFICATION PENDING` marker | A draft is marked unverified until its verifier has run | Procedure (agent contract) | — | `agents/lit-scout.md:10` |
| `/review-paper` | A panel of fresh-context reviewer lenses, plus a no-LLM pre-pass that checks every citation key resolves. Contested findings are re-checked against sources before the report ships | Pre-pass enforced; step 4 an instruction | The `.bib` file; the sources | `scripts/review-paper-prepass.py:19-23`; `skills/review-paper/SKILL.md:100-104`; `171fa07` |
<!-- markdownlint-enable MD013 -->

### 3.4 Cross-model review

<!-- markdownlint-disable MD013 -->
| Guard | What it does | Type | Status | Anchor |
| --- | --- | --- | --- | --- |
| GPT in Codex as peer reviewer | Changes to shared policy go through a pull request reviewed by the other agent | Process, no code gate | Live | `wiki/continuity.md:2281-2293` |
| Second reader from a different vendor | A second-model verifier with a different lineage, recommended by Brian Ballsun-Stanton | — | **Not built**; design sketch | `wiki/planning/cross-model-verification-plan-2026-07-27.md:3-5` |
<!-- markdownlint-enable MD013 -->

### 3.5 Domain claim registers

- **Style-guide numeric verifier.** A deterministic check that exits non-zero
  when a style guide's figures do not match the corpus (`c4b47d5`).
- **Applications repository (private).** A register of verified literature
  figures with three evidence levels, and a claim audit giving every CV claim a
  source and a status. Motivated by a wrong figure copied through three
  applications before anyone checked it.

### 3.6 Self-critique registers

`wiki/claude-observations.md` records the model's own failures as dated
observations, `claude-obs 88` among them. `/confab` logs user corrections and
self-catches (`commands/confab.md`; `aa62095`). Neither enforces anything. They
are the raw material from which new guards have been built.

## 4. Evidence that it works

- **Verifier log** (`data/logs/confab-flags.log`, private; `353a45a`): 18
  verifier runs, 1,261 claims checked, 32 flagged, 11 classed as confabulation,
  up to 2026-09-24. There are also 4 manual entries (2 self-catches, 2 user
  corrections).
- **Cross-model review:** on 2026-09-22/23 the GPT reviewer caught Claude
  overclaiming three times, "every one ... an intended effect stated as a
  verified one" (`wiki/continuity.md:2281-2293`).
- **Anchor drift:** the sweep of 2026-09-21 found 1,247 of 6,650 anchored
  memories (18.8%) failing re-verification (`data/logs/drift-sweep.jsonl`, last
  row). An earlier reading of 28.2% was traced to a measurement artefact
  (`wiki/continuity.md:2432-2435`).

**What this evidence cannot show.** Every figure counts *catches*; none measures
*escapes*. No verifier has been tested with seeded errors, and the manual log
has no denominator.

### 4.1 Escapes, found by accident: Paper B (2026-09-24)

Compiling this document included a read-only pass over Paper B, to extract its
failure modes for §6. That pass found errors in the submitted paper that none of
the checks aimed at the paper had caught, either before submission or in the
corrections register kept since:

- **Missed carriers.** The register of post-submission corrections listed only
  tables. Supplement A restates the same figures in prose, so its discovery
  totals (242 tools and 154 verified, corrected to 241 and 153), its per-model
  and per-journal figures, and a subsection describing three rows since repaired
  all went out uncorrected. They would have stayed that way at revision.
- **Four consistency issues.** "Confabulated" is defined three ways, one per
  stage. "Misattribution" is used in two senses, one of which overlaps
  "confabulated". One journal's confabulation rate appears as 93%, 82%, and 78%
  on unstated denominators. And the cause of that rate is argued both ways.

All are now recorded for the revision round, with every corrected figure
re-derived from the repaired data. Paper B's registers are in a private
repository. The preprint is public at [osf.io/m376w](https://osf.io/m376w/), and
the journal's open peer review will publish the reviews and responses alongside
the article.

**Why the register missed them.** Its discipline, "re-verify before applying",
checks every carrier it lists. It cannot find a carrier it never listed. The
pass that found them asked the paper a *different question*. That is Paper B's
own orthogonal framing (§5.2) working on Paper B.

**What it shows here.** Strictly, these errors escaped the checks around Paper
B, not the guards inventoried in §3. What the episode shows is *how* escapes get
found, and it is the nearest thing to an escape measurement in this document. It
was also accidental; §7, question 9, asks whether to make it deliberate.

## 5. Weaknesses the documents themselves admit

1. **Anchors check existence, not truth.** "The file existing does *not* verify
   the memory's claim" (`wiki/planning/anchor-coverage-proposal.md:34`).
2. **Verification happens once, at write time.** The drift sweep reports but
   does not repair, and it runs only when chosen. The repair tool has been
   blocked since it needs a quiet corpus the extraction hook keeps re-dirtying
   (`wiki/continuity.md:2440-2443`).
3. **Coverage is thin.** Anchor production is "flat at ~27 % of post-v2 writes"
   (`wiki/planning/anchor-coverage-proposal.md:6-7`).
4. **Zotero and URL anchors are never checked.** Both return `pending`
   unconditionally (`scripts/anchor_verify.py:858`, `:885`).
5. **The literature verifier checks the findings table, not the narrative.**
   "You ignore the analysis sections for the purposes of verification"
   (`agents/lit-scout-verifier.md:62`). Narrative synthesis is where the
   confabulation was found (`wiki/reflections/abductive-reasoning.md:79-86`).
6. **Every automated verifier is Claude**
   (`wiki/planning/cross-model-verification-plan-2026-07-27.md:31`).
7. **The disclaimer does not stop conviction.** "Even with the 'pointers, not
   authorities' disclaimer, Opus 4.7 references surfaced entries with high
   conviction" (`wiki/planning/vector-2-design.md:100-105`).
8. **Instruction load.** Each session opens with about 370 lines of standing
   instruction, which weighs on every instruction-only guard (private task
   inbox, capture of 2026-08-25).
9. **The review loop is carrying too much.** "The cross-agent review loop is
   working and should not have to carry this much" (`wiki/continuity.md:2293`).

## 6. Paper B's lessons, mapped onto the apparatus

Paper B (Ross and Ballsun-Stanton, *Reliability in research with large language
models is a property of the human–AI system*, submitted 2026) argues that
deficiencies persisted across models and harnesses because they are "structural,
not a characteristic of particular models or harnesses" (§5.1). It proposes
three architectural principles and five further ones (§5.2). Its conclusion
calls for "sharing the scaffolding itself (skills, agent definitions, verifier
contracts) through open repositories" (§6). This document is a step in that
direction.

<!-- markdownlint-disable MD013 -->
| Paper B principle (§5.2) | Where the apparatus has it | Coverage |
| --- | --- | --- |
| **Independence of context.** "Freshness alone is not enough": a verifier can be captured by the artefact it audits | Proposer–verifier pairs with a pure-transfer hand-off (§3.3). **But session-state claims** (continuity notes, standups, recaps) are checked only by the session that wrote them | Partly |
| **External re-grounding.** "Each verdict terminated outside the model" | Registry re-queries (§3.3); anchor resolution against git (§3.2). Zotero and URLs are stubs | Partly |
| **Orthogonal framing.** "Start from the evidence and re-derive each claim, rather than start from the claim and seek its confirmation" | Registry re-derivation for bibliographic facts. Anchors confirm that the cited file exists, which is the confirmation direction the paper warns against. The narrative is unchecked (§5, item 5). The one clear demonstration so far was accidental (§4.1) | Weakest |
| **Procedure over pleading.** "Encode requirements that matter as workflow steps, not as exhortations" | The anchor gate, confidence binding, digest filter, citation pre-pass, and no-bypass loops are procedure. The read-side and write-side rules, the core of the apparatus, are still pleading | Partly |
| **Persistent external state, with tombstones.** Record "not only what was kept but what was rejected and why" | Continuity and observation registers; killed and superseded tasks archived, not deleted; corrections struck through with a dated reason, not erased | Largely built |
| **Stage-gated workflows with human checkpoints.** "'This stage failed' is an output the tool must be able to produce" | `VERIFICATION PENDING`; iterate loops that stop on PARTIAL, UNVERIFIABLE, no progress, or the cap, and flag it; pre-run and phase-gate audits | Built for research pipelines |
| **Match the mandate.** "Where a failure arises that nothing available can see, the mandate over that aspect must shrink until something can" | Not applied systematically. Status judgements ("late", "stalled", "unchased") are where the `claude-obs 88` failures occurred, and nothing independent checks them | Not built |
| **Working with the grain.** "Absorb the unwanted, codify the useful" | "Fail soft, never silent" (§2): a memory that fails verification still lands, flagged, and the digest labels unverified entries rather than dropping them. The self-critique registers (§3.6) turn logged failures into new guards. [`orthogonal-verification.md`](orthogonal-verification.md) §6 makes logging lucky finds a procedure, but only as a proposal | Partly |
| **Seed known errors to benchmark the verifier** (§6) | Not done | Not built |
<!-- markdownlint-enable MD013 -->

Two of the paper's failure modes deserve a guard of their own here:

- **Compounding across sessions.** Paper B's Supplement A records confabulations
  from one session becoming "authoritative inputs to the next". The memory layer
  defends against this (the verified-only digest, the "pointers" header).
  Handoff notes, resume prompts, and continuity entries have no equivalent
  defence, and they are where the "record read as a source" failures in §1
  occurred.
- **The self-check that passes its own error.** "Any self-check reproduces the
  error" (§2.2). Within a session, the read-side rule *is* a self-check.

## 7. Open questions for review

Proposals only. Nothing here is decided, and the apparatus stays as it is until
a question has been reviewed. These questions feed the standing-instruction
streamlining session already on the task list (private task inbox, capture of
2026-08-25). They are not a separate programme.

1. **Pleading to procedure for status claims.** Should a status word ("late",
   "stalled", "unchased") require citing the line re-read in this session,
   enforced by a hook or a command step? Or should the mandate shrink, so that
   the model reports dates and facts and the human assigns the status? (Paper B:
   procedure over pleading; match the mandate.)
2. **Verify the synthesis boundary.** Extend the literature verifier to the
   narrative sections, where the documented confabulation occurred.
3. **From existence to re-derivation.** For a sample of anchored memories,
   re-derive the claim from the anchored source rather than confirming that the
   file exists.
4. **Seed errors.** Measure what the verifiers catch by seeding known errors
   into their inputs, and so estimate escapes, not only catches.
5. **Re-verification over time.** Decide whether the drift sweep should run on a
   schedule, and whether the repair tool needs a design that tolerates a live
   corpus.
6. **Consolidate the restatements.** Keep one canonical rule and point to it
   from elsewhere, reducing instruction load without weakening anything.
7. **Model independence.** Decide between building the different-vendor second
   reader and formalising the existing GPT review loop, or doing both, given
   that "delegating the check to a second model does not automatically solve
   this problem" (Paper B §2.2).
8. **Handoffs as inputs.** Give resume prompts and continuity entries a defence
   equivalent to the digest's. For example, a handoff could mark which
   statements were re-verified at writing time, and the next session could treat
   every other statement as a pointer.
9. **Make orthogonal passes deliberate.** §4.1 found escapes by accident, while
   using a paper as input to a different task. Before a revision, a resubmission,
   or any artefact's release, should a pass run that *uses* the artefact rather
   than re-checking its listed items? Examples: extracting its claims for another
   purpose, or tracing every place a figure appears rather than every place a
   register names. (Paper B: orthogonal framing.)
   **Proposal:** the design rule, a catalogue of passes, a three-question drill,
   and a pilot at Paper B's revision are in
   [`orthogonal-verification.md`](orthogonal-verification.md). The organising
   idea is the *traversal key*: every check walks a list and is blind to what
   its list omits, so an orthogonal pass is one that walks a different list,
   ideally by building something from the artefact that will not compose if
   the artefact is wrong.

## How to update this document

- Add a guard when it ships, with its commit and anchor. Mark a retired guard as
  retired; do not delete it (tombstones).
- Refresh the evidence figures in §4 from source, with the date, and never from
  this page.
- Keep private content out. Describe private surfaces; do not quote them.
