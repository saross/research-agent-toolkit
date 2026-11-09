# Prompt Hardening Techniques

16 field-tested techniques for closing the escape hatches that allow LLMs
to satisfice. Each technique targets a specific failure mode and provides
a reusable structural pattern.

## How to Use This File

During Phase 4 (Apply), look up each technique selected by the
task-type profile. Use the **Pattern** section to structure additions to
the seed prompt. Use the **Escape hatch closed** to verify the technique
addresses a real vulnerability in the specific prompt.

---

## Category: Structure

### #1 Phase Decomposition

**Escape hatch closed:** The model tries to do everything in a single
pass, producing a plausible-looking but shallow result. Separation into
explicit phases forces each step to complete before the next begins.

**Pattern:**

```text
Phase 1: [Extract / Enumerate / Inventory]
{specific extraction task — output format specified}

Phase 2: [Verify / Analyse / Evaluate]
{specific evaluation task — uses Phase 1 output as input}

Phase 3: [Synthesise / Report / Recommend]
{specific synthesis task — uses Phase 2 output as input}
```

**Before:** "Review this document against the source material and fix
any errors."

**After:** "Phase 1: Extract every factual claim from the document into
a numbered list. Phase 2: For each claim, verify it against the source
material. Record the verdict (Correct / Error / Unverifiable) with
evidence. Phase 3: Fix every claim marked Error. Flag every claim marked
Unverifiable."

**Applicability:** Review (ALWAYS), Analysis (ALWAYS), Debugging
(ALWAYS), Extraction (RECOMMENDED), Planning (RECOMMENDED)

**Field-tested insight:** The critical move is making Phase 1's output
become Phase 2's input. This creates a forcing function — you cannot
evaluate claims you haven't first extracted, which prevents the model
from skipping straight to "looks good."

---

## Category: Anti-satisficing

### #2 Claims Inventory (Extract Before Evaluate)

**Escape hatch closed:** The model reads a document, recognises it as
plausible, and declares it correct without actually checking individual
claims. Separating extraction from evaluation forces enumeration.

**Pattern:**

```text
Before evaluating anything, extract every [claim / element / data point]
into a numbered list. Do not assess correctness during extraction.
Only after the complete list is assembled, evaluate each item.
```

**Before:** "Check this documentation for accuracy."

**After:** "Phase 1 — Claims inventory: Extract every factual claim from
this documentation into a numbered list. Include UI element names,
behavioural descriptions, counts, and procedural instructions. Do not
assess accuracy during this phase. Phase 2 — Verification: For each
numbered claim, verify it against [source]. Record your verdict."

**Applicability:** Review (ALWAYS), Analysis (RECOMMENDED), Extraction
(ALWAYS)

**Field-tested insight:** This is the single highest-leverage
anti-satisficing technique. Recognition (reading something and thinking
"that seems right") is cognitively cheap; enumeration (listing every
claim) is expensive. By forcing enumeration first, you make the model do
the expensive work before it can declare anything correct. Focus on
mastering this one technique before adding others.

---

### #3 Bidirectional Verification

**Escape hatch closed:** One-directional checking misses errors
systematically. Checking doc → source catches fabrications but misses
omissions. Checking source → doc catches omissions but misses
fabrications. Both directions are required.

**Pattern:**

```text
Check in BOTH directions:
Direction 1 (source → document): For every element in the source,
verify it appears in the document.
Direction 2 (document → source): For every claim in the document,
verify it has evidence in the source.
```

**Before:** "Verify the documentation matches the screenshots."

**After:** "Verify in both directions. Direction 1: For every visible UI
element in the screenshot, confirm it is documented. Direction 2: For
every claim in the documentation, confirm it has visible evidence in the
screenshot."

**Applicability:** Review (ALWAYS), Analysis (RECOMMENDED)

**Field-tested insight:** A documentation review once attributed
Speech-to-Text capability to the wrong field type. The error passed
doc → source checking (the claim was internally consistent) but failed
source → doc checking (the screenshot showed no Speech-to-Text for that
field). Always check both directions.

---

### #4 Structured Output (Tables/Checklists)

