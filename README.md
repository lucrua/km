# knowledge-manager

Your documents say what is true. This tells you **which of it you actually approved.**

## The chancel

**A copy of each file, as you last endorsed it, kept in `refs/km/chancela`.** Reviewing is
comparing that copy with the file on disk; endorsing a passage is writing that passage into
the copy. Nothing is stored per passage — no identity, no anchor, no hash — and the ref is
written with plumbing and never checked out, so your branch, index and working tree are
untouched.

```bash
km pendente                       # what changed since the chancel, and what never had one
km chancela regras.md --hunk 2    # that passage, into the ref — `git add -p` semantics
km chancela regras.md --all       # the file as it is today
km restore regras.md --hunk 2     # put the chancelled text back on disk
km lint                           # the writing convention, mechanically
km quando regras.md --trecho "colunas"   # when that passage last had a chancel
```

Reservations live **in the document**, as blockquotes, because a note only a tool can see is
a note the next agent rewrites without knowing it existed:

```markdown
> ⚠️ **sem certeza** — enters the chancel and stays visible
> ❓ **a confirmar até 2026-10-15** — a pending item, with a date
> 🚫 **discordo** — blocks the chancel of this passage until it is resolved
```

One ref and a writing convention, not a parallel store of comments. A caveat that disappears
from a rewrite is flagged on its own, apart from ordinary edits, because that is the change
designed to pass unnoticed. The design, with the measurements behind it, is in
[docs/chancel.md](docs/chancel.md).

## The claim queue

The older half of the tool reads Markdown documents, splits them into claims, and keeps a
separate record of the claims a human approved — together with the exact text that was
approved. When the text changes, the approval stops counting.

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

## Nothing to remember

```bash
km install-hooks
```

Writes a `post-commit` hook that prints one line after every commit — how many files are in
step with the chancel, how many passages moved, how many files it never saw, and anything
that clashes with something already approved. It reports and exits 0: it never blocks a
commit, and the only command left to remember is `km pendente`.

## Does this fight something already settled?

```bash
km conflicts export pairs.json   # candidates: claims overlapping an approved claim
km conflicts import pairs.json   # {key, against, verdict, reason} from the model
km conflicts                     # what was found
```

Comparing every claim against every other is 69k pairs for 372 claims and answers the wrong
question. What matters is whether a claim fights something **you already approved**, so the
settled set is one side of every pair. A cheap overlap picks candidates — the share of the
smaller claim's term mass, never an absolute sum, since length alone would make a changelog
paragraph match everything — and a model gives the verdict. A conflict is shown on the card
with both texts; it never approves or rejects anything by itself.

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

- It does not edit your documents, except when you ask it to: `km restore` puts back text
  you had chancelled, and that is the only command that writes a document.
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

- [docs/chancel.md](docs/chancel.md) — **the current model, built**: the chancel as a
  reviewed copy in a git ref, caveats as a writing convention, the commands, and what git
  answers for free.
- [docs/format.md](docs/format.md) — what counts as a claim, how text is normalised, what
  the approval record stores.
- [docs/roadmap.md](docs/roadmap.md) — what comes after shadow mode, and what is
  deliberately out of scope.

Language: code, CLI and documentation in English; the documents `km` reads can be in any
language.

## Status

Early. The chancel is built and in use; the claim queue stays as it was. `.km/` holds
configuration and the claim record — the chancel itself is in git, under `refs/km/chancela`,
and `git update-ref -d refs/km/chancela` undoes it entirely.
