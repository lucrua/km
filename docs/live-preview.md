# Live preview: editing that looks like the document

## What this is for

While editing in the panel, the text looks like formatted Markdown — typing `## Título`
becomes a heading as you type — without the display ever changing a byte of the file.

The constraint that decides everything: **the chancel is a byte copy, and the diff is the
product.** A WYSIWYG editor (TipTap, Milkdown — ProseMirror underneath) parses Markdown into
its own model and writes Markdown back on save, which rewrites bytes: hard-wrapped lines
joined, `*` and `_` swapped, list markers and table padding changed. Every save would show
changes nobody made, and partial approval — which counts positions in the source — would
break. So the editor must hold the source itself, and formatting must be a display layer.

## Decisions, and why

| Decision | Why |
|---|---|
| **CodeMirror 6 with a live-preview layer** — the model Obsidian uses | the document is always the exact source; formatting is decoration, so save, diff and partial approval see the file's bytes |
| **Markers hidden off the cursor line** | reads like a document; the markers come back where you click, and are always in the file |
| **Hard-wrapped paragraph lines joined** into one flowing paragraph, real breaks shown when the cursor enters it | reads like a document |
| **Tables rendered as a grid** off the cursor, with **add/remove row and column** controls | the documents are table-heavy; a wide table becomes readable without horizontal scrolling; every control rewrites the table's source lines, so what you see is what is saved |
| **The action column is sticky** within its change | on a long change you do not scroll back up for *Aprovar* |
| **One editor per page segment; a MergeView per change** | unchanged text is one full-width editor; each change is CodeMirror's own side-by-side comparison, which aligns the columns and marks the difference live while you type |

## Architecture

### The bundle

CodeMirror is bundled **once**, with esbuild, into a single ES module, `km/vendor/cm.js`,
committed to the repository. The recipe lives in `tools/build-cm/` (a `package.json` pinning
the versions and the build command). The panel loads it from its own server: no network, no
npm at run time, and the Python side stays standard-library only.

Packages: `@codemirror/state`, `@codemirror/view`, `@codemirror/commands`,
`@codemirror/language`, `@codemirror/lang-markdown` (with GFM, for tables),
`@codemirror/merge`.

### Our modules

Served as static files from `km/painel/`:

| Module | Does |
|---|---|
| `preview.js` | the live-preview extension: decorations over the Markdown syntax tree |
| `tabela.js` | pure functions over a table's source lines — parse cells, add/remove row, add/remove column |
| `paragrafo.js` | pure function: the newline ranges inside paragraphs to show as spaces, given the cursor |
| `editores.js` | creates the editors for the page's segments and connects them to save, dirty tracking, selection and marks |
| `marcas.js` | the three marks' exact forms and the line each button inserts — pure |
| `pontos.js` | converts CodeMirror's UTF-16 offsets to the server's code points — pure |

The pure modules have no DOM and no CodeMirror imports, so they are tested with `node --test`.

### Segments from the server

`serve.segmentos` returns plain text, no HTML:

- unchanged stretch: `{"tipo": "igual", "linha", "texto", "n_linhas"}`;
- change: `antes`, the chancel's text of the passage; `agora`, today's; `unidades`, each
  block's `sha` and its offsets inside `agora`; and the marks it removes.

## The live preview

Off the cursor line:

| In the file | Shown as |
|---|---|
| `#`…`######` heading | large text, marker hidden |
| `**bold**`, `_italic_`, `` `code` `` | formatted, markers hidden |
| `[text](url)` | "text" styled as a link, the URL hidden |
| `- item`, `1. item` | a bullet or the number, with the item's indentation |
| `- [ ]` / `- [x]` | ☐ / ☑ — display only; click the line to change it |
| `> quote` | a bar on the left, `>` hidden |
| `> 📌 **to_do · …**` · `> ❓ **to_validate by …**` · `> 💬 …` | blue, amber and neutral boxes — only in the exact form; an overdue ❓ highlights its date (local time) |
| fenced code | its own background, fence lines hidden |
| `---` | a horizontal rule |

On the cursor line everything is shown as it is in the file.

### Paragraph lines

Inside a paragraph (and inside a list item's continuation lines), each newline is shown as a
space while the cursor is outside that paragraph. When the cursor enters it, the real line
breaks appear and editing is line by line. Nothing is changed in the text.

### Tables

A GFM table off the cursor is replaced by a grid: bold header, inline formatting in cells,
long cells wrapping. Clicking a cell puts the cursor on that cell's line and the table turns
back into text.

On hover:

- each row has **+** (insert a row below) and **×** (remove this row);
- each header cell has **+** (insert a column to the right) and **×** (remove this column).

Each control rewrites the table's lines in the document:

- a new row has one empty cell per column;
- a new column adds a cell to every row and `---` to the separator row;
- the header row and the separator row cannot be removed, nor the last remaining column;
- cells split on unescaped `|` only; `\|` stays inside its cell.

Re-aligning the padding is not a change for the diff, which already compares tables in their
canonical form, so the controls need not pad.

### The chancel column

The left editor of a change is read-only and has no cursor, so it is always formatted. The
MergeView's marks sit on top: a tinted background on the changed chunk and marks on the words
that differ.

Inside a table shown as a grid the MergeView's word marks would be hidden under the widget, so
the grid draws them itself: it reads the changed ranges of its side from the MergeView
(`getChunks`) and wraps the changed text of each cell in the same `cm-changedText` class —
struck through on the chancel side, underlined on today's, a new or removed row marked whole.
The marks sit inside the cell's formatting and are display only; the grid is redrawn when the
MergeView recomputes its chunks, so a word typed in a cell is marked when the cursor leaves the
table. In the Código mode there is no grid and CodeMirror's own marks show.

## The page

- **Unchanged stretch:** one full-width editor.
- **Change:** a MergeView, left read-only, right editable, and the action column.
- **Sticky actions:** the action cell's contents stick just under the top bar while the change
  is on screen, and leave with it.
- **Saving:** *Salvar no arquivo* and Ctrl+S, the save located by the text
  it replaces, the refusal that shows what is in the file now. Dirty means the editor's text
  differs from the original.
- **Approving a selection:** the selection's offsets come from the right editor, and are turned
  into "this part of this block" with the `unidades` offsets.
- **📌 ❓ 💬 at the cursor:** a transaction inserting the mark after the block the cursor is in,
  with one blank line before and after, and `add your comment here` selected.
- **Undo:** Ctrl+Z inside an editor undoes text (CodeMirror's history). In the *Arquivos* view,
  Ctrl+Z still undoes the config.

## Tests

The pure modules — tables, paragraph ranges, marks, offsets — run under `node --test`
(`tests/js/`), with the bundled CodeMirror for the live-preview decorations.