**Escape hatch closed:** Prose allows the model to hedge, summarise, and
skip items. Tabular output with mandatory columns forces explicit
verdicts for every item.

**Pattern:**

```text
Present results as a table with these columns:
| Item | Source Evidence | Document Claim | Verdict |
Every row must have a verdict. Every verdict must cite evidence.
"Looks fine" is not a verdict.
```

**Before:** "Summarise the differences between these two files."

**After:** "Present every difference in a table with columns: Line,
File A Content, File B Content, Nature of Difference (addition /
deletion / modification). Every row must be a specific, enumerable
difference — not a summary."

**Applicability:** Review (ALWAYS), Extraction (ALWAYS), Analysis
(RECOMMENDED)

**Field-tested insight:** The instruction "every row must have a verdict"
is more powerful than it looks. Without it, the model will leave ambiguous
items blank or write "N/A" — which is itself a form of satisficing.
Mandatory verdicts force engagement with every item.

---

### #5 Completeness Check

**Escape hatch closed:** The model finishes "enough" work and stops.
A mandatory final pass with an explicit completeness question forces a
second look at coverage.

**Pattern:**

```text
After completing the [analysis / review / extraction], perform a
completeness check: "Have I addressed every [item / claim / element]
in the [source / scope]? List any items I did not address and explain
why."
```

**Before:** "Review the codebase for security vulnerabilities."

**After:** "Review the codebase for security vulnerabilities. After
completing your review, perform a completeness check: list every file
you examined and every file you did not examine. For files not examined,
state why."

**Applicability:** Review (ALWAYS), Extraction (ALWAYS), Analysis
(RECOMMENDED)

**Field-tested insight:** The completeness check works best when it asks
the model to list what it *didn't* do, not just what it did. Listing
unexamined files reveals gaps that the model would otherwise never
mention.

---

### #6 Exhaustive Quantifiers

**Escape hatch closed:** Weak quantifiers ("any," "some," "check for")
grant implicit permission to stop after finding a few items. Strong
quantifiers ("every," "all," "each") demand exhaustive coverage.

**Pattern:**

Replace weak quantifiers with strong ones throughout the prompt:

| Weak (permits satisficing) | Strong (demands exhaustion) |
| --- | --- |
| "check for issues" | "list every issue" |
| "note any errors" | "enumerate all errors" |
| "look at the code" | "examine every function" |
| "find problems" | "identify each problem" |
| "some examples" | "every instance" |

**Before:** "Find any inconsistencies in the naming conventions."

**After:** "List every inconsistency in the naming conventions. For
each file, report: filename, line number, inconsistent name, expected
convention, suggested fix."

**Applicability:** Review (ALWAYS), Extraction (ALWAYS), Analysis
(ALWAYS), Debugging (RECOMMENDED)

**Field-tested insight:** Scope constraints stack: FULL (nothing
excluded), COMPREHENSIVE (every module), GRANULAR (smallest unit). Each
closes a different escape hatch. "Full, comprehensive, granular" in a
single prompt is not redundant — each word does different work.

---

## Category: Authority Control

### #7 Ground Truth Declaration

**Escape hatch closed:** Without an explicit authority source, the model
draws on training data, which may be outdated, incorrect, or
inconsistent with the user's specific context.

**Pattern:**

```text
The source of truth for this task is: [specific file / document / API /
screenshot]. When the source of truth conflicts with your training data
or general knowledge, the source of truth wins. Do not infer, assume, or
supplement from other sources.
```

**Before:** "Check that the API documentation is correct."

**After:** "The source of truth for this task is the live API response
at [endpoint]. Check every claim in the documentation against this
source. When the documentation and the API response disagree, the API
response is correct."

**Applicability:** Review (ALWAYS), Debugging (ALWAYS), Extraction
(RECOMMENDED)

**Field-tested insight:** Ground truth declarations are especially
critical when the model's training data includes outdated versions of the
same system. Without an explicit declaration, the model may "verify"
claims against its own stale knowledge and find them correct when they
are actually wrong.

---

## Category: Specificity

### #8 Concrete References

**Escape hatch closed:** Vague references ("the file," "the module,"
"the settings") allow the model to operate in the abstract without
actually locating and reading specific content.

