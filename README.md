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

### Optional: connect your reference library

The literature scout can check what you already hold, and import what it finds, through two
commands of your own. Both are plugin options, both are off until you set them, and the plugin
ships no reference-manager code: you point it at a script that knows your library.

| Option | The command is given | The command prints |
| --- | --- | --- |
| `library_check_command` | Candidate DOIs on standard input, one per line | One line for each DOI your library holds: the DOI, then optionally a tab and a note. The scout marks those rows `[HAVE]` |
| `library_import_command` | One argument: the run folder of a finished `lit-scout-iterate`, in which the verified papers are listed separately from the rest | A Markdown summary, which becomes the report's "Library import" section |

**Import from `verified-claims.jsonl`.** Before it runs your import command, the plugin divides
the run's results into two files in the run folder:

| File | Holds |
| --- | --- |
| `verified-claims.jsonl` | The claims (authors, year, title, citation count, DOI) for papers whose every claim passed. One record per claim, each with the full `doi` |
| `unverified-claims.jsonl` | The same for every other paper: a claim failed, was only a partial match, couldn't be checked, or has no verdict. Each record has a `verification` field saying which |

A run can end with unverified papers still in its table, for example when a registry was
throttled. An import command that reads only `verified-claims.jsonl` can't put one of those into
your library by accident. Import the unverified ones only if your command marks them clearly
(a tag, a separate collection), so that you check them before you cite them.

The run folder also holds `query.txt` (your query) and one `iter-N` folder per iteration; the
highest-numbered holds the final `claims.jsonl`, `corrections.jsonl` (the verifier's verdict on
each claim), and `report.md` (the verified report).

**Failing clearly.** Both commands must exit with an error status when they couldn't do their
job, and a check command must print a DOI only when it found exactly that DOI. A check that
exits cleanly with no output means "nothing held", so a check that can't read your library and
still exits cleanly hides every duplicate. On an error the scout reports the library as not
checked and never marks a row `[HAVE]`. An import command can also finish with some items not
imported; it should say which in its summary, which the report keeps in full. The plugin never
runs an import a second time, since that could create duplicates: if one fails part-way, you
decide what to do.

**What a value may be.** A value is a script or program with any fixed arguments, written as
you would type it in a shell; the plugin adds the run folder, or the DOIs on standard input.
Quote a path that contains spaces. Put pipelines and anything more involved inside a script of
your own, and give its path.

Set the options when you install, or later:

```bash
claude plugin install verification-agents@research-agent-toolkit \
  --config library_check_command="python3 $HOME/bin/zotero-library-check.py"
claude plugin configure verification-agents@research-agent-toolkit
```

Inside Claude Code, `/plugin configure verification-agents` opens the same options. Use full
paths, and keep API keys out of the option values: they are stored in your `settings.json` and
shown to the model. A script that needs a key should read it from its own environment or file.

**An example for Zotero.**
[`plugins/verification-agents/examples/zotero-library-check.py`](plugins/verification-agents/examples/zotero-library-check.py)
is a working check command for a Zotero library on the same computer. It reads the DOI field of
every item in your local Zotero database, in all your libraries, never changes your library,
and needs only Python. Copy it somewhere of your own, read it, and set `library_check_command` to
`python3` followed by its full path. There is no example import command: importing writes to
your library, and how you want new items filed, tagged, and de-duplicated is yours to decide.
The Zotero web API and the `pyzotero` library are the usual route.

The values are commands that the agent runs in your shell, so set them only to scripts you
trust; this is not a sandbox. What your scripts print goes into the agent's context and the
report as text, and the agents are told to treat it as data, not instructions. An unset option
needs Claude Code to leave its placeholder in the text or to fill it with nothing, which is how
version 2.1.322 behaves; the agents treat either as "not set".

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
