/**
 * review-paper — multi-lens review panel for academic paper prose
 * ===========================================================================
 * The workflow behind the review-paper skill of the writing plugin
 * (research-agent-toolkit). Run it through that skill, which runs the
 * mechanical pre-pass first and asks before spending on agents; it is kept in
 * scripts/, not workflows/, so it is not offered as a command of its own.
 * Two stances, one architecture:
 *
 *   - critical-friend (default): constructive, drafting-phase; findings are
 *     improvements; strengths recorded; no fail-by-default.
 *   - adversarial: hostile "Reviewer 2", pre-submission gate; fail-by-default
 *     preamble + Devil's-Advocate hard rules (every finding names its target
 *     claim, cites checkable evidence, states a falsifiable counter-condition,
 *     and self-declares its retraction condition); a meta-reviewer pass reads
 *     the panel's findings adversarially (hallucinated-objection taxonomy);
 *     an [UNANIMOUS-CHECK] devil's advocate fires when the panel comes back
 *     clean.
 *
 * Design invariants:
 *   - FRESH-CONTEXT PANEL: each lens is a fresh-context agent that reads only
 *     the target artefact(s) — no drafting-conversation memory.
 *   - SETTLED RULINGS travel with the target: author-settled guard registers
 *     are passed in and must not be re-litigated (only drift is reportable).
 *   - EVIDENCE-ANCHORED findings; explicit CLEAN lines per dimension.
 *   - DETERMINISTIC AGGREGATION: the verdict is computed from severities
 *     (including the mechanical pre-pass findings passed via args), never
 *     from any agent's pass boolean. The meta-reviewer critiques and
 *     prioritises; it NEVER overrides the computed verdict.
 *   - CONVERGENCE UPGRADES PRIORITY: findings from >= 2 lenses sharing an
 *     anchor token are flagged converged (priority, not verdict).
 *   - MODEL PINNED AT DISPATCH: every agent() call passes an explicit model;
 *     the caller stamps the rendered report with the model requested, the run
 *     date, the workflow run ID, and the plugin version.
 *
 * The mechanical pre-pass (review-paper-prepass.py, beside this script) runs
 * BEFORE this workflow — the workflow sandbox has no filesystem access, so
 * deterministic checks live there and their findings arrive via
 * args.prepassFindings.
 *
 * args (object; JSON-string tolerated — the harness sometimes stringifies):
 *   REQUIRED
 *     targets        [string]  absolute paths of the section .tex files
 *     repo           string    absolute paper-repo root (agents' working dir)
 *   OPTIONAL
 *     stance         'critical-friend' (default) | 'adversarial'
 *     scope          'section' | 'paper' (default: 'section' iff 1 target)
 *     model          string    default 'opus' (an alias for the current
 *                              Opus-class model); pass a full model ID to pin
 *     run_date       string    echoed for artefact stamping (no Date.now here)
 *     paperBrief     string    what the paper argues (shared static context)
 *     constraints    string    hard constraints -> activates the constraints lens
 *     settledRulings string | {targetPath: string}   author-settled registers;
 *                              object keys may be absolute target paths OR
 *                              repo-relative (the prepass emits repo-relative)
 *     sourceNotesDir string    folder of source notes, one per cited work,
 *                              named by citekey and holding verbatim quotes
 *                              from that work (the source-fidelity substrate)
 *     bibPaths       [string]  .bib files (source-fidelity context)
 *     readOnlyContext[string]  extra paths lenses MAY consult (supplements etc.)
 *     lensSet        [string]  subset of lens keys to run (default: the four
 *                              core lenses, plus constraints/voice when those
 *                              are configured); unknown or unconfigured keys
 *                              fail fast
 *     voice          boolean   enable the off-by-default voice lens
 *     voiceReference string    register/corpus note path (required if voice)
 *     prepassFindings [ {check, severity, detail, evidence, target} ]
 */

export const meta = {
  name: 'review-paper',
  description: 'Fresh-context multi-lens review panel for paper prose (critical-friend or adversarial), with deterministic severity aggregation.',
  phases: [
    { title: 'Review', detail: 'independent fresh-context lenses per target section' },
    { title: 'Synthesis', detail: 'cross-section synthesis (paper scope only)' },
    { title: 'Meta-review', detail: 'adversarial meta-reviewer + unanimous-check (adversarial stance only)' },
  ],
}

