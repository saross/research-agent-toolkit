---
name: improve-prompt
description: >-
  Systematically improve a seed prompt using anti-satisficing techniques
  and structured prompt hardening. This skill should be used when the
  user wants to strengthen, harden, or optimise a prompt before deploying
  it — particularly for review, comparison, or analytical tasks where
  LLMs tend to satisfice. Trigger phrases include "improve this prompt,"
  "harden this prompt," "make this anti-satisficing," or
  `/improve-prompt [seed text]`.
---

# Systematic Prompt Hardening

Improve seed prompts by closing the escape hatches that allow LLMs to
satisfice — to produce output that reads plausibly but is shallow,
incomplete, or factually unchecked. This skill applies 16 field-tested
techniques drawn from real-world prompt engineering experience across
documentation review, code auditing, schema validation, and analytical
tasks.

## Core Principle

**Never rewrite the user's intent** — improve HOW the prompt asks, not
WHAT it asks. The seed prompt's goal is sacred. Every change must close
a specific escape hatch or add a verifiable constraint.

## When to Use This Skill

- The user has a seed prompt they want to strengthen before use
- The user has experienced shallow or incomplete LLM output and wants to
  prevent it
- The prompt involves review, comparison, analysis, extraction, or
  debugging — tasks where satisficing is most damaging
- The user explicitly asks for prompt improvement, hardening, or
  anti-satisficing treatment

## Reference Files

This skill uses progressive disclosure. Load reference files only when
needed during Phase 4 (Apply):

| File | Purpose | When to load |
| --- | --- | --- |
| `references/techniques.md` | 16-technique library with patterns and examples | Phase 4: to select and apply techniques |
| `references/task-type-profiles.md` | 7 task-type classifications with technique mappings | Phase 2: to classify the seed prompt; Phase 4: to determine which techniques apply |

## Workflow

### Phase 1: Parse

Receive the seed prompt and display it verbatim for confirmation.

**Actions:**

1. Extract the seed prompt from the user's input
2. Display the full seed prompt in a fenced `text` code block
3. Ask the user to confirm this is the prompt they want to improve
4. If no seed prompt is provided, ask the user to provide one

**Rules:**

- Do not paraphrase or summarise the seed prompt — display it exactly
- If the seed prompt is very long (>500 words), display it in full but
  note the length as a potential issue to address

### Phase 2: Classify

Determine the seed prompt's task type by matching against the 7 profiles
in `references/task-type-profiles.md`.

**Actions:**

1. Read `references/task-type-profiles.md`
2. Match signal words and structural patterns from the seed prompt against
   each profile
3. Display the classification with confidence level
4. Score the seed prompt on 5 quality dimensions (see below)

**Output format:**

```text
Classification: {Task Type} ({Risk Level})
Confidence: {HIGH / MEDIUM / LOW}
Rationale: {1-2 sentences explaining why this classification fits}
```

**Quality scoring** (computed now, displayed in Phase 5):

Score the seed prompt on each dimension from 1-10:

| Dimension | What it measures | Low (1-3) | High (8-10) |
| --- | --- | --- | --- |
| Clarity | Is the goal unambiguous? | Multiple valid interpretations | Single clear objective |
| Specificity | Are requirements detailed? | Vague or abstract | Concrete and measurable |
| Context | Is necessary background provided? | No context given | Full situation described |
| Constraints | Are boundaries and limits specified? | Open-ended, no fences | Explicit scope and limits |
| Structure | Is the work organised into steps? | Single undifferentiated ask | Phased with clear ordering |

Record these scores internally. They inform Phase 3 (question
prioritisation) and are displayed to the user in Phase 5 alongside the
improved prompt's scores for comparison.

**Rules:**

- If the prompt spans multiple types (e.g., extract then analyse), classify
  by the highest-risk component
- If confidence is LOW, ask the user to confirm the classification before
  proceeding
- A CRITICAL or HIGH risk classification means more techniques will be
  applied — this is expected and correct
- A total quality score below 25 (out of 50) indicates a prompt that needs
  heavy intervention — expect most RECOMMENDED techniques to be applied

### Phase 3: Interview

