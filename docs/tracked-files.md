# Tracked files: which documents the chancel covers

## What this is for

Choosing, by file and by folder, which Markdown documents the chancel covers — from a
screen, without editing JSON — and knowing at a glance what a choice means for files that
do not exist yet.

Decisions taken, and why:

| Decision | Why |
|---|---|
| A ticked **folder is a rule**: files created in it later are tracked | an agent writes a new decision into `decisoes/`; it must show up as *sem chancela* without anyone remembering to add it |
| **Untracking keeps the chancel** in the ref; the file shows as *pausado* | stopping costs nothing and is reversible; tracking again resumes where it stopped |
| **Exceptions** inside a ticked folder | leave `decisoes/README.md` out without losing the folder rule |
| **No patterns** | a list of folders and files is what a tree can show and a person can read; a glob is the part nobody can predict |
| A second view of the panel: **Revisar · Arquivos** | the tree has three levels and 48 files; the 210 px rail cannot hold it |
| **No save button**; each click writes | nothing here is destructive — a wrong click costs one more click |
| **One undo** with the last 5 steps, and redo | the undo menu of Word or Google Docs, instead of a link on every message |

## The model

### Configuration

`.km/config.json` holds three lists of repository-relative paths, and nothing else:

```json
{
  "folders": ["decisoes"],
  "files":   ["glossario.md", "requisitos.md"],
  "except":  ["decisoes/README.md"]
}
```

- `folders` — folders whose Markdown files are tracked, at any depth, including files that
  appear later. `"."` is the whole repository.
- `files` — single files tracked on their own.
- `except` — files or folders left out, overriding a folder rule above them.

Paths are relative, use `/`, never contain `..`, and never end in `/`. A config with any
other key is rejected with a message naming the key.

`km mv <from> <to>` rewrites every entry equal to or under `<from>` when it moves a file or
a folder, and never untracks: a folder covered by a rule above it takes the rule along, and
a tracked file moved out of its folder is listed in `files`. There is no command to track or
untrack; that is the *Arquivos* view.

### Which files exist

Candidates come from git: `git ls-files --cached --others --exclude-standard -- '*.md'`.
Git decides what exists, so `.gitignore` is respected — on one repository, 48 files instead
of the 1,624 a disk walk finds, almost all in `node_modules`. There is no hand-written
exclusion list.

Files that exist only in the chancel ref are also listed, so a paused file and a file that
no longer exists are visible.

### Is a file tracked — the closest decision wins

For a path, walk from the file up to the root and take the first decision found:

1. the file itself in `files` → tracked; in `except` → not tracked;
2. each folder, deepest first: in `folders` → tracked; in `except` → not tracked;
3. `"."` in `folders` → tracked;
4. otherwise → not tracked.

At the same level `except` wins. This is inheritance with overrides — a permission set on
a file beats the one it inherits from its folder — and it lets a single file be ticked
inside an excluded subfolder, which `.gitignore` famously cannot do.

### Normalisation

Every write normalises the config before saving, so the file stays short and readable:

- a file in `files` already covered by a folder rule, with no exception between, is dropped;
- an entry in `except` that no folder rule covers is dropped;
- a folder in `folders` covered by a rule above it, with no exception between, is dropped;
- duplicates go; each list is sorted.

### States of a file

| State | Meaning |
|---|---|
| *em dia* | tracked, chancel equals the file |
| *X% a aprovar* | tracked, changes pending — the same percentage as the review view |
| *sem chancela* | tracked, never chancelled |
| *pausado · chancela guardada* | not tracked, has a chancel in the ref |
| *não existe mais* | in the chancel ref or in `files`, absent from disk |
| *—* | not tracked, never had a chancel |

## The screen

`Revisar · Arquivos` in the top bar switches between the review and this view. The tree
takes the full width.

```
 demo-sla-project   [ Revisar | Arquivos ]                  [ ↶ Desfazer ▾ ]  [ ↷ ]
 ✓ decisoes/ passou a ser acompanhada (+ novos) · 9 arquivos entraram
 ▾ ☐ demo-sla-project/                              7 de 48
     ☑ requisitos.md                                8% a aprovar
     ☐ glossario.md                                 pausado · chancela guardada
   ▾ ◐ decisoes/            + novos                 9 de 10 · 1 exceção
       ☑ 0001-usar-o-delta-do-tasks.md              sem chancela
       ☐ README.md                                  exceção
   ▸ ☐ design/                                      nenhum
```

### What a row shows

- **Checkbox — the standard three states** (HTML `indeterminate`, WAI-ARIA *mixed*): ☑ all
  Markdown under it is tracked today, ☐ none, ◐ some. It describes coverage now, and means
  what it means everywhere else.
- **`+ novos`** — only on folders whose rule picks up files created later. This is what tells
  "a folder with one exception" apart from "a folder with one file picked by hand"; both are
  ◐, only one has `+ novos`.
- **Folders:** "N de M" — tracked Markdown files over all Markdown files under it, at any
  depth — plus "· K exceção(ões)" when there are any.
- **Files:** the state from the table above.
- Folders start open when something inside is tracked, closed otherwise.

### What a click does

Standard tri-state tree behaviour, expressed in the three lists:

| Click on | Result |
|---|---|
| ☐ file | added to `files`, or removed from `except` if an exception was hiding it |
| ☑ file | removed from `files`; if a folder rule covers it, added to `except` |
| ☐ or ◐ folder | added to `folders` (gets `+ novos`); every entry below it is cleared |
| ☑ folder | removed from `folders` and every entry below it cleared; if a rule above covers it, added to `except` |

Every click writes the config at once and reports what it did in one line at the top:
"✓ glossario.md saiu do acompanhamento · a chancela fica guardada". The review rail and the
percentages reflect it on the next load.

### Keyboard

The WAI-ARIA tree pattern: `role="tree"` / `treeitem`, `aria-checked` with `mixed`,
`aria-expanded`. ↑ ↓ move, ← → close and open, Space ticks, Ctrl+Z undoes, Ctrl+Shift+Z
redoes.

### Undo

- **↶ Desfazer** undoes the last step; **▾** lists the last 5 and undoes back to the one
  clicked, including the ones above it; **↷** redoes.
- The history lives in the page and is lost on reload — the tree always shows the current
  state, and every step is cheap.
- Each step stores the config before and after. Undo writes *before* only if the file on disk
  is still *after*; otherwise it refuses with "a configuração mudou por fora — a tela foi
  atualizada" and reloads the tree. Nobody else's change is overwritten.

## Server

| Route | Does |
|---|---|
| `GET /api/arquivos` | the tree: per node the path, kind, checkbox state, `+ novos`, "N de M", exceptions, file state; plus the config's sha |
| `POST /api/arquivos` | `{caminho, marcar: bool, sha}` — applies the click, normalises, writes, returns the new tree and the step `{rotulo, antes, depois}`; refuses if the config changed since `sha` |
| `POST /api/arquivos/desfazer` | `{config, esperado}` — writes `config` only if the file on disk equals `esperado` |

Writes are atomic: a temporary file in `.km/`, then rename.