**Pattern:**

```text
Read the following files before proceeding:
- `path/to/specific-file.md` (lines 45-120)
- `path/to/other-file.py` (the `validate()` function)
Do not proceed until you have read these files. Do not rely on
assumptions about their contents.
```

**Before:** "Review the documentation against the source code."

**After:** "Read `docs/api-reference.md` and
`src/api/handlers/auth.py:authenticate()`. For every parameter
documented in the markdown, verify it exists in the function signature."

**Applicability:** All types (RECOMMENDED for Review and Debugging,
CONDITIONAL for others)

**Field-tested insight:** Precision beats politeness. Hedging language
("if possible," "you might want to," "consider checking") grants
permission to skip. "Read this file" is an instruction. "You might want
to consult this file" is a suggestion the model will ignore under
pressure.

---

## Category: Calibration

### #9 Error Mode Anchoring

**Escape hatch closed:** Without calibration examples, the model's
internal threshold for "correct" is set by its training distribution,
which optimises for plausibility over accuracy. Concrete error examples
reset this threshold.

**Pattern:**

```text
Known error modes for this type of task (watch specifically for these):
- [Specific past error #1: what happened, what should have happened]
- [Specific past error #2: what happened, what should have happened]
If you find similar patterns, flag them explicitly.
```

**Before:** "Review this code for bugs."

**After:** "Review this code for bugs. Known error modes for this
codebase: (1) Non-null assertions (`!`) are used inconsistently — caught
in two of three spec files but missed in the third during a prior audit.
Check every file. (2) Hook output format has `suppressOutput` nested
inside `hookSpecificOutput` instead of at the top level, causing silent
validation failures. Check nesting levels explicitly."

**Applicability:** Debugging (ALWAYS), Review (RECOMMENDED), Analysis
(RECOMMENDED)

**Field-tested insight:** The most powerful anchors are drawn from the
user's own past mistakes. During the interview phase, the question "Is
there a specific failure mode you've seen?" often surfaces exactly the
kind of concrete error that makes this technique effective. A subagent
once documented a feature based on a plan statement without verifying it
against screenshots — the feature didn't exist. Anchoring on that
specific error mode prevents recurrence.

---

## Category: Scope Control

### #10 Negative Constraints

**Escape hatch closed:** Telling the model what to do leaves implicit
permission to also do other things — including cutting corners by
substituting an easier task. Explicit prohibitions close specific known
shortcuts.

**Pattern:**

```text
DO NOT:
- Summarise when asked to enumerate
- Infer capabilities from names or descriptions without verification
- Declare items "correct" without citing specific evidence
- Skip items because they "appear straightforward"
- Group multiple items under a single verdict
```

**Before:** "Verify the field descriptions are accurate."

**After:** "Verify the field descriptions are accurate. DO NOT: declare
a description 'accurate' without quoting the specific source text that
confirms it. DO NOT: skip fields that appear straightforward. DO NOT:
group multiple fields under a single 'all correct' verdict."

**Applicability:** Review (RECOMMENDED), Analysis (RECOMMENDED),
Extraction (RECOMMENDED)

**Field-tested insight:** Negative constraints are most effective when
they target observed failure modes rather than hypothetical ones. "DO NOT
summarise" is generic; "DO NOT declare items correct without citing
specific evidence" targets the exact shortcut the model takes when
satisficing.

---

### #15 Scope Fence

**Escape hatch closed:** Without explicit boundaries, the model may
either over-scope (addressing tangential issues and diluting focus) or
under-scope (addressing only the easiest subset).

**Pattern:**

```text
IN SCOPE:
- [Specific item 1]
- [Specific item 2]
- [Specific item 3]

OUT OF SCOPE (do not address):
- [Item that might seem related but should be excluded]
- [Item that would be easier to address but is not the task]
```

**Before:** "Review the authentication module."

**After:** "IN SCOPE: The OAuth2 callback handler
(`src/auth/oauth.py`), the token refresh logic
(`src/auth/refresh.py`), and the session middleware
(`src/middleware/session.py`). OUT OF SCOPE: The registration flow, the
password reset flow, and the admin authentication (these use different
code paths and will be reviewed separately)."