Resolve ambiguities and gather context through targeted questions. This
phase uses AskUserQuestion to collect information that will inform
technique selection and application.

**Use quality scores to prioritise questions.** The two lowest-scoring
dimensions from Phase 2 indicate where the prompt is weakest — ask about
those gaps first. For example, if Constraints scored 2/10, prioritise the
scope/boundary question over a question about an already-clear dimension.

**Universal questions** (ask for every prompt):

1. "What does 'done well' look like? What would make you confident the
   output is thorough?" — elicits success criteria
2. "Is there a specific failure mode you've seen — something the model
   tends to get wrong or skip on this kind of task?" — surfaces error
   modes for anchoring

**Task-type-specific questions** (ask 1-2 from the classified type's
profile in `references/task-type-profiles.md`, prioritising questions
that address the lowest-scoring quality dimensions):

| Type | Key question |
| --- | --- |
| Review | "What is the ground truth or source of authority?" |
| Analysis | "Should the analysis be exhaustive or representative?" |
| Generation | "Is there an exemplar of what good output looks like?" |
| Debugging | "What behaviour did you expect vs what actually happened?" |
| Extraction | "Is the list expected to be complete, or is a sample acceptable?" |
| Transformation | "Is there a specific output format or standard to match?" |
| Planning | "What constraints or non-negotiables exist?" |

**Interview rules:**

- Maximum 3-4 questions total (avoid fatigue)
- Batch related questions into a single AskUserQuestion call
- Every question set must include a "Let's discuss further" free-text
  option so the user can redirect or elaborate
- **Skip the interview entirely** if the seed prompt already specifies:
  ground truth, success criteria, scope fence, and exhaustive quantifiers.
  In this case, note which elements were already present and proceed to
  Phase 4

### Phase 4: Apply

Select techniques based on the task-type profile and apply them to the
seed prompt in canonical order.

**Actions:**

1. Read `references/techniques.md` and `references/task-type-profiles.md`
   (if not already loaded)
2. From the task-type profile, identify all ALWAYS techniques
3. Add RECOMMENDED techniques that address gaps identified in the
   interview
4. Add CONDITIONAL techniques only when specifically triggered by user
   responses
5. Apply selected techniques to the seed prompt in the canonical order
   below

**Canonical application order:**

Apply techniques in this order to build the improved prompt logically.
Not all techniques will apply to every prompt — skip those not selected:

