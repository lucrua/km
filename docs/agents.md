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
- Notes for people and agents are written **in the documents**, as one-line marks: 📌 ❓ 💬
  (below).

The repository uses km if `.km/config.json` exists at its root. `km` is on the PATH; if it
is not, it is `~/knowledge-manager/bin/km`. Every command works from any folder inside the
repository.

```bash
km pendente           # what changed since the chancel, per file, and what never had one
km pendente --json    # the same, for a script: file, pct, changes, vanished marks, overdue ❓
```

km prints in the language of the documents. `pendente`, `marcas` and `chancela` also answer
to `pending`, `marks` and `chancel`.

## Hard rules

1. **Never approve.** `km chancela` is the author's act. Do not run it — not with `--all`,
   not with `--from` — unless the author explicitly tells you to, for named files.
2. **Never write `refs/km/chancela`.** No `git update-ref`, `commit-tree`, `push` or
   `branch` on it, no `git update-ref -d`. Only `km` writes it.
3. **Never edit `.km/config.json` by hand for a move** — `km mv` rewrites it. Change which
   files are tracked only when the author asks; the panel's *Arquivos* view is the author's
   tool for that.
4. **Never run `km restore`** unless asked: it overwrites the file with the reviewed text
   and discards whatever changed since, including other people's edits.
5. **Never delete or rewrite a mark** except as this guide says for each kind.
6. Leave `km serve` alone: do not start, stop or restart the author's panel.

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
- **Moving text between files** (splitting one document, merging two, moving a section):
  review does not follow a passage across files. The text shows as **new** in the destination
  and **removed** in the source, and the author reviews both. That is correct; do not try to
  avoid it.
- **Carry the marks with their passage.** A 📌 ❓ 💬 stays directly after the passage it
  annotates, in the file the passage ends up in. Never drop one along the way.
- The source then reports *marca removida* (a mark vanished) for each mark that left it.
  List them in your summary with where each one went.

## The marks

One line each, a blockquote starting at column 0, in exactly these forms. Shown together
here; in a document each is its own paragraph, with a blank line before and after:

```markdown
> 📌 **to_do · 2026-09-24** — what to do
> ❓ **to_validate by 2026-10-01** — what to confirm, by that date
> 💬 a note for whoever reads this passage later
```

The regular expressions (the same in `km/chancela.py` and `km/painel/marcas.js`):

```text
^> 📌 \*\*to_do · (\d{4}-\d{2}-\d{2})\*\* — (.+)$
^> ❓ \*\*to_validate by (\d{4}-\d{2}-\d{2})\*\* — (.+)$
^> 💬 (\S.*)$
```

A line in any other shape is an ordinary quote and means nothing to km. The dash is an em
dash (`—`), the dot in `to_do · ` is a middle dot (`·`), dates are `YYYY-MM-DD` in local time.
A mark whose text is still `add your comment here` is a placeholder and `km lint` reports it.

To find them:

```bash
km marcas                    # 📌 and ❓ in every Markdown file git knows
km marcas --todas            # also 💬
km marcas --tipo to_do       # one kind: to_do, to_validate or comment
km marcas --json             # [{file, line, kind, date, text, overdue}]
km lint                      # tracked files: ❓ past its date, placeholders, vanished marks
```

`km marcas` reads **every** Markdown file git knows about, committed or not, ignored ones
excepted — tracked by km or not. `km lint` reads only tracked files.

### 📌 to_do — work for you

When asked to "handle the to_dos" (or one of them):

1. Do what it says.
2. When it is **fully** done, delete the 📌 line (and one of the blank lines around it). The
   author sees the deletion flagged as *marca removida*; that is intended — it is how they
   check your work. In a file km does not track nothing is flagged, so your report is the
   only record.
3. When you **cannot** do it — ambiguous, blocked, needs a decision, out of scope — or did
   only part of it: leave the 📌 line exactly as it is and add a 💬 right after it saying
   what is missing:

   ```markdown
   > 📌 **to_do · 2026-09-20** — trocar a tabela pela do contrato

   > 💬 not done: the contract has two tables (§4 and annex B); which one?
   ```

4. Report each one as `file:line — what you did`, or `file:line — not done: why`.

Write a 📌 yourself only when the author asks you to leave work for a later agent.

### ❓ to_validate — a question for the author

It waits for the author, by its deadline. Do not answer it by deleting it, and never change
its line — not the date, not the text.

- If you find evidence either way, add a 💬 right after it, with the source:
  `> 💬 evidence: <what, and where — file, section, commit>`.
- Report the overdue ones (`"overdue": true` in `km marcas --json`) in your summary.

### 💬 comment — for future readers

Keep it. When you move or rewrite the passage it annotates, it goes along, right after that
passage. Edit its text only if the author asks.

### Adding your own

When you are unsure of something you wrote, say so in the document:

- a question the author must settle: `> ❓ **to_validate by <today + 7 days>** — <question>`;
- context the next reader needs: `> 💬 <note>`.

Put it right after the passage, exact form, local date (`date +%F`, and
`date -d '+7 days' +%F`). Mention each one in your summary.

## Before you finish

```bash
km pendente         # everything you changed shows here; a pure km mv adds nothing
km lint             # no placeholder left; every vanished mark is one you can explain
km marcas --todas   # the to_dos you handled are gone; the rest have a 💬 saying why
```

Then write a summary with:

- moves (`from → to`) and deletions;
- vanished marks: file, the mark, and where it went (or why it was removed);
- to_dos handled (`file:line — what you did`) and not handled (`— why`);
- ❓ and 💬 you added, and overdue ❓ you found.

## For the author: the snippet

Paste this into another repository's `CLAUDE.md` or `AGENTS.md`:

```markdown
This repository's documents are reviewed with km (`.km/config.json`). Before moving,
deleting or rewriting any Markdown file, or handling 📌 to_do / ❓ to_validate marks,
read `~/knowledge-manager/docs/agents.md` and follow it. Never run `km chancela`.
```
