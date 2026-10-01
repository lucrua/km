# The chancel: a reviewed copy, kept in a git ref

## What the chancel is

**A copy of each tracked file, as you last endorsed it, stored in `refs/km/chancela`.**
Which files are tracked is chosen by folder and file in the panel — see
[tracked-files.md](tracked-files.md); a file you stop tracking keeps its copy in the ref.

Reviewing is comparing that copy with the file on disk. Approving a block means writing
that block into the copy. There is nothing else: no identity per block, no anchors, no
hashes to maintain.

Nothing is stored per passage because granularity is an outcome of reviewing, not an input
to it: what you approve together is whatever the diff offered you at that moment.

## Why a ref and not a branch

`refs/km/chancela` is written with plumbing — `hash-object`, a temporary index,
`write-tree`, `commit-tree`, `update-ref` — and is **never checked out**: the current branch,
the repository's index and the working tree are untouched.

A branch would show up in `git branch`, invite a checkout, and tangle with the feature
branches already in use. A ref under `refs/km/` is invisible to the normal flow, interferes
with no merge, and disappears with one command.

### Why not a copy in `.km/`

A folder of approved copies next to `.km/config.json` would be simpler to see, and loses what
the ref gives: every approval kept, with its parent, message and author — which is what undo
and `km quando` stand on; one store shared by every worktree, where `.km/` belongs to one
folder; out of reach of `git clean -X`, of an agent's `grep -r` or search-and-replace and of an
editor, where a gitignored copy of every document is none of those; and the same text stored
once, packed as deltas. A blob *is* a copy of the file, compressed and named by its content —
built in `.km/` with history, dedup and sharing, it would be git's object store again.

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

## What you approve

The ref holds whole files; the gesture is per **Markdown block** — a paragraph, a list item,
a table, a heading, a quote, a code fence. What lands in the ref is *the previous chancel plus
the blocks you accepted* — `git add -p` semantics, at the grain prose actually has, where a
line diff would cut through sentences.

Less than a block is possible too: a selection over the new text takes only the changes
inside it, decided word by word, with the spaces around each word travelling with it. The
same function, inverted, undoes only the selected part in the file.

How much is pending is measured in characters, not in blocks: what is left to decide over
what the file holds today, which is what the chancel would hold if everything were approved.

A **change** is a run of blocks that differ between two runs that do not, and it is read as
**one passage**: one text on each side and one set of verdicts, however many blocks it spans.
Blocks are how the engine finds and applies changes, not how you read them; less than the
passage is a selection. It is one number in `km pendente` (`2`); `--hunk 2.1` still addresses
one of its blocks for a script. Headings cut nothing: they label the passage they sit in.

Blocks are paired by similarity and only with blocks of the same kind, so a rewritten
paragraph is an edit and an unrelated one in the same place is one that left and one that
arrived. A re-aligned table has the same key as before and is not a change. Accepting every
block reproduces the file byte for byte; accepting none reproduces the chancel.

On the page a block is named by the hash of its content, not its position: a page that
asks to approve a block after the file moved underneath it is refused rather than served a
different block.

## Marks live in the document

Measured on the author's other repository: review notes are written as **visible
blockquotes**, not hidden HTML comments — the whole repository holds two HTML comments, both
tool markers. The practice is right, for reasons worth keeping: an agent reads a blockquote
natively with no tooling, a human opening the file sees the mark, and the note moves
with the text when the paragraph is edited.