// --- args: defensive parse + fail-fast validation ---------------------------
// (The harness has been seen to deliver args as a JSON-encoded STRING.
// Parse before validating.)
let A = args
if (typeof A === 'string') {
  try { A = JSON.parse(A) } catch (e) {
    throw new Error('review-paper: args arrived as a non-JSON string: ' + e.message)
  }
}
if (!A || typeof A !== 'object' || Array.isArray(A)) {
  throw new Error('review-paper: args must be an object — see the script header.')
}
const TARGETS = A.targets
if (!Array.isArray(TARGETS) || !TARGETS.length) {
  throw new Error('review-paper: args.targets (non-empty array of section paths) is required.')
}
for (const t of TARGETS) {
  if (typeof t !== 'string' || !t.startsWith('/')) {
    throw new Error(`review-paper: every target must be an absolute path; got ${JSON.stringify(t)}.`)
  }
}
const REPO = A.repo
if (typeof REPO !== 'string' || !REPO.startsWith('/')) {
  throw new Error('review-paper: args.repo (absolute paper-repo root) is required.')
}
const STANCE = A.stance || 'critical-friend'
if (!['critical-friend', 'adversarial'].includes(STANCE)) {
  throw new Error(`review-paper: unknown stance "${STANCE}".`)
}
const SCOPE = A.scope || (TARGETS.length === 1 ? 'section' : 'paper')
if (!['section', 'paper'].includes(SCOPE)) {
  throw new Error(`review-paper: unknown scope "${SCOPE}".`)
}
// Model provenance: pinned at dispatch, with a stated default. An alias such
// as 'opus' resolves to the current model of that tier; the run's transcript
// records which model actually answered.
const MODEL = A.model || 'opus'
const RUN_DATE = A.run_date || null
const PREPASS = Array.isArray(A.prepassFindings) ? A.prepassFindings : []
const VOICE = !!A.voice
if (VOICE && !A.voiceReference) {
  throw new Error('review-paper: voice lens enabled but args.voiceReference missing.')
}

// Repo-relative form of a path. Findings and register lookups are normalised
// through this so the prepass (which emits repo-relative paths) and the panel
// (absolute targets) agree — without it the settled-rulings register never
// matched and prepass<->lens convergence on the same line was impossible.
const relPath = (p) =>
  (typeof p === 'string' && p.startsWith(REPO + '/')) ? p.slice(REPO.length + 1) : p

function rulingsFor(target) {
  if (!A.settledRulings) return null
  if (typeof A.settledRulings === 'string') return A.settledRulings
  return A.settledRulings[target] || A.settledRulings[relPath(target)] || null
}

// --- Schemas ----------------------------------------------------------------
// Adversarial findings additionally carry the Devil's-Advocate hard-rule
// fields; building the schema per stance makes them REQUIRED there, so a
// vibes-based objection fails validation instead of reaching the report.
function findingSchema(stance) {
  const base = {
    severity: { type: 'string', enum: ['blocker', 'major', 'minor'] },
    dimension: { type: 'string', description: 'which checked dimension this belongs to' },
    detail: { type: 'string' },
    evidence: {
      type: 'string',
      description: 'checkable anchor: file:line, grep hit, citekey, source-note quote, or verbatim source quote',
    },
    standingRulingDrift: {
      type: 'boolean',
      description: 'true ONLY if this reports prose drifting from a recorded author ruling',
    },
  }
  const adversarialExtra = {
    targetClaim: { type: 'string', description: 'the exact sentence/claim objected to (quote it)' },
    counterCondition: {
      type: 'string',
      description: 'falsifiable: precisely what, if shown, would prove this objection wrong',
    },
    retractionCondition: {
      type: 'string',
      description: 'self-declared: the evidence that, if produced, retracts this finding',
    },
  }
  const properties = stance === 'adversarial' ? { ...base, ...adversarialExtra } : base
  const required = stance === 'adversarial'
    ? ['severity', 'dimension', 'detail', 'evidence', 'targetClaim', 'counterCondition', 'retractionCondition']
    : ['severity', 'dimension', 'detail', 'evidence']
  return { type: 'object', additionalProperties: false, required, properties }
}

