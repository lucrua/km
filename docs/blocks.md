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

**Not a writer.** The layer never edits a document, and the split below follows from that:

| What | Who writes it | Where |
|---|---|---|
| **Structure** — headings, and optionally a block id | the author, in the same act that writes the text | in the file: it is content |
| **Judgement** — chancel, confidence, comment | the reviewer, later, while others write | **outside the file, always** |

Annotation is asynchronous by nature. Writing it into the document would make the reviewer
one more concurrent writer, in exactly the file an agent is editing — and that file is the
liveliest one (23 hunks in a single commit, measured). Structure is authored; judgement is
annotated. In the common case, with headings as the boundary, **nothing at all is written
into the file**.

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

### Finer than a heading

Nothing is written into the file for this — not even an invisible marker. Where a block
must be finer than a heading, **the layer anchors it by quoted text** (the passage, plus
enough of what precedes and follows it to find it again), which is the same anchor the
orphan-resolution chain already needs.

And when a document is too coarse to review, the honest fix is in the document: **add a
heading**, which serves the reader as well. The measured case is the decision file with one
heading over 70 lines — written as a single narrative, so any edit anywhere resets all of
it. Giving it the headings it already deserves fixes the review granularity as a side
effect, and a reader gets a better document.

### What may live in the file, and what may not

The rule is not "nothing in the file, ever" — it is about **who is already writing**:

| | A reader who never uses this tool wants it? | Where |
|---|---|---|
| "This rule came from the meeting of 14/09" | **yes** | in the file, as content |
| "No proof for this yet — confirm" | **yes**, while unresolved | in the file; removed by whoever resolves it |
| A block id | no, only the tool | outside |
| Chancel, confidence, reviewer comment | no — it is about the reviewer's trust, not the content | **outside, always** |

**Whoever is already writing may annotate in the file; whoever is not writing must annotate
outside.** An agent writing a document annotates in the same act: no concurrency, no second
writer, and provenance captured at the only moment it is known. A reviewer is not writing,
so the same gesture would make them a concurrent writer in the file an agent is most likely
editing.

This also means **no migration step is needed**. Author annotations are read by the layer on
every scan and disappear when someone resolves them in a normal edit — no hook rewriting
files mid-commit, nothing changing under an agent's feet.

### Why judgement, specifically, stays out

- **A marker that exists only for this tool is annotation in disguise.** An author writes a
  heading for the reader, and a provenance line for the reader; nobody writes a block id for
  themselves. Calling that "content" would be smuggling the layer into the document.
- **Any write makes the reviewer a concurrent writer**, in the file an agent is most likely
  editing — 23 hunks in a single commit, measured.
- **Markdown is unpaired by design**, so paired delimiters would also introduce a failure
  state that need not exist: an unclosed block or an orphan closer.

What a closing delimiter would protect is already covered: text appended at the end of a
section joins that block, the content hash changes, and the check drops.

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

## Moving and renaming

Annotations follow the content, in three levels:

1. **A command that knows** (`km mv`, or wrapping `git mv`) rewrites the index. Exact.
2. **A committed rename by someone else**: git detects it by content similarity and hands
   it over as `R<score> old new`. Free.
3. **A rename in the dirty tree** — the common case with agents: git cannot help, because
   detection only runs between commits. Measured on the real repository: **zero renames in
   the whole history**, and yet a decision file was renamed — in the working tree, before
   the first commit, where git never saw it. The anchor carries this case: a file
   disappears, another appears holding blocks with identical content hashes, and the
   annotations re-point by content.

When nothing matches, the annotation becomes an **orphan on a list**, with the text it was
written against. It is never dropped silently.

**Key by content, index by path.** An earlier version keyed claims by path *and* text, to
solve collisions: boilerplate like `**Descartado.**` repeats once per decision file, and
approving one would have approved seven. That fix made every move break every key in the
file. The collisions were 16 of 17 cases of pure boilerplate, which is not a claim at all
and leaves the queue through triage or a keystroke — the wrong problem to solve with the
key. Keying by content makes moves free and turns duplication into a visible property: the
record lists every location where that exact text appears.

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

## Decided

1. **Block ids are internal.** Generated by the layer, never in the file, never shown. They
   exist so the log can name a block across versions; identity across a rewrite is a
   judgement the layer makes (by heading path, then by content similarity). If that
   judgement is wrong the worst case is re-reviewing a block — no state is corrupted,
   because the thing that actually matters is always "vouched at content hash X".
2. **Carry-over after a rewrite is the curator's job.** When one commit replaces 98 claims
   with 105, most are the old ones reworded, and the reviewer must not face 105 new items.
   Mechanical similarity proposes the pairing — it is good at *same subject*, which is
   exactly what pairing needs, and bad at *contradicts*, which is not asked here — and the
   reviewer confirms with one keystroke, carrying the original approval date and origin.
3. **`accepted` expires in 14 days by default**, configurable.
4. **Comments live outside the file.** A utility *projects* them into a rendered copy when a
   person or an agent reads — annotations shown inline, disk untouched. Caution to carry
   into implementation: an agent that reads a projected copy must not be able to echo the
   injected marks back into the real file, so the projection is read-only and labelled.

## Still open

5. **The first interface.** In definition. It can stay undefined without blocking anything:
   a generated page is the cheapest surface and forecloses nothing.

## Rejected, and why## Rejected, and why

| Rejected | Why |
|---|---|
| The git index as the store of approval | It means "what goes in the next commit", not "what I vouch for", and any `git add -A` forges it. Observed happening. |
| Blocks created by diff hunks | 1.7-line fragments in the liveliest file; boundaries follow edit timing, not meaning |
| Closing tags | Markdown is unpaired; unbalanced markers are a failure state that need not exist; the hash already covers the risk |
| A "git-like" layer | Rebuilds merge between people, a problem a single reviewer does not have |
| One claim per file (OKF-style) | ~170 files and metadata heavier than content; measured 646–1258 characters of frontmatter against 471–829 of body |
| Status written by the agent | The writing is exactly what fails; computed status needs no discipline |
| A separate review application with an embedded agent panel | Competes with the editor the reviewer already lives in, and the agent panel duplicates what is one window away |
| Any marker in the file for the tool's benefit | It only serves the layer, so it is annotation in disguise; and writing it makes the reviewer a concurrent writer in the liveliest file |
| A watcher warning during writing | A crossover study with 34 inspectors measured macro F1 **falling ~8%** with LLM assistance, with no time saved. The watcher accumulates and reports at consolidation instead |

## Where the rest of the reasoning lives

The research behind this — review backlogs at scale, contradiction detection accuracy,
multi-agent conflict rates — is recorded outside this repository, in the consulting
knowledge base, because it contains material about a specific engagement.
