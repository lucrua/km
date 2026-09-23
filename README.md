# knowledge-manager

Your documents say what is true. This tells you **which of it you actually reviewed.**

Code, CLI and documentation in English; the documents `km` reads, and everything it prints
on screen, are in the language they were written in.

## The chancel

**A copy of each file, as you last endorsed it, kept in `refs/km/chancela`.** Reviewing is
comparing that copy with the file on disk; endorsing a passage is writing that passage into
the copy. Nothing is stored per passage — no identity, no anchor, no hash — and the ref is
written with plumbing and never checked out, so your branch, your index and your open files
are untouched.

Which documents it covers is the `include` list in `.km/config.json`: opt-in, and anything
outside it never appears.

## The panel

```bash
km serve          # binds 127.0.0.1:8431 — Ctrl-C ends it
```

The document, whole, from top to bottom. **Text that did not change is just text**: one
column, full width, no buttons — headings cut nothing. **Each change is one row**, placed
where it happened, in three columns:

| | |
|---|---|
| **the chancel** | the blocks as you endorsed them, with what left struck through. A selector swaps it for any branch or commit |
| **now** | the file today, with what arrived marked in place. Editable, like everything else in this column |
| **what to do** | a verdict per block, and one for the whole change |

**The everyday unit is a Markdown block** — a paragraph, a list item, a table, a heading, a
quote, a code fence — and a change can be approved whole or block by block. When you need
less than a block, **select part of the text** in the second column: a bar offers *Aprovar
seleção* and *Reverter seleção*, and only the changes inside the selection are taken — like
staging half a hunk in a code review. A selection that touches part of a word takes the word.

How much is left is a **percentage of the content**: the characters still to decide over the
characters the file would have if everything were approved. Not a count of blocks or
changes — a one-word fix and a new section are not "one" each.

The middle column is Markdown **source**, highlighted, with the change marked the way a
tracked-changes document does it, in the spirit of [pandiff](https://github.com/davidar/pandiff).
Source and not rendered prose on purpose: the column is editable, and editing rendered
Markdown means a serialiser rewrites the whole file on save. Wide tables scroll sideways
instead of wrapping.

| | |
|---|---|
| **Aprovar** | the block goes into the chancel |
| **A validar…** | writes `> ❓ **a confirmar até …**` right after the block, and chancels both: the half-chancel is a visible line, not a hidden state |
| **Reverter** | puts the chancel's text back in the file |
| **⚠️ · 🚫** | start a reservation after the block, in the agreed form, for you to finish |

The whole second column is always editable — click and type. The action column offers
**Salvar no arquivo** when there is something to save; Ctrl+S saves, Esc discards. A save is
located by what the text said, not by line number, so a line an agent inserted above does not
make you write over someone else's paragraph; if your text is no longer in the file, the save
is refused and the page shows what is there now. **⚠️ ❓ 🚫 at the top** insert a
reservation at the cursor, on its own line.

A block is identified by its content, never its position: a page that asks to approve a
block after the file moved gets a refusal, not a different block.

Keyboard: `j` `k` move between changes, `a` approves the change in focus.

The server does not stay up: you start it when you sit down to review. Inside VS Code, the
command **km: abrir o painel da chancela** (`Ctrl+Alt+P`) starts it and opens it in the same
window, and it dies with the window.

## The convention

Reservations live **in the document**, as blockquotes, because a note only the tool can see
is a note the next agent rewrites without knowing it existed:

```markdown
> ⚠️ **sem certeza** — enters the chancel and stays visible
> ❓ **a confirmar até 2026-10-15** — a pending item with a date; reported once it passes
> 🚫 **discordo** — blocks the chancel of this passage until it is resolved
```

One ref and a writing convention, not a parallel store of comments. A caveat that
**disappears** from a rewrite is flagged on its own, apart from ordinary edits, because that
is the change designed to pass unnoticed.

## The command line

The panel is where reviewing happens; these are the same things in a terminal, and how a
script or an agent reads the state.

```bash
km init                          # creates .km/config.json — the include list is the opt-in
km pendente                      # what changed since the chancel, and what never had one
km pendente --novos              # the list of files with no chancel
km chancela regras.md --hunk 2   # change 2 into the ref; `--hunk 2.1` only its first block
km chancela regras.md --all      # the file as it stands today
km restore  regras.md --hunk 2.1 # put the chancelled text of that block back on disk
km lint                          # 🚫 pending · ❓ past its date · ⚠️ caveat that vanished
km quando   regras.md --trecho "colunas"   # when that passage last had a chancel
km baseline regras.md            # the chancelled copy, for a diff's left-hand column
km install-hooks                 # one line after every commit, saying where you stand
```

`chancela`, `pendente` and `quando` also answer to `chancel`, `pending` and `when`.

## What git gives for free

| Question | Answer |
|---|---|
| what is pending | `git diff refs/km/chancela -- <file>` |
| word-level diff, which is what prose needs | `git diff --word-diff --word-diff-regex='[^[:space:]]+'` |
| **when did this passage last have a chancel** | `git log -L '/## Heading/,/## Next/:<file>' refs/km/chancela` |
| why you endorsed it | the commit message on the ref |
| the whole review history | `git log refs/km/chancela` |

## In the editor

The extension in [`vscode/`](vscode/) paints each passage in the gutter, puts in the
Problems panel what moved since your chancel, what never had one, a caveat past its date and
a caveat that vanished, and opens the diff against `km baseline`. The verdicts are the same
ones, and they write the marks into the text.

## What it does not do

- It decides nothing. No LLM call, no network, no telemetry.
- It does not write in your documents except when you ask: `restore`, the marks, and editing
  a passage in the panel.
- It does not lock or coordinate sessions. Concurrency is handled where it already is: the
  editor refuses stale writes, git merges, and the panel shows both texts when the file
  moved under you.

## Requirements

Python 3.11+. No third-party dependencies.

```bash
git clone <this repo> ~/knowledge-manager
export PATH="$HOME/knowledge-manager/bin:$PATH"
```

## Documentation

- [docs/chancel.md](docs/chancel.md) — the model, with the measurements behind it.
- [docs/roadmap.md](docs/roadmap.md) — what comes next, and what is deliberately out of
  scope.

## Status

The chancel is in use. Everything it holds lives in `refs/km/chancela` — `git update-ref -d
refs/km/chancela` undoes it completely — and the only file written in the target repository
is `.km/config.json`.
