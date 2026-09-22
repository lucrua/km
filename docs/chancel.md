# The chancel: a reviewed copy, kept in a git ref

Status: **built, current.** Supersedes `docs/blocks.md`, which stored review state per
block; git history keeps it. Written 2026-09-22 from a working session and implemented the
same day, with every number below measured on a real repository.

## What the chancel is

**A copy of each tracked file, as you last endorsed it, stored in `refs/km/chancela`.**

Reviewing is comparing that copy with the file on disk. Approving a passage means writing
that passage into the copy. There is nothing else: no identity per block, no anchors, no
hashes to maintain.

Blocks were a storage decision wearing the costume of a model decision. In practice a
"block" is whatever hunk the diff offered you at that moment, so granularity is an outcome
of reviewing, not an input to it.

## Why a ref and not a branch

`refs/km/chancela` is written with plumbing — `hash-object`, `mktree`, `commit-tree`,
`update-ref` — and is **never checked out**. Verified on the target repository: creating and
advancing it left the current branch untouched and the working tree with zero changes.

A branch would show up in `git branch`, invite a checkout, and tangle with the feature
branches already in use. A ref under `refs/km/` is invisible to the normal flow, interferes
with no merge, and disappears with one command.

## What git gives for free

| Question | Answer |
|---|---|
| what is pending | `git diff refs/km/chancela -- <file>` |
| word-level diff, which is what prose needs | `git diff --word-diff --word-diff-regex='[^[:space:]]+'` |
| **when did this passage last have a chancel** | `git log -L '/## Heading/,/## Next/:<file>' refs/km/chancela` |
| what changed in that chancel | the same command with `-1` |
| why I endorsed it | the commit message on the ref |
| the whole review history | `git log refs/km/chancela` |

All verified. The `-L` form is the important one: it answers a per-passage question with no
per-passage storage, delimiting by the text of the heading rather than by any identifier.

## The act is per passage

The ref holds whole files; the gesture is per hunk. What lands in the ref is *the previous
chancel plus the hunks you accepted* — `git add -p` semantics. Accepting everything and
accepting one paragraph are the same operation at different scales.

## Caveats live in the document

Measured on the author's other repository: review notes are written as **visible
blockquotes**, not hidden HTML comments — the whole repository holds two HTML comments, both
tool markers. The practice is right, for reasons worth keeping: an agent reads a blockquote
natively with no tooling, a human opening the file sees the reservation, and the note moves
with the text when the paragraph is edited.

So there is **one ref and a writing convention**, not a parallel store of comments. Three
marks, because each changes what happens next:

```markdown
> ⚠️ **sem certeza** — entra na chancela e continua visível
> ❓ **a confirmar até AAAA-MM-DD** — vira pendência com data
> 🚫 **discordo** — bloqueia a chancela deste trecho até ser resolvido
```

"Approved with a reservation" is therefore a passage that is **in the chancel and carries a
`⚠️` line**. That is what replaces the second ref an earlier draft proposed: the reservation
is visible to every reader instead of hidden in a tool.

### The failure this creates, and the mechanism against it

An agent rewrites the paragraph and drops the caveat. Nothing lies, but the tool would then
see a fully endorsed passage.

It is detectable: the chancelled copy **had** the caveat, so its removal is a change like any
other and shows in the diff. The reviewer decides, as with anything else. The tool's job is
to make that specific change impossible to wave through — a removed `⚠️`/`❓`/`🚫` line gets
its own mark in the review, separate from ordinary edits.

## What this deletes from the current implementation

- keys per block, heading paths, per-block hashes
- re-anchoring, orphans, the fallback chain
- the vouched body stored in `.km/` — the git blob is already content-addressed storage
- `km baseline` assembling a document — becomes `git show refs/km/chancela:<file>`

Table canonicalisation survives, no longer to protect a hash but to let the diff ignore a
cosmetic re-alignment.

## The commands

| | |
|---|---|
| `km pendente [<arquivo>]` | what changed since the chancel, and what never had one. `--json` feeds the editor |
| `km chancela <arquivo> --hunk <n\|título>` | write that passage into the ref. Repeatable; `--all` takes the file as it is |
| `km restore <arquivo> --hunk <n\|título>` | put the chancelled text back on disk — the only command that writes a document |
| `km lint [<arquivo>]` | the convention: a `🚫` pending, a `❓` past its date, a caveat that vanished |
| `km quando <arquivo> --trecho <título>` | when this passage last had a chancel (`git log -L`) |
| `km baseline <arquivo>` | the chancelled copy, for a diff's left-hand column |
| `km status --short` | the line after every commit: files in step, passages moved, files with no chancel |

`chancela`, `pendente` and `quando` also answer to `chancel`, `pending` and `when`.

Hunk numbers come from the diff, and the diff moves when the ref does: after a partial
chancel the command says so, and several `--hunk` in one call are applied against one
listing. The `🚫` refusal is enforced here — the passage is left out and named, and only
`--force` overrides it.

The surfaces read the ref, not a ledger: `km baseline` is the left-hand column of the VS
Code diff, the extension's passage states come from `km pendente --json`, and the standalone
mock builds its word-level diff from `git show refs/km/chancela:<file>` against disk. The
extension also **writes the marks**: approving, deferring with a date or disagreeing all
insert the agreed blockquote into the document, so the convention is the path of least
resistance rather than something to remember.

`tools/migrar_ledger.py <repo> --apply` carries an old `.km/blocks.jsonl` into the ref: the
vouched body of each block, projected as the reviewed copy of its file.

## Still open

- **Deleting a passage that never had a chancel.** `km restore --hunk` on a pure addition
  already removes it, because reverting the hunk is removing the text; `restore` only
  refuses when the file has no chancel at all. What is still missing is the reason going
  anywhere but the commit message.
- **Editing outside the editor.** A standalone surface needs a local server to save, with
  block-scoped writes and optimistic concurrency: re-read the file, compare, refuse and show
  both versions if it moved. Designed, not built.
- **WYSIWYG.** Any serialising editor rewrites Markdown on save. With the chancel as text,
  that shows up as a diff of the whole file rather than as silent loss — better than under
  the hash model, still noisy. CodeMirror with live preview avoids it entirely.
- **Which files are tracked**, and whether the ref carries every file or only those opted in.

## Measured, so nobody re-derives it

- 99.8% of 6,252 re-anchoring steps resolved by heading path — the machinery this design
  removes was working, and was still machinery.
- 605 claim writes produced 378 survivors in two days: reviewing mid-flight spends 37.5% of
  the effort on text that will not exist by evening. Review committed text.
- One commit replaced 98 claims with 105. Nothing renders that as inline marks; above
  roughly four words in ten moved, a passage needs two columns.
- A file the index called fully staged had been staged wholesale by another session's
  `git add -A`. A signal a routine command can forge is not a chancel.
