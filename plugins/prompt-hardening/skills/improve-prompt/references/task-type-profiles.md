# Task-Type Profiles

7 task-type classifications for seed prompt analysis. Each profile
defines signal words for classification, satisficing risk level,
technique mappings, interview questions, and the common failure mode
that hardening should prevent.

## How to Use This File

During Phase 2 (Classify), match signal words from the seed prompt
against each profile to determine the task type. During Phase 4 (Apply),
use the technique mapping to select which techniques to apply.

**Priority levels:**

| Level | Meaning |
| --- | --- |
| ALWAYS | Apply this technique regardless of context |
| RECOMMENDED | Apply unless the seed prompt already addresses this concern |
| CONDITIONAL | Apply only when triggered by a specific user response or prompt feature |

---

## Review / Comparison

**Satisficing risk:** CRITICAL

The highest-risk task type. Review tasks ask the model to evaluate
existing work, where the path of least resistance is to read the work,
find it plausible, and declare it correct.

**Signal words:** review, compare, verify, check, audit, validate,
assess, evaluate, cross-reference, QA, quality check, diff, reconcile

**Technique mapping:**

| Priority | Techniques |
| --- | --- |
| ALWAYS | #1 Phase decomposition, #2 Claims inventory, #3 Bidirectional verification, #4 Structured output, #5 Completeness check, #6 Exhaustive quantifiers, #7 Ground truth declaration, #13 Task-type declaration |
| RECOMMENDED | #8 Concrete references, #9 Error mode anchoring, #10 Negative constraints, #11 Uncertainty flagging, #14 Success criteria, #15 Scope fence |
| CONDITIONAL | #12 Output exemplar (when the review output format matters), #16 CoT scaffolding (when verification requires weighing competing evidence) |

**Interview questions:**

1. "What is the ground truth or source of authority?" — Critical for
   establishing what "correct" means
2. "Should the review be exhaustive (every claim checked) or targeted
   (specific areas of concern)?" — Determines scope