function lensVerdictSchema(stance) {
  return {
    type: 'object',
    additionalProperties: false,
    required: ['lens', 'passes', 'findings', 'clean', 'confidence'],
    properties: {
      lens: { type: 'string' },
      passes: {
        type: 'boolean',
        description: 'the agent’s own call; aggregation IGNORES it and uses severities',
      },
      findings: { type: 'array', items: findingSchema(stance) },
      clean: {
        type: 'array', items: { type: 'string' },
        description: 'one entry per checked dimension with NO findings — silence is never ambiguous',
      },
      strengths: {
        type: 'array', items: { type: 'string' },
        description: 'critical-friend only: what already works (omit or [] when adversarial)',
      },
      confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
    },
  }
}

const META_REVIEW_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['classifications', 'priorities', 'blindSpots', 'verifyBeforePresenting'],
  properties: {
    classifications: {
      type: 'array',
      description: 'trustworthiness call on each panel finding, by its [ref] id',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['findingRef', 'trust', 'note'],
        properties: {
          findingRef: { type: 'string' },
          trust: {
            type: 'string',
            // Hallucinated-objection taxonomy (arXiv 2602.05930) as vocabulary.
            enum: ['sound', 'total-fabrication', 'partial-corruption',
                   'identifier-hijacking', 'placeholder', 'semantic-drift'],
          },
          note: { type: 'string' },
        },
      },
    },
    priorities: {
      type: 'array', items: { type: 'string' },
      description: 'the findings the author should act on first, most urgent first, by [ref] + one line why',
    },
    blindSpots: {
      type: 'array', items: { type: 'string' },
      description: 'what NONE of the lenses examined that a real Reviewer 2 would',
    },
    verifyBeforePresenting: {
      type: 'array', items: { type: 'string' },
      description: '[ref]s the orchestrator must verify against authoritative sources before the report ships',
    },
  },
}

// --- Stance preambles -------------------------------------------------------
const HARD_RULES = `
HARD RULES OF DISSENT (Devil's-Advocate protocol — a finding that fails ANY rule is
invalid; do not emit it):
- NAME the target: quote the exact sentence/claim you object to (targetClaim).
- CITE checkable evidence: a file:line, grep hit, citekey, source-note quote, or verbatim
  source quote (evidence). No anchor, no finding.
- STATE a falsifiable counter-condition: precisely what, if shown, would prove your
  objection wrong (counterCondition).
- SELF-DECLARE the retraction condition: the evidence that, if produced, retracts the
  finding (retractionCondition).`

function stancePreamble(stance) {
  if (stance === 'adversarial') {
    return `You are a HARSH, SCEPTICAL peer reviewer ("Reviewer 2") assessing a manuscript at a
pre-submission gate. FAIL BY DEFAULT: your job is to find what is WRONG, not what is good;
where you are uncertain whether something is a problem, flag it. Do NOT invent problems,
but do NOT let real ones pass.
${HARD_RULES}`
  }
  return `You are a rigorous but CONSTRUCTIVE critical friend reviewing a work-in-progress draft.
Find real problems and frame each as an improvement the author can act on; also record
what already works (strengths) so revision does not destroy it. Do NOT invent problems,
and do NOT soften real ones. Every finding MUST carry checkable evidence (a file:line,
grep hit, citekey, or verbatim quote) — no anchor, no finding.`
}

// --- Shared prompt scaffolding ----------------------------------------------
function commonBrief(target) {
  const rulings = rulingsFor(target)
  const context = []
  context.push(`TARGET (read it in full, first): ${target}`)
  context.push(`Working directory / repo root: ${REPO}`)
  if (A.paperBrief) context.push(`PAPER BRIEF (static context):\n${A.paperBrief}`)
  if (Array.isArray(A.readOnlyContext) && A.readOnlyContext.length) {
    context.push(`You MAY also consult (read-only): ${A.readOnlyContext.join(', ')}`)
  }
  context.push(`Do NOT read any other draft, notes, or planning file — you are a fresh-context
reviewer and your independence is the point. If it's not in the artefacts named here, it
doesn't count.`)
  if (rulings) {
    context.push(`SETTLED RULINGS REGISTER (author-settled — do NOT re-flag these; they are closed.
Report one ONLY if the prose has DRIFTED from the recorded ruling, and mark that finding
standingRulingDrift=true):\n${rulings}`)
  }
  context.push(`REPORTING RULES:
- Every finding: severity in {blocker, major, minor}, the dimension it belongs to, and a
  checkable evidence anchor.
- For every dimension you checked and found NOTHING in, emit its name in "clean" — silence
  is never ambiguous.
- Your "passes" boolean is advisory only; the verdict is computed deterministically from
  severities.`)
  return context.join('\n\n')
}

