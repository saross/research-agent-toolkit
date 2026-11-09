---
name: code-audit
description: "Line-by-line debug audit of new or changed code, using two independent fresh-context reviewers: one for implementation correctness, one for test adequacy. Finds semantic bugs, logic errors, data-format assumptions, edge cases, and cross-module inconsistencies that ordinary review misses, and asks whether the tests would catch a broken feature. Use after writing significant code, before relying on it, or when the user asks for an audit of a file, a diff, or a project."
---

# Code Audit

A line-by-line debug audit built on anti-satisficing techniques: the reviewer presupposes that bugs
exist, rather than looking for confirmation that the code works. It finds semantic bugs, logic
errors, data-format assumptions, edge cases, and cross-module inconsistencies that ordinary review
misses.

It began as a debug-audit prompt by Pliny the Prompter, extended with structured output, category
guidance, cross-file analysis, and a second lens for test adequacy.

## Scope

Work out what to audit from the request:

- **Nothing named**: the files changed since the last commit (`git diff --name-only HEAD`). If there
  are none, say so and stop.
- **Staged and unstaged changes**: `git diff --name-only`.
- **A whole project**: every source file, excluding generated, vendored, and archived folders.
- **Named files**: those files.

Keep to source code: skip binaries, images, data files, lock files, and generated output. Report the
list before starting: "Auditing N files: [list]".

## Before you start: two non-negotiables

**1. Commit the code first, or audit a frozen copy.** Auditing agents that share a working tree can
destroy uncommitted work: an agent that applies a mutation and restores it with `git checkout` loses
whatever wasn't committed, and nothing can recover it. Either commit before delegating, or export a
read-only copy (`git archive HEAD | tar -x -C <folder>`) and point the auditors at that. If neither
is possible, audit inline.

**2. Never audit your own work in your own context.** If you wrote the code in this session, you
will re-derive the same assumptions and confirm them. This is measured, not theoretical: self-checks
in the same context reliably *false-confirm*. In practice, one such check reported "match" against a
value that was wrong by two orders of magnitude, and code that passed its author's whole test suite
shipped with a defect that made the feature unusable. Delegate to a fresh context, or say plainly in
the report that the audit was done in the same context and is therefore weak evidence.

## Two orthogonal lenses, not N copies of one

Don't fan one prompt out across files. Run **two reviewers with different questions**, each in a
fresh context, and each covering the whole change:

- **Lens A, implementation correctness.** Does the code do what it claims? Work through the
  categories below.
- **Lens B, test adequacy.** *Assume the implementation is wrong, and ask whether these tests would
  catch it.* A suite that passes while the feature is broken is worse than no suite.

Orthogonality is the point. Two agents asked the same question return the same answer, including the
same mistake; two asked different questions find disjoint classes of defect. In practice Lens A
finds the bug and Lens B finds *why it got past review*, which is the finding that prevents the next
one.

Give both lenses the same constraints:

- **Read-only on shared trees.** No edits, commits, `git checkout`, `git stash`, or `git restore`. A
  lens that wants to know whether a mutation survives either reasons from the assertions, or applies
  it in its own disposable copy, never in the shared tree.
- **Anchor every finding** to `file:line`, quoting the offending code. Label anything unconfirmed
  `SUSPECTED — needs X to confirm`; never assert it.
- **Remove false positives** on a second pass. A finding that misreads the intent is worse than no
  finding.

Tell each lens what changed and *why*, not just which files. A lens that understands the intent can
tell you the intent wasn't achieved.

## Lens A: categories to check, line by line

### Logic errors

- Off-by-one errors and boundary conditions
- Incorrect boolean logic (confusing and with or, negation errors)
- Wrong comparison operators (`<` or `<=`, `==` or `is`)
- Short-circuit bugs (`x or default` when `x` could be 0 or an empty string)
- Missing `return` statements and unreachable code

### Data-format assumptions

- Assuming a key exists in a dictionary without a guard
- Assuming a list is non-empty before indexing it
- Assuming a string format, such as JSON or an ISO date, without checking it
- Type confusion: string or path, integer or float, `None` or empty

### Edge cases

- Empty inputs, `None` values, and missing keys
- File paths: symbolic links, permissions, missing parent folders
- Unicode and encoding
- Concurrent access and race conditions

