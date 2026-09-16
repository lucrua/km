# Format

## What counts as a claim

A claim is the unit you approve. In shadow mode it is found in the document itself, with no
markup of your own:

| Counts as a claim | Context, not a claim |
|---|---|
| a list item (`- …`, `1. …`) | headings |
| a paragraph | tables, quotes, code blocks, front matter, images |

A list item and the lines indented under it are one claim. Adjacent non-blank lines are one
paragraph, so a claim never spans a blank line.

This is a deliberate under-approximation: tables and quotes carry claims too, but splitting
them reliably needs rules you would have to learn. Put a claim you care about in a list item
or a paragraph and `km` will see it.

**An item written as a checkbox (`- [ ] …`) is an open question, not a claim.** It says what
is missing, so there is nothing to approve: `km` counts these separately and keeps them out
of the queue. Measured on a real repository in design phase, they were 43 of 370 items —
enough to bury the queue if they were treated as claims.

## Order of the queue

`km list` sorts by risk, and **takes turns between documents at the same risk level**. A
single long document otherwise owns the whole first page: in the same repository, the first
ten entries were all from one file before the round robin, and covered nine documents after
it. Risk is a coarse heuristic — a point for digits or a percentage, two for a term in
`risk_terms`, two for a path in `high_risk_files` — and it only affects order, never status.

## Identity

Two ways, and a document can mix them.

**By hash (default).** The key is `h:` plus the first 12 hex characters of the SHA-256 of
the normalised text. Nothing is written in the document. Rewording a claim produces a new
key, so the old approval shows up under `km gone` and `km approve N --carry` moves it over.

**By ID (optional, later).** A list item starting with `**DSP-3**` is keyed by `DSP-3`. The
approval then survives rewording: the record keeps the text hash separately, so an edit
still drops the claim back to the queue — it just stays the same claim.

## Normalisation

The hash is computed over text reduced to what a change of meaning would have to survive:

- Unicode NFKC, lowercase, whitespace collapsed
- emphasis and code markers removed (`*`, `_`, `` ` ``, `~`)
- link text kept, link target dropped
- checkbox markers (`[ ]`, `[x]`) removed
- trailing punctuation removed

So fixing a typo in the markup, re-wrapping a line or turning a word bold does not break an
approval. **Digits are never normalised**: `98%` and `89%` are different claims.

## The approval record

`.km/approvals.jsonl`, one JSON object per line, sorted by key — a small, diffable file.

```json
{"key": "h:3f9a1c0b2d44", "kind": "hash", "text_hash": "3f9a1c0b2d44",
 "preview": "Availability is measured per contract, never as the sum of clients",
 "file": "rules/availability.md", "approved_at": "2026-09-16", "by": "human:lucas",
 "origin": "stated · meeting 2026-09-14", "validate": "confirm with the contract owner",
 "due": "2026-10-15", "lot": true, "carried_from": "h:8b02de1177aa",
 "reapproved_at": "2026-09-22"}
```

Only `key`, `kind`, `text_hash`, `preview`, `file`, `approved_at` and `by` are always
present. `superseded_by` is accepted and read, and will be written by a later command.

Three sidecars keep what reviewing produces, in the same JSONL shape, keyed by claim:

| File | Holds | Effect on the queue |
|---|---|---|
| `deferrals.jsonl` | `until`, `at` | hidden until the date |
| `discussions.jsonl` | `at`, `file`, `line` | stays, flagged as under discussion |
| `notes.jsonl` | a list of `{at, text}` | stays proposed; `km notes` lists them |
| `ignored.jsonl` | `at`, `preview`, `reason` | out of the queue until the text changes |

`ignored.jsonl` is how the parser is corrected without a model: a heading-like sentence, a
provenance line ("read from the spreadsheet received on…"), a pointer to another document —
all of them parse as claims and none of them is one. Marking them costs a keystroke and the
decision is recorded, not silent.

A note never approves anything. It is the answer to "this is wrong or incomplete, and I am
not going to fix it right now": the claim stays proposed, and the note is there for whoever
edits the document next — a person or an agent. When the text is fixed, the hash changes and
the claim returns to the queue by itself.

`.km/config.json` holds `include`, `exclude`, `high_risk_files` and `risk_terms`.
`high_risk_files` and `risk_terms` only affect the order of the queue.

`.km/last-listing.json` maps the numbers printed by `km list` to keys. It is local scratch
and is git-ignored by `km init`.

## Derived status

| Record | Status |
|---|---|
| absent | `proposed` |
| `text_hash` equals the current text | `approved` |
| plus `validate`/`due`, due date in the future | `to-validate` |
| plus `due` in the past | `expired` |
| `text_hash` differs | `changed` |
| `superseded_by` present | `superseded` |

Status is never stored. There is nothing to keep in sync, and no way for a tool to declare
something approved by writing a word into a document.