// --- Lens definitions (the review dimensions, parameterised) ---------------
// Bodies are target-independent, so the set is built ONCE and lensSet is
// validated at TOP level. Validating inside the pipeline stage would be
// swallowed: a throwing stage drops its item to null instead of rejecting the
// run, and an invalid lensSet would sail on to a false-clean verdict.
function buildLensDefs() {
  const lenses = []

  lenses.push({
    key: 'source-fidelity',
    prompt: `LENS: SOURCE FIDELITY & CLAIM-EVIDENCE (the killer dimension). Work decompose ->
classify -> verify:
(a) DECOMPOSE the section into its load-bearing claims, each carrying enough context to be
    checkable (no context-stripped fragments).
(b) CLASSIFY each claim: cited / the paper's own finding / load-bearing but uncited.
(c) VERIFY:
    - A CITED claim is checked against the source note for its citekey${A.sourceNotesDir
      ? ` (notes folder: ${A.sourceNotesDir} — find the note file for the citekey; its
    verbatim quotes from the source are the oracle)`
      : ` (NO source notes supplied — flag every cited claim as "unverifiable: no substrate"
    at minor severity rather than guessing)`}: does the source, as attested, actually
    support the claim AS PHRASED? Overstatement, reversal, and scope-creep are findings.
    - A LOAD-BEARING UNCITED claim is flagged: "should this be cited?"
    - An OWN-FINDING claim passes (the consistency lens owns it).
(d) Every concrete specific (number, date, name, quoted phrase) must be LOOKED UP against
    its source${Array.isArray(A.bibPaths) && A.bibPaths.length
      ? ` (bibs: ${A.bibPaths.join(', ')})` : ''} — do NOT assume an expected value; the
    source is the only oracle. A missing source note for a cited key is itself a finding
    (minor, "substrate gap").
Match the FULL citation command family (any \\...cite... variant — \\citealp misses have
produced false "uncited" findings before).`,
  })

  lenses.push({
    key: 'consistency',
    prompt: `LENS: INTERNAL CONSISTENCY & ONCE-AND-ONLY-ONCE.
(1) Contradictions: does this section contradict itself${SCOPE === 'paper'
      ? ' or any other section in the target list' : ''}? Numbers, claims, terminology.
(2) Once-and-only-once: each concept introduced once and covered thoroughly — no
    redundancy, no gap. IMPORTANT: a duplication finding is a POLICY QUESTION, not
    automatically a defect — where a guard says "don't restate X" but the author has
    deliberately written compressed worked examples, report the TENSION (guard-vs-prose)
    for the author to rule on; treat only objective breaches (identical strings, verbatim
    cross-section echoes) as defects.
(3) Cross-references: does every \\ref{} target the right place? Distinguish wrong-level
    refs (defect) from deliberate section-level refs (fine). An undefined-but-forthcoming
    label is EXPECTED while drafting — not a defect.
(4) Dangling references, orphaned definitions, terms used before introduction.`,
  })

  lenses.push({
    key: 'calibration',
    prompt: `LENS: CALIBRATION & OVER-CLAIM.
(1) Is each claim proportionate to its evidence? Flag over-claim verbs ("shows",
    "demonstrates", "clearly", "proves") where the evidence supports weaker.
(2) Mis-calibrated hedges — in BOTH directions: a hedge on a strongly-evidenced claim
    undersells; an unhedged weakly-evidenced claim oversells.
    CRITICAL CALIBRATION GUARD: careful humanities/social-science prose uses deliberate
    hedging and risk/limitation language as a mark of RIGOUR. A calibrated hedge is a
    STRENGTH — do NOT flag hedging, cautious framing, or limitation acknowledgements as
    weakness unless you can show the hedge is genuinely mis-calibrated against the
    evidence it covers. (LLM reviewers systematically underrate hedged prose; do not be
    that reviewer.)
(3) Altitude: the body should argue at altitude with limited illustrative examples;
    exhaustive detail belongs in a supplement. Flag raw detail leaking into the body, and
    argument floating with no example at all.
(4) Confirmation-bias sweep: scrutinise every "close enough", "minor", "as expected" —
    is the dismissal earned?`,
  })

  lenses.push({
    key: 'completeness',
    prompt: `LENS: COMPLETENESS & GAPS (the adversarial edge).
(1) What objection would a hostile Reviewer 2 raise that the section never addresses?
(2) What does the section PROMISE (roadmap sentences, "we show below", forward refs) but
    not deliver?
(3) Name the WEAKEST sentence — the one a sceptical reviewer would single out as
    hand-wavy, unsupported, or doing load-bearing work it cannot carry — and say why.
(4) Structural counts: if the prose announces N of anything (principles, phases, cases),
    COUNT what follows and verify N. (Three lenses once independently caught a
    five-vs-six miscount — announced counts rot under revision.)
(5) Missing limitations: what would a referee expect acknowledged that is not?`,
  })

  if (A.constraints) {
    lenses.push({
      key: 'constraints',
      prompt: `LENS: HARD-CONSTRAINT COMPLIANCE. The author declares these binding constraints for
this target. Check EACH literally and mechanically (grep before judging); report each
constraint as satisfied (in "clean") or violated (a finding, severity major unless the
constraint text says otherwise):
${A.constraints}`,
    })
  }

  if (VOICE) {
    lenses.push({
      key: 'voice',
      prompt: `LENS: VOICE & REGISTER (diagnostic). Compare the target's prose against the author's
register reference at ${A.voiceReference} (read it first). Flag departures from the
attested register: sentence-rhythm drift, vocabulary the author would not use, hedging
style mismatches, en/em-dash and punctuation habits. This lens is diagnostic — findings
are minor unless the drift changes meaning.`,
    })
  }

  return lenses
}

