---
name: reflect
description: >-
  End-of-session reflection protocol. Use when the user invokes reflect,
  or asks to reflect on the current session, do end-of-session
  reflections, or similar. Guides Claude through updating the project's
  reflection documents in priority order, answering structured prompts,
  and keeping the reflection and investigation logs, and an agent-kept
  register of observations about the collaboration (created only with
  the user's agreement).
---

# End-of-session reflection

Update the current project's reflection documents by the protocol below.
Work through them in priority order; if context is short, do the top of
the list first.

**Why this exists.** Reflection documents record the texture of a working
session: what surprised, what changed belief, what will be hard to
reconstruct later. A factual log of what was done does not keep those
things, and they are what a researcher studying the work, or a future
session picking it up, most often lacks.

## Project context

The skill works in any project. Reflections are always scoped to the
**current working directory**, the project worked on in this session.

1. **Determine the project** from the working directory, and name it at
   the start ("Reflecting on session work in" and the project's name).
2. **Find the reflection documents:** a reflections folder the
   project's `CLAUDE.md` names; else `wiki/reflections/`, falling back
   to `docs/notes/reflections/`, relative to the project root. If none
   exists, propose the starting structure below and create it once the
   user agrees (`wiki/reflections/` unless they choose another place).
3. **Tag each entry** with the session date in its heading, in the form
   the document uses, and name the project in the entry's first lines,
   so entries are unambiguous when read out of context.

## Starting structure (new projects)

When no reflections folder exists and the user has agreed to one, create
it and fill it in two tiers. The front matter of each document is in this skill's
`templates/` folder, `${CLAUDE_PLUGIN_ROOT}/skills/reflect/templates/`.

### Always create

**`session-reflection.md`** (priority 1, scope: always; template
`session-reflection.md`): reflection on the texture, dynamics, and
significance of the session, using the prompt pool below.

**`session-log.md`** (priority 5, scope: always; template
`session-log.md`): a factual record of what was done, decided, and
produced. Summarise, don't reflect: that is the reflection's job.

When relevant, close a log entry with a brief **Contextual assumptions**
note: what was true at the time that won't be obvious from the facts
alone, such as decisions made under time pressure, tool or interface
constraints that shaped the approach, or outside dependencies. Skip it
when the context is self-evident.

### Always ask

After creating the two core documents, ask the user whether they want
this one too, and say briefly what it does.

**`abductive-reasoning.md`** (priority 3, scope: conditional; template
`abductive-reasoning.md`): captures sequences of surprising fact, probe,
and belief revision. It is updated only when a session produced a
genuinely surprising finding, a belief revision, or a hypothesis tested
and confirmed or disconfirmed; the condition keeps entries sharp. Kept
across several projects, the documents form a corpus for studying how
reasoning with an AI agent goes in practice.

### Abductive entry contract

The document is a research corpus, so entries must be findable,
auditable, and comparable across projects. Every new entry follows this
contract:

- **Heading:** `## Entry N — YYYY-MM-DD: <title>`, continuing the file's
  numbering.
- **First two lines of every entry (mandatory):**
  - `**Session:**` and this session's ID, which Claude Code gives
    here: `${CLAUDE_SESSION_ID}`. If that is still an unfilled
    placeholder (a dollar sign, a brace, and the words
    `CLAUDE_SESSION_ID`), write `unrecorded`. Never guess.
  - `**Instance:** primary` (the default), or `post-compaction` or
    `continuation-from-summary` when this instance did not directly
    experience the episode.
- **Core sections:** `### Surprising fact`, `### Probe`, and
  `### Belief revision`, always with these names.
- **Named optional sections** (use these titles, not improvised ones):
  `### What would change this belief` (a falsifier; use it liberally),
  `### Implications for practice`, and `### What this is not`.
- **Skip assessments are mandatory.** When the skill runs and no episode
  qualifies, append a one-line dated assessment (`### YYYY-MM-DD —
  Assessment: no qualifying episodes`, then one sentence on why). The
  skips are the denominator for any analysis; silence loses data.
- **Annotations added afterwards** are always marked as such:
  `**Session anchor (retro-matched YYYY-MM-DD):** …`, with a confidence
  label. Never present a later match as contemporaneous.

> **Never create or edit `working-notes.md`.** A project's working notes
> are the research record itself, not a reflection document; if one sits
> inside the reflections folder, leave it out of the loop below.

### Never create automatically

Domain-specific documents (for example a log of model behaviour in a
project that studies language models) are not created from templates.
Let them emerge when the user sees a need.

## Instance boundary

Reflections are most valuable when written by the instance that did the
session's work. If this run follows a compaction or a continuation (you
are working from a summary of the conversation, not from direct
experience), say so explicitly in the entries, and distinguish
first-person observation from plausible reconstruction.

## Protocol

Process every `.md` file in the reflections folder, sorted by the
`priority` field in its front matter (lowest number first). **Exclude
`working-notes.md`** if it is present.

For each document, **read it first**, for its numbering and context.
Then append a new dated section that responds to what was distinctive
about *this* session. Don't copy the structure of earlier entries: let
the content set the form.

### Conditional documents

A document with `scope: conditional` in its front matter has a
`conditions` field saying when to update it. Judge whether this session
meets the conditions; if not, state that assessment and skip it (for the
abductive document, with the mandatory skip line above).

### Session reflection prompts

For the session reflection (priority 1), choose two or three prompts
from this pool, by relevance to the session. Don't use them all, and
don't impose a fixed structure: let the prompts guide free reflection.

**Rotation guard.** Over many entries the document should hear from the
whole pool, not a favourite few. Before choosing, glance at the previous
two entries: if a prompt appears in both, prefer one that appears in
neither. Relevance still wins, but between two equally apt prompts, take
the one the document has heard from least.

**Core pool** (use at least one):

- What surprised you about this session?
- What would you do differently if you replayed this session?
- What question emerged that wasn't pursued?
- What context from this session will be hardest to reconstruct in six
  months?

**When relevant:**

- What felt uncertain or unresolved at the end?
- What was different about this session compared with recent ones?
- Where did you and the human disagree, and who was right?
- What decision or trade-off made today will look arbitrary without this
  session's context?
- What is the single most important thing a future reader should know
  about this session?

When both parties' contributions matter, weave them into the narrative
of how the session went. A ledger of what each party brought loses the
session's texture, which is what the reflection exists to record (see
**Why this exists** above).