**Applicability:** Review (RECOMMENDED), Planning (ALWAYS), Analysis
(RECOMMENDED)

**Field-tested insight:** Dual-task dilution is real: "find errors or
improvements" splits attention and lets the model fill the report with
easy cosmetic observations while missing genuine bugs. When you need
bugs, ask only for bugs. Scope fencing prevents this dilution by
explicitly excluding the easier task.

---

## Category: Quality

### #11 Uncertainty Flagging

**Escape hatch closed:** When the model encounters ambiguous or
unverifiable items, it either silently skips them or makes a confident
guess. Explicit flagging instructions force transparency.

**Pattern:**

```text
If you cannot verify a claim from the available sources, DO NOT skip it
and DO NOT guess. Instead, flag it as:
"UNVERIFIABLE: [claim] — Reason: [why it cannot be verified from
available sources]"
```

**Before:** "Check the API documentation for accuracy."

**After:** "Check every claim in the API documentation against the
source code. If a claim cannot be verified from the source code (e.g.,
it describes runtime behaviour not visible in static analysis), flag it
as UNVERIFIABLE with the reason, rather than skipping it or guessing."

**Applicability:** Review (RECOMMENDED), Analysis (RECOMMENDED),
Extraction (ALWAYS)

**Field-tested insight:** The flag-rather-than-skip instruction is
crucial. Without it, the model's default behaviour is to silently omit
items it is uncertain about, which produces a clean-looking but
incomplete result. The user needs to see what wasn't checked, not just
what was.

---

## Category: Format Control

### #12 Output Exemplar

**Escape hatch closed:** Format descriptions in prose are ambiguous.
A concrete example of the expected output format eliminates format
interpretation as a failure mode.

**Pattern:**

```text
Format your output exactly like this example:

## File: `example.py`
| Line | Issue | Severity | Fix |
|------|-------|----------|-----|
| 42 | Unused import `os` | Low | Remove import |
| 87 | SQL injection in `query()` | Critical | Use parameterised query |

[Your output here, following this exact format]
```

**Before:** "List the issues you find in a structured format."

**After:** (Provide a concrete example table with 2-3 representative
rows showing the exact columns, formatting, and level of detail
expected.)

**Applicability:** Generation (ALWAYS), Extraction (RECOMMENDED),
Transformation (RECOMMENDED), Review (CONDITIONAL)

**Field-tested insight:** Output exemplars work best when they include
2-3 rows covering different cases (e.g., one low-severity and one
critical issue). A single-row example may be interpreted as a format
template without enough variety to establish the expected level of
detail.

---

## Category: Context

### #13 Task-Type Declaration

**Escape hatch closed:** Without an explicit task-type frame, the model
may misinterpret the task — e.g., treating a verification task as a
creative rewriting task, or treating an exhaustive extraction as a
representative sampling task.

**Pattern:**

```text
This is a [verification / extraction / debugging / ...] task.
The goal is to [specific objective].
This is NOT a [common misinterpretation] task.
```

**Before:** "Look at the test results and tell me what happened."

**After:** "This is a debugging task. The goal is to identify the root
cause of the test failure, not to propose a fix. This is NOT a code
review — do not comment on style, naming, or structure unless it is
directly related to the failure."

**Applicability:** All types (ALWAYS for Review, Analysis, Debugging,
Extraction; RECOMMENDED for Generation, Transformation, Planning)

**Field-tested insight:** The "This is NOT" clause is as important as
the "This is" clause. Open-ended prompts help for generative work but
hurt for analytical work. "Any issues?" gets a few; "list every
assumption" gets all of them. Declaring the task type closes the
interpretive gap.

---

## Category: Evaluation

### #14 Success Criteria

**Escape hatch closed:** Without explicit completion criteria, the model
decides internally when it has done "enough." Explicit criteria make
completion verifiable.

**Pattern:**

```text
This task is complete when:
- [ ] Every [item] in [source] has been [action]
- [ ] Each [item] has a [verdict / result / output]
- [ ] No items are skipped or summarised
- [ ] A completeness check has been performed
```