const ALL_LENSES = buildLensDefs()
let ACTIVE_LENSES = ALL_LENSES
if (Array.isArray(A.lensSet) && A.lensSet.length) {
  const known = new Set(ALL_LENSES.map((l) => l.key))
  for (const k of A.lensSet) {
    if (!known.has(k)) {
      throw new Error(
        `review-paper: lensSet names "${k}", which is unknown or not configured ` +
        '(the constraints lens needs args.constraints; the voice lens needs args.voice ' +
        `+ voiceReference). Available: ${[...known].join(', ')}.`)
    }
  }
  ACTIVE_LENSES = ALL_LENSES.filter((l) => A.lensSet.includes(l.key))
}

function lensPrompts(target) {
  return ACTIVE_LENSES.map((l) => ({
    key: l.key,
    prompt: `${stancePreamble(STANCE)}

${commonBrief(target)}

${l.prompt}

Return a LENS_VERDICT (lens = "${l.key}").`,
  }))
}

// --- Phase 1: per-target fresh-context panels -------------------------------
const LENS_SCHEMA = lensVerdictSchema(STANCE)
log(`review-paper: ${STANCE} / ${SCOPE} over ${TARGETS.length} target(s), model ${MODEL}.`)

const shortName = (p) => p.split('/').pop()

// pipeline: each target's panel fans out immediately; no cross-target barrier
// until the synthesis genuinely needs every panel (paper scope only).
const panels = await pipeline(
  TARGETS,
  (target) => parallel(
    lensPrompts(target).map((L) => () =>
      agent(L.prompt, {
        label: `${L.key}:${shortName(target)}`,
        phase: 'Review',
        schema: LENS_SCHEMA,
        agentType: 'general-purpose',
        model: MODEL,
      }).then((v) => (v ? { ...v, target } : null))
    )
  ).then((verdicts) => ({ target, verdicts: verdicts.filter(Boolean) })),
)

const panelResults = panels.filter(Boolean)

