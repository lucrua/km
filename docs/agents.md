# Working in a repository that km tracks — a guide for AI agents

You are editing documents that a person reviews with `km`. Follow this guide so that your
changes reach them as changes to review, nothing they reviewed is lost, and nothing is
approved in their name. It is short: read all of it before you start.

## What km is

- The author **reviews** Markdown documents. Reviewing a passage is called *chancela*
  (the chancel).
- The reviewed copy of each file lives in the git ref `refs/km/chancela`, never checked out.
  Anything on disk that differs from it is *pending*: the author sees it in a local panel
  and approves or reverts it.
- `.km/config.json` says which files are reviewed (*tracked*): three lists, `folders`,
  `files` and `except`.
- Notes for people and agents are written **in the documents**, as one-line marks: 📌 💬
  (below).

The repository uses km if `.km/config.json` exists at its root. `km` is on the PATH; if it
is not, it is `~/knowledge-manager/bin/km`. Every command works from any folder inside the
repository.

```bash
km pendente           # what changed since the chancel, per file, and what never had one
km pendente --json    # the same, for a script: file, pct, changes, vanished marks
```

km prints in the language of the documents. `pendente`, `marcas` and `chancela` also answer
to `pending`, `marks` and `chancel`.

## Hard rules

1. **Never approve.** `km chancela` is the author's act. Do not run it — not with `--all`,
   not with `--from` — unless the author explicitly tells you to, for named files.
2. **Never forget.** `km forget --apply` rewrites the chancel's history and deletes reviewed
   text for good — the same rule as `km chancela`: only when the author tells you to, for
   files they name. Without `--apply` it only shows what would happen; that you may run.
3. **Never write `refs/km/chancela`.** No `git update-ref`, `commit-tree`, `push` or
   `branch` on it, no `git update-ref -d`, no `git filter-repo`. Only `km` writes it —
   `km chancela`, `km mv` and `km forget`.
4. **Never push `refs/km/*`** — not by name, not with `git push --mirror` (which sends every
   ref), not with `--no-verify` past the hook that refuses it. The chancel keeps the full
   text of files that were never committed to any branch. Push branches and tags by name.
5. **Never edit `.km/config.json` by hand for a move** — `km mv` rewrites it. Change which
   files are tracked only when the author asks; the panel's *Arquivos* view is the author's
   tool for that.
6. **Never run `km restore`** unless asked: it overwrites the file with the reviewed text
   and discards whatever changed since, including other people's edits.
7. **Never delete or rewrite a mark** except as this guide says for each kind.
8. Leave `km serve` alone: do not start, stop or restart the author's panel.
9. **Never edit the project registry** (`~/.config/km/projects.json`). Run
   `km projects add <repository root>` only when the author tells you to — and never
   `km projects rm`.

## Moving and renaming

Always `km mv`, never plain `git mv` or `mv`, for anything under a tracked folder or any
Markdown file. A plain move leaves the review behind: the moved file shows as never
reviewed and the old one as deleted.

```bash
km mv docs/a.md guides/a.md --dry-run   # what would happen; writes nothing
km mv docs/a.md guides/a.md             # a file
km mv docs guides                       # a folder, with everything under it
```

`km mv` runs `git mv` (the rename is staged; commit as you normally would), moves the
reviewed copy to the new path, and rewrites the config entries. The content does not
change, so a pure move shows **nothing** to approve. Uncommitted edits move with the file
and stay pending.

- Paths are relative to the repository root. The destination must not exist; missing
  parent folders are created.
- If it says the source is not in git, run `git add <source>` and try again.
- If it says the destination still has a chancel, a deleted file there is waiting for the
  author's approval: pick another name or tell the author.
- After moving, fix links that pointed to the old paths. Those edits show as changes to
  review; that is expected.

## Deleting, splitting, merging

- **Deleting a tracked file** is allowed (`git rm <file>`). The author sees it as a pending
  deletion and approves it. List every deleted file in your summary.
- **Deleting is not forgetting.** Every version the author approved stays in the chancel's
  history. When the author wants a file's text gone from `.git` — a private draft, a
  repository about to be handed over — run `km forget <path>` (a dry run) and show them what
  it lists; `km forget <path> --apply --prune` only when they say so. `km lint` points at
  the files whose text exists only in the chancel.
- **Moving text between files** (splitting one document, merging two, moving a section):
  review does not follow a passage across files. The text shows as **new** in the destination
  and **removed** in the source, and the author reviews both. That is correct; do not try to
  avoid it.
- **Carry the marks with their passage.** A 📌 or 💬 stays directly after the passage it
  annotates, in the file the passage ends up in. Never drop one along the way.
- The source then reports *marca removida* (a mark vanished) for each mark that left it.
  List them in your summary with where each one went.

## The marks

One line each, a blockquote starting at column 0, in exactly these forms. Shown together
here; in a document each is its own paragraph, with a blank line before and after:

```markdown
> 📌 **to_do · 2026-09-24** — a review point: what the author wants changed or answered
> 💬 a caveat on the passage right before it
```

The regular expressions (the same in `km/chancela.py` and `km/painel/marcas.js`):

```text
^> 📌 \*\*to_do · (\d{4}-\d{2}-\d{2})\*\* — (.+)$
^> 💬 (\S.*)$
```

A line in any other shape is an ordinary quote and means nothing to km. The dash is an em
dash (`—`), the dot in `to_do · ` is a middle dot (`·`), dates are `YYYY-MM-DD` in local time.
A mark whose text is still `add your comment here` is a placeholder and `km lint` reports it.

