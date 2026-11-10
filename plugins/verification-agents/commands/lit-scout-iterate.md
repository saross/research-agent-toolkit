---
description: Closed-loop literature scout, iterating on the verifier's corrections until the claims pass
argument-hint: "[query]"
---

# Closed-loop literature scout

Run `lit-scout` and `lit-scout-verifier` as a closed loop:

1. the proposer drafts, and the verifier audits;
2. if any claim fails, the proposer applies the verifier's `true_value` to
   the affected rows, and removes rows whose DOIs the registry has
   authoritatively reported as not existing;
3. repeat, up to five iterations.

The loop stops on PASS, on PARTIAL or UNVERIFIABLE (both flagged to the
user), at the limit, or on no progress: when the set of failed `claim_id`s
doesn't change between iterations. The verifier runs on every iteration;
the command has no option that skips it.

**A row is only ever removed on an authoritative negative.** A lookup that
didn't complete (HTTP 429, a 5xx error, a timeout, an exhausted API budget)
is `unverifiable`, and unverifiable rows are kept and flagged, never
removed. Without this rule, a throttled run deletes genuine citations and
reports them as confabulations, which is the opposite of what the loop is
for.

The query is: $ARGUMENTS

It takes the same form as for the `lit-scout` command: it can include target
venues, scope limits, time periods, and so on.

## Behaviour

The command is a thin orchestrator. It does **no reasoning about the
content** of either agent's output. Its only substantive actions are to:

- start the agents;
- extract the machine-readable `claims.jsonl` and `corrections.jsonl`
  blocks from their Markdown output (subagents can't reliably write report
  files themselves);
- pass file paths between iterations;
- track the state of the iterations, and decide when to stop.

All judgement about content lives inside the agents.

### Iteration policy

- **Limit:** five iterations. A hard stop: don't extend it silently.
- **Iterate on FAIL only.** PARTIAL verdicts go to the user with the full
  divergence details; the command doesn't iterate on them.
- **Stop on no progress.** If iteration *k* produces the same set of failed
  `claim_id`s as iteration *k − 1*, stop.
- **Flag PARTIAL clearly.** When the loop stops on PARTIAL, return the
  verifier's full integrated output with a banner flagging the partial
  divergences for the user to review.

### Before iteration 0

```bash
ITERATE_ROOT="/tmp/lit-scout-iterate-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$ITERATE_ROOT"
```

Each iteration writes to `${ITERATE_ROOT}/iter-{N}/`, so the whole sequence
is kept for inspection. Start the no-progress tracker with
`LAST_FAIL_SET=""`.

Save the user's query, verbatim, to `${ITERATE_ROOT}/query.txt` with the
Write tool. It records what the run was for, and the optional library
import reads it.

### Extracting the blocks

Both agents embed their machine-readable data as fenced `jsonl` blocks
between comment markers. Extract them with:

```bash
extract_block() {
  # Arguments: input_file marker output_file
  # Writes the lines between <!-- BEGIN ${marker} --> and <!-- END ${marker} -->,
  # without the fence lines, to output_file.
  awk "/<!-- BEGIN $2 -->/,/<!-- END $2 -->/" "$1" \
    | sed -n '/^```jsonl/,/^```$/{/^```/d; p}' \
    > "$3"
}
```

Use it twice in each iteration: on the proposer's draft (marker
`claims.jsonl`), and on the verifier's integrated report (marker
`corrections.jsonl`).

### The loop

For `N` from 0 to 5:

#### Step A: start the proposer

- **Iteration 0 (first run):** start the `verification-agents:lit-scout`
  agent with the Agent tool, with the user's query as the prompt. Pass the
  query through as received, without paraphrasing or enriching it. It
  typically takes 10 to 15 minutes.
- **Iterations 1 to 5 (iterate mode):** start it with a prompt that includes
  the user's original query AND:

  ```text
  This is iterate-mode invocation N for the closed-loop driver.
  Follow the iterate-mode section of your instructions, then apply
  the verifier's corrections to the previous draft.

  previous_draft_path: ${ITERATE_ROOT}/iter-{N-1}/draft.md
  previous_corrections_path: ${ITERATE_ROOT}/iter-{N-1}/corrections.jsonl

  Original user query (do not re-run discovery; preserve PASS
  claims; substitute true_value for FAIL claims; remove rows
  whose doi_resolves is fail; preserve rows whose claims are
  unverifiable — an unverifiable claim means the check did not
  complete, not that the row is wrong):

  [original query verbatim]
  ```

Run it in the foreground, because verification can't start until it
returns.

#### Step B: save the proposer's draft

```bash
DRAFT="${ITERATE_ROOT}/iter-${N}/draft.md"
mkdir -p "${ITERATE_ROOT}/iter-${N}"
# Use the Write tool with the proposer's full returned content
```

#### Step C: extract the proposer's claims

```bash
extract_block "${ITERATE_ROOT}/iter-${N}/draft.md" "claims.jsonl" \
              "${ITERATE_ROOT}/iter-${N}/claims.jsonl"
