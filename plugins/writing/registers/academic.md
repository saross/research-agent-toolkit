---
name: register-academic-default
description: >-
  Generic academic prose register bundled with the writing plugin: the
  drafting contract, voice and stance, sentence construction,
  punctuation, anti-flourish rules, and a quantitative gate. Used by the
  academic-prose skill when the user has set no register of their own.
---

# Academic register (bundled default)

**Load with this file:** `anti-tic.md`, in the same folder.

**What this is.** A starting register for plain, evidence-forward
scholarly prose, used when you have not set one of your own. It was
distilled from one author's register: a style guide derived from 18 of
that author's publications (about 128,000 words, humanities and digital
humanities), calibrated against a comparison of a model's draft with the
author's final text, section by section. The rules generalise; **the
numbers are one author's measurements**. Measure your own published
prose and replace them, or copy this file, edit it, and point the
plugin's `academic_register` option at your copy.

**Orthography is yours.** Spelling, -ise or -ize, and the serial comma
follow your `CLAUDE.md`, the project's register notes, or the venue's
style. This file sets none of them.

## The drafting contract

Draft as **concept skeletons at target density, not polished voice**.
The author is always the prose editor; optimise the draft for their
editing, not for passing as them.

- Every load-bearing point gets all three legs: **mechanism** (how it
  works), **one concrete instance** (a named case, a number tied to the
  claim, or a worked illustration), and the **honest boundary** (the
  stated limit or counter-case). Partial skeletons, such as a mechanism
  without an instance or an instance without a boundary, were the
  largest single editing cost in the measured comparison.
- **Section types take different contracts.** Framing prose (abstract,
  introduction, background) is where drafts over-write: compress, with
  no rhetoric. Evidence prose (methods, results, discussion) is where
  drafts under-develop: expand every compressed assertion into a full
  skeleton. One uniform register produces both failures at once.
- **Anchor density** (concrete examples, quotations, and numbers tied to
  claims, per 1,000 words), as measured in the source corpus: evidence
  sections about 28–32; introductions about 13; abstracts about 35;
  background 8–14. Density comes from selection, not accumulation: an
  example must carry a claim.
- **Every specific is anchored.** A number, name, date, origin story, or
  model identity that can't be traced to the project's record is marked
  `[unverified]` in the draft, never stated smoothly.

## Voice and stance

- **First-person plural** ("we") in co-authored work, singular in
  sole-authored work. Vary the grammatical subject rather than opening
  every clause with "we". Never "the authors", and never a third-person
  self-reference such as "the researcher".
- **No direct address to the reader**, and no rhetorical questions.
- **No boosters**: "clearly", "obviously", "certainly", "definitely",
  "undoubtedly". Emphasis comes from precision or warrant.
- **Epistemic hedging is load-bearing.** "May", "might", "suggests", and
  "indicates" calibrate a claim to its evidence: keep them, and hedge
  the claim, not the verb. **Performed candour is out** ("We are candid
  about its reach"): state the real boundary quietly instead.
- **Concede only where the counter-position has real merit.** Model
  drafts concede about twice as often as the source corpus.
- **Attribution verbs match the evidence**: demonstrates or establishes;
  indicates or suggests; argues or proposes; notes or reports.
- **Plain, data-forward, argued.** Put explicit logical connectives at
  sentence heads where the logic would otherwise be implicit ("Since…",
  "In response…", "Finally…"). A sequence of assertions reads as a
  draft; an argued sequence survives editing.

## Sentences and paragraphs

- **Mean sentence length about 21–24 words.** Drafts run to 30 or more;
  split long chains. Never three consecutive sentences of five words or
  fewer.
- **Subordinators carry the connected register**: "while", "although",
  "despite". "However" sits mid-sentence, set off by commas, and opens a
  sentence only for a real paragraph-level turn.
- **Tense:** prior work in simple tenses ("Smith showed", not "Smith has
  shown"); past tense for completed fieldwork and methods; present for
  claims.
- **Passive voice is fine in methods.** Interpretive and claim-making
  prose stays active. No agentless "It was found that…".
- **Topic sentence first**, so that a skim of first sentences recovers
  the argument.
- **Anchor demonstratives**: "This evidence suggests", never a bare
  "This suggests". Keep "there are" and "it is" openers rare.

## Punctuation

- **Em-dashes: minimise** (at most about 0.2 per 1,000 words). Readers
  now associate them with model output. A survivor carries data or a
  definition, never drama. Use a pair of commas or parentheses instead.
- **Semicolons: permitted, not promoted.** Prefer a full stop or a
  subordinate clause; keep a semicolon only where it is the best
  construction.
- **Colons: sparing**, for a list or a definition only. No "X: Y" as a
  rhetorical move, and no colon-appended interpretive tags ("…: the
  reason X matters").
- **Parentheses are the main interruption device**, carrying
  definitions, qualifications, and data, not asides. Define an acronym
  in parentheses at first use, then use the short form.
- **Digits for numbers** ("92", not "ninety-two") unless the venue says
  otherwise.

## Anti-flourish

Over-performed voice was the failure the comparison found. Out by
default: figurative language and metaphor (literalise); "not X but Y"
antithesis as a recurring move (make the positive claim); ornate
parallelism; identity claims where the evidence shows similarity
("similar patterns", not "the same class"); and sentences about the
manuscript rather than the world ("A single case stands for the
class.", "The diagnosis is now visible.", trailing segues to the next
section, self-justifying appositions). A leading roadmap at a section
head is fine; backward and sideways narration is not. The companion
file `anti-tic.md` holds the full set of these rules.

## Citations

Citation style is set by the venue, and is not part of voice. When
drafting or editing, never add, remove, or restyle citations; leave
their placement and format to the author. "E.g." and "i.e." are
ordinary register.

## Known generation biases

Against the targets above, model drafts systematically: over-produce
"we" (about 1.3 times the corpus rate); over-concede (about twice);
over-lengthen sentences (means of 30 or more against 21–24); over-write
framing prose and under-develop evidence prose; perform voice; and state
unanchored specifics smoothly. Draft against these drifts.

## Quantitative gate

Run on request. A deviation is a flag for judgement, not a verdict. The
targets are the source corpus's measurements; replace them with your
own.

| Metric | Target | Tolerance |
| --- | ---: | ---: |
| Em-dashes per 1,000 words | ≤ 0.20 | hard ceiling |
| Semicolons per 1,000 words | ≤ 3.4 | draft low |
| Announcement colons per 1,000 words | ≤ 1.6 | sparing |
| Mean sentence length (words) | 21–24 | ±10 |
| Consecutive sentences of five words or fewer | 0 | 0 |
| Boosters per 100 words | 0 | 0 |
| Hedges per 100 words | 0.72 | ±0.1 |
| Concession rate (share of sentences) | 0.13 | ±0.05 |
| Anchor density per 1,000 words (evidence prose) | 28–32 | judgement |
| Skeleton completeness (load-bearing points) | 3 of 3 legs | judgement |
