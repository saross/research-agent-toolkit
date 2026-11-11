---
name: academic-prose
description: >-
  Use when drafting, revising, or reviewing academic prose: papers,
  preregistrations, grant text, supplements. Loads the user's register
  (their own or the bundled default, then any project register notes)
  before touching prose, then enforces the drafting contract: concept
  skeletons at target density, five per-sentence tests, and countable
  exit checks.
---

# Academic prose: delivery discipline

**Announce at start:** "I'm using the academic-prose skill; loading
the register before I touch prose."

This skill is a **delivery mechanism, not a style guide**. The
register (voice, punctuation, measured targets) lives in Markdown
files and is loaded at the gate below. The skill supplies what those
files cannot: the gate itself, the drafting contract, the per-sentence
tests, and the exit checks. The architecture is borrowed, with thanks,
from Brian Ballsun-Stanton's academic-writing skill in
[denubis-plugins](https://github.com/Denubis/denubis-plugins), with
the register kept outside the skill.

In what follows, **the author** is the person whose prose this is:
the user, or the user and their co-authors.

## Gate: load the register (before prose work; re-open, don't recall)

Read these in full, in this order.

**1. The base register.** The user's own register, if they have set
one, is the path on the line below:

```text
${user_config.academic_register}
```

The option is **not set** in exactly two cases. One: the line is
empty, or only spaces. Two: the line is an unfilled placeholder and
nothing else, which reads as a dollar sign, an opening brace, the
words `user_config.academic_register`, and a closing brace. In either
case, read the generic register bundled with this skill instead:

```text
${CLAUDE_PLUGIN_ROOT}/registers/academic.md
```

If the option is set but the file can't be read, say so in your first
reply, naming the path, and use the bundled register meanwhile. Don't
guess at what the missing file said.

**2. Its companions.** Read every file the base register tells you to
load with it (the bundled register names one, its anti-tic rules).

**3. The project's register notes.** These override the base register
wherever the two conflict. Read every file the project's `CLAUDE.md`
names as a register or style note, and every Markdown file this finds,
run from the project's root, skipping any that is plainly not about
prose (a coding style guide, say):

```bash
ls .notes/*.md docs/*.md 2>/dev/null | grep -Ei 'register|prose|style|voice|writing'
```

A summary in `CLAUDE.md`, or a memory of the rules, is a pointer, not
the rule. Re-open the files. This gate fires for every kind of prose
work, including a two-sentence tweak deep in a long session. Where the
register and this skill differ on style (a word, a mark, a flourish),
the register wins: it is the author's.

| Rationalisation | Reality |
| --- | --- |
| "I read them earlier this session" | A skim forty tool calls ago is not the rule in front of you. Re-open. |
| "It's a tiny edit" | Small edits are where drift regrows fastest. Same gate. |
| "This is only a preregistration or a review note" | Registered documents outlive papers. Same gate. |
| "I know the author's voice by now" | In one measured case, only 4–12% of the sentences in a draft written to imitate the author's voice survived near-verbatim into the final text. |

If the project has prose conventions that no register note records
yet, propose writing one at the end of the session.

## The drafting contract

The deliverable is a **concept skeleton at target density**, not
polished voice. The author is always the prose editor; the draft's
job is to make their edit fast. Imitating their voice optimises the
wrong objective.

Each load-bearing point needs all three legs: **mechanism, one
concrete instance, and its honest boundary**. Section types take
opposite disciplines. Framing prose (abstract, introduction,
background) compresses, with no rhetoric. Evidence prose (methods,
results, discussion) expands, with the full skeleton for every point.
The anchor-density targets are in the register.

## The five per-sentence tests

Run these on every sentence drafted or revised:

1. **Subject test** (filler): is the sentence's subject the *study*
   or the *manuscript*? A sentence about the manuscript (a
   significance announcement, structural narration, a trailing segue,
   a self-justifying apposition, a colon-appended interpretive tag) is
   cut or rewritten to state the substance. A leading roadmap at a
   section head is exempt; backward or sideways narration is not.
2. **Skeleton test** (compression): if the sentence carries a
   load-bearing claim, do mechanism, instance, and boundary all appear
   within its paragraph? Missing legs are the largest measured editing
   cost. Add them now, not "later".
3. **Anchor test** (confabulation): does every specific (number, name,
   date, origin, model identity) trace to the project's record? If it
   can't be verified this session, write `[unverified: …]` rather than
   stating it smoothly. Never invent a plausible specific.
4. **Density test** (starvation): does every claim running past about
   three sentences carry a concrete instance? Check the section's
   density against the register's targets before calling it done.
5. **Flourish test** (performed voice): figurative language, "not X
   but Y" antithesis, ornate parallelism, intensifiers, performed
   candour, and identity claims where similarity is what the evidence
   shows. Strip them on sight. Plain, data-forward, argued with
   explicit connectives.

## Revision and review passes

For revision of existing prose, including review of a draft someone
else wrote, run the tests as a classifier, not a rewriter. Produce a
finding for each flagged sentence (the test it failed, why, a proposed
fix), and apply fixes only where the pass was asked for as an edit.
When a reviewer or co-author asks to "signpost", "make explicit", or
"clarify the connection", answer with substance (the claim, stated
plainly, where it belongs), never with a sentence about the
manuscript.

Never launder earlier AI output: working text that looks authored may
be an unreviewed draft. Check it against the primary source before
promoting it.

## Countable exit checks (run before declaring prose done)

Run on the changed prose: copy the new or revised passage into a file of
this session's own, outside the project, and set `FILE` to its path (the
em-dash count also catches Markdown rules and LaTeX dashes; read each hit):

