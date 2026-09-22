# The chancel: a reviewed copy, kept in a git ref

Status: **design, current.** Supersedes `docs/blocks.md`, which stored review state per
block; git history keeps it. Written 2026-09-22 from a working session, with every number
below measured on a real repository.

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

## What to build

1. `km chancela <file> [--all|--hunk]` — write accepted passages into the ref, with a commit
   message that carries the reasoning.
2. `km pendente [<file>]` — the two questions: what changed since the chancel, and which
   files have no chancel at all.
3. `km restore` — already written; put back the chancelled text of a passage.
4. The review surface reads `git diff`/`git show` instead of a ledger. The editor extension
   and the standalone mock both survive: the view does not change, only where the left-hand
   column comes from.
5. A lint for the convention: a `🚫` line blocks the chancel of its passage; a `❓` past its
   date is reported; a caveat that vanished is flagged on its own.

## Still open

- **Deleting a passage that never had a chancel.** Reverting means removing text an agent
  added. Today `restore` refuses with "nothing to go back to". Should deletion be possible
  with a confirmation?
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