```

If `claims.jsonl` comes out empty or malformed, note a warning. The verifier
handles this case by emitting its `_legacy` placeholder, and the command
doesn't iterate when that placeholder appears in `corrections.jsonl`.

#### Step D: start the verifier

Start the `verification-agents:lit-scout-verifier` agent with the Agent
tool, with the prompt:

```text
Verify this lit-scout draft for confabulation per the
lit-scout-verifier specification. Treat the attached markdown as
your sole input; you have no access to the proposer's context.

[contents of ${ITERATE_ROOT}/iter-${N}/draft.md verbatim, with no
edits, summary, pre-amble, or commentary]
```

Pure transfer: don't add hints, or flag particular rows as suspicious. Run
it in the foreground. It typically takes 3 to 8 minutes for a table of 20
to 40 rows.

#### Step E: save the verifier's integrated report

```bash
REPORT="${ITERATE_ROOT}/iter-${N}/report.md"
# Use the Write tool with the verifier's full returned content
```

#### Step F: extract the corrections

```bash
extract_block "${ITERATE_ROOT}/iter-${N}/report.md" "corrections.jsonl" \
              "${ITERATE_ROOT}/iter-${N}/corrections.jsonl"
```

If the verifier's output has no corrections block at all, treat it as a
verifier failure (see "Failures and recovery" below).

#### Step G: read the verdict

Read the verdict from the **Summary** in the report's Verification section,
or work it out from `corrections.jsonl` directly:

```bash
PASS_CT=$(grep -c '"status":"pass"' "${ITERATE_ROOT}/iter-${N}/corrections.jsonl" || true)
PARTIAL_CT=$(grep -c '"status":"partial"' "${ITERATE_ROOT}/iter-${N}/corrections.jsonl" || true)
FAIL_CT=$(grep -c '"status":"fail"' "${ITERATE_ROOT}/iter-${N}/corrections.jsonl" || true)
UNVER_CT=$(grep '"status":"unverifiable"' "${ITERATE_ROOT}/iter-${N}/corrections.jsonl" \
  | grep -vc '"claim_id":"_legacy"' || true)
