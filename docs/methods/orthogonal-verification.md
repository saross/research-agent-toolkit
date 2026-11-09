---
title: "Orthogonal verification — traversal keys, and how to plan for serendipity"
tags: [anti-confabulation, verification, llm-craft, audit-pattern]
created: 2026-09-24
updated: 2026-09-24
status: reviewed
reviewed: 2026-11-09
---

# Orthogonal verification — traversal keys, and how to plan for serendipity

Some of the most productive checks in this system have been accidents. A pass
made for one purpose turns up errors that every check aimed at the artefact had
missed. This page explains why that happens and turns the explanation into
something that can be planned. It is the working answer to question 9 of the
[anti-confabulation apparatus](anti-confabulation-apparatus.md#7-open-questions-for-review).

The difficulty it addresses is real. Serendipitous orthogonal passes are
powerful, but asking "what check would find the thing I missed?" does not work
on demand. The question describes the goal and gives no route to it. The
concept below supplies the route.

## 1. The case that prompted it

On 2026-09-24, compiling the apparatus document meant extracting the failure
modes of Paper B (Ross and Ballsun-Stanton, *Reliability in research with large
language models is a property of the human–AI system*, submitted 2026; preprint
at [osf.io/m376w](https://osf.io/m376w/)). That read-only pass found errors in
the submitted paper that nothing aimed at the paper had found (apparatus
document, §4.1):

- The paper's corrections register listed every file it expected to carry each
  corrected figure, and every place it listed was a table. The supplement
  restated the same figures in prose, so it went out uncorrected, and the
  register would never have caught it.
- The paper defined "confabulated" three ways, used "misattribution" in two
  senses, and gave one journal's error rate three different values.

The register was diligent: "re-verify before applying", with a command for
every figure. Its checks were sound. They were aimed along the wrong line.

## 2. The concept: every check has a traversal key

Every check walks a list, and the list is its **traversal key**. A check can
only find errors on the items its list contains. It is blind, by construction,
to everything its list omits, however carefully it examines what it does visit.

- The corrections register walked from **each correction** to **the places its
  author expected that figure to appear**. It found every place it listed and
  could never find one it didn't.
- The pass that found the errors walked **the text itself**, sentence by
  sentence, because its job was to extract failure modes. It met the
  supplement's figures in place. Where the paper would not hold together, it
  met *friction*: no single definition of "confabulated" could be written down,
  because the paper has three.

The orthogonality was not in the checker's intent; it had no intention of
checking anything. **It was in a task whose success required the artefact to be
consistent.**

<!-- markdownlint-disable MD013 -->
| Existing check | Its traversal key | Blind by construction to | An orthogonal key |
| --- | --- | --- | --- |
| Corrections register | Each correction → the places its author expected the figure | Places no one listed | Every figure in the text, wherever it sits (a **number census**) |
| Literature verifier | Rows of the findings table | The narrative synthesis, where confabulation actually occurred | The sentences of the narrative |
| Anchor verification | Each anchor → does the file exist? | Whether the file says what the memory claims | Each claim → re-derive it from the anchored source |
| Status claims ("late", "unchased") | The model's own earlier summaries | Anything that changed since | Walk the files, then derive the status |
| Proofreading | Sentences, in reading order | Whether a term means the same thing in §2 and §5 | Each defined term → every place it is used (a **term census**) |
<!-- markdownlint-enable MD013 -->

## 3. Why planned verification usually shares the key

Checks are designed by the people, or models, who built the artefact, from
their model of it. The register's list of expected places *was* its author's
model of the paper, so it could not see past that model. This is why a planned
check and the production it checks so often share blind spots, even when a
different person or a fresh context runs the check.

It is the same trap Paper B names at the level of a single claim: "start from
the evidence and re-derive each claim, rather than start from the claim and
seek its confirmation" (§5.2). A register that walks from the correction to its
expected places is starting from the claim.

The craft notebook already held the rule that should have caught this. "A fix
is not complete until everything derived from the fixed thing has been
re-derived" (2026-09-14). Its first step, "enumerate the consumers", is
exactly what the register did, from the upstream side. Its third step says to
"measure coverage from the artefact the final consumer actually reads, not from
the upstream side". That step is the orthogonal move, and it is the one that
was skipped. The rule was right; nothing turned its third step into a
procedure.

## 4. Why derivative tasks find errors: the Harris matrix

Archaeology has the clearest version of this. You do not find stratigraphic
recording errors by re-reading context sheets, which is a check walking the
sheets in the order they were written. You find them by **building the Harris
matrix**. The derived product will not compose if the records are wrong: a
cycle appears, or a context ends up both above and below another. The error
shows up as the impossibility of building something, not as a flag raised by a
checker.

The same happened with Paper B. The failure-mode extraction was a derivative
task, a product built from the artefact, and the errors appeared as places
where the product would not compose. So the useful signal is **friction**: the
points where a derivative task stalls, contradicts itself, or needs a choice
the source never made.

The everyday version happens constantly. On the same day, recording one new
task meant reading an old waiting-for row, and the row turned out to be stale.
Nobody had checked that row. A different task walked past it.

## 5. The design rule

1. **Name the traversal key of each check you already have.** What list does it
   walk?
2. **Plan a second pass with a different key**, one that walks something the
   artefact contains which the first list does not enumerate.
3. **Make the second pass a derivative task**: have it produce something new
   from the artefact, and log every point of friction. The friction log is the
   list of findings.

## 6. A catalogue of passes, cheapest first

1. **Censuses (scriptable).** A **number census** pulls every figure and
   percentage from every file a reader sees (main text, supplement, tables,
   abstract, cover letter), groups them by what they count, and reconciles each
   group against the data. A **term census** lists each defined term, where it
   is defined, and every use. Both walk the text, not the author's list.
   Between them they would have caught every Paper B finding except one:
   the contradiction over one journal's *cause* is an argument, not a figure
   or a term, and it needs a reading pass (item 2).
2. **Derivative tasks at the gates that matter** (submission, revision,
   release). In a fresh context, turn the artefact into something else: a
   150-word reviewer summary, a table of its claims, a teaching version, a
   replication plan for one table. The instruction is to log friction, not to
   check.
3. **Walk the files for status.** Derive status words from the underlying
   files rather than from summaries of them. This is the orthogonal fix for the
   "record read as a source" failure (apparatus document, §1).
4. **Log the lucky finds.** Tag each serendipitous catch with the task that
   produced it. Over time this builds an empirical catalogue of which uses find
   errors, so the list above grows from evidence rather than theory.

## 7. How to construct one on demand: a drill

When a check has passed and you still want to know what it could not see, ask
three questions:

1. **What does my check iterate over?** Name the list.
2. **What else does the artefact contain that this list does not enumerate?**
   Figures in prose, terms, dates, names, cross-references, the reader's actual
   path through the document.
3. **What could I build from the artefact that would fail to compose if it were
   wrong?** A matrix, a timeline, a summary, a table, a replication plan.

Then build it, in a fresh context if possible, and sort the friction.

## 8. What not to do, and caveats

- **Don't build a generic "orthogonal verifier" agent.** It collapses into an
  ordinary checker walking the claims list. The orthogonality lives in the
  *task*, not in the agent.
- **Some friction is legitimate.** Stage-specific definitions may be
  deliberate, so a human still has to sort the friction log.
- **Orthogonal is not the same as independent.** Paper B's three architectural
  principles answer three separate questions: where the check runs
  (independence of context), what its verdict rests on (external re-grounding),
  and which question it asks (orthogonal framing). A fresh-context verifier
  walking the same list is independent but not orthogonal. The traversal key is
  one practical way to specify the third question.
- **Calibrate with known errors.** Where some answers are already known, use
  them as seeded errors: a pass that misses them does not work. Paper B's
  conclusion asks for exactly this kind of benchmarking.

## 9. Proposed pilot

At Paper B's revision, run the number census and the term census over the main
text and supplement. This week's findings are known answers, so they calibrate
the method. If the censuses fail to find the supplement's places for the
corrected figures, the method does not work. If they find those and more, it is
worth generalising, starting with the gates in §6 and the status-claim walk
inside this system.

---

*Articulated 2026-09-24, in the session that found the Paper B errors. Proposal
only: nothing here is implemented, and planning is scheduled for an
infrastructure day.*