// Coverage accounting, up front: null verdicts (user skip / terminal agent
// error) are silent in the results, and a verdict computed over a failed
// panel would be a false-clean gate.
const EXPECTED_PANEL_AGENTS = TARGETS.length * ACTIVE_LENSES.length
const PANEL_SUCCESSES = panelResults.reduce((n, p) => n + p.verdicts.length, 0)
const failedLenses = EXPECTED_PANEL_AGENTS - PANEL_SUCCESSES
if (PANEL_SUCCESSES === 0) {
  throw new Error(
    `review-paper: all ${EXPECTED_PANEL_AGENTS} lens agents failed or were skipped — ` +
    'no review was performed, so no verdict can be computed. (The mechanical ' +
    "pre-pass results remain valid in the caller's prepass JSON.)")
}
if (failedLenses > 0) {
  log(`WARNING: ${failedLenses}/${EXPECTED_PANEL_AGENTS} lens agent(s) returned null ` +
      '(skipped/errored) — coverage is PARTIAL; any verdict below is not a valid gate.')
}

// --- Phase 2: cross-section synthesis (paper scope only; barrier is correct:
// it needs every section + every panel verdict together) ---------------------
let crossSection = null
if (SCOPE === 'paper') {
  const findingsDigest = panelResults.flatMap((p) =>
    p.verdicts.flatMap((v) => (v.findings || []).map((f) =>
      `- [${v.lens} @ ${shortName(p.target)}] ${f.severity}: ${f.detail}`))).join('\n')
  const csResult = await agent(`${stancePreamble(STANCE)}

${commonBrief(TARGETS.join('\n  '))}

LENS: CROSS-SECTION SYNTHESIS (whole paper). Read EVERY target file listed above, in
order, then assess the COMPOSED paper:
(1) Thesis coherence: does every section serve one argument arc, with no section pulling
    against the thesis?
(2) Once-and-only-once ACROSS sections: concepts introduced twice, or in the wrong
    section; verbatim or near-verbatim echoes between sections.
(3) Claim -> evidence traceability across the paper: does every promissory note in early
    sections get paid off where it points?
(4) Whole-paper heading review: heading accuracy, parallelism, grammatical consistency of
    heading forms, and collisions (e.g. two "Limitations" headings left by a restructure).
(5) Cross-reference audit at paper level: wrong-level refs (defect) vs deliberate
    section-level refs (fine); targets that lack labels.
(6) Argument arc: does the ending answer the opening?

For context, the per-section panels reported (do NOT re-litigate these — find what they
COULD NOT see from inside one section):
${findingsDigest || '(no per-section findings)'}

Return a LENS_VERDICT (lens = "cross-section").`,
  {
    label: 'cross-section',
    phase: 'Synthesis',
    schema: LENS_SCHEMA,
    agentType: 'general-purpose',
    model: MODEL,
  })
  crossSection = csResult ? { ...csResult, target: '(whole paper)' } : null
  if (!crossSection) {
    log('WARNING: cross-section synthesis agent returned null — its dimensions are UNREVIEWED.')
  }
}

// --- Deterministic aggregation ----------------------------------------------
// Verdict authority lives HERE — in severities — not in any agent's opinion.
// Every finding's target is normalised to the repo-RELATIVE path: the prepass
// emits relative paths while lens findings carry absolute ones, and without a
// common form prepass<->lens convergence on the same line is structurally
// impossible. Report rendering also gets one
// consistent grouping key.
function collectFindings() {
  const out = []
  for (const p of panelResults) {
    for (const v of p.verdicts) {
      for (const f of (v.findings || [])) {
        out.push({ ...f, lens: v.lens, target: relPath(v.target) })
      }
    }
  }
  if (crossSection) {
    for (const f of (crossSection.findings || [])) {
      out.push({ ...f, lens: 'cross-section', target: crossSection.target })
    }
  }
  for (const f of PREPASS) {
    out.push({
      severity: f.severity, dimension: f.check || 'mechanical',
      detail: f.detail, evidence: f.evidence,
      lens: 'mechanical-prepass', target: relPath(f.target || '(prepass)'),
    })
  }
  return out.map((f, i) => ({ ...f, ref: `F${String(i + 1).padStart(3, '0')}` }))
}