There is no other mark. `> ❓ **to_validate by …**` was retired: do not write one, and if you
find one left in a document, leave it as it is and tell the author.

To find them:

```bash
km marcas                    # 📌 in every Markdown file git knows
km marcas --todas            # also 💬
km marcas --tipo comment     # one kind: to_do or comment
km marcas --json             # [{file, line, kind, date, text}]
km lint                      # tracked files: placeholders, vanished marks
```

`km marcas` reads **every** Markdown file git knows about, committed or not, ignored ones
excepted — tracked by km or not. `km lint` reads only tracked files — and, run without a
file, `.km/config.json` (see [Before you finish](#before-you-finish)).

### 📌 to_do — a review point from the author

The author read the document and left a 📌 where something is wrong, unclear, missing or
in doubt. It is their voice, and work for you. When asked to "handle the to_dos" (or one of
them), each 📌 ends in one of three ways.

**1. Done.** Put the answer **in the text**: correct the passage, add what was missing,
answer the question where a reader will look for it. Then delete the 📌 line (and one of the
blank lines around it). Whoever reads the finished document must find the answer in the
document itself — never leave a note saying the point was handled. The author sees the
passage you changed with the deletion flagged beside it as *marca removida*; that is
intended — it is how they check your work. In a file km does not track nothing is flagged,
so your report is the only record.

**2. Nothing to change.** The text is right as it stands, or the point is already covered:
delete the 📌 line, leave the text alone, and say why in your report. The author sees a mark
removed with no change beside it — the reason is what they will look for.

**3. It needs the author.** Ambiguous, blocked, a decision that is theirs to make, a point
you disagree with, or one you could only do part of: do not delete the 📌. Append
` → <your question, proposal, or what is missing>` to the end of **the same line**, and take
it up in the conversation:

```markdown
> 📌 **to_do · 2026-09-20** — trocar a tabela pela do contrato → the contract has two tables (§4 and annex B); which one?
```

A 📌 with a `→` is waiting for the author. This is the only place you write to the author
in the document, and only on a point they raised.

- Each round, **rewrite** what follows the `→` with where the question stands now. One line,
  never a thread: the discussion lives in the conversation.
- When it is settled, finish as in 1 or 2.
- The author may answer in the document instead: they rewrite the 📌 and take the `→` out.
  It is yours again.
- When sweeping, skip a 📌 that already has a `→`, unless the author answered it in the
  conversation.

Report each one as `file:line — what you did`, `file:line — nothing to change: why`, or
`file:line — waiting: the question`.

Write a 📌 yourself only when the author asks you to leave work for a later agent. A
question of your own goes in the conversation, not in the document.

### 💬 comment — a caveat on the passage

A 💬 qualifies the passage right before it: the author is not sure of it, it was not checked,
or it may change (`não tenho certeza disso`, `não revisado item a item`).

- **Reading one:** that passage is not settled. Do not follow it to the letter, and do not
  build on it without checking it against the source — the code, the data, the author. Say
  in your report when you relied on a passage that carries a 💬.
- **Keep it.** Never delete a 💬 or edit its text unless the author asks — not even when you
  checked the passage and it is right; say so in your report and let the author remove it.
  When you move or rewrite the passage it annotates, it goes along, right after that passage.
- **Writing one:** only to flag uncertainty in something **you** wrote — a claim you could
  not verify, a number you inferred. Put it right after the passage, in the exact form, and
  mention each one in your report. Not for evidence, progress notes, replies or questions:
  those go in the conversation, or after the `→` of the 📌 they answer.

## Pushing, migrating, handing a repository over

- Push branches and tags **by name**: `git push <remote> <branch>`, `git push <remote> --tags`.
  `git push --mirror` sends every ref, the chancel included. Where the author ran
  `km install-hooks`, a pre-push hook refuses it with `km: push recusado`; then push by name —
  never `--no-verify`.
- A copy of `.git` carries the chancel even when no push does: a zip, a backup, a synced
  folder, an import into another server. Before a repository leaves the machine, tell the
  author, run `km lint` and list what it says exists only in the chancel. Forgetting it is the
  author's call (rule 2).

## Before you finish

```bash
km pendente         # everything you changed shows here; a pure km mv adds nothing
km lint             # no placeholder left; every vanished mark is one you can explain
km marcas --todas   # the to_dos you handled are gone; the rest have a → saying what is missing
```

`km lint` also reports, as the author's to settle and not yours to fix:

- `tem chancela e não está mais no disco` — a deleted file still waiting for the author to
  approve its deletion. With `o texto só existe nela`, it was never committed to any branch:
  only `km forget` takes that text out of `.git`.
- under `.km/config.json`, a `folders` or `files` entry with nothing on disk.

Then write a summary with:

- moves (`from → to`) and deletions;
- vanished marks: file, the mark, and where it went (or why it was removed);
- to_dos: handled (`file:line — what you did`), removed with nothing to change (`— why`),
  and waiting for the author (`— the question`);
- 💬 you added, and passages carrying a 💬 that you relied on;
- what `km lint` said exists only in the chancel, and stale config entries — for the author.

## For the author: the snippet

Paste this into another repository's `CLAUDE.md` or `AGENTS.md`:

```markdown
This repository's documents are reviewed with km (`.km/config.json`). Before moving,
deleting or rewriting any Markdown file, or handling 📌 to_do marks,
read `~/knowledge-manager/docs/agents.md` and follow it. Never run `km chancela` or
`km forget --apply`, and never push `refs/km/*`.
```
