/**
 * workflow_harness.mjs — run the review-paper workflow offline
 * ============================================================
 *
 * Claude Code runs a workflow script with a few globals (args, agent,
 * parallel, pipeline, log, phase) and allows a top-level `return`. This
 * harness supplies stand-ins for them, so the script's own logic (argument
 * checks, lens selection, coverage accounting, convergence, and the
 * deterministic verdict) can be tested with no model at all.
 *
 * Usage: node workflow_harness.mjs SCRIPT SCENARIO_JSON
 *
 * The scenario is a JSON file:
 *   { "args": <passed to the script as `args`>,
 *     "responses": { "<label or lens key>": <verdict object> | null | "throw" },
 *     "default": <verdict object> }
 * An agent call is answered by its exact label, then by the part of the
 * label before the first colon (the lens key), then by "default". A
 * verdict without a `lens` gets the lens key filled in. null stands for a
 * skipped or failed agent, which the real runtime also returns as null.
 *
 * Output (stdout, one JSON document):
 *   { "ok": true, "result": <the script's return value>, "calls": [...], "logs": [...] }
 *   { "ok": false, "error": "<message>", "calls": [...], "logs": [...] }
 */

import { readFileSync } from 'node:fs'

const [scriptPath, scenarioPath] = process.argv.slice(2)
const source = readFileSync(scriptPath, 'utf8')
const scenario = JSON.parse(readFileSync(scenarioPath, 'utf8'))

const calls = []
const logs = []

// The runtime's `meta` export is read by Claude Code, not by the script;
// inside a function body it becomes an ordinary constant.
const body = source.replace(/^export const meta\s*=/m, 'const meta =')

function answerFor(label) {
  const key = label.split(':')[0]
  const table = scenario.responses || {}
  let answer
  if (Object.prototype.hasOwnProperty.call(table, label)) answer = table[label]
  else if (Object.prototype.hasOwnProperty.call(table, key)) answer = table[key]
  else answer = scenario.default ?? { passes: true, findings: [], clean: ['all'], confidence: 'high' }
  if (answer === 'throw') throw new Error(`stub agent ${label} failed`)
  if (answer && typeof answer === 'object' && !Array.isArray(answer) && !('lens' in answer) &&
      !('classifications' in answer)) {
    answer = { lens: key, ...answer }
  }
  return answer === undefined ? null : JSON.parse(JSON.stringify(answer))
}

async function agent(prompt, opts = {}) {
  calls.push({
    label: opts.label ?? null,
    model: opts.model ?? null,
    phase: opts.phase ?? null,
    agentType: opts.agentType ?? null,
    required: opts.schema?.required ?? null,
    findingRequired: opts.schema?.properties?.findings?.items?.required ?? null,
    prompt,
  })
  return answerFor(opts.label ?? '')
}

// The runtime turns a failed item or thunk into null rather than rejecting.
async function parallel(thunks) {
  return Promise.all(thunks.map(async (t) => {
    try { return await t() } catch { return null }
  }))
}

async function pipeline(items, ...stages) {
  return Promise.all(items.map(async (item) => {
    let value = item
    for (const stage of stages) {
      try { value = await stage(value) } catch { return null }
    }
    return value
  }))
}

function log(message) { logs.push(String(message)) }
function phase() {}

const AsyncFunction = Object.getPrototypeOf(async () => {}).constructor
const run = new AsyncFunction('args', 'agent', 'parallel', 'pipeline', 'log', 'phase', body)

try {
  const result = await run(scenario.args, agent, parallel, pipeline, log, phase)
  process.stdout.write(JSON.stringify({ ok: true, result, calls, logs }))
} catch (err) {
  process.stdout.write(JSON.stringify({ ok: false, error: String(err?.message ?? err), calls, logs }))
}