So there is **one ref and a writing convention**, not a parallel store of comments. Three
marks, one line each, in the exact forms listed in the README's
[convention](../README.md#the-convention):

```markdown
> ❓ **to_validate by AAAA-MM-DD** — something to confirm by that deadline
> 💬 for whoever reads the passage later
> 📌 **to_do · AAAA-MM-DD** — for an agent to find and address; the day it was written
```

None of them blocks a chancel. A passage approved with a mark in it is **in the chancel and
carries the mark**, visible to every reader instead of hidden in a tool.

### The failure this creates, and the mechanism against it

An agent rewrites the paragraph and drops the mark. Nothing lies, but the tool would then
see a fully endorsed passage.

It is detectable: the chancelled copy **had** the mark, so its removal is a change like any
other and shows in the diff. The reviewer decides, as with anything else. The tool's job is
to make that specific change impossible to wave through — a change that leaves a block
without a kind of mark it had gets its own flag (*marca removida*) in the review and in
`km lint`, separate from ordinary edits. Rewording a mark is an ordinary edit.

## Moving a file

The ref is keyed by path. A plain `git mv` leaves the chancel under the old path: the moved
file reads as never reviewed and the old one as a deletion to approve. `km mv <from> <to>`
does the `git mv`, rewrites the entries of `.km/config.json` equal to or under `<from>`, and
re-keys the ref's entries in one commit, blob for blob. The content is untouched, so a pure
move leaves nothing to approve.

A passage moved to another file is not followed: it is new text in the destination and a
removal in the source, reviewed as such.

## Forgetting a file

Approving stores the file in the ref whether git has it or not, and the ref keeps every
version: a draft kept out of every branch is in `.git` anyway once approved, deleting it
leaves every earlier version in the ref's history, and untracking keeps the chancel by
design. `refs/km/*` is not shown by `git branch`, but `git push --mirror` sends it and any
copy of `.git` carries it.

`km forget <path>…` is the one command that rewrites the ref's history instead of
advancing it — the author's act, like `km chancela`. Without `--apply` it only lists what it
would do: the versions found, the commits that touched the paths and which of them would be
left empty, the config entries that go, and where else the same text still lives.

- **The ref.** Every commit is rebuilt without the paths. A commit left empty — it only
  approved, deleted or undid those paths — is dropped; the others keep their message,
  author, committer and dates, and the ones before the first that held a path keep their
  sha. A message line that is just a forgotten path (how `--from` lists its files) goes.
  The ref moves with compare-and-swap: an approval in the panel meanwhile makes the command
  fail, and nothing is lost. Forgetting everything deletes the ref.
- **The config.** The paths leave `folders` and `files`. One still on disk under a tracked
  folder becomes an exception, or the next approval would store it again; an existing
  exception stays, since it is what keeps the path out.
- **The objects.** `--prune` expires the ref's reflog, if it has one, and runs
  `git gc --prune=now`, then checks that the old versions are gone. Without it the command
  prints those two commands. Worktrees share one `.git`, so this covers all of them.

What it does not reach, and says so: the same text under another path of the chancel, in a
commit of a branch, tag or stash, or in the index; and copies of the repository made
before. `km serve` reads the ref on every request and needs no restart; an *↶ Desfazer
aprovação* from before the rewrite is refused, not misapplied. `km lint` flags the deleted
files whose text exists only in the chancel, and config entries with nothing on disk.

## Addresses move with the diff

The commands are listed in the README's [command line](../README.md#the-command-line).
`km pendente` numbers each change (`2`) and each of its blocks (`2.1`); those numbers come
from the diff, and the diff moves when the ref does. After a partial chancel the command
says so, and several `--hunk` in one call are applied against one listing.

The panel, `km serve`, and the VS Code extension read the same ref; neither keeps a ledger
of its own. How the panel edits without changing a byte is in
[live-preview.md](live-preview.md).

## Measured, so nobody re-derives it

- 99.8% of 6,252 re-anchoring steps resolved by heading path — the machinery this design
  removes was working, and was still machinery.
- 605 claim writes produced 378 survivors in two days: reviewing mid-flight spends 37.5% of
  the effort on text that will not exist by evening. Review committed text.
- One commit replaced 98 claims with 105. Nothing renders that as inline marks; above
  roughly four words in ten moved, a passage needs two columns.
- A file the index called fully staged had been staged wholesale by another session's
  `git add -A`. A signal a routine command can forge is not a chancel.
