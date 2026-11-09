# Research agent toolkit

Verification-first AI tooling for research: agents, skills, prompts, and methods for working with
large language models (LLMs) without trusting what they say unchecked.

The tools come from the author's own research practice in archaeology, history, and digital
humanities, where an invented citation, a wrong number, or an unpowered decision is expensive. Each
one either checks work independently or forces a check at the point where errors are cheapest to
catch.

**Status: version 0.1** (November 2026). The tools have been used in real research, and were
rewritten for release so that they run without the author's private set-up. Expect rough edges.

## What is here

| Part | What it does |
| --- | --- |
| [`plugins/verification-agents`](plugins/verification-agents) | Proposer and verifier agent pairs: literature scouting with citation chaining, prior-art discovery, and dataset profiling. A second agent, in a fresh context, re-checks the first one's factual claims against authoritative sources: each row of a findings table (authors, title, DOI, citations; repositories and packages), and each key figure of a data profile. The literature scout's narrative synthesis is not verified |
| [`plugins/research-gates`](plugins/research-gates) | Checkpoints: statistical power before scaling up (`phase-gate`), configuration audits before paid runs (`audit-config`), reviews of unattended pipelines (`pre-run-review`), implementation reviews (`review-implementation`), and two-lens code audits (`code-audit`) |
| [`plugins/prompt-hardening`](plugins/prompt-hardening) | `improve-prompt`: strengthens a prompt against the model stopping at good enough |
| [`prompts`](prompts) | Six plain prompts that work with any capable model |
| [`docs/methods`](docs/methods) | How the verification approach works, and the evidence for it |
| [`guard`](guard) | A pre-push check and an agent hook that keep secrets and private material out of public repositories, and a watcher that reports what reaches them by other routes |

## Install the Claude Code plugins

In Claude Code, add this repository as a plugin marketplace, then install the plugins you want:

```text
/plugin marketplace add saross/research-agent-toolkit
/plugin install verification-agents@research-agent-toolkit
/plugin install research-gates@research-agent-toolkit
/plugin install prompt-hardening@research-agent-toolkit
```

Plugin commands and agents are namespaced, so the literature scout runs as
`/verification-agents:lit-scout`.

**Requirements:**

- The verification agents' helper scripts need [`uv`](https://docs.astral.sh/uv/), which installs
  their Python dependencies on first use.
- The prior-art scout works best with the GitHub CLI, `gh`, signed in.
- Optionally, set `LIT_SCOUT_MAILTO` to your own email address. Scholarly APIs give identified
  callers higher rate limits.

The agents take your field and language conventions from your `CLAUDE.md`, so they need no other
configuration.

## Why verification first

A model states an invented specific, such as a citation, author list, number, or file path, with the
same fluency as a true one. Asking it to check its own work in the same context mostly confirms the
error. These tools separate the roles: one agent proposes, a second agent with no access to the
first one's reasoning verifies against authoritative sources, and the disagreements are resolved by
evidence, not by whichever agent spoke last. The commands carry out these steps as instructions to
Claude: they have no option that skips the verifier, but no hook forces it to run.
[`docs/methods`](docs/methods) sets out the method and what it has caught in practice.

## Licence

[Apache License 2.0](LICENSE).
