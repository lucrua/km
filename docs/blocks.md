# Blocks: the unit of review

Status: **design, not implemented.** Written 2026-09-17 from a long working session, so
the reasoning survives the context window. Every number here was measured on a real
repository of ~380 claims across 16 documents, actively written by several agents.

## Why a layer at all

Agents write faster than a person reviews. There are only two honest answers to that:

1. **Block at the door.** Nothing enters the truth documents without review. Simple, no
   layer, no marks — and the reviewer becomes the bottleneck for everything.
2. **Let writing run ahead, and keep a record of what has been vouched for.** That record
   is this layer. It buys parallelism and pays for it with a marking system to maintain.

This document specifies (2). If maintaining the layer ever costs more than the bottleneck,
(1) is the correct answer and this should be deleted.

## What this is not

**Not a version control system.** Git already stores content, history and merges. The
temptation is to build something "git-like" for review state; resist it. A VCS exists to
merge concurrent work between people, and there is one reviewer here. Three small
primitives are enough:

| Primitive | Status |
|---|---|
| Content identity | exists — hash of normalised text |
| **"What changed since I last looked"** | **missing everywhere; this is the layer** |
| Append-only decision log | trivial — a JSONL file |

The missing primitive is not exotic. Gerrit has "reviewed" per file per reviewer, GitHub
has the "Viewed" checkbox that clears when the file changes, and Reviewable exists largely
because GitHub loses that state across force-pushes. What is new here is wanting it **per
block instead of per file**, and **outside a pull-request flow**.

**Not a writer.** The layer never edits a document. Splitting a block is an edit, so it is
done by whoever edits documents — a person in the editor, or an agent — never by the
review tool. One writer per file stays the rule.

## Block boundaries

### Default: the heading

**A block runs from a heading to the next heading of the same or higher level.** No new
syntax, nothing for anyone to maintain: Markdown already carries this structure, and
authors maintain it for their own reasons.

Measured on the real repository:

| Document | Lines | Headings | Lines/section | Largest |
|---|---|---|---|---|
| rules | 258 | 20 | 12.9 | 27 |
| requirements | 146 | 9 | 16.2 | 30 |
| design | 391 | 19 | 20.6 | 83 |
| glossary | 94 | 8 | 11.8 | 14 |
| one decision file | 70 | **1** | **70.0** | 70 |

Twelve to twenty lines is a reviewable unit — roughly the size of the ranges the reviewer
was already selecting by hand in the editor. Decision files are the exception: written as
one narrative under a single heading, they are one 70-line block until someone adds either
a heading or a marker.

### Escape hatch: an opening marker

Where a heading is too coarse, an invisible marker opens a block:

```markdown
<!-- block: alias-do-estado · origin: measurement 2026-09-16 · agent: design-v1 -->
```

`origin` is written at write time by whoever writes the text. This is deliberate: audit
systems that ask for evidence afterwards do not get it — Phabricator's own documentation
says authors have a much weaker incentive to address anything raised after the fact.

### Why no closing tag

- **Markdown is unpaired by design.** Headings, lists and quotes all end by context. Going
  against the grain of the format costs more than it returns.
- **Unbalanced pairs are the failure agents actually produce.** An unclosed block or an
  orphan closer is a new broken state; with no closer, that state cannot exist.
- **What a closer would protect is already protected.** Text appended at the end of a
  section joins that block — and the content hash catches it (see below). The check drops
  and 13 lines come back for review, instead of two sentences being silently inherited.

## Who creates a block

**Intent creates blocks. Mechanics never do.**

- A person approving a range creates one.
- An agent declaring provenance creates one.
- **An edit creates nothing.** It only marks the block containing it as changed.

### Not the diff

The tempting rule — "a git edit becomes a new block and splits the rest" — was measured and
rejected:

| Document | Lines | Hunks in history | Block size if each hunk split |
|---|---|---|---|
| rules | 258 | **149** | **1.7 lines** |
| requirements | 146 | 60 | 2.4 |
| design | 391 | 12 | 28.9 |

In the document that matters most, diff-driven blocks would average 1.7 lines: debris, not
blocks. A single commit touched 23 hunks in that file, several of them one line. Boundaries
would record *when an agent happened to touch a line*, not what the text says. The design
file looks fine at 28.9 lines only because it was written in large passes — the mechanism
appears to work exactly where nothing is being refined, and shreds whatever is alive.

## Review state

### States

| State | Meaning | How it ends |
|---|---|---|
| `unseen` | nobody looked | reviewer looks |
| `approved` | read and vouched for | text changes |
| `accepted` | approved without real reading — the honest state for a bulk gesture | **expires** into `assumption` |
| `assumption` | acted on, nobody will confirm soon | someone confirms, or it is superseded |
| `to-validate` | someone specific will confirm, by a date | the date, or the answer |
| `rejected` | wrong; kept and marked so it is not re-added | superseded |
| `commented` | a question is attached and unanswered | the answer |

`accepted` is honest — bulk gestures happen — and it is an attractor: on a tired day
everything becomes `accepted`. Three antidotes, all required:

1. **It expires.** Unreviewed after N days it becomes `assumption`, with a date. This is
   how the kernel's patch queue and Gerrit's auto-abandon drain, and it is the only
   mechanism with a track record against unbounded backlogs.
2. **It is counted in your face.** "62% of this base is `accepted`" changes behaviour; a
   hidden field does not.
3. **It is sampled.** One in N returns to the queue as a real review.

`rejected` keeps the text rather than deleting it, so the same claim is not re-added later.
This is Wikidata's `deprecated` rank, and it is also the repository's own rule about
recording what was discarded.

### Nobody invalidates

State is never stored as "reviewed". It is stored as **"reviewed at content hash X"**, and
every read recomputes the hash and compares.

**There is no moment of invalidation for anyone to miss.** A stored boolean would need
every path that touches the file — agent, editor, merge, rebase, revert, checkout — to
remember to flip it. That class of bug is what kills annotation systems. Here, invalidation
is a consequence of reading.

Consequences worth relying on:

- Works for edits from anywhere, including outside the agent tooling.
- **Revert restores the check**: text back to what it was, hash matches again.
- Cosmetic edits survive: the hash is over normalised text (whitespace, emphasis, link
  targets, case), so fixing italics keeps the check and changing a word drops it.

### What the hash covers

A block's hash covers **its own text only**, up to the first nested boundary. Nested blocks
are excluded, or editing one subsection would reset the whole chapter and the invalidation
would cascade.

Coarser levels are **computed, never stored**: "this file is reviewed" means "every block in
it is". State is recorded only at the level where someone actually decided.

**Coarse blocks give coarse invalidation** — while a decision file is one 70-line block, any
edit anywhere resets all of it. That friction is the signal telling you where to split, so
granularity grows where the text is alive, without anyone planning it.

### Confidence from the gesture

How a block entered the reviewed set says how carefully it was read, and it can be observed
rather than asked:

| Gesture | Recorded as |
|---|---|
| a hand-selected range | `approved` |
| a whole file staged at once | `accepted` (bulk) |
| `git add -A` from another session | **nothing** — this is not a human gesture |

The last row matters: on the real repository, an unrelated session ran `git add -A` and
staged files nobody had reviewed. A signal that a routine command can forge is not a
chancel, which is why the record must be written at the moment of the gesture and must
distinguish its shape.

## Where state lives

Outside the documents, keyed by block id, append-only. Documents carry at most an opening
marker and the `origin` an author wrote. The layer reads git — any ref: working tree, index,
HEAD, a branch — and the choice of ref is per moment, not per design:

- **During expansion, read committed text.** Measured: 605 claim writes produced 378
  survivors in two days, so 37.5% of anything reviewed mid-flight is reviewing text that
  will not exist by evening.
- **During consolidation, read whatever you are curating**, including the dirty tree.

## What the layer does not know

**Who edited a block, and why.** That is `git log -L` on the block's range. Do not duplicate
git; the layer would drift and lose.

## Open questions

1. **Block ids.** Derived from the heading path (breaks on rename) or explicit in the
   marker (needs maintenance)? Probably: implicit until a block gets state, explicit from
   then on — but the moment of promotion is an edit, so who performs it?
2. **Carry-over after a rewrite.** One commit replaced 98 claims with 105. The reviewer
   should see "this is the old block, reworded", not 105 new ones. Similarity matching is
   good at *same subject* — which is exactly what it is good for, and exactly what it is bad
   at when asked *does this contradict*.
3. **Expiry period** for `accepted`, and **the ceiling** on the queue that stops expansion.
   Both are numbers only the reviewer can pick.
4. **Where comments live.** In the file (agent reads them immediately, pollutes the source)
   or outside anchored by quoted text (clean, needs W3C-style prefix/suffix anchoring).
5. **First interface.** Probably a generated "what changed since I last looked" page, not an
   application. If it is not opened for two weeks, the answer was not an interface.

## Rejected, and why

| Rejected | Why |
|---|---|
| The git index as the store of approval | It means "what goes in the next commit", not "what I vouch for", and any `git add -A` forges it. Observed happening. |
| Blocks created by diff hunks | 1.7-line fragments in the liveliest file; boundaries follow edit timing, not meaning |
| Closing tags | Markdown is unpaired; unbalanced markers are a failure state that need not exist; the hash already covers the risk |
| A "git-like" layer | Rebuilds merge between people, a problem a single reviewer does not have |
| One claim per file (OKF-style) | ~170 files and metadata heavier than content; measured 646–1258 characters of frontmatter against 471–829 of body |
| Status written by the agent | The writing is exactly what fails; computed status needs no discipline |
| A separate review application with an embedded agent panel | Competes with the editor the reviewer already lives in, and the agent panel duplicates what is one window away |
| A watcher warning during writing | A crossover study with 34 inspectors measured macro F1 **falling ~8%** with LLM assistance, with no time saved. The watcher accumulates and reports at consolidation instead |

## Where the rest of the reasoning lives

The research behind this — review backlogs at scale, contradiction detection accuracy,
multi-agent conflict rates — is recorded outside this repository, in the consulting
knowledge base, because it contains material about a specific engagement.
