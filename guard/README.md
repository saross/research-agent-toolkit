# Publish guard

A pre-push check, and a watcher, for people and AI agents who keep private material near public
repositories. Before anything reaches a public repository, the check looks for secrets, listed
private terms, network details, and files of the wrong kind, and it refuses the push if it finds
any. The watcher then reads the Git content that has reached the watched repositories, however it
got there, after the fact. Both are built against accidents and misdirected agents, not a
determined adversary: getting past them takes a deliberate act, and neither asks a person anything
in ordinary work.

It runs on the Python standard library plus one external scanner,
[`gitleaks`](https://github.com/gitleaks/gitleaks).

## Why it exists

Assume that agents will read every repository's full history and use any detail in it. A rewrite
can't recall what has already been copied, so the guard checks before a push, and the response to
anything already public is to change the real thing (rotate the key, change the port) rather than
the history.

## What it checks

Every push asks GitHub, with no cache, whether the destination is public. Anything other than an
unambiguous "private" counts as public, including errors and other hosts.

| Destination | Checks |
| --- | --- |
| Public | Secrets; listed terms; network details such as private addresses and SSH settings; the repository's allowed paths; binary and Git Large File Storage (LFS) files need an allowance; changes to the scanner's own rules; submodules; symbolic links that leave the repository; refs outside branches and tags |
| Private, may go public | Secrets and the secrets tier block; the public checks run as warnings, with counts in the log |
| Private, never public | Secrets and the secrets tier only |
| A folder on this machine | Not checked |

It reads every commit the destination doesn't already have, asking the destination rather than
trusting local tracking refs. It reads through git's object store, so merges, `.gitattributes`,
replace refs, and local git settings can't hide content. Author, committer, and tag details, commit
messages, other commit headers, branch names, and file names are all checked. For a public
destination, the text around each change is checked as well as the added lines, so a listed name
that an edit completes across a line break, or by deleting the word between, is found too. Private
pushes do the same for the secrets tier, which blocks everywhere.

**It never shows what it matched.** A finding gives a rule and a location. A location that itself
contains a listed term appears as `<path hidden>`.

**It fails closed.** A missing scanner, policy, or list, a scanner that doesn't match its pinned
checksum, a list whose source was edited but not rebuilt, an unreadable answer from GitHub, or an
internal error all refuse the push. A missing secrets tier refuses private pushes too, once that
tier is expected: see "The lists". The scanner's rules are written from the engine on every push,
so a changed copy on disk has no effect.

## Install

**Requirements:** Python 3.11 or later; Linux, where it is tested, or macOS, where it is untested
(the engine uses POSIX terminal and file-locking calls, so it doesn't run on Windows); Git; the
GitHub CLI, `gh`, signed in, which every push uses to ask GitHub whether its destination is
public, and the watcher uses to list repositories and alerts; and a `gitleaks` binary.

The commands below are for GNU/Linux. On macOS, substitute equivalents, for example
`shasum -a 256` for `sha256sum`, and `mkdir -p` followed by `install -m 755` for `install -D`.

Set up in this order, so the hooks are active only once there is a policy and lists for them to
apply. `G` stands for the installed engine throughout this page.

1. **Get gitleaks** from its [releases](https://github.com/gitleaks/gitleaks/releases). Check the
   archive against the release's checksums file, then extract the binary. The guard pins the
   checksum of the *extracted binary*, not of the archive, so compute that one:

   ```bash
   sha256sum --check --ignore-missing gitleaks_<version>_checksums.txt
   tar -xzf gitleaks_<version>_<platform>.tar.gz gitleaks
   install -D -m 755 gitleaks ~/.config/publish-guard/bin/gitleaks
   sha256sum ~/.config/publish-guard/bin/gitleaks   # the checksum to give install
   ```

2. **Install the engine**, not yet active:

   ```bash
   python3 -I guard/publish_guard.py install \
     --gitleaks ~/.config/publish-guard/bin/gitleaks \
     --gitleaks-sha256 <the binary's checksum>
   G="python3 -I $HOME/.config/publish-guard/engine/publish_guard.py"
   ```

3. **Write the policy and the lists.** Create `~/.config/publish-guard/policy.toml` (see "The
   policy file"). Put each tier's terms, one per line, in a file named after the tier, with
   `.txt`: for example `~/.config/publish-guard/deny-sources/tier2a-people.txt`, or, for a tier
   of secrets, `deny-sources/secrets/tier1-exploit.txt` (see "The lists"). Only `.txt` files are
   read, and the names in `required_tiers` must match the file names without `.txt`. Then build
   the lists with `$G deny-rebuild`, at a terminal. Every tier in `required_tiers` must hold at
   least one term.

4. **Check, then activate:**

   ```bash
   $G doctor --scan ~/Code       # before activation, it reports that the hooks aren't active
   python3 -I guard/publish_guard.py install --gitleaks ~/.config/publish-guard/bin/gitleaks \
     --gitleaks-sha256 <the binary's checksum> --activate-global
   $G doctor --scan ~/Code       # now: "the guard is in force"
   ```

`install` copies the engine to `~/.config/publish-guard/engine/` and writes read-only hook stubs.
`--activate-global` points git's global `core.hooksPath` at them. The stubs also pass control on to
a repository's own hooks, including Git LFS, so those keep working.

`doctor` checks that the guard is really in force: the global setting, every stub, the engine and
scanner checksums, the lists, and any repository whose own settings would bypass the guard.

**To switch it off:** `git config --global --unset core.hooksPath`.

The home folder holds two files you supply, usually as links into a private repository:

- `policy.toml`, described below;
- `deny/`, the lists, with their plain-text sources in `deny-sources/`.

## The policy file

```toml
required_tiers = ["tier1-exploit", "tier2a-people", "tier3-private"]

[repos."owner/new-public-repository"]
label = "public"
allowed_paths = ["README.md", "LICENSE", "docs/**", "src/**"]
binary_allow = ["docs/images/*"]
block_home_paths = true

[repos."owner/working-notes"]
label = "never-public"
```

| Key | Meaning |
| --- | --- |
| `label` | `public`, `may-go-public`, or `never-public`. A public repository with no entry is refused until it has one |
| `allowed_paths` | If set, nothing outside these paths may be added. `*` stays within a folder and `**` crosses folders |
| `binary_allow` | Paths where binary and LFS files may go. Each one is logged, and searched for secrets and listed terms where its text is readable |
| `skip_tiers` | Lists that don't apply to this repository. The secrets tier can't be skipped |
| `block_home_paths` | Refuse home-folder paths, which are mostly a portability problem |
| `required_tiers` | Lists that must exist and hold at least one term before any public push |
| `watch_owners` | Owners whose public repositories the watcher reads |
| `watch` | `true` or `false` for one repository, overriding `watch_owners` |

A repository labelled `never-public` that reads as public is refused with an alert. So is one
labelled `may-go-public` that has become public: review it first, then change its label.

## The lists

Each list, or tier, is a file of keyed hashes in `deny/`, which is all the check reads. A tier you
want to review has a plain-text source file, `deny-sources/<tier>.txt` (or
`deny-sources/secrets/<tier>.txt`), with one term per line; the tier takes its name from the file.

`tier1-exploit` is the secrets tier, for known secret values such as those in `.env` files. Unlike
the others, it blocks on every remote, private ones included, as the secret scan does. Once it is
expected, because `required_tiers` names it, it has a source file, or it has been built here
before (which leaves a `secret-tier-expected` file in the guard's folder), a missing or damaged
file refuses every push rather than switching the tier off. To retire the tier on purpose, remove
it from all three.

```bash
G="python3 -I $HOME/.config/publish-guard/engine/publish_guard.py"
$G deny-rebuild            # after editing any source file
$G deny-stats              # entries per tier
$G deny-check              # look up one term; needs a terminal, and doesn't show what you type
$G deny-add --tier T       # add to a tier that has no source file
$G deny-remove --tier T    # remove from such a tier; needs a terminal
```

**Matching** works on words. Case, accents, hyphens, underscores, punctuation, and line breaks don't
matter, and words run together or two-word names reversed are added automatically. Abbreviations and
different number layouts are not, so add the forms people actually write. Use specific strings, such
as full names, distinctive identifiers, and addresses written as number, street, and street type.
Leave out topics and common words, which would block ordinary text.

## When a push is refused

The message lists each rule and location. Fix the commits, for example by amending or rebasing
before the push. If a finding is a false positive, a person can exempt that exact push from their
own terminal, with the command the message prints. The command names the push by an identifier that
covers each destination ref and the commit sent to it, so it never prints a ref name that was
blocked. The identifier also covers the findings, so a push that has grown since the person looked isn't
covered. An exemption needs a typed reason, works once, lapses after an hour or when the policy or
lists change, and is logged.

The terminal requirement keeps exemptions and list changes out of an agent's ordinary reach, but it
isn't authentication: anything running as the same user can fake a terminal or write the exemption
file directly. The agent hook, below, refuses the plain forms of both.

Scripts that retry failed pushes should look for the line `publish-guard: BLOCKED`, because git
reports a failed hook with its own exit status.

## Checking existing history

```bash
$G audit --repo PATH --name owner/repo --as public --rev=--since=2026-01-01 --rev=HEAD
```

This applies the same rules to commits already made, and reports counts and locations. With
`--rev=--all` it also reads every ref name and every tag object, which commits alone don't show.
Run it that way before making a repository public.

## The agent hook

`agent_hook.py`, installed beside the engine, is a Claude Code `PreToolUse` hook. It only refuses,
and only what ordinary work never needs: commands that would switch the pre-push check off or skip
it (`--no-verify`, `git commit -n`, a `core.hooksPath` override, a push from a clone where the guard
isn't in force), the guard's own administration (exemptions, list changes, clearing the watcher's
findings), writes into the guard's folder by shell or by the file tools, and running
`build-tier1.py`. It reads write destinations in the usual forms: redirections, the last operand,
target-directory options such as `install -t`, folders a recursive copy lands in, and in-place
`sed` and `perl` edits with their programme attached or separate. It never asks, so it doesn't
interrupt autonomous work.

Other publishing routes go through: creating a repository, changing its visibility, GitHub API
writes, gists, releases, `git lfs push`, `git send-pack`, a push run over SSH. Each is noted in
`log/agent-hook.jsonl` (the route and the folder, never the command), and the watcher reports the
counts. Its docstring gives the settings to wire it in.

## The watcher

```bash
$G watch --report ~/notes/publish-watch.md
```

The pre-push check stops accidents on this machine. The watcher looks afterwards at the watched
repositories, whatever route content took to them: other machines, agent sessions with hooks off,
collaborators, web edits, and API writes. Each run:

- compares every listed repository's visibility with its label, and lists public repositories of
  the watched owners that have no policy entry;
- reads the new commits, refs, and tags of each watched public repository with the same scanner
  and rules as a public push;
- counts GitHub's open secret-scanning alerts for those repositories (the count only);
- counts the publishing routes the agent hook noted.

A repository is watched if its owner is in the policy's `watch_owners`, or its entry says
`watch = true`; other public repositories get visibility checks only.

| What reached GitHub | What the watcher does |
| --- | --- |
| Commits, branches, tags, and tag objects in a watched public repository | Reads them, as a public push would |
| Pull-request refs that GitHub advertises | Reads them, as other refs |
| A watched repository's visibility, and new public repositories of watched owners | Checks against the policy |
| Secrets GitHub's own scanning has found | Counts open alerts |
| Releases, release files, gists, issues, comments, wikis, and LFS files | Doesn't read them; routes the agent hook saw are counted, nothing more |
| Content published and then removed between two runs | Doesn't see it (see Limits) |
| Repositories of owners not watched | Checks visibility only |

**Status.** The report opens with one of three states, and the command exits with its number:
clean (0), something needs attention (1), or incomplete (3), when some check couldn't run: an
owner couldn't be listed, alerts couldn't be read, a repository couldn't be fetched or ran out of
time, or a prerequisite (the scanner, the policy, a list, or a list edited but not rebuilt) failed.
An incomplete run still writes its report, with the findings already recorded, and says what it
couldn't check and when that last succeeded. While a run is going, the report says INCOMPLETE ("a
run started … hasn't finished"), so a run stopped from outside, by its time limit or a shutdown,
leaves the report saying so rather than repeating the last clean result. That marker needs no list
or saved state, so damaged ones can't hold it back, and they make the run incomplete (3). If
even the report can't be written, the run still ends with 3 and says so on standard error.
"Clean" says when some history is still unread or some findings were acknowledged. The example
service treats 1 as success and 3 as failure, so `systemctl --user status` shows a watcher that
has stopped working.

**What has been read.** For each repository the watcher saves the refs it last read, and the rules
that read them: the policy entry, the lists, and the scanner. It never saves a ref as read unless
its objects were fetched and read. Every ref and object a listing shows is saved as pending before
the fetch, so a failed fetch or read can't forget it. When a ref moves between listing and
fetching, the watcher asks for the listed object by its identifier; if that fails, the repository
stays incomplete, and is retried each run, until the object is read or a person acknowledges it.
When the rules change, for example when a term is added to a list, what the watcher has read is
read again under the new ones; the rules recorded are the ones the run actually loaded, so a list
rebuilt during a run is applied on the next. Repositories are read least recently attempted first,
each attempt saved before it starts, so a run cut short, or one failing on the same repositories,
doesn't keep missing the rest. After updating the engine itself, run
`watch --rescan all`.

**First sight.** A repository seen for the first time is recorded without reading its history, and
the report lists it as "initial audit pending" until `watch --rescan NAME` reads its whole history
(or `--full` on the first run reads it at once). `audit --rev=--all` on a clone does the same job
outside the watcher, but doesn't clear the note.

**Findings** stay in the report until a person acknowledges them, at a terminal, with
`watch --clear NAME` or `watch --clear all`; the agent hook refuses that command. An acknowledged
finding isn't raised again when the same content is read again, but acknowledging doesn't make the
content clean: rotate the secret, or rewrite and force-push. The report gives locations and counts,
never values. A repository whose name itself holds a listed term appears as
`<repository withheld …>`, a stand-in built from a hash of its name. Findings are stored as
locations and shown under the lists in force when each report is written, so a name or path
listed later is withheld from then on; when no list can be loaded, every name and path is. The
report's content changes at most once a day when nothing happens.

To run it hourly, install `systemd/publish-guard-watch.service` and `.timer` from this folder as
user units (add `--report PATH` to the service), then
`systemctl --user daemon-reload && systemctl --user enable --now publish-guard-watch.timer`. Each
repository has a time limit (15 minutes), the service a limit for the whole run, and a lock keeps a
manual run from overlapping the timer's: the second one does nothing and says so.

## Limits

- **Local only.** It doesn't run for collaborators on their own machines, for tools that switch git
  hooks off, or in cloud sessions. Server-side secret scanning and branch rules cover part of that
  gap.
- **Patterns can't read meaning.** Free-form personal writing gets past every pattern. Allowed paths
  keep the wrong kinds of file out, and a person's review catches the rest.
- **The lists are only as good as what is on them.** Matching is by whole words, so a term inside a
  longer word, an abbreviation, a middle name, a lookalike character, or encoded or compressed text
  isn't matched. The hashes are keyed, but anyone holding the key and the files can test guesses
  offline, and short or common names are quick to guess.
- **Not every push goes through a hook.** Lower-level git commands, `git lfs push`, direct GitHub
  API writes, and pushes from other machines skip it. The agent hook notes the routes it can see,
  and the watcher reads the Git content of the watched repositories, but only after the fact: a
  leak can be public until the next watch, and copies made in that time can't be recalled. Rotate
  a leaked secret at once. The watcher's coverage table says what it doesn't read.
- **The watcher sees snapshots.** It compares what each repository holds at one run with the
  next. Content published and then corrected by a force-push, or a ref deleted and recreated,
  before the next run is never seen, though it was public in between. Hourly runs keep that window
  short; only GitHub's own event record would close it.
- **The same user can change everything.** The guard's folder, policy, lists, and exemptions are all
  writable by anything running as the same user. The checks make getting past the guard a
  deliberate act; they don't make it impossible.
- **Folders on this machine aren't checked.** A push to a local path is trusted, including one that
  a backup or sync service later copies elsewhere.
- **Binary allowances cover a path, not a reviewed file.** Later contents of an allowed path pass
  too, and text inside compressed formats (most PDFs, images, and office files) isn't seen. LFS
  pointers are checked, but the files they point to aren't read.
- **Private pushes check added lines for most tiers.** Only public pushes read the text around
  each change for every tier; private pushes do so for the secrets tier alone. A name completed
  across lines in a private repository may give no warning. The audit before a visibility change
  reads whole files.
- **Signature headers are skipped.** The `gpgsig` and `gpgsig-sha256` headers of a commit or tag
  aren't read, on the assumption that they hold an encoded signature. Git doesn't check that they
  do, so text deliberately placed there gets past the check.
- **Reading around a change doesn't make a check cheap.** It keeps the deny-list matching in
  proportion to the change, but each changed file is still read and decoded whole, and git still
  computes its diff, so a push of large files costs time in proportion to their size.