### Cross-module consistency

- Function signatures matching how callers use them
- Return-value contracts: does every caller handle every return type?
- Shared data structures changed in unexpected places
- Import cycles

### Security

- Command injection and path traversal
- Secrets in code, logs, or error messages
- Unsafe deserialisation

### Project conventions

- The project's language and style conventions, for example from its `CLAUDE.md`
- Code style, such as PEP 8 for Python

## Lens B: test adequacy

Not "are there tests?" but "would these tests fail if the feature were broken?"

**Mutation reasoning.** For each test, name a concrete one-line change to the implementation that
would make it wrong while leaving the test green. Be specific: "the tests are weak" is useless;
"changing `>=` to `>` on line N leaves all seven green" is actionable. Reliable survivors to check:

- deleting the call site that *wires* a guard into the pipeline
- flipping a boundary operator
- narrowing an emptiness test (`not in (None, "")` to `is not None`)
- widening an exception clause to swallow everything
- returning a constant that satisfies the assertions
- removing a set difference or filter, so that a check fires on everything

**Is the wiring tested, or only the functions?** Unit tests of pure helpers can all pass while the
helper is never called, or is called after the thing it was meant to protect. Look for at least one
test that runs the real entry point from end to end and asserts the *consequence*, such as the file
not being written or the process exiting with an error, not merely a returned value.

**Do fixtures match what the pipeline actually produces?** A hand-built fixture can encode a shape
the real code path can't produce, so the test passes against something that never exists in
practice. This is a recurring reason defects ship green. Prefer fixtures built through the real
constructor, and check any hand-built one against a real artefact.

**Are negatives pinned?** A test that something fires is half a test. Without a case asserting that
it does *not* fire in the ordinary situation, a mutation that makes it fire always will pass.

**Does the test take the path a user takes?** Tests that only pass an injected temporary path, mock,
or override may never reach the default branch used in practice, so a mutation in that branch
survives.

## Running the test suite during an audit

Run it in a clean copy, with a throwaway home folder, so the run proves the suite doesn't depend on,
or write to, anything outside itself:

```bash
D=$(mktemp -d) && git archive --format=tar HEAD | tar -x -C "$D"
H=$(mktemp -d)
cd "$D" && env -i PATH=/usr/bin:/bin HOME="$H" LANG=C.UTF-8 python3 -m pytest -q --basetemp="$H/bt"
```

Use `--basetemp` inside the throwaway home when other agents may be running suites at the same time:
pytest's shared numbered temporary folders otherwise collide. If the project has its own isolation
or hermeticity checks, run those too, and say which ones ran.

## Cross-file analysis

After the per-file audits, check consistency across files:

- Do function signatures match their call sites in every file?
- Are shared data structures and return values used consistently?
- Is error handling consistent?
- Do naming and import conventions agree?

## Report

```text
## Audit Report: [N] files, [date]

### Critical (must fix)
[issues that would cause crashes, data loss, or wrong results, INCLUDING "the feature could be broken
 with every test green"]

### Medium (should fix)
[issues that would cause problems in edge cases or break contracts]

### Low (note for later)
[style, performance, missing coverage]

### Surviving mutations
[each: the one-line change, its location, and what it would let through]

### Cross-file issues
[consistency problems across modules]

### No issues found
[the categories checked where nothing was found]
```

For each issue, give its location (`file:line`), category, a one-sentence description, and its
impact in practice.

## Loop

Review the findings. For each, check that it is real and not a misreading of the code's intent, and
remove false positives. Then re-read the files looking specifically for what the first pass missed.
The goal: a sceptical developer who believes prompting can't find real bugs should be proven wrong
by the report.

## Resolve, then re-audit if the fixes were substantial

Fix everything Medium and above, plus any Low that matters. If the fixes were more than cosmetic,
**audit the fixes again**: they are new code, written under time pressure by someone who has just
been told they were wrong, which isn't a state associated with careful work. A second pass over a
first round of fixes routinely finds fresh defects.

When a finding is deliberately *not* fixed, record the decision and its reasoning somewhere durable,
together with what the code may and may not be claimed to do as a result. An unresolved finding that
lives only in a chat log gets rediscovered at the worst moment, and the weaker claim it implies is
the first thing forgotten.