LEGACY_CT=$(grep -c '"claim_id":"_legacy"' "${ITERATE_ROOT}/iter-${N}/corrections.jsonl" || true)
TOTAL_CT=$(grep -c . "${ITERATE_ROOT}/iter-${N}/corrections.jsonl" || true)
```

`UNVER_CT` leaves out the `_legacy` placeholder, which also carries
`status: unverifiable` but means something else entirely (see G.5).

Five cases, checked in order:

##### G.1: PASS (`FAIL_CT == 0 && PARTIAL_CT == 0 && UNVER_CT == 0 && LEGACY_CT == 0`)

The loop ends successfully. Go to "Final report".

##### G.2: PARTIAL (`FAIL_CT == 0 && PARTIAL_CT > 0 && UNVER_CT == 0 && LEGACY_CT == 0`)

The loop ends with the PARTIAL flag, without iterating. Go to "Final
report".

##### G.3: UNVERIFIABLE (`FAIL_CT == 0 && UNVER_CT > 0 && LEGACY_CT == 0`)

Some claims couldn't be checked. Do **not** iterate: iterating can't fix a
claim whose problem is that the registry didn't answer, and re-running the
verifier under the same throttle just produces the same result more slowly.

Stop with status `UNVERIFIABLE`. This is deliberately not reported as PASS:
the run established nothing about those rows, and calling it PASS would
claim a verification that didn't happen. Go to "Final report".

##### G.4: FAIL (`FAIL_CT > 0`): go on to the throttle check

Any unverifiable claims in the same iteration ride through untouched.
Iterate on the `fail` claims only.

##### G.5: older proposer, or a structural failure (`LEGACY_CT > 0`)

The proposer didn't emit a `claims.jsonl` block, so the closed loop can't
work. Go to "Final report" with status `LEGACY_PROPOSER`.

#### Step H0: throttle check (FAIL only)

Before spending another iteration, check whether the registries were
actually answering:

```bash
# Stop rather than iterate if a third or more of the claims
# couldn't be checked at all.
if [ "${TOTAL_CT}" -gt 0 ] && [ $(( UNVER_CT * 3 )) -ge "${TOTAL_CT}" ]; then
  STATUS=THROTTLED
fi
```

If `STATUS=THROTTLED`, stop and go to "Final report". A run this heavily
throttled hasn't tested the table, and each further iteration costs several
minutes of retry back-off to learn nothing more. The `fail` claims found so
far stand, because under the verifier's rules a FAIL needs a status code it
actually saw. Report them, but don't act on the table until it can be
re-verified.

#### Step H: no-progress check (FAIL only)

```bash
CURRENT_FAIL_SET=$(grep -E '"status":"fail"' \
  "${ITERATE_ROOT}/iter-${N}/corrections.jsonl" \
  | python3 -c "import sys,json; print(' '.join(sorted(json.loads(l)['claim_id'] for l in sys.stdin)))")
```

If `CURRENT_FAIL_SET` equals `LAST_FAIL_SET` and `N > 0`, stop with status
`NO_PROGRESS`: the proposer can't act on the remaining fix hints. Go to
"Final report".

Otherwise set `LAST_FAIL_SET` to `CURRENT_FAIL_SET`, increase `N`, and loop.

#### Step I: limit check

If `N == 5` and the verdict is still FAIL, stop with status `CAP_REACHED`.
Go to "Final report".

### Final report

Always return:

```markdown
# lit-scout-iterate result: <query>

**Status:** <PASS | PARTIAL | UNVERIFIABLE | THROTTLED | FAIL | NO_PROGRESS | CAP_REACHED | LEGACY_PROPOSER>
**Iterations run:** <0..5>
**Workspace:** ${ITERATE_ROOT}

## Per-iteration trajectory

| Iter | Verdict | PASS | PARTIAL | FAIL | UNVERIFIABLE | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | FAIL | 25 | 1 | 4 | 0 | initial draft |
| 1 | FAIL | 28 | 1 | 1 | 0 | 3 corrections applied |
| 2 | PASS | 30 | 0 | 0 | 0 | final |

