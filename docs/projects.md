# Projects: one panel for every repository you review

## What this is for

Reviewing several repositories without one `km serve` per repository, one port each and one
browser tab each that you have to remember. One server, one address
(<http://127.0.0.1:8431>), and a switcher in the top bar.

## The model

**A project is a repository root in a list.** Nothing moves into the list: each project keeps
its own `.km/config.json` and its own `refs/km/chancela`, and every command other than
`km projects` and `km serve` works exactly as before, on the repository you are standing
in.

### The registry

`$XDG_CONFIG_HOME/km/projects.json` — `~/.config/km/projects.json` when the variable is not
set — holds one key:

```json
{
  "projects": [
    "/home/you/demo-sla-project",
    "/home/you/knowledge-manager"
  ]
}
```

- Paths are absolute, resolved (no symlinks), without repeats, sorted. `km` writes the file
  this way, through a temporary file renamed over the old one, so a reader never sees half
  of it.
- Any other key, a path that is not absolute or a value that is not a list is refused with
  one sentence, the way a broken `.km/config.json` is.
- It is per user, not per repository: nothing is written in the repositories to register
  them.

### Names

A project is named by its folder: `/home/you/demo-sla-project` is `demo-sla-project`. When
two folders share a name, both take their parent — `work/app` and `personal/app` — and more
parents if that still does not tell them apart. Adding a second `app` therefore renames the
first one in the panel: an open page follows it by its path, and a bookmark with the old
name lands on the Projetos view with a warning.

The tab title keeps the **folder name** first (`app · km chancela`), even when the project
is shown as `work/app`: ActivityWatch records the title, and the time is billed to what comes
before ` · `. With no project selected — an empty list — the title is `km · projetos`.

## The rules

| Rule | Why |
|---|---|
| A project must be the **root of a git work tree** (`git rev-parse --show-toplevel` is the path itself) | the chancel is a ref of that repository; a subfolder would be a second project over the same ref |
| A project must **already use km** (`.km/config.json`); `--init` (or the panel's checkbox) writes the empty one `km init` writes | the list is of repositories you review, not of every repository you have |
| Adding a project already in the list is **not an error** | the VS Code extension adds the repository of the window every time it opens the panel |
| **Removing only edits the list** | the repository, its `.km/config.json` and its chancel stay as they are; adding it back resumes where it was |
| The server resolves a name to a path **only through the list**; the only request that carries a path is the one that adds a project | a page, or a request, never picks an arbitrary folder to read or write |
| Every route of the panel **names its project**: `?projeto=<name>` on GET, `"projeto"` in the POST body. No project is **400**; an unknown one, or one whose folder is gone, is **404** | no route falls back to "the current project" — two tabs on two projects cannot write in each other's |
| The list is **read on every request** | `km projects add` in a terminal shows up in a running panel without a restart |
| Adding and removing are POSTs with the same guard as every other write: JSON only, and the page's own origin | another site must not be able to register a folder |
| `km serve` **inside a repository that uses km registers it** and opens on it; elsewhere it still starts | serving from a repository means you want to see it |

## Which project the page opens

1. `?projeto=<name>` in the URL — a bookmark, a reload, the VS Code extension. An unknown
   name selects nothing: the page opens on Projetos and says so.
2. The last project used in this browser (`localStorage`).
3. The repository `km serve` was started from.
4. The first project in the list; with no project at all, the Projetos view.

The selected project is written back into the URL (`history.replaceState`), so a reload
stays on it.

## The command line

```bash
km projects                          # name · % a aprovar (or "em dia", "—" when broken) · path
km projects --json                   # [{nome, caminho, pct, n, pendentes, erro}]
km projects add ~/demo-sla-project   # a repository root that already has .km/config.json
km projects add ~/novo --init        # writes the empty .km/config.json first
km projects rm demo-sla-project      # by name or by path; the repository is not touched
```

`projects` also answers to `projetos`, `add` to `adicionar`, `rm` to `remover`.

## The VS Code extension

`Ctrl+Alt+P` registers the window's repository (only if it has `.km/config.json`) and opens
`http://127.0.0.1:8431/?projeto=<name>`. If a panel already answers on the port, it only
opens the address; otherwise it starts `km serve`. A port taken by something that is not
this panel (another program, or an older single-repository `km serve`) is skipped for the
next one.

The server the extension starts **belongs to that window**: closing the window ends it — the
panel of every project, also for other windows that were using it. In those, the next
`Ctrl+Alt+P` starts a new one. A `km serve` started in a terminal lives until Ctrl-C.
