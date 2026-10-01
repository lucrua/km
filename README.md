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
   when you start `km serve` from a terminal (adjust the Windows user name; `km boot` in
   step 5 finds it on its own):

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

4. **In each repository you want to review, once:** `km init` writes `.km/config.json` with
   nothing tracked.

5. **Start the panel with the machine, for every repository** — `km boot` shows what it would
   do, `km boot --apply` installs it as a systemd user unit, like the esteira's; after
   updating km, run `km boot --apply` again. Details: [docs/boot.md](docs/boot.md). Without
   it, `km serve` in a terminal does the same until Ctrl-C. Then <http://127.0.0.1:8431>. Started inside a repository that uses km, it adds it to your
   list of projects and opens on it; add the others with `km projects add <path>` or in the
   panel's **Projetos** view (its *km init se ainda não tiver* box does step 4 for you). In
   VS Code, **km: abrir o painel da chancela** (`Ctrl+Alt+P`) adds the window's repository and
   opens the panel on it. The first time, a project's **Arquivos** tab is where you tick the
   files and folders to review. The model: [docs/projects.md](docs/projects.md).

6. **Working with AI agents:** point them to [docs/agents.md](docs/agents.md) — how to move
   files, handle the marks and never approve for you. It ends with the three lines to paste
   into a repository's `CLAUDE.md` or `AGENTS.md`.

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