## Claude observations (after the reflection documents)

`claude-observations.md` is **not** a reflection document. It is a
**default-keep** register of what *you*, the agent, observed about *the
user* (their working style, choices, and decision dynamics), plus your
own self-critiques of the collaboration. The defining axis is **the
observer**: what you observe about the user goes here, not what the
user observes about you. It lives beside the reflection set (for
example `wiki/claude-observations.md`), **never inside the reflections
folder**, so it is outside the priority loop above.

**The first time, ask.** If the file doesn't exist, say what it is for
and ask whether to keep one; if the user agrees, create it from this
skill's template (`templates/claude-observations.md`). Once it exists,
you write it directly: entries are kept by default, not waiting on the
user's acceptance.

After the reflection documents, append an entry for each thing worth
carrying forward from how the user worked this session: a working-style
choice, a productive push-back, a self-critique of your own part, or a
win or pitfall of how you work together, seen from your side. Most
sessions yield at least one; when there is nothing worth recording, say
so in the closing message instead of writing a thin entry.

**Duplicate guard.** Check for entries already dated today first; if
this session's observations are there, add only what is genuinely new.

**Show them.** After writing, show the full text of the new entries in
the session's closing message. The user reads them at session close to
correct course; kept by default does not mean unseen.

Format: `## claude-obs N — YYYY-MM-DD: <one-line summary>`, with
**Pattern.**, **Lesson.**, and **How to apply.** sub-blocks. Never change
an entry in place once the user has read it: a correction is a new entry
that cross-references the old one.

## Standards

- Follow the user's language and spelling conventions (their
  `CLAUDE.md`).
- Concise but substantive: these are research documents.
- Continue existing numbering sequences; never restart them.
- Use dated section headers in the established format.
- Update document footers or timestamps where they exist.
