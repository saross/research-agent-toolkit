---
name: register-academic-default
description: >-
  Generic academic prose register bundled with the house-style plugin: the
  drafting contract, voice and stance, sentence construction,
  punctuation, and a quantitative gate. Used by the academic-prose skill
  when the user has set no register of their own.
---

# Academic register (bundled default)

**These rules serve the reader.** A draft that obeys every rule and
still reads stiffly has failed; prefer the sentence a good reader would
want.

**Load with this file:** `anti-tic.md`, in the same folder. It holds the
rules shared by every register, which this file does not repeat; the
gate below counts some of them.

**What this is.** A starting register for plain, evidence-forward
scholarly prose, used when you have not set one of your own. It was
distilled from one author's register: a style guide derived from 18 of
that author's publications (about 128,000 words, humanities and digital
humanities), calibrated against a comparison of a model's draft with the
author's final text, section by section. The rules generalise; **the
numbers are one author's measurements**. Measure your own published
prose, then copy this file, replace the numbers, and point the plugin's
`academic_register` option at your copy.

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
  stated limit or counter-case). Partial skeletons were the largest
  single editing cost in the measured comparison.
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
- **Every specific is anchored** in the project's record or marked
  `[unverified]` in the draft. `anti-tic.md` says what counts as a
  specific and how to check a quotation.
- **Make each claim belong to this study.** A sentence that would stand
  unchanged in a paper on another site, period, or archive carries no
  information here. Tie it to this case with a name, a number, a date,
  or a source, or cut it. "Settlement patterns reflect a complex
  interplay of environmental and social factors" fits any survey;
  "Farmsteads cluster within 500 m of the spring line, while the later
  towers do not" fits only this one.
- **Every sentence adds information.** Cut a sentence that restates the
  last, announces the next, asserts importance without content, or
  brings in background the paragraph's claim does not use.

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
  the claim, not the verb.
- **Claims match the evidence.** Attribution verbs follow its strength:
  demonstrates or establishes; indicates or suggests; argues or
  proposes; notes or reports. Where the evidence shows similarity, claim
  similarity, not identity ("similar patterns", not "the same class").
- **Say what the evidence shows, as the author's reading.** Where the
  evidence supports a judgement, state it and hedge it to its warrant,
  rather than listing positions and leaving the reader to choose. "Some
  scholars see the deposit as votive, others as a hoard" reports; "The
  deposit is more likely votive, since the coins were pierced before
  burial" argues. If the author's position is not in the notes, leave a
  marked gap (`[author's reading?]`), never a neutral survey. A reading
  you propose goes inside the marker, never in the prose:
  `[author's reading? Proposal: poor visibility would understate the
  pattern, not produce it]`. Deleting the marker then deletes the
  proposal, so no argument the author didn't make survives an edit.
- **Plain, data-forward, argued.** Put explicit logical connectives at
  sentence heads where the logic would otherwise be implicit ("Since…",
  "In response…", "Finally…"). A sequence of assertions reads as a
  draft; an argued sequence survives editing.
- **Write directly.** Prefer a strong verb and a concrete noun to a
  roundabout phrase ("if", not "in the event of"), and turn
  nominalisations back into verbs ("indicate", not "are indications
  of"). Directness is not monotony: vary openings and structure, so that
  plain subject–verb sentences don't become a tic of their own.
- **Coin sparingly.** Introduce a coined term only if you will use it
  again, define it at first use, and don't stack abstract compounds.

## Sentences and paragraphs

- **Mean sentence length about 21–24 words.** Split long chains. Vary
  length: an occasional sentence ten or more words either side of the
  mean is welcome; a run of them is not. Runs of short sentences are in
  `anti-tic.md`.
- **Subordinators carry the connected register**: "while", "although",
  "despite". "However" sits mid-sentence, set off by commas, and opens a
  sentence only for a real paragraph-level turn.
- **Tense:** prior work in simple tenses ("Smith showed", not "Smith has
  shown"); past tense for completed fieldwork and methods; present for
  claims.
- **Passive voice is fine in methods.** Interpretive and claim-making
  prose stays active. No agentless "It was found that…".
- **Topic sentence first** in most paragraphs, so that a skim of first
  sentences recovers the argument. Weighting paragraphs by importance
  is in `anti-tic.md`.
- **Anchor demonstratives**: "This evidence suggests", never a bare
  "This suggests". Keep "there are" and "it is" openers rare.

## Punctuation

Colons, parentheses, and why em-dashes are a tell are in `anti-tic.md`.

- **Em-dashes: at most about 0.2 per 1,000 words.**
- **Semicolons: permitted, not promoted.** Prefer a full stop or a
  subordinate clause; keep a semicolon only where it is the best
  construction.
- **Acronyms:** define one in parentheses at first use, then use the
  short form.
- **Numbers:** spell out one to nine and use digits from 10; always
  digits with a unit of measurement ("9 cm") and in tables. The venue's
  style overrides.

## Citations

Citation style is set by the venue, and is not part of voice. When
drafting or editing, never add, remove, or restyle citations; leave
their placement and format to the author. "E.g." and "i.e." are
ordinary register.

## Check these first

Against the targets above, model drafts have been measured to
over-produce "we" (about 1.3 times the corpus rate); over-concede (about
twice); over-lengthen sentences (means of 30 or more against 21–24);
over-write framing prose and under-develop evidence prose; perform
voice; and state unanchored specifics smoothly. After drafting, check
these first. Use counts to check measurable drift, and source checks and
judgement for the other faults; a clean count does not excuse an
unanchored specific. A model
checking its own draft tends to under-flag, so the author's read, or a
fresh reviewer's, is the real check.

## Quantitative gate

The academic-prose skill runs these counts before handing prose over. A
deviation is a flag for judgement, not a verdict. The targets are the
source corpus's measurements.

| Metric | Target | Tolerance |
| --- | ---: | ---: |
| Em-dashes per 1,000 words | ≤ 0.20 | hard ceiling |
| Semicolons per 1,000 words | ≤ 3.4 | draft low |
| Announcement colons per 1,000 words | ≤ 1.6 | sparing |
| Mean sentence length (words) | 21–24 | ±3 |
| Runs of three or more sentences of five words or fewer | 0 | 0 |
| Boosters per 100 words | 0 | 0 |
| Hedges per 100 words | 0.72 | ±0.1 |
| Concession rate (share of sentences) | 0.13 | ±0.05 |
| Anchor density per 1,000 words (evidence prose) | 28–32 | judgement |
| Skeleton completeness (load-bearing points) | 3 of 3 legs | judgement |