**The chancel is part of `.git`, and so is everything you approved.** A file you approve is
stored in the ref even if it was never committed — and deleting it later keeps every
version it had. The ref is not shown by `git branch`, but it leaves with `git push --mirror`
and with any copy of `.git` (a zip, a backup, a synced folder). So: `km chancela` and the
panel warn when the file is not in git; `km install-hooks` adds a pre-push hook that refuses
to send `refs/km/*`; and `km forget <path>` takes a file out for good — from every commit of
the ref, from `.km/config.json` and, with `--prune`, from `.git`'s objects. Details:
[docs/chancel.md](docs/chancel.md#forgetting-a-file).

## The panel

```bash
km serve          # binds 127.0.0.1:8431, from any folder — Ctrl-C ends it
```

**One panel for every project.** The repository name at the left of the top bar is a
switcher: it lists your projects with how much each has to approve (`12% a aprovar`, `em
dia`) and changes the whole page — rail, summary, Arquivos — to the one you pick, asking
first if you have text not yet saved. The address carries the project (`?projeto=<name>`),
so a reload, a bookmark or the VS Code extension land on it, and the browser remembers the
last one. The third view, **Projetos**, is the list: name, path, what is left and how many
files each tracks; a row opens its project, **×** takes it off the list (the repository, its
config and its chancel stay as they are), and a path at the bottom adds one — with *km init
se ainda não tiver* ticked, a repository that never used km. The list lives in
`~/.config/km/projects.json`; the rules are in [docs/projects.md](docs/projects.md).

The document, whole, from top to bottom. **Text that did not change is just text**: one
column, full width, no buttons — headings cut nothing. **Each change is one passage**:
everything that moved between two unchanged stretches — a heading, a table and a
paragraph in a row are one thing to read — placed where it happened, in three columns:

| | |
|---|---|
| **the chancel** | the passage as you endorsed it, read-only, with what differs marked. A selector swaps it for any branch or commit |
| **now** | the file today, editable, with what differs marked live as you type |
| **what to do** | one set of verdicts for the passage |

**The second column can read from elsewhere.** The chancel is one for every branch and
worktree of the repository, so **lendo**, in the top bar, puts another source on the right
against the same chancel: this folder, another **worktree** of the repository — its files on
disk, uncommitted work included, with every action writing there — or a **branch no worktree
has checked out**, read from its last commit, where a passage can only be approved whole (and
undone): there is no file to write to. The files listed are this project's `.km/config.json`
applied to that source. Approving from any of them moves the one chancel, so a file here that
differs from what you approved there shows as pending here.

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
a display layer. Headings, bold, links, lists, task boxes and the 📌 ❓ 💬 boxes show
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
| **Aprovar** | the passage goes into the chancel — with any mark written in it |
| **Reverter** | puts the chancel's text back in the file |
| **📌 · ❓ · 💬** | write a [mark](#the-convention) right after the passage, as a block of its own, with `add your comment here` selected so what you type replaces it. Nothing is approved: the mark is your text, saved like any edit |

**An approval can be undone.** Its message carries *↶ desfazer*, and **↶ Desfazer
aprovação** in the top bar (or Ctrl+Z outside the text) takes back the last ones of the
session, newest first — a whole file approved by mistake goes back to *novo*. Undoing is a new
commit on the ref that puts back the chancel the file had before, so approvals of other files
made since stay; it is refused if that file was approved again after, until the newer one is
undone. The file on disk is not touched.

On a long passage the actions **stay on screen** under the top bar while you scroll it, and
leave with the passage.

The whole second column is always editable — click and type. The action column offers
**Salvar no arquivo** when there is something to save; Ctrl+S saves, Esc discards. A save is
located by what the text said, not by line number, so a line an agent inserted above does not
make you write over someone else's paragraph; if your text is no longer in the file, the save
is refused and the page shows what is there now. **📌 ❓ 💬** insert a mark after
the block the cursor is in, the same way — on a change they are always in its action cell; on
unchanged text they appear there while the cursor is in the block.

A block is identified by its content, never its position: a page that asks to approve a
block after the file moved gets a refusal, not a different block.

**The left rail is a tree** of the files under review and their folders; a chain of
single-folder folders is one row (`descoberta/guides`). Each row says what is left — `21%` to
approve, `✓` up to date, `novo` never had a chancel, ❓ an overdue mark — and a folder shows `●N`
files to approve below it. Folders with something to approve start open; the ones you open or
close stay that way. It takes the keyboard like any tree (↑ ↓ ← → Enter Home End). **Drag its
right edge to resize it** (or ← → on the edge); a double-click resets it, and the browser
remembers the width.

Keyboard: `j` `k` move between changes, `a` approves the change in focus.

**abrir no VS Code**, in the document header, runs `code <file>` (or `code -g <file>:<line>` at the change in focus) — under WSL, Windows VS Code in WSL mode; `code` must be on the PATH of whoever started `km serve`. **copiar caminho**, beside it, copies the file's path in the repository; Shift+click, the full path.

The server does not stay up: you start it when you sit down to review. Inside VS Code, the
command **km: abrir o painel da chancela** (`Ctrl+Alt+P`) opens it on the window's
repository in your default browser, starting it if no panel answers on the port; a server the
extension started dies with that window — for every project.

## The convention

Marks live **in the document**, one line each, as a blockquote, because a note only the tool
can see is a note the next agent rewrites without knowing it existed:

```markdown
> ❓ **to_validate by 2026-10-01** — add your comment here
> 💬 add your comment here
> 📌 **to_do · 2026-09-24** — add your comment here
```

| | for | the date |
|---|---|---|
| ❓ **to_validate** | something to confirm by a deadline | the deadline — the panel writes today + 7 days, local time; `km lint` reports it once passed |
| 💬 comment | whoever reads the passage later | none |
| 📌 **to_do** | an agent, to find and address | the day it was written |

The forms are exact, so an agent can grep for them:

```text
^> ❓ \*\*to_validate by (\d{4}-\d{2}-\d{2})\*\* — (.+)$
^> 📌 \*\*to_do · (\d{4}-\d{2}-\d{2})\*\* — (.+)$
^> 💬 (\S.*)$
```

— or run `km marcas`. A line in any other shape is an ordinary quote. No mark blocks a
chancel: approving the passage takes its marks with it.

One ref and a writing convention, not a parallel store of comments. A mark that
**disappears** from a rewrite is flagged on its own, apart from ordinary edits, because that
is the change designed to pass unnoticed.

## The command line

The panel is where reviewing happens; these are the same things in a terminal, and how a
script or an agent reads the state.

```bash
km init                          # creates .km/config.json with nothing tracked
km projects                      # the projects the panel shows, and what each has to approve
km projects add ~/repo [--init]  # add a repository root to the panel; --init runs km init first
km projects rm repo              # take it off the list — the repository is not touched
km pendente                      # what changed since the chancel, and what never had one
km pendente --novos              # tracked files that never had a chancel
km chancela regras.md --hunk 2   # change 2 into the ref; `--hunk 2.1` only its first block
km chancela regras.md --all      # the file as it stands today
km restore  regras.md --hunk 2.1 # put the chancelled text of that block back on disk
km mv docs guides                # git mv, and the chancel and the config entries follow; --dry-run
km forget rascunho               # what forgetting it would rewrite; --apply does it, --prune also runs git gc
km lint                          # ❓ past its date · a placeholder mark · a mark that vanished · a config entry with nothing on disk
km marcas                        # ❓ and 📌 in every Markdown file git knows; --todas adds 💬, --tipo, --json
km quando   regras.md --trecho "colunas"   # when that passage last had a chancel
km baseline regras.md            # the chancelled copy, for a diff's left-hand column
km boot [--apply]                # the panel starts with the machine (systemd user unit)
km install-hooks                 # one line after every commit, and a pre-push that refuses refs/km/*
```

`chancela`, `pendente`, `marcas` and `quando` also answer to `chancel`, `pending`, `marks` and
`when`; `mv` answers to `mover`; `forget` to `esquecer`; `projects` (`add`, `rm`) to `projetos` (`adicionar`,
`remover`). Every command except `projects` and `serve` works on the repository you are in. `km marcas` reads every Markdown file git knows about, tracked or not — a to-do is
written for whoever passes by. `--json` gives `[{file, line, kind, date, text, overdue}]`.

**Moving a reviewed file is `km mv`, not `git mv`.** The chancel is keyed by path: after a
plain `git mv` the file reads as never reviewed and the old path as a deletion. `km mv
<from> <to>` takes a file or a folder, runs `git mv`, rewrites the entries of
`.km/config.json` equal to or under `<from>`, and re-keys the chancel in one commit on the
ref. The content is untouched, so a pure move leaves nothing to approve; edits not yet
committed move along and stay pending. A move never untracks a file. It refuses `..`,
absolute paths, a destination that exists, and a source git does not know.

## What git gives for free

| Question | Answer |
|---|---|
| what is pending | `git diff refs/km/chancela -- <file>` |
| word-level diff, which is what prose needs | `git diff --word-diff --word-diff-regex='[^[:space:]]+'` |
| **when did this passage last have a chancel** | `git log -L '/## Heading/,/## Next/:<file>' refs/km/chancela` |
| why you endorsed it | the commit message on the ref |
| the whole review history | `git log refs/km/chancela` |

## In the editor

The extension in [`vscode/`](vscode/), on a Markdown file the chancel covers:

- a line at the top of the file — how much is left to approve, or that it never had a
  chancel — and an amber left border on each pending passage;
- the status bar shows the same %, also when the file is open in a custom editor such as
  Markdown Editor, where the top line and the border cannot be drawn;
- `Ctrl+Alt+K` approves or reverts the change under the cursor — the same verdicts as the
  panel's; a command opens the diff against `km baseline`;
- `Ctrl+Alt+P`, the top line or the status bar adds the repository to the panel's projects
  (when it has `.km/config.json`) and opens the panel on it in your default browser, starting
  `km serve` if none answers on the port (from WSL, the port is forwarded). A server it
  started lives as long as the window. The marks are written in the panel.

## What it does not do

- It decides nothing. No LLM call, no network, no telemetry.
- It does not write in your documents except when you ask: `restore`, `mv`, the marks, and
  editing a passage in the panel.
- It does not lock or coordinate sessions. Concurrency is handled where it already is: the
  editor refuses stale writes, git merges, and the panel shows both texts when the file
  moved under you.

## Requirements

Python 3.11+. No third-party Python dependencies. The panel's CodeMirror is bundled once
into `km/vendor/cm.js` and served by `km serve` — no network and no npm at run time; the
recipe to rebuild it is in [tools/build-cm/](tools/build-cm/README.md). Installing: [Getting started](#getting-started).

## Documentation

- [docs/boot.md](docs/boot.md) — the panel starting with the machine (`km boot`).
- [docs/agents.md](docs/agents.md) — the guide to hand an AI agent working in a repository
  km tracks.
- [docs/chancel.md](docs/chancel.md) — the model, with the measurements behind it.
- [docs/tracked-files.md](docs/tracked-files.md) — which documents the chancel covers.
- [docs/projects.md](docs/projects.md) — one panel for every repository: the registry and its
  rules.
- [docs/live-preview.md](docs/live-preview.md) — how the panel edits without changing a byte.
- [docs/roadmap.md](docs/roadmap.md) — what comes next, and what is deliberately out of
  scope.

## Status

The chancel is in use. Everything it holds lives in `refs/km/chancela` — `git update-ref -d
refs/km/chancela` undoes it completely — and the only file written in the target repository
is `.km/config.json`. The list of projects is yours, outside every repository:
`~/.config/km/projects.json`.
