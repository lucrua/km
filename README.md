# knowledge-manager

Your documents say what is true. This tells you **which of it you actually reviewed.**

Code, CLI and documentation in English; the documents `km` reads, and everything it prints
on screen, are in the language they were written in.

## Getting started

1. **Clone it and put `km` on your PATH** — in `~/.bashrc`, so every new terminal has it:

   ```bash
   git clone <this repo> ~/knowledge-manager
   echo 'export PATH="$HOME/knowledge-manager/bin:$PATH"' >> ~/.bashrc
   ```

2. **Under WSL, put VS Code's `code` on the same PATH**, for the panel's *abrir no VS Code*
   (adjust the Windows user name):

   ```bash
   echo 'export PATH="$PATH:/mnt/c/Users/<you>/AppData/Local/Programs/Microsoft VS Code/bin"' >> ~/.bashrc
   ```

   Open a new terminal after steps 1 and 2 — a `km serve` already running keeps the old PATH.

3. **Install the VS Code extension** — a link to the folder, so it updates with the repo:

   ```bash
   ln -s ~/knowledge-manager/vscode ~/.vscode-server/extensions/km-review-0.1.0   # VS Code in WSL
   # outside WSL: ~/.vscode/extensions/km-review-0.1.0
   ```

   Then *Developer: Reload Window*.

4. **In the repository you want to review, once:** `km init` writes `.km/config.json` with
   nothing tracked.

5. **Open the panel** from inside that repository — `km serve`, then
   <http://127.0.0.1:8431> — or, in VS Code, **km: abrir o painel da chancela**
   (`Ctrl+Alt+P`). The first time, the **Arquivos** tab is where you tick the files and folders
   to review; `km serve --port 8451` runs a second panel next to the first.

## The chancel

**A copy of each file, as you last endorsed it, kept in `refs/km/chancela`.** Reviewing is
comparing that copy with the file on disk; endorsing a passage is writing that passage into
the copy. Nothing is stored per passage — no identity, no anchor, no hash — and the ref is
written with plumbing and never checked out, so your branch, your index and your open files
are untouched.

Which documents it covers is chosen in the panel's **Arquivos** view: a tree of the
repository's Markdown files where a ticked folder takes the files created in it later
(`+ novos`), a file can be ticked on its own, and an exception leaves one out. It is stored
in `.km/config.json` as three lists — `folders`, `files`, `except` — and nothing outside
them appears. Untracking keeps the chancel, so the file is *paused*, not forgotten. The
design: [docs/tracked-files.md](docs/tracked-files.md).

## The panel

```bash
km serve          # binds 127.0.0.1:8431 — Ctrl-C ends it
```

The document, whole, from top to bottom. **Text that did not change is just text**: one
column, full width, no buttons — headings cut nothing. **Each change is one passage**:
everything that moved between two unchanged stretches — a heading, a table and a
paragraph in a row are one thing to read — placed where it happened, in three columns:

| | |
|---|---|
| **the chancel** | the passage as you endorsed it, read-only, with what differs marked. A selector swaps it for any branch or commit |
| **now** | the file today, editable, with what differs marked live as you type |
| **what to do** | one set of verdicts for the passage |

**To approve less than the passage, select it.** In the second column, select a paragraph,
a table row, or a few words: a bar offers *Aprovar seleção* and *Reverter seleção*, and only
the changes inside the selection are taken — like staging half a hunk in a code review. A
selection that touches part of a word takes the word. Underneath, the engine still works in
Markdown blocks; the page turns a selection over the passage into "this part of this block".

How much is left is a **percentage of the content**: the characters still to decide over the
characters the file would have if everything were approved. Not a count of blocks or
changes — a one-word fix and a new section are not "one" each.

The text is edited in [CodeMirror](https://codemirror.net/) with a **live preview**, the
model Obsidian uses: the editor always holds the file's exact bytes, and formatting is only
a display layer. Headings, bold, links, lists, task boxes and the ⚠️ ❓ 🚫 boxes show
formatted, with their markers hidden except on the line with the cursor; a hard-wrapped
paragraph reads as one flowing paragraph until you click into it. Nothing is rewritten on
save — which is why a WYSIWYG editor was not used: it would rewrite the file and every save
would show changes nobody made. Each change is CodeMirror's own side-by-side comparison, so
the two columns stay aligned while you type.

**Formatado | Código**, in the top bar, switches every editor on the page between that live
preview and the plain source: all markers visible, the real line breaks, tables as their
`|` lines, in a monospace font so the columns align. Only the display changes — the cursor,
Ctrl+Z and anything typed and not yet saved stay put — and the browser remembers the choice.

**Tables show as a grid**, with long cells wrapping. Clicking a cell turns the table back into
source at that line. On hover, each row has **+** (a row below) and **×** (remove it), and each
header cell has **+** (a column to the right) and **×** (remove it); every control rewrites the
table's lines in the file. The header, the separator row and the last column cannot be
removed.

| | |
|---|---|
| **Aprovar** | the passage goes into the chancel |
| **A validar…** | writes `> ❓ **a confirmar até …**` right after the passage, and chancels both: the half-chancel is a visible line, not a hidden state |
| **Reverter** | puts the chancel's text back in the file |
| **⚠️ · 🚫** | start a reservation after the passage, in the agreed form, for you to finish |

On a long passage the actions **stay on screen** under the top bar while you scroll it, and
leave with the passage.

The whole second column is always editable — click and type. The action column offers
**Salvar no arquivo** when there is something to save; Ctrl+S saves, Esc discards. A save is
located by what the text said, not by line number, so a line an agent inserted above does not
make you write over someone else's paragraph; if your text is no longer in the file, the save
is refused and the page shows what is there now. **⚠️ ❓ 🚫 at the top** insert a
reservation at the cursor, on its own line.

A block is identified by its content, never its position: a page that asks to approve a
block after the file moved gets a refusal, not a different block.

Keyboard: `j` `k` move between changes, `a` approves the change in focus.

**abrir no VS Code**, in the document header, runs `code <file>` (or `code -g <file>:<line>` at the change in focus) — under WSL, Windows VS Code in WSL mode; `code` must be on the PATH of whoever started `km serve`.

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
km init                          # creates .km/config.json with nothing tracked
km pendente                      # what changed since the chancel, and what never had one
km pendente --novos              # tracked files that never had a chancel
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

Python 3.11+. No third-party Python dependencies. The panel's CodeMirror is bundled once
into `km/vendor/cm.js` and served by `km serve` — no network and no npm at run time; the
recipe to rebuild it is in [tools/build-cm/](tools/build-cm/README.md). Installing: [Getting started](#getting-started).

## Documentation

- [docs/chancel.md](docs/chancel.md) — the model, with the measurements behind it.
- [docs/tracked-files.md](docs/tracked-files.md) — which documents the chancel covers.
- [docs/live-preview.md](docs/live-preview.md) — how the panel edits without changing a byte.
- [docs/roadmap.md](docs/roadmap.md) — what comes next, and what is deliberately out of
  scope.

## Status

The chancel is in use. Everything it holds lives in `refs/km/chancela` — `git update-ref -d
refs/km/chancela` undoes it completely — and the only file written in the target repository
is `.km/config.json`.