// Convergence upgrades PRIORITY, not verdict: findings from >= 2 distinct
// lenses sharing an anchor token (a :line number or a citekey-shaped token)
// are independent confirmations of the same issue.
function anchorTokens(f) {
  const s = `${f.evidence || ''} ${f.targetClaim || ''}`
  const tokens = new Set()
  for (const m of s.matchAll(/:(\d{1,5})\b/g)) tokens.add(`line:${f.target}:${m[1]}`)
  for (const m of s.matchAll(/\b([A-Za-z][\w.-]*_\d{4}[a-z]?|[A-Z][A-Za-z]+\d{4}[A-Za-z]*)\b/g)) {
    tokens.add(`key:${m[1]}`)
  }
  return [...tokens]
}

function markConvergence(findings) {
  const byToken = new Map()
  for (const f of findings) {
    for (const t of anchorTokens(f)) {
      if (!byToken.has(t)) byToken.set(t, [])
      byToken.get(t).push(f)
    }
  }
  const groups = []
  for (const [token, fs] of byToken) {
    const lensSet = new Set(fs.map((f) => f.lens))
    if (lensSet.size >= 2) {
      groups.push({ token, lenses: [...lensSet], refs: fs.map((f) => f.ref) })
      for (const f of fs) f.converged = true
    }
  }
  return groups
}

let all = collectFindings()
let convergenceGroups = markConvergence(all)
const tally = (fs) => ({
  blockers: fs.filter((f) => f.severity === 'blocker').length,
  majors: fs.filter((f) => f.severity === 'major').length,
  minors: fs.filter((f) => f.severity === 'minor').length,
  info: fs.filter((f) => !['blocker', 'major', 'minor'].includes(f.severity)).length,
})

// --- Phase 3 (adversarial only): unanimous-check + meta-reviewer ------------
let unanimousCheck = null
let metaReview = null
if (STANCE === 'adversarial') {
  // [UNANIMOUS-CHECK]: a clean bill from every sceptic is itself suspicious.
  // Force one devil's advocate to produce the strongest objection under the
  // hard rules; its findings join the deterministic aggregation. The trigger
  // tallies the LLM panel's OWN findings (mechanical-prepass excluded — a
  // mundane word-budget major should not suppress the stress test of a
  // unanimously clean panel) and only fires when the panel ran in full
  // (unanimity among agents that never reported is no unanimity at all).
  const llmCounts = tally(all.filter((f) => f.lens !== 'mechanical-prepass'))
  if (llmCounts.blockers === 0 && llmCounts.majors === 0 && failedLenses === 0) {
    log('[UNANIMOUS-CHECK] LLM panel returned no blockers/majors — dispatching devil\'s advocate.')
    unanimousCheck = await agent(`${stancePreamble('adversarial')}

${commonBrief(TARGETS.length === 1 ? TARGETS[0] : TARGETS.join('\n  '))}

[UNANIMOUS-CHECK] A full sceptic panel just returned NO blocker or major findings on this
target. Unanimity among reviewers is itself a signal worth stress-testing. Your single
job: construct the STRONGEST objection a hostile Reviewer 2 could still raise — the one
finding, if it exists, that the panel's shared framing made all of them miss. Attack the
framing itself: what does every lens take for granted?

If, after genuine effort, no rule-compliant objection exists, return zero findings and
name (in "clean") the strongest candidate you constructed and why it failed the hard
rules. Do NOT manufacture a finding to look useful.

Return a LENS_VERDICT (lens = "unanimous-check").`,
    {
      label: 'unanimous-check',
      phase: 'Meta-review',
      schema: lensVerdictSchema('adversarial'),
      agentType: 'general-purpose',
      model: MODEL,
    })
    if (!unanimousCheck) {
      log('WARNING: unanimous-check agent returned null — the unanimity stress test did not run.')
    }
    if (unanimousCheck && (unanimousCheck.findings || []).length) {
      const start = all.length
      for (const [i, f] of unanimousCheck.findings.entries()) {
        all.push({
          ...f, lens: 'unanimous-check',
          target: TARGETS.length === 1 ? relPath(TARGETS[0]) : '(whole paper)',
          ref: `F${String(start + i + 1).padStart(3, '0')}`,
        })
      }
      convergenceGroups = markConvergence(all)
    }
  }

  // Meta-reviewer: reads the panel's own findings ADVERSARIALLY before the
  // report is assembled. Critiques and prioritises; NEVER overrides the
  // computed verdict (a design constraint: an editor-style aggregator may
  // prioritise findings, but the severities alone decide the verdict).
  const digest = all.map((f) =>
    `[${f.ref}] (${f.lens} @ ${shortName(f.target)}) ${f.severity}` +
    `${f.converged ? ' CONVERGED' : ''}: ${f.detail}\n    evidence: ${f.evidence}` +
    `${f.targetClaim ? `\n    target claim: ${f.targetClaim}` : ''}`).join('\n')
  metaReview = await agent(`You are the META-REVIEWER (editor persona) in an adversarial review pipeline. A panel
of fresh-context sceptic lenses has reviewed ${TARGETS.length} section(s) of a manuscript
(repo: ${REPO}; targets: ${TARGETS.join(', ')}). Your job is to review the REVIEWS —
adversarially — before the report reaches the author. You may read the target file(s) to
check a finding, but your subject is the panel's findings, not the manuscript.

For EACH finding below, classify its trustworthiness:
- sound — well-grounded; evidence anchor checks out.
- total-fabrication — the objection's evidence does not exist in the target/source.
- partial-corruption — real anchor, but the detail misstates what is there.
- identifier-hijacking — anchor points at the wrong entity (wrong citekey/line/section).
- placeholder — generic boilerplate objection that would apply to any paper.
- semantic-drift — quote/paraphrase real but the objection shifts its meaning.

Then: PRIORITIES (what the author should act on first — weigh severity, convergence, and
how load-bearing the affected claim is); BLIND SPOTS (what NONE of the lenses examined
that a real Reviewer 2 would); VERIFY-BEFORE-PRESENTING (every finding whose evidence you
could not confirm yourself, or where lenses contradict each other, or which contradicts a
recorded anchor — the orchestrator will verify these against authoritative sources before
the report ships).

You do NOT set the verdict — it is computed deterministically from severities. Your
output shapes priority and trust, never the pass/fail.

PANEL FINDINGS:
${digest || '(none — the panel and unanimous-check both returned clean)'}

MECHANICAL PRE-PASS included above with lens "mechanical-prepass": treat its findings as
deterministic ground truth (classify them "sound" without re-derivation unless one is
self-evidently mis-parsed).

Return a META_REVIEW.`,
  {
    label: 'meta-reviewer',
    phase: 'Meta-review',
    schema: META_REVIEW_SCHEMA,
    agentType: 'general-purpose',
    model: MODEL,
  })
  if (!metaReview) {
    log('WARNING: meta-reviewer agent returned null — findings ship without a trust classification.')
  }
}

