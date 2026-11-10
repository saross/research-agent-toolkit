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
 * label before the first colon (the lens key), then by "default", then by a
 * schema-valid default for its role (a clean lens verdict, or an empty
 * meta-review). A verdict without a `lens` gets the lens key filled in. null
 * stands for a skipped or failed agent, which the real runtime also returns
 * as null; "throw" makes the stand-in throw.
 *
 * Every non-null answer is checked against the schema the script passed. An
 * answer that fails is a mistake in the test, reported as ok: false, unless
 * the scenario sets "invalidAs": "null", which models an agent whose output
 * the runtime could not accept. That is an assumption about the runtime, not
 * a property of it: this harness is a stand-in for the runtime's globals, not
 * an equivalent of it.
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
const harnessErrors = []

// A checker for the subset of JSON Schema the workflow's schemas use.
function schemaErrors(value, schema, path = '$') {
  if (!schema) return []
  const errors = []
  const type = schema.type
  const isObject = value !== null && typeof value === 'object' && !Array.isArray(value)
  if (type === 'object' && !isObject) return [`${path}: not an object`]
  if (type === 'array' && !Array.isArray(value)) return [`${path}: not an array`]
  if (type === 'string' && typeof value !== 'string') return [`${path}: not a string`]
  if (type === 'boolean' && typeof value !== 'boolean') return [`${path}: not a boolean`]
  if (schema.enum && !schema.enum.includes(value)) errors.push(`${path}: not one of ${schema.enum}`)
  if (type === 'object') {
    for (const key of schema.required || []) {
      if (!(key in value)) errors.push(`${path}.${key}: missing`)
    }
    for (const [key, v] of Object.entries(value)) {
      const sub = (schema.properties || {})[key]
      if (!sub) {
        if (schema.additionalProperties === false) errors.push(`${path}.${key}: not allowed`)
        continue
      }
      errors.push(...schemaErrors(v, sub, `${path}.${key}`))
    }
  }
  if (type === 'array') {
    value.forEach((item, i) => errors.push(...schemaErrors(item, schema.items, `${path}[${i}]`)))
  }
  return errors
}

function roleDefault(schema) {
  if (schema && (schema.required || []).includes('classifications')) {
    return { classifications: [], priorities: [], blindSpots: [], verifyBeforePresenting: [] }
  }
  return { passes: true, findings: [], clean: ['all'], confidence: 'high' }
}

// The runtime's `meta` export is read by Claude Code, not by the script;
// inside a function body it becomes an ordinary constant.
const body = source.replace(/^export const meta\s*=/m, 'const meta =')

function answerFor(label, schema) {
  const key = label.split(':')[0]
  const table = scenario.responses || {}
  let answer
  if (Object.prototype.hasOwnProperty.call(table, label)) answer = table[label]
  else if (Object.prototype.hasOwnProperty.call(table, key)) answer = table[key]
  else if (scenario.default !== undefined) answer = scenario.default
  else answer = roleDefault(schema)
  if (answer === 'throw') throw new Error(`stub agent ${label} failed`)
  if (answer === null || answer === undefined) return null
  answer = JSON.parse(JSON.stringify(answer))
  if (typeof answer === 'object' && !Array.isArray(answer) && !('lens' in answer) &&
      !('classifications' in answer) && (schema?.required || []).includes('lens')) {
    answer = { lens: key, ...answer }
  }
  const errors = schemaErrors(answer, schema)
  if (errors.length) {
    if (scenario.invalidAs === 'null') return null
    harnessErrors.push(`stub answer for ${label} violates its schema: ${errors.join('; ')}`)
  }
  return answer
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
  return answerFor(opts.label ?? '', opts.schema)
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
  if (harnessErrors.length) {
    process.stdout.write(JSON.stringify({ ok: false, error: 'harness: ' + harnessErrors.join(' | '),
      calls, logs }))
  } else {
    process.stdout.write(JSON.stringify({ ok: true, result, calls, logs }))
  }
} catch (err) {
  process.stdout.write(JSON.stringify({ ok: false, error: String(err?.message ?? err), calls, logs }))
}
