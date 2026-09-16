# knowledge-manager

Your documents say what is true. This tells you **which of it you actually approved.**

`km` reads Markdown documents in a repository, splits them into claims, and keeps a
separate record of the claims a human approved — together with the exact text that was
approved. When the text changes, the approval stops counting. Nothing else changes: the
tool never rewrites your documents.

Status is **derived**, never written by hand:

| In the approval record | Status |
|---|---|
| nothing | `proposed` |
| hash matches the current text | `approved` |
| hash matches, plus `validate` and `due` | `approved · to validate` |
| hash differs | `changed after approval` — back to the queue |
| `superseded_by` | `superseded` |

An agent can write documents all day. It cannot make anything approved: only `km approve`
does that, and it is meant to be run by a person (or by an agent asking a person first).

## Shadow mode

The first mode is deliberately additive. **Claims are identified by the hash of their own
text**, so your documents need no IDs, no front matter and no edits to get started. The
only thing that appears in the target repository is a `.km/` directory, and removing it
undoes everything.

```bash
km init                 # create .km/ in the current repository
km scan                 # parse documents, print what was found — writes nothing
km status               # counts per file: approved, proposed, changed, gone
km list --proposed      # the queue, most risky first, numbered
km show 12              # one claim: text, file:line, heading
km approve 12           # record the approval with the hash of today's text
km approve 12 --validate "confirm with the contract owner" --due 2026-10-15
km carry 12             # this is a reworded claim 12 — keep the old approval's date and origin
```

Stable IDs are optional and can be introduced later, one line at a time: write
`**DSP-3** ...` at the start of a list item and `km` keys that claim by `DSP-3` instead of
by its hash, so rewording no longer looks like a new claim.

## What it does not do

- It does not edit your documents, ever. Only `.km/` is written.
- It does not decide anything. No LLM call, no network, no telemetry.
- It does not merge, lock or coordinate sessions. Concurrency is handled where it already
  is: the editor refuses stale writes, git merges, and a claim touched by two sessions
  simply loses its approval and comes back to the queue.

## Requirements

Python 3.11+. No third-party dependencies.

```bash
git clone <this repo> ~/knowledge-manager
export PATH="$HOME/knowledge-manager/bin:$PATH"
```

## Documentation

- [docs/format.md](docs/format.md) — what counts as a claim, how text is normalised, what
  the approval record stores.
- [docs/roadmap.md](docs/roadmap.md) — what comes after shadow mode, and what is
  deliberately out of scope.

Language: code, CLI and documentation in English; the documents `km` reads can be in any
language.

## Status

Early. Shadow mode only. The format of `.km/approvals.jsonl` may still change; it is small
and versioned in git, so migration is a script.