// --- Verdict ----------------------------------------------------------------
// (Coverage was accounted for after the panels ran: a fully failed panel
// throws; partial failure logged a warning and is echoed in partialCoverage.)
const counts = tally(all)
// Adversarial maps to the reproducibility-framework ladder; critical-friend
// keeps the prototype's cleared boolean (it is not a gate).
const verdict = STANCE === 'adversarial'
  ? (counts.blockers > 0 ? 'CHALLENGED' : counts.majors > 0 ? 'QUALIFIED' : 'CONFIRMED')
  : null
const cleared = counts.blockers === 0 && counts.majors === 0

log(`review-paper done: ${counts.blockers} blocker / ${counts.majors} major / ` +
    `${counts.minors} minor${verdict ? ` -> ${verdict}` : ''} (model ${MODEL}).`)

return {
  stance: STANCE,
  scope: SCOPE,
  model: MODEL,                       // echo for the artefact stamp
  ...(RUN_DATE ? { run_date: RUN_DATE } : {}),
  targets: TARGETS,
  verdict,                            // adversarial ladder; null for critical-friend
  cleared,                            // no blockers and no majors
  counts,
  partialCoverage: failedLenses > 0 ? failedLenses : 0,
  findings: all,                      // every finding, ref'd, with lens/target/converged
  convergenceGroups,
  clean: panelResults.flatMap((p) => p.verdicts.map((v) => ({
    target: p.target, lens: v.lens, clean: v.clean || [], confidence: v.confidence,
  }))),
  strengths: STANCE === 'critical-friend'
    ? panelResults.flatMap((p) => p.verdicts.flatMap((v) =>
        (v.strengths || []).map((s) => ({ target: p.target, lens: v.lens, strength: s }))))
    : [],
  crossSection,
  unanimousCheck,
  metaReview,
  rawVerdicts: panelResults,
}