1. **Task-type declaration** (#13) — frame the task
2. **Ground truth declaration** (#7) — establish authority
3. **Phase decomposition** (#1) — structure the work
4. **CoT scaffolding** (#16) — add reasoning instructions within phases
5. **Scope fence** (#15) — define boundaries
6. **Claims inventory / extraction** (#2, #3) — close escape hatches
7. **Error mode anchoring** (#9) — calibrate with known failures
8. **Exhaustive quantifiers** (#6) — replace weak language
9. **Negative constraints** (#10) — explicit prohibitions
10. **Structured output** (#4) + **output exemplar** (#12) — specify format
11. **Success criteria** (#14) — define completion
12. **Uncertainty flagging** (#11) — handle unknowns
13. **Completeness check** (#5) — mandatory final pass

**Rules:**

- Preserve the user's original language and intent wherever possible
- Add technique-driven text as new sections, instructions, or constraints
  — do not silently reword existing instructions
- Each addition should be annotatable back to a specific technique number
- If the seed prompt is already well-structured, focus on filling gaps
  rather than restructuring

### Phase 5: Present

Deliver the improved prompt with educational context.

**Output has five sections:**

#### Section 1: Improved Prompt

The complete improved prompt in a fenced `text` code block, ready to
copy-paste. Add inline annotations as `<!-- [#N Technique name] -->`
comments to explain each addition. These annotations help the user
understand what was added and why, and can be stripped before use.

#### Section 2: Prompt Quality Assessment

Display the before/after quality scores computed in Phase 2. Re-score
the improved prompt on the same 5 dimensions to show the improvement.

**Output format:**

```text
| Dimension    | Before | After | Change |
|-------------|--------|-------|--------|
| Clarity      |   3    |   8   |  +5    |
| Specificity  |   2    |   9   |  +7    |
| Context      |   4    |   7   |  +3    |
| Constraints  |   1    |   8   |  +7    |
| Structure    |   2    |   9   |  +7    |
| ----------- | ------ | ----- | ------ |
| Total        |  12/50 | 41/50 | +29    |
```

Below the table, add 1-2 sentences identifying the dimension with the
largest gain and explaining what drove it (which techniques contributed
most to that dimension's improvement).

**Rules:**

- Score honestly — do not inflate After scores to make the improvement
  look dramatic. The scores should be defensible if challenged
- If a dimension scores 8+ in the Before column, note it as a strength
  of the original prompt rather than claiming improvement
- The total score provides a quick summary but the per-dimension breakdown
  is the actionable information

#### Section 3: Change Summary

A 3-5 sentence prose paragraph explaining:

- The seed prompt's main vulnerability (what escape hatch was open)
- The improved prompt's defence strategy (how the escape hatches were
  closed)
- The most significant single change

#### Section 4: Techniques-Used Table

| # | Technique | Why applied | Escape hatch closed |
| --- | --- | --- | --- |
| (number) | (name) | (specific reason for this prompt) | (what satisficing behaviour it prevents) |

Include only techniques that were actually applied. Order by technique
number for easy cross-referencing with `references/techniques.md`.

#### Section 5: Technique of the Run

Highlight the single most impactful technique for this specific
improvement. Include:

- **The principle** (1-2 sentences explaining the technique)
- **Why it mattered here** (specific to this prompt and its vulnerabilities)
- **Try it yourself** (a one-liner the user can apply immediately to
  their next prompt without invoking this skill)

The Technique of the Run should rotate across invocations — avoid always
highlighting the same technique. Prioritise techniques the user may not
have encountered before, or techniques with counterintuitive effects.

#### Section 6: Prompt Library Offer

If the user keeps a prompt library (a "grimoire"), offer to capture the
improved prompt in it after presenting sections 1–5. Look for its
location in the user's `CLAUDE.md` or ask; if they don't keep one, skip
this section.

```text
Add to your prompt library? This prompt could be captured in
[library file] for future reuse.
```

If the user accepts, append an entry in this format:

```markdown
## [Descriptive title based on the prompt's purpose]

**Incantation:**

> [The complete improved prompt, stripped of <!-- annotation --> comments]

**Effect:** [1-2 sentences: what this prompt produces when used]

**Mechanism:** [Which techniques drive the improvement and why they
matter for this specific task type]

**Results:** [If known — what happened when the prompt was used. If the
prompt hasn't been used yet, write "Not yet field-tested."]

**Source:** Generated via /improve-prompt, [date].
```

**Rules for library entries:**

- Strip the inline `<!-- [#N ...] -->` annotations from the incantation
  — the library is for the user, not for this skill
- The title should describe the prompt's purpose, not its techniques
  (e.g., "Field Type Documentation Review" not "Bidirectional
  Verification with Claims Inventory")
- Keep the mechanism section concise — reference technique numbers for
  anyone who wants to look them up, but explain in plain language
- If the prompt is very long (>300 words), ask whether to capture the
  full prompt or a condensed version highlighting the key structural
  patterns

## Edge Cases

### Very short seed prompts (<20 words)

Short prompts are often the most vulnerable to satisficing because they
leave almost everything implicit. Treat them as HIGH risk regardless of
task type, and use the interview phase to surface implicit assumptions.

### Already-hardened prompts

If the seed prompt already contains 5+ techniques (phases, structured
output, scope fence, exhaustive quantifiers, etc.), focus the improvement
on:

- Gaps in the technique coverage (what's missing?)
- Strengthening weak applications of existing techniques
- Adding error mode anchoring if absent (this is almost always missing)

### Prompts with embedded examples or data

Do not modify example data or embedded content within the prompt. Apply
techniques to the instructional wrapper around the examples.

### Multi-step or compound prompts

If the seed prompt contains multiple distinct phases or sub-tasks,
apply techniques to each phase independently. Phase decomposition (#1)
may already be partially present — strengthen it rather than restructuring.
