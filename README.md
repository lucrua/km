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
km serve                # the same queue as a local page, one claim at a time
```

## The review page

`km serve` binds a page to `127.0.0.1:8431`. One claim fills the screen, most risky first,
with the document's progress above it and the keyboard doing the work:

| key | |
|---|---|
| <kbd>A</kbd> | approve |
| <kbd>V</kbd> | approve, but flag what would confirm it and when it comes back |
| <kbd>N</kbd> | note what is wrong or missing — the claim stays proposed, the note waits in `.km/notes.jsonl` |
| <kbd>D</kbd> | defer for two weeks — a valid answer, recorded in `.km/deferrals.jsonl` |
| <kbd>C</kbd> | discuss: copies the claim with its location to the clipboard, ready to paste into a chat |
| <kbd>S</kbd> | approve every pending claim in this section — each keeps its own hash, the ones you did not read one by one are marked `lot` |
| <kbd>X</kbd> | not a claim — parsing over-collects, and this is how the queue learns |
| <kbd>U</kbd> | undo the last one |

The card shows the whole section around the claim in focus: the record is per claim, the
reading is per section.

Each card carries the lines around it, its section, and any note you left on it before.

`km notes` prints what you wrote, grouped by document: the list an agent reads to fix the
text. Fixing it changes the text, so the claim comes back to the queue on its own — which is
the whole point. `km notes --open` hides the ones already approved.

Plain HTML from a single Python file: no build, no npm, no network, no framework. It writes
the same `.km/` files the CLI writes, so terminal and page are interchangeable.

## Enumerating, then classifying

The parser splits and identifies; it does not understand. Judging what kind of sentence a
claim is belongs to a model, and stays advisory:

```bash
km triage export claims.json    # what has no current classification
km triage import claims.json    # {key, kind, risk, reason} from the model
km list --kind procedencia      # inspect what was hidden
```

Only `norma` reaches the default queue, one in seven hidden claims is shown anyway as a
sample, and a classification dies when the text changes. **Triage hides and orders; it never
approves.**

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
