# Roadmap

Ordered by what unlocks the next thing. Nothing here is committed to a date.

## Now — shadow mode

`init · scan · status · list · show · approve · carry · gone · serve`. No document is
modified. `serve` is the queue as a local page: one claim at a time, keyboard first, with
defer and undo, writing the same `.km/` files as the CLI.

## Next

- **`km projections`** — generated views, no agent involved: what holds on a subject, what
  is to validate and when it expires, what changed after approval. Written to
  `.km/projections/`, git-ignored, regenerated on demand.
- **`km lint`** — mechanical checks only: a claim approved with a source that does not
  exist, a due date in the past, a duplicate ID, a broken link.
- **`km export --okf`** — the approval record rendered as Open Knowledge Format fields
  (`status`, `verified`, `sources`) for anything outside that expects it.
- **Pre-commit hook** — refuses a commit that writes `.km/approvals.jsonl` without a human,
  and refuses a whole-file rewrite of a document under `include`.

## Later

- **Dependencies across repositories.** A claim in one repository can declare that it
  affects a claim in another; when its text changes, the dependent claim is reported as
  suspect. The declaration lives on the side that may not be shared, so the shared
  repository never points at the private one.
- **Cards.** The queue as a board, one card per claim that needs a decision, with the
  sources next to it and an option to open a conversation from the card.
- **Session intake.** Turning what was decided in a conversation into proposed claims, so a
  decision does not stay only in a transcript.

## Deliberately out of scope

- **Deciding anything.** No LLM call, no network. The tool reports; a person approves.
- **Confidence scores.** A number invented for a claim is false precision; the chain to the
  source is what carries weight.
- **Locking and session coordination.** Editors already refuse stale writes and git already
  merges. A claim touched by two people simply loses its approval and comes back to the
  queue.
- **Being a document editor.** `km` never rewrites a document.