**Before:** "Analyse the survey data and report your findings."

**After:** "This task is complete when: (1) Every response category has
been quantified with exact counts and percentages. (2) Every
statistically significant trend has been identified with supporting
numbers. (3) Every anomaly or outlier has been flagged with possible
explanations. (4) A completeness check confirms every survey question
has been addressed."

**Applicability:** All types (ALWAYS for Debugging; RECOMMENDED for
Review, Analysis, Extraction, Generation, Planning; CONDITIONAL for
Transformation)

**Field-tested insight:** Checklist-style success criteria are more
effective than prose criteria because each item is independently
verifiable. "Analyse thoroughly" is uncheckable; "every response category
has been quantified with exact counts" is binary.

---

## Category: Reasoning

### #16 Chain-of-Thought Scaffolding

**Escape hatch closed:** The model jumps directly from input to output,
producing an answer that looks correct but skips the intermediate
reasoning that would catch errors. Explicit reasoning instructions force
the model to show (and perform) its work.

**Pattern:**

```text
Before producing your [answer / verdict / recommendation], reason
through the problem step by step:
1. [Specific reasoning step relevant to this task]
2. [Next reasoning step]
3. [Verification or cross-check step]
Show your reasoning in <thinking> tags, then provide your final answer.
```

**Before:** "Determine the root cause of this test failure."

**After:**

```text
Determine the root cause of this test failure. Before stating your
conclusion, reason through the problem:
1. What does the error message tell us about where the failure occurs?
2. What are the possible causes at that location (list at least 3)?
3. For each possible cause, what evidence in the code supports or
   refutes it?
4. Which cause has the strongest supporting evidence?
Show your reasoning in <thinking> tags, then state the root cause
with supporting evidence.
```

**Applicability:** Analysis (RECOMMENDED), Debugging (RECOMMENDED),
Planning (CONDITIONAL), Review (CONDITIONAL)

**Relationship to #1 Phase Decomposition:** These techniques are
complementary, not redundant. Phase decomposition (#1) structures the
*task* into sequential steps (extract → verify → report). CoT
scaffolding (#16) structures the *reasoning within each step* (consider
alternatives → weigh evidence → conclude). Apply #1 to organise what the
model does; apply #16 to deepen how the model thinks within each phase.

**Field-tested insight:** CoT scaffolding is most valuable when the
task involves choosing between alternatives (debugging root causes,
selecting analytical approaches, evaluating trade-offs). For tasks that
are purely mechanical (extraction, transformation), CoT adds token
overhead without improving accuracy. The key is to scaffold reasoning
around the specific decision points in the task — generic "think step by
step" instructions are weaker than task-specific reasoning steps like
"list at least 3 possible causes" or "what evidence supports or refutes
each hypothesis."

---

## Quick Reference: Technique Selection by Task Type

See `task-type-profiles.md` for the full mapping. Summary:

| # | Technique | Review | Analysis | Generation | Debugging | Extraction | Transform | Planning |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Phase decomposition | A | A | — | A | R | — | R |
| 2 | Claims inventory | A | R | — | — | A | — | — |
| 3 | Bidirectional verification | A | R | — | — | — | — | — |
| 4 | Structured output | A | R | — | — | A | — | — |
| 5 | Completeness check | A | R | — | — | A | — | — |
| 6 | Exhaustive quantifiers | A | A | — | R | A | — | — |
| 7 | Ground truth declaration | A | — | — | A | R | — | — |
| 8 | Concrete references | R | — | — | R | — | — | — |
| 9 | Error mode anchoring | R | R | — | A | — | — | — |
| 10 | Negative constraints | R | R | — | — | R | — | — |
| 11 | Uncertainty flagging | R | R | — | — | A | — | — |
| 12 | Output exemplar | C | — | A | — | R | R | — |
| 13 | Task-type declaration | A | A | R | A | A | R | R |
| 14 | Success criteria | R | R | R | A | R | C | R |
| 15 | Scope fence | R | R | — | — | — | — | A |
| 16 | CoT scaffolding | C | R | — | R | — | — | C |

A = ALWAYS, R = RECOMMENDED, C = CONDITIONAL, — = Not applicable