(Generate from each iteration's corrections.jsonl counts.)

**Rows removed, if any, must be listed explicitly** with the status
code that justified each removal, carried up from the proposer's
"## Rows removed in iterate mode" section. A removal with no observed
status code behind it is a defect in the run, not a finding — report
it as such and restore the row.

## Outcome detail

(Status-specific block — see below.)

## Final integrated report

(Verbatim contents of the final iteration's report.md: the verifier's
integrated report from the iteration that ended the loop, including the
corrected Findings table, which is what the user actually wants.)

---

**Per-iteration trajectory:** ${ITERATE_ROOT}/iter-*/
**Final verifier report:** ${ITERATE_ROOT}/iter-{N}/report.md
**Final claims:** ${ITERATE_ROOT}/iter-{N}/claims.jsonl
**Final corrections:** ${ITERATE_ROOT}/iter-{N}/corrections.jsonl
**Library import:** (only if a library import command ran: the heading
"## Library import", then the command's output verbatim)
**BibTeX file:** /tmp/lit-scout-iterate-bibtex-YYYYMMDD-HHMMSS.bib
(N entries; import it into your reference manager)
```

#### Outcome-detail blocks

- **PASS**: "Loop converged after N iterations. All claims pass verifier
  tolerance. Final corrected report below."
- **PARTIAL**: "**⚠ PARTIAL VERDICT — DRIVER DID NOT ITERATE.** Tolerance
  exceeded but within the partial-tolerance band on K claims. The corrected
  Findings table below reflects the iter-{N-1} corrections applied; PARTIAL
  claims preserve the proposer's value. Review the divergences in
  `${ITERATE_ROOT}/iter-{N}/corrections.jsonl` and decide whether to (a)
  accept the report as-is, (b) re-invoke with a stricter tolerance, or (c)
  manually re-run on specific rows."
- **UNVERIFIABLE**: "**⚠ VERIFICATION INCOMPLETE — DRIVER DID NOT
  ITERATE.** K claims across R rows could not be checked; the registries did
  not answer. No claim failed. **Those rows are preserved in the table below
  and flagged, not removed** — an unanswered lookup is not evidence against
  a citation. The observed cause for each row is in
  `${ITERATE_ROOT}/iter-{N}/corrections.jsonl` under `source_method`. If the
  cause is an exhausted OpenAlex budget it resets at midnight UTC; re-run
  lit-scout-verify on the final report then, rather than editing the table
  now."
- **THROTTLED**: "**⚠ RUN THROTTLED — LOOP STOPPED EARLY.** A third or more
  of the claims could not be checked, so the loop terminated rather than
  spending iterations on retry backoff. The K FAIL claims listed below were
  each confirmed against a status code and stand. The rest of the table is
  untested. Re-run once the rate limit resets."
- **FAIL** (only through CAP_REACHED): "**⚠ ITERATION CAP REACHED.** Five
  iterations did not produce a PASS or PARTIAL verdict. K FAIL claims
  remain. Manual investigation required."
- **NO_PROGRESS**: "**⚠ LOOP STALLED.** Iteration {N} produced the same FAIL
  `claim_id` set as iteration {N-1}. The proposer's iterate-mode cannot act
  on the remaining fix_hints — the hints may be ambiguous, the metadata API
  may be returning inconsistent results, or there is a methodology mismatch.
  Review iter-{N}/draft.md for the proposer's self-check notes on what it
  tried."
- **LEGACY_PROPOSER**: "**⚠ CLOSED LOOP NOT POSSIBLE.** The proposer's draft
  did not contain a machine-readable `claims.jsonl` block. Returning the
  single-round verifier output without iteration."

### Library import (optional)

The user can set a library import command in this plugin's options
(`library_import_command`). Its value is the single line in this block:

```text
${user_config.library_import_command}
```

The option is **not set** if that line is empty, or if it begins with a
dollar sign and an opening brace (an unfilled placeholder). In that case
skip this step and say nothing about it.

If it is set, run this after the final iteration, on every status except
`LEGACY_PROPOSER` (which has no structured claims to import). First
divide the final claims into verified and unverified papers:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/split_claims.py" "${ITERATE_ROOT}"
```

That writes `verified-claims.jsonl` (papers whose every check passed) and
`unverified-claims.jsonl` (all the others, each claim with a
`verification` field saying what didn't pass) into the run folder, and
prints the two counts. If it fails, don't run the import command: report
"Library import skipped:" with the error text in the section below.

Then run the import command once, with the run folder as its one
argument:

```bash
<the command, exactly as given> "${ITERATE_ROOT}"
```

The command is expected to import from `verified-claims.jsonl`. What it
does with the unverified papers is the user's decision, built into their
command; the full iteration folders and `query.txt` are there if it
wants them. Put into the final report a "## Library import" section,
just before the BibTeX pointer, holding one line with the two counts
from the split ("N papers verified, M unverified") and then the
command's standard output, verbatim. If it exits
with an error, put "Library import failed:" and the error text in that
section instead, and still return the report and the BibTeX file. Run it
once only: don't retry a failed import, because a second run may create
duplicates in the user's library.

### BibTeX

Run this after the final iteration, whatever the status, because the
corrected table is still useful. Take the DOIs from the `doi` field of the
final claims, not from the `claim_id` slug, which can't be reversed for
DOIs with hyphens or several slashes:

```bash
BIBTEX_PATH="/tmp/lit-scout-iterate-bibtex-$(date +%Y%m%d-%H%M%S).bib"
mapfile -t DOIS < <(python3 -c "
import json, sys
seen = []
for line in open(sys.argv[1]):
    doi = json.loads(line).get('doi')
    if doi and doi not in seen:
        seen.append(doi)
print('\n'.join(seen))
" "${ITERATE_ROOT}/iter-${N}/claims.jsonl")
"${CLAUDE_PLUGIN_ROOT}/scripts/lit-search" bibtex "${DOIS[@]}" > "$BIBTEX_PATH"
```

If it fails, add a brief note to the output ("BibTeX generation failed:
[reason]"), but still return the verified report.

## Examples

```text
Bayesian methods for archaeological dating uncertainty

LLM-assisted data extraction from historical documents; scope:
2022-present; include preprints
```

## Failures and recovery

| Failure | Symptom | Recovery |
| --- | --- | --- |
| The proposer errors at iteration 0 | The agent returns an error and no draft | Run the command again with the same query; nothing was saved that could conflict |
| The proposer errors at a later iteration | Iterate mode fails | The previous iteration's outputs remain. Start `lit-scout` by hand with `previous_draft_path` and `previous_corrections_path` pointing at them |
| The verifier errors | Step D returns an error or malformed output | The iteration's `draft.md` is kept: verify it with the `lit-scout-verify` command |
| No corrections block | Step F produces an empty file | Treat it as a verifier failure: show the verifier's own output, and don't iterate |
| Limit reached | Status `CAP_REACHED` | Look at the remaining failed claims and their fix hints: the proposer may be unable to satisfy the verifier on those rows |
| Stall | Status `NO_PROGRESS` | As for the limit, but sooner. Often a sign of an ambiguous fix hint, or a metadata API returning inconsistent results |
| BibTeX errors | The BibTeX step fails | Note it in the output; still return the integrated report |
| Library import errors | The library import command exits with an error | Note it in the "Library import" section; still return the integrated report and the BibTeX file. Don't run the import again automatically |
| The user stops it | The loop is interrupted | The partial sequence in `${ITERATE_ROOT}/` can be inspected; start later runs in a new folder |

## Notes

- The proposer and verifier each run in the foreground as separate subagent
  calls, each with a fresh context window. Neither can see the other's
  reasoning or tool calls.
- The main conversation is the channel between them, and by design does no
  reasoning about the content: it only passes file paths and extracts
  blocks.
- **Why the data travels inside the Markdown:** in testing, subagents were
  blocked from writing Markdown files, and their behaviour with `.jsonl`
  files is untested. So both agents embed their structured data as fenced
  `jsonl` blocks between comment markers, which the command extracts. This
  avoids the restriction entirely, at the cost of one extra extraction pass
  per iteration.
- The limit of five iterations is a rule of thumb, shared with the
  data-profile loop. Tune it in the light of experience.
- The PARTIAL band is also a rule of thumb, with per-field thresholds in the
  verifier's "Tolerance bands" section.
- Each iteration is one full proposer call and one full verifier call. A
  typical query takes 15 to 25 minutes per iteration; later iterations are
  faster (3 to 8 minutes), because the proposer skips discovery.
- Don't try to start the verifier from inside the proposer's context, or the
  reverse: Claude Code doesn't let subagents start subagents.
- For one-off work without iteration, use the `lit-scout` command, which runs
  a single proposer and verifier round. Use this command when an uncorrected
  confabulation would cost more than one to three extra iterations.