```bash
# Em-dashes (LaTeX and Unicode), semicolons, colons
grep -o -- '---\|—' FILE | wc -l
grep -o ';' FILE | wc -l
grep -o ':' FILE | wc -l
# Booster deny-list
grep -n -iE '\b(clearly|obviously|certainly|definitely|undoubtedly)\b' FILE
# "The authors", "it is important to note", and "whilst" (a register may allow it)
grep -n -iE '\bwhilst\b|the authors\b|important to note' FILE
# Stock additive openers ("Moreover", "Furthermore", "Additionally", "In addition")
grep -n -E '(^|[.!?][[:space:]]+)(Moreover|Furthermore|Additionally|In addition)\b' FILE
# Three consecutive short sentences (crude): eyeball any cluster
grep -nE '(\b\w+\b[[:space:]]+){0,4}\w+[.!?][[:space:]]+(\b\w+\b[[:space:]]+){0,4}\w+[.!?][[:space:]]+(\b\w+\b[[:space:]]+){0,4}\w+[.!?]' FILE
wc -w FILE
```

Turn the counts into rates per 1,000 words and report them against the
register's gate table; if the register sets no target for a count,
report the raw rate. A deviation is a flag for judgement, not an
automatic fail, but an unreported count is a skipped check.

## Red flags: stop if you catch yourself thinking

- "This sentence sounds like the author." Wrong objective. Is it
  plain, anchored, and skeleton-complete?
- "The section flows nicely." Flow is the author's job. Density is
  yours.
- "It's reviewer-facing, so pre-empt the objection." Defensive hedging
  is scar tissue. State the design, and put limits in the limitations.

## Before declaring the prose done

- [ ] Gate run this session; register files read in full
- [ ] Five tests run on every new or revised sentence
- [ ] Every load-bearing point skeleton-complete (3/3 legs)
- [ ] Section anchor density checked against the register's targets
- [ ] All specifics anchored or explicitly `[unverified]`
- [ ] Every in-text pointer to a section, table, or figure names one that exists
- [ ] Countable exit checks run and counts reported
- [ ] Other places in the project that need the same change (a fact, a name, a
      threshold) listed for the author