**Common failure mode:** The model reads the document, recognises it as
plausible, finds 2-3 surface issues, and declares "looks good overall."
Genuine errors, omissions, and fabrications pass unchecked because the
model verified by recognition rather than by enumeration. The claims
inventory technique (#2) directly addresses this failure.

---

## Analysis

**Satisficing risk:** HIGH

Analysis tasks ask the model to derive insights from data or evidence.
The risk is that the model produces a plausible narrative by
cherry-picking evidence that fits a coherent story, while ignoring
contradictory or ambiguous data points.

**Signal words:** analyse, investigate, examine, study, explore,
characterise, profile, assess, diagnose, determine, explain why,
identify patterns, interpret, correlate

**Technique mapping:**

| Priority | Techniques |
| --- | --- |
| ALWAYS | #1 Phase decomposition, #6 Exhaustive quantifiers, #11 Uncertainty flagging, #13 Task-type declaration |
| RECOMMENDED | #2 Claims inventory, #3 Bidirectional verification, #4 Structured output, #5 Completeness check, #9 Error mode anchoring, #10 Negative constraints, #14 Success criteria, #15 Scope fence, #16 CoT scaffolding |
| CONDITIONAL | #7 Ground truth declaration (when baseline exists), #8 Concrete references (when sources are known) |

**Interview questions:**

1. "Should the analysis be exhaustive (cover every data point) or
   representative (identify key patterns)?" — Determines whether
   sampling is acceptable
2. "Are there competing hypotheses, or is this open-ended exploration?"
   — Determines whether bidirectional verification applies

**Common failure mode:** The model produces a coherent narrative that
reads convincingly but is built from cherry-picked evidence. Data points
that complicate or contradict the narrative are silently omitted. The
exhaustive quantifiers technique (#6) and completeness check (#5) force
the model to account for all evidence, not just the convenient subset.

---

## Generation

**Satisficing risk:** MODERATE

Generation tasks ask the model to produce new content. The risk is lower
because generation is what LLMs do well, but the failure mode shifts
from shallow evaluation to plausible-but-wrong output — content that
reads well but doesn't meet unstated requirements.

**Signal words:** create, write, generate, draft, produce, compose,
build, design, make, develop, author, construct, formulate

**Technique mapping:**

| Priority | Techniques |
| --- | --- |
| ALWAYS | #12 Output exemplar, #13 Task-type declaration, #14 Success criteria |
| RECOMMENDED | #15 Scope fence |
| CONDITIONAL | #1 Phase decomposition (for complex multi-section output), #7 Ground truth declaration (when factual accuracy matters), #9 Error mode anchoring (when past generation errors are known) |

**Interview questions:**

1. "Is there an exemplar of what good output looks like?" — Provides a
   concrete target
2. "What would make this output fail — what are the deal-breakers?" —
   Surfaces implicit requirements

**Common failure mode:** The model produces something that looks right
on first read but misses requirements that were implicit in the user's
mind. The output is plausible, well-formatted, and coherent — but
doesn't do what was actually needed. Success criteria (#14) and output
exemplars (#12) make implicit requirements explicit.

---

## Debugging

**Satisficing risk:** HIGH

Debugging tasks ask the model to find and explain the cause of a
failure. The risk is that the model proposes the most statistically
likely fix (based on training data) without verifying that it addresses
the actual root cause in this specific codebase.

**Signal words:** debug, fix, troubleshoot, diagnose, investigate (a
failure), why does, what causes, root cause, error, exception, fails,
broken, not working, unexpected behaviour, regression

**Technique mapping:**

| Priority | Techniques |
| --- | --- |
| ALWAYS | #1 Phase decomposition, #7 Ground truth declaration, #8 Concrete references, #9 Error mode anchoring, #13 Task-type declaration, #14 Success criteria |
| RECOMMENDED | #6 Exhaustive quantifiers, #10 Negative constraints, #15 Scope fence, #16 CoT scaffolding |
| CONDITIONAL | #4 Structured output (for multi-bug reports), #5 Completeness check (for audits) |

**Interview questions:**

1. "What behaviour did you expect vs what actually happened?" —
   Establishes the gap between expected and actual
2. "Have you tried anything already? What did you rule out?" —
   Prevents re-treading explored ground

**Common failure mode:** The model proposes the most likely fix based on
the error message pattern without reading the actual code, verifying the
hypothesis against the specific codebase, or considering alternative
root causes. A prior audit missed unsafe `!` non-null assertions in one
of three spec files — the pattern was caught in two files but overlooked
in the third. Error mode anchoring (#9) with phase decomposition (#1)
prevents this pattern.

---

## Extraction

**Satisficing risk:** HIGH

Extraction tasks ask the model to pull structured data from unstructured
sources. The risk is that the model produces a representative sample
rather than a complete extraction — finding enough items to look
thorough without actually achieving exhaustive coverage.

**Signal words:** extract, list, enumerate, catalogue, inventory, find
all, collect, gather, compile, identify every, pull out, parse, scrape,
harvest

**Technique mapping:**

| Priority | Techniques |
| --- | --- |
| ALWAYS | #2 Claims inventory, #4 Structured output, #5 Completeness check, #6 Exhaustive quantifiers, #11 Uncertainty flagging, #13 Task-type declaration |
| RECOMMENDED | #7 Ground truth declaration, #10 Negative constraints, #12 Output exemplar, #14 Success criteria |
| CONDITIONAL | #1 Phase decomposition (for complex multi-source extraction) |

**Interview questions:**

1. "Is the list expected to be complete, or is a representative sample
   acceptable?" — Determines exhaustiveness requirement
2. "What format should each extracted item take?" — Determines whether
   an output exemplar is needed

**Common failure mode:** The model produces a representative sample (10-
15 items that cover the main categories) rather than a complete
extraction. The output looks thorough because it covers the major
categories, but silently omits edge cases, exceptions, and less common
items. Exhaustive quantifiers (#6) and completeness checks (#5)
counteract this by demanding accountability for every source item.

---

## Transformation

**Satisficing risk:** LOW

Transformation tasks ask the model to convert content from one format to
another. This is the lowest-risk type because the task is well-defined:
input format, output format, and the mapping between them are usually
explicit. Failures are typically format errors rather than satisficing.

**Signal words:** convert, transform, translate, reformat, restructure,
migrate, port, transpose, adapt, map, reshape, normalise

**Technique mapping:**

| Priority | Techniques |
| --- | --- |
| ALWAYS | #13 Task-type declaration |
| RECOMMENDED | #12 Output exemplar, #14 Success criteria |
| CONDITIONAL | #1 Phase decomposition (for multi-step transformations), #4 Structured output (when output format is complex), #5 Completeness check (when input completeness matters) |

**Interview questions:**

1. "Is there a specific output format or standard to match?" — Provides
   the transformation target
2. "Are there edge cases in the input that need special handling?" —
   Surfaces transformation exceptions

**Common failure mode:** Generally well-defined and low-risk. When
failures occur, they tend to be format-level errors (wrong escaping,
missing fields, incorrect nesting) rather than satisficing. An output
exemplar (#12) and success criteria (#14) catch most issues.

---

## Planning

**Satisficing risk:** MODERATE

Planning tasks ask the model to design an approach, strategy, or
sequence of actions. The risk is that the model produces a plausible-
sounding plan that lacks concrete steps, ignores constraints, or
hand-waves over the hardest parts.

**Signal words:** plan, design, architect, strategy, approach, roadmap,
propose, outline, structure, organise, schedule, prioritise, sequence,
break down, scope

**Technique mapping:**

| Priority | Techniques |
| --- | --- |
| ALWAYS | #1 Phase decomposition, #13 Task-type declaration, #14 Success criteria, #15 Scope fence |
| RECOMMENDED | #6 Exhaustive quantifiers, #10 Negative constraints |
| CONDITIONAL | #7 Ground truth declaration (when constraints are documented), #8 Concrete references (when existing systems constrain the plan), #9 Error mode anchoring (when past plans have failed), #16 CoT scaffolding (when the plan involves evaluating trade-offs between approaches) |

**Interview questions:**

1. "What constraints or non-negotiables exist?" — Surfaces hard
   boundaries the plan must respect
2. "What does success look like — how will you know the plan worked?" —
   Elicits measurable outcomes

**Common failure mode:** The model produces a plan that reads well but
lacks concreteness — steps like "implement the authentication layer"
without specifying which library, what token format, or how sessions
are managed. Phase decomposition (#1) forces concrete sub-steps, and
success criteria (#14) make each step verifiable.
