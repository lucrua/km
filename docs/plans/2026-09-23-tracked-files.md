# Tracked files Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Choose which Markdown files the chancel covers from a tree in the panel — folders as rules, files, exceptions — replacing the include/exclude glob model entirely.

**Architecture:** A new module `km/acompanhamento.py` owns the config (three lists), the closest-decision resolution, normalisation, git candidates, the tree and the click semantics. `km/chancela.py` loses every trace of the glob model. The panel's HTML moves out of a Python string into `km/painel.html` (no more escaping), gains a *Revisar · Arquivos* switch, and the server gets three `/api/arquivos` routes.

**Tech Stack:** Python 3.11+ standard library only; plain HTML/CSS/JS served by `http.server`; `unittest`; Chrome DevTools Protocol on port 9225 for the browser check.

**Spec:** `docs/tracked-files.md`

## Global Constraints

- Python 3.11+, no third-party dependencies.
- Code, identifiers and docs in English; everything a person reads on screen or in the terminal in Portuguese.
- Config file `.km/config.json` has exactly the keys `folders`, `files`, `except`; any other key is rejected naming the key; no reader for the old format.
- Paths: relative, `/` separators, no `..`, no trailing `/`; `"."` only as a folder.
- Candidates come from `git ls-files --cached --others --exclude-standard -- '*.md'`.
- Resolution: file first, then folders deepest first, then `"."`; at the same level `except` wins.
- Each click writes at once; undo keeps the last 5 steps; redo exists; undo/redo refuse when the file changed from outside.
- Tree: WAI-ARIA tree pattern, checkbox `aria-checked` true/false/mixed; `+ novos` marks folders that pick up future files.
- Nothing of the glob model is kept, adapted or read for compatibility.

## Review Focus

1. **File names with spaces and accents** (`decisões/a b.md`) — listed, resolved and clicked like any other; git's `-z` output keeps them intact.
2. **Hand-edited config that is not valid JSON, or has a wrong type** — the panel and the CLI say what is wrong in one line instead of a traceback.
3. **No `.km/config.json` at all** — nothing is tracked, the tree shows every candidate unticked, and the first click creates the file.
4. **A file listed in `files` that git ignores or that no longer exists** — listed in the tree (*não existe mais* when absent), never silently dropped from the config.
5. **A click arriving after an agent changed the config** — refused, tree reloaded, nothing overwritten.

---

## File Structure

| File | Responsibility |
|---|---|
| `km/acompanhamento.py` (new) | config IO and validation, `decisao`, `normalizar`, `candidatos`, `documentos`, `marcar`, `desmarcar`, `arvore` |
| `km/chancela.py` | loses `DEFAULT_CONFIG`, `load_config`, `_casa`, `documentos`, `fnmatch`; gains `pendencia_do_arquivo` (moved from `cli._pct`) |
| `km/cli.py` | uses `acompanhamento.documentos`; `km init` writes empty lists; vocabulary *acompanhado* |
| `km/serve.py` | serves `km/painel.html`; `/api/arquivos` routes; loses dead `diff_inline`, `diff_palavras`, `_vencida` |
| `km/painel.html` (new) | the page, moved verbatim from `serve.PAGE`, then the Arquivos view |
| `tests/test_acompanhamento.py` (new) | resolution, normalisation, clicks, candidates, tree, safety |
| `tests/test_chancela.py` | callers updated to the new config |
| `README.md`, `docs/chancel.md` | vocabulary and the new screen |

---

### Task 1: The tracking model

**Files:**
- Create: `km/acompanhamento.py`
- Modify: `km/chancela.py` (remove lines from `#: Which files the chancel covers` through the `DEFAULT_CONFIG` block, and from `def load_config` through the end of `def documentos`; remove `import fnmatch`; add `pendencia_do_arquivo`)
- Modify: `km/cli.py` (`_pct` → `ch.pendencia_do_arquivo`; `ch.documentos` → `ac.documentos`)
- Modify: `km/serve.py` (`ch.documentos` → `ac.documentos`; `cli._pct` → `ch.pendencia_do_arquivo`)
- Test: `tests/test_acompanhamento.py`

**Interfaces:**
- Produces:
  - `acompanhamento.CHAVES: tuple[str, ...] = ("folders", "files", "except")`
  - `acompanhamento.ConfigInvalida(Exception)`
  - `acompanhamento.vazia() -> dict`
  - `acompanhamento.carregar(root: Path) -> dict` (raises `ConfigInvalida`)
  - `acompanhamento.gravar(root: Path, cfg: dict) -> None` (atomic)
  - `acompanhamento.sha_config(cfg: dict) -> str`
  - `acompanhamento.decisao(rel: str, cfg: dict) -> bool`
  - `acompanhamento.herdado(caminho: str, cfg: dict) -> bool`
  - `acompanhamento.normalizar(cfg: dict) -> dict`
  - `acompanhamento.candidatos(root: Path) -> list[str]`
  - `acompanhamento.documentos(root: Path, cfg: dict | None = None) -> list[str]`
  - `chancela.pendencia_do_arquivo(s: Situacao) -> tuple[int, int]`

- [ ] **Step 1: Write the failing tests** — `tests/test_acompanhamento.py`

```python
"""Run: python3 -m unittest discover -s tests -t . -v"""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from km import acompanhamento as ac


def git(root, *args):
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


class RepoTest(unittest.TestCase):
    ARQUIVOS = ["README.md", "requisitos.md", "decisoes/0001-a.md", "decisoes/README.md",
                "decisoes/antigas/0000-x.md", "design/v1.md", "decisões/a b.md"]

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        git(self.dir, "init", "-q", "-b", "main")
        git(self.dir, "config", "user.email", "t@t")
        git(self.dir, "config", "user.name", "t")
        for rel in self.ARQUIVOS:
            (self.dir / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.dir / rel).write_text(f"# {rel}\n\ntexto\n", encoding="utf-8")
        (self.dir / "node_modules" / "pkg").mkdir(parents=True)
        (self.dir / "node_modules" / "pkg" / "README.md").write_text("# lixo\n")
        (self.dir / ".gitignore").write_text("node_modules/\n.km/\n")
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-qm", "i")

    def tearDown(self):
        shutil.rmtree(self.dir)


class DecisaoTest(unittest.TestCase):
    def test_the_closest_decision_wins(self):
        cfg = {"folders": ["decisoes"], "files": ["decisoes/antigas/0000-x.md"],
               "except": ["decisoes/README.md", "decisoes/antigas"]}
        self.assertTrue(ac.decisao("decisoes/0001-a.md", cfg))
        self.assertFalse(ac.decisao("decisoes/README.md", cfg))
        self.assertTrue(ac.decisao("decisoes/antigas/0000-x.md", cfg))   # arquivo vence a pasta
        self.assertFalse(ac.decisao("decisoes/antigas/0001-y.md", cfg))
        self.assertFalse(ac.decisao("design/v1.md", cfg))

    def test_a_folder_rule_takes_files_that_do_not_exist_yet(self):
        self.assertTrue(ac.decisao("decisoes/9999-nova.md", {"folders": ["decisoes"], "files": [], "except": []}))

    def test_dot_is_the_whole_repository(self):
        self.assertTrue(ac.decisao("qualquer/coisa.md", {"folders": ["."], "files": [], "except": []}))

    def test_at_the_same_level_except_wins(self):
        cfg = {"folders": ["decisoes"], "files": ["x.md"], "except": ["decisoes", "x.md"]}
        self.assertFalse(ac.decisao("decisoes/0001-a.md", cfg))
        self.assertFalse(ac.decisao("x.md", cfg))


class NormalizarTest(unittest.TestCase):
    def test_redundant_entries_go_and_lists_are_sorted(self):
        cfg = {"folders": ["decisoes", "decisoes/antigas", "decisoes"],
               "files": ["decisoes/0001-a.md", "requisitos.md", "README.md"],
               "except": ["design/v1.md", "decisoes/README.md"]}
        self.assertEqual(ac.normalizar(cfg), {
            "folders": ["decisoes"],                    # antigas já está coberta
            "files": ["README.md", "requisitos.md"],    # 0001-a já está coberto
            "except": ["decisoes/README.md"],           # design/v1.md não tinha regra acima
        })

    def test_an_exception_between_keeps_the_entry_below(self):
        cfg = {"folders": ["decisoes", "decisoes/antigas/novas"], "files": [],
               "except": ["decisoes/antigas"]}
        self.assertEqual(ac.normalizar(cfg)["folders"], ["decisoes", "decisoes/antigas/novas"])

    def test_normalising_twice_changes_nothing(self):
        cfg = {"folders": ["b", "a"], "files": ["c.md"], "except": ["a/x.md"]}
        self.assertEqual(ac.normalizar(ac.normalizar(cfg)), ac.normalizar(cfg))


class ConfigTest(RepoTest):
    def test_no_config_tracks_nothing(self):
        self.assertEqual(ac.carregar(self.dir), ac.vazia())
        self.assertEqual(ac.documentos(self.dir), [])

    def test_the_old_format_is_rejected_naming_the_key(self):
        (self.dir / ".km").mkdir()
        (self.dir / ".km" / "config.json").write_text('{"include": ["**/*.md"]}')
        with self.assertRaises(ac.ConfigInvalida) as e:
            ac.carregar(self.dir)
        self.assertIn("include", str(e.exception))

    def test_invalid_json_and_bad_paths_say_what_is_wrong(self):
        (self.dir / ".km").mkdir()
        cfg = self.dir / ".km" / "config.json"
        cfg.write_text("{ isto não é json")
        with self.assertRaises(ac.ConfigInvalida):
            ac.carregar(self.dir)
        for ruim in ('{"files": "a.md"}', '{"files": ["../fora.md"]}', '{"folders": ["a/"]}',
                     '{"files": ["/abs.md"]}', '{"files": ["."]}'):
            cfg.write_text(ruim)
            with self.assertRaises(ac.ConfigInvalida, msg=ruim):
                ac.carregar(self.dir)

    def test_writing_is_atomic_and_normalised(self):
        ac.gravar(self.dir, {"folders": ["decisoes"], "files": ["decisoes/0001-a.md"], "except": []})
        dados = json.loads((self.dir / ".km" / "config.json").read_text())
        self.assertEqual(dados, {"folders": ["decisoes"], "files": [], "except": []})
        self.assertEqual([p.name for p in (self.dir / ".km").iterdir()], ["config.json"])


class CandidatosTest(RepoTest):
    def test_git_decides_what_exists(self):
        c = ac.candidatos(self.dir)
        self.assertIn("decisões/a b.md", c)
        self.assertNotIn("node_modules/pkg/README.md", c)

    def test_a_new_file_git_does_not_know_yet_is_a_candidate(self):
        (self.dir / "decisoes" / "0002-b.md").write_text("# nova\n")
        self.assertIn("decisoes/0002-b.md", ac.candidatos(self.dir))

    def test_documents_are_the_candidates_the_config_tracks(self):
        ac.gravar(self.dir, {"folders": ["decisoes"], "files": ["requisitos.md"],
                             "except": ["decisoes/README.md"]})
        self.assertEqual(ac.documentos(self.dir),
                         ["decisoes/0001-a.md", "decisoes/antigas/0000-x.md", "requisitos.md"])

    def test_a_listed_file_git_ignores_still_counts_if_it_is_on_disk(self):
        ac.gravar(self.dir, {"folders": [], "files": ["node_modules/pkg/README.md"], "except": []})
        self.assertEqual(ac.documentos(self.dir), ["node_modules/pkg/README.md"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_acompanhamento -v`
Expected: `ModuleNotFoundError: No module named 'km.acompanhamento'`

- [ ] **Step 3: Write `km/acompanhamento.py`**

```python
"""Which documents the chancel covers: three lists and the closest decision.

`.km/config.json` holds `folders`, `files` and `except`. A folder is a rule — it takes the
Markdown files under it, including the ones created later; a file is taken on its own; an
exception leaves a file or folder out of a rule above it. For any path the closest decision
wins, walking from the file up to the root. The design is in docs/tracked-files.md.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

KM_DIR = ".km"
CONFIG = "config.json"
CHAVES = ("folders", "files", "except")


class ConfigInvalida(Exception):
    """The config says something `km` cannot read. The message is shown as it is."""


def vazia() -> dict:
    return {k: [] for k in CHAVES}


def _caminho_valido(caminho: object, pasta: bool) -> bool:
    if not isinstance(caminho, str) or not caminho:
        return False
    if caminho == ".":
        return pasta
    return (not caminho.startswith("/") and not caminho.endswith("/")
            and "\\" not in caminho and ".." not in caminho.split("/"))


def carregar(root: Path) -> dict:
    """The config, validated. No file means nothing is tracked."""
    path = root / KM_DIR / CONFIG
    if not path.exists():
        return vazia()
    try:
        dados = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigInvalida(f".km/config.json não é JSON válido (linha {e.lineno}): {e.msg}")
    if not isinstance(dados, dict):
        raise ConfigInvalida(".km/config.json tem que ser um objeto com folders, files e except")
    sobra = sorted(set(dados) - set(CHAVES))
    if sobra:
        raise ConfigInvalida(f".km/config.json tem chave(s) que o km não lê: {', '.join(sobra)}"
                             " — o formato é folders, files, except")
    cfg = vazia()
    for chave in CHAVES:
        lista = dados.get(chave, [])
        if not isinstance(lista, list):
            raise ConfigInvalida(f".km/config.json: `{chave}` tem que ser uma lista")
        for caminho in lista:
            if not _caminho_valido(caminho, pasta=chave != "files"):
                raise ConfigInvalida(f".km/config.json: caminho inválido em `{chave}`: {caminho!r}"
                                     " — relativo, com /, sem .. e sem / no fim")
        cfg[chave] = list(lista)
    return cfg


def sha_config(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(normalizar(cfg), sort_keys=True).encode()).hexdigest()[:12]


def gravar(root: Path, cfg: dict) -> None:
    """Write the config normalised, atomically: a reader never sees half a file."""
    d = root / KM_DIR
    d.mkdir(parents=True, exist_ok=True)
    texto = json.dumps(normalizar(cfg), indent=2, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(texto)
        os.replace(tmp, d / CONFIG)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _pais(caminho: str) -> list[str]:
    """The folders above a path, deepest first, without "."."""
    partes = caminho.split("/")[:-1] if caminho != "." else []
    return ["/".join(partes[:i]) for i in range(len(partes), 0, -1)]


def herdado(caminho: str, cfg: dict) -> bool:
    """The decision a path gets from the folders above it, ignoring any entry for itself."""
    for pasta in _pais(caminho):
        if pasta in cfg["except"]:
            return False
        if pasta in cfg["folders"]:
            return True
    return caminho != "." and "." in cfg["folders"]


def decisao(rel: str, cfg: dict) -> bool:
    """Is this file tracked? The closest decision wins; at the same level, except wins."""
    if rel in cfg["except"]:
        return False
    if rel in cfg["files"]:
        return True
    return herdado(rel, cfg)


def normalizar(cfg: dict) -> dict:
    """The same decisions, with nothing redundant, sorted — so the file stays readable."""
    pastas = sorted(set(cfg["folders"]))
    arquivos = sorted(set(cfg["files"]))
    excecoes = sorted(set(cfg["except"]))
    bruto = {"folders": pastas, "files": arquivos, "except": excecoes}
    pastas = [p for p in pastas if p not in excecoes and (p == "." or not herdado(p, bruto))]
    limpo = {"folders": pastas, "files": [], "except": excecoes}
    excecoes = [e for e in excecoes if herdado(e, limpo)]
    limpo = {"folders": pastas, "files": [], "except": excecoes}
    arquivos = [a for a in arquivos if a not in excecoes and not herdado(a, limpo)]
    return {"folders": pastas, "files": arquivos, "except": excecoes}


def candidatos(root: Path) -> list[str]:
    """The Markdown files git knows about or would add — `.gitignore` respected."""
    r = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard",
                        "--", "*.md"], cwd=root, capture_output=True)
    if r.returncode != 0:
        return []
    return sorted({p for p in r.stdout.decode("utf-8").split("\0") if p})


def documentos(root: Path, cfg: dict | None = None) -> list[str]:
    """The files the chancel covers today: tracked candidates, plus files named explicitly
    that exist on disk even if git ignores them — naming a file is a decision."""
    cfg = cfg if cfg is not None else carregar(root)
    achados = {c for c in candidatos(root) if decisao(c, cfg)}
    achados |= {f for f in cfg["files"] if (root / f).is_file() and decisao(f, cfg)}
    return sorted(achados)
```

- [ ] **Step 4: Remove the glob model from `km/chancela.py` and move `_pct` there**

Delete `import fnmatch`, the `#: Which files the chancel covers…` comment with `DEFAULT_CONFIG`, and the whole `# ---- which files` section (`load_config`, `_casa`, `documentos`). Keep `KM_DIR` only if still referenced (it is not after this task — delete it and `CONFIG` too; `acompanhamento` owns them). Add after `percentual`:

```python
def pendencia_do_arquivo(s: "Situacao") -> tuple[int, int]:
    """(characters to decide, characters in the file). A file never chancelled is all of it."""
    if not s.tem_chancela:
        n = _conta(s.depois)
        return n, n
    return pendencia(s.antes, s.depois, s.mudancas)
```

In `km/cli.py`: delete `_pct`; replace every `_pct(` with `ch.pendencia_do_arquivo(`; add `from . import acompanhamento as ac`; replace `ch.documentos(root)` with `ac.documentos(root)`. In `km/serve.py`: add `from . import acompanhamento as ac`; replace `ch.documentos(root)` with `ac.documentos(root)` and `cli._pct(` with `ch.pendencia_do_arquivo(`.

- [ ] **Step 5: Point the existing tests at the new config**

In `tests/test_chancela.py`, `RepoTest.setUp` tracks nothing now; add after the initial commit:

```python
        from km import acompanhamento as ac
        ac.gravar(self.dir, {"folders": ["."], "files": [], "except": []})
```

- [ ] **Step 6: Run everything**

Run: `python3 -m unittest discover -s tests -t . -v`
Expected: all pass. `grep -rn "fnmatch\|DEFAULT_CONFIG\|_casa\|load_config\|rglob" km/` prints nothing.

- [ ] **Step 7: Commit**

```bash
git add km/acompanhamento.py km/chancela.py km/cli.py km/serve.py tests/
git commit -m "Tracked files: three lists and the closest decision, over git's candidates"
```

---

### Task 2: The tree and the clicks

**Files:**
- Modify: `km/acompanhamento.py` (add `marcar`, `desmarcar`, `rotulo`, `arvore`)
- Test: `tests/test_acompanhamento.py`

**Interfaces:**
- Consumes: Task 1's `decisao`, `herdado`, `normalizar`, `candidatos`, `carregar`, `sha_config`; `chancela.arquivos`, `chancela.situacao`, `chancela.pendencia_do_arquivo`, `chancela.percentual`.
- Produces:
  - `marcar(cfg: dict, caminho: str, pasta: bool) -> dict`
  - `desmarcar(cfg: dict, caminho: str, pasta: bool) -> dict`
  - `rotulo(root: Path, antes: dict, depois: dict, caminho: str, pasta: bool, marcou: bool) -> str`
  - `arvore(root: Path) -> dict` — `{"raiz": No, "sha": str, "config": dict, "erro": str}` where `No` is `{"nome", "caminho", "tipo": "pasta"|"arquivo", "filhos": [No], "marcado": "sim"|"nao"|"misto", "novos": bool, "regra_propria": bool, "acompanhados": int, "total": int, "excecoes": int, "estado": str, "excecao": bool}`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_acompanhamento.py`)

```python
class CliqueTest(unittest.TestCase):
    def test_ticking_a_file_adds_it_or_lifts_its_exception(self):
        self.assertEqual(ac.marcar(ac.vazia(), "requisitos.md", pasta=False)["files"], ["requisitos.md"])
        cfg = {"folders": ["decisoes"], "files": [], "except": ["decisoes/README.md"]}
        self.assertEqual(ac.marcar(cfg, "decisoes/README.md", pasta=False),
                         {"folders": ["decisoes"], "files": [], "except": []})

    def test_unticking_a_file_under_a_rule_makes_an_exception(self):
        cfg = {"folders": ["decisoes"], "files": [], "except": []}
        self.assertEqual(ac.desmarcar(cfg, "decisoes/README.md", pasta=False)["except"],
                         ["decisoes/README.md"])
        self.assertEqual(ac.desmarcar({"folders": [], "files": ["a.md"], "except": []}, "a.md", False),
                         ac.vazia())

    def test_ticking_a_mixed_folder_clears_what_is_below(self):
        cfg = {"folders": [], "files": ["decisoes/0001-a.md"], "except": []}
        self.assertEqual(ac.marcar(cfg, "decisoes", pasta=True),
                         {"folders": ["decisoes"], "files": [], "except": []})
        cfg = {"folders": ["decisoes"], "files": [], "except": ["decisoes/README.md", "decisoes/antigas"]}
        self.assertEqual(ac.marcar(cfg, "decisoes", pasta=True)["except"], [])

    def test_unticking_a_folder_under_a_parent_rule_makes_it_an_exception(self):
        cfg = {"folders": ["decisoes"], "files": [], "except": []}
        self.assertEqual(ac.desmarcar(cfg, "decisoes/antigas", pasta=True)["except"], ["decisoes/antigas"])
        self.assertEqual(ac.desmarcar(cfg, "decisoes", pasta=True), ac.vazia())

    def test_a_single_file_inside_an_excluded_subfolder(self):
        cfg = {"folders": ["decisoes"], "files": [], "except": ["decisoes/antigas"]}
        novo = ac.marcar(cfg, "decisoes/antigas/0000-x.md", pasta=False)
        self.assertTrue(ac.decisao("decisoes/antigas/0000-x.md", novo))
        self.assertFalse(ac.decisao("decisoes/antigas/outra.md", novo))

    def test_the_root(self):
        self.assertEqual(ac.marcar({"folders": [], "files": ["a.md"], "except": ["b.md"]}, ".", True),
                         {"folders": ["."], "files": [], "except": []})
        self.assertEqual(ac.desmarcar({"folders": ["."], "files": [], "except": []}, ".", True), ac.vazia())


class ArvoreTest(RepoTest):
    def no(self, arv, caminho):
        pilha = [arv["raiz"]]
        while pilha:
            n = pilha.pop()
            if n["caminho"] == caminho:
                return n
            pilha += n.get("filhos", [])
        raise KeyError(caminho)

    def test_a_folder_with_an_exception_and_a_folder_picked_by_hand_are_both_mixed(self):
        ac.gravar(self.dir, {"folders": ["decisoes"], "files": ["design/v1.md"],
                             "except": ["decisoes/README.md"]})
        (self.dir / "design" / "v2.md").write_text("# v2\n")
        arv = ac.arvore(self.dir)
        dec, des = self.no(arv, "decisoes"), self.no(arv, "design")
        self.assertEqual((dec["marcado"], dec["novos"], dec["excecoes"]), ("misto", True, 1))
        self.assertEqual((des["marcado"], des["novos"]), ("misto", False))
        self.assertEqual((dec["acompanhados"], dec["total"]), (2, 3))

    def test_file_states(self):
        from km import chancela as ch
        ac.gravar(self.dir, {"folders": [], "files": ["requisitos.md", "README.md"], "except": []})
        ch.escrever(self.dir, {"requisitos.md": (self.dir / "requisitos.md").read_text(),
                               "design/v1.md": "# velho\n"}, "chancela")
        (self.dir / "requisitos.md").write_text("# requisitos.md\n\ntexto mudado\n")
        arv = ac.arvore(self.dir)
        self.assertTrue(self.no(arv, "requisitos.md")["estado"].endswith("a aprovar"))
        self.assertEqual(self.no(arv, "README.md")["estado"], "sem chancela")
        self.assertEqual(self.no(arv, "design/v1.md")["estado"], "pausado · chancela guardada")
        self.assertEqual(self.no(arv, "decisoes/0001-a.md")["estado"], "—")

    def test_a_listed_file_that_is_gone_is_shown_not_dropped(self):
        ac.gravar(self.dir, {"folders": [], "files": ["sumiu.md"], "except": []})
        self.assertEqual(self.no(ac.arvore(self.dir), "sumiu.md")["estado"], "não existe mais")
        self.assertEqual(ac.carregar(self.dir)["files"], ["sumiu.md"])

    def test_untracking_keeps_the_chancel(self):
        from km import chancela as ch
        ac.gravar(self.dir, {"folders": [], "files": ["requisitos.md"], "except": []})
        ch.escrever(self.dir, {"requisitos.md": "# antes\n"}, "chancela")
        antes = ch.chancelado(self.dir, "requisitos.md")
        ac.gravar(self.dir, ac.desmarcar(ac.carregar(self.dir), "requisitos.md", False))
        self.assertEqual(ch.chancelado(self.dir, "requisitos.md"), antes)
        self.assertEqual(self.no(ac.arvore(self.dir), "requisitos.md")["estado"],
                         "pausado · chancela guardada")

    def test_a_broken_config_is_reported_not_raised(self):
        (self.dir / ".km").mkdir(exist_ok=True)
        (self.dir / ".km" / "config.json").write_text('{"include": []}')
        arv = ac.arvore(self.dir)
        self.assertIn("include", arv["erro"])
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m unittest tests.test_acompanhamento -v`
Expected: FAIL — `AttributeError: module 'km.acompanhamento' has no attribute 'marcar'`

- [ ] **Step 3: Implement** (append to `km/acompanhamento.py`)

```python
def _abaixo(caminho: str, outro: str) -> bool:
    return caminho == "." or outro.startswith(caminho + "/")


def _limpar_abaixo(cfg: dict, caminho: str) -> dict:
    return {k: [p for p in cfg[k] if not _abaixo(caminho, p)] for k in CHAVES}


def marcar(cfg: dict, caminho: str, pasta: bool) -> dict:
    """Tick a file or folder, as a tri-state tree does."""
    novo = {k: list(v) for k, v in cfg.items()}
    novo["except"] = [e for e in novo["except"] if e != caminho]
    if pasta:
        novo = _limpar_abaixo(novo, caminho)
        novo["folders"].append(caminho)
    elif not decisao(caminho, novo):
        novo["files"].append(caminho)
    return normalizar(novo)


def desmarcar(cfg: dict, caminho: str, pasta: bool) -> dict:
    """Untick a file or folder. Under a rule it becomes an exception; the chancel is kept."""
    novo = {k: list(v) for k, v in cfg.items()}
    novo["files"] = [f for f in novo["files"] if f != caminho]
    novo["folders"] = [f for f in novo["folders"] if f != caminho]
    if pasta:
        novo = _limpar_abaixo(novo, caminho)
        if caminho != "." and herdado(caminho, novo):
            novo["except"].append(caminho)
    elif decisao(caminho, novo):
        novo["except"].append(caminho)
    return normalizar(novo)


def rotulo(root: Path, antes: dict, depois: dict, caminho: str, pasta: bool, marcou: bool) -> str:
    """One line saying what the click did, in terms of files."""
    from . import chancela as ch

    ja, agora = set(documentos(root, antes)), set(documentos(root, depois))
    entraram, sairam = len(agora - ja), len(ja - agora)
    nome = "o repositório inteiro" if caminho == "." else caminho + ("/" if pasta else "")
    if pasta and marcou:
        return f"{nome} passou a ser acompanhada (+ novos) · {entraram} arquivo(s) entraram"
    if pasta:
        return f"{nome} saiu do acompanhamento · {sairam} arquivo(s) saíram · as chancelas ficam guardadas"
    if marcou:
        return f"{nome} passou a ser acompanhado"
    guardada = " · a chancela fica guardada" if caminho in ch.arquivos(root) else ""
    return f"{nome} saiu do acompanhamento{guardada}"


def arvore(root: Path) -> dict:
    """The repository as a tree of Markdown files, with what each tick means."""
    from . import chancela as ch

    try:
        cfg = carregar(root)
        erro = ""
    except ConfigInvalida as e:
        cfg, erro = vazia(), str(e)
    cands = set(candidatos(root))
    na_chancela = set(ch.arquivos(root))
    todos = sorted(cands | na_chancela | set(cfg["files"]))

    raiz = {"nome": root.name, "caminho": ".", "tipo": "pasta", "filhos": []}
    pastas = {".": raiz}

    def pasta_de(caminho: str) -> dict:
        if caminho in pastas:
            return pastas[caminho]
        pai = pasta_de(caminho.rsplit("/", 1)[0] if "/" in caminho else ".")
        n = {"nome": caminho.rsplit("/", 1)[-1], "caminho": caminho, "tipo": "pasta", "filhos": []}
        pai["filhos"].append(n)
        pastas[caminho] = n
        return n

    for rel in todos:
        existe = rel in cands or (root / rel).is_file()
        acomp = existe and decisao(rel, cfg)
        if not existe:
            estado = "não existe mais"
        elif acomp:
            s = ch.situacao(root, rel)
            estado = ("sem chancela" if not s.tem_chancela
                      else f"{ch.percentual(*ch.pendencia_do_arquivo(s))} a aprovar" if s.mudancas
                      else "em dia")
        elif rel in na_chancela:
            estado = "pausado · chancela guardada"
        else:
            estado = "—"
        pai = pasta_de(rel.rsplit("/", 1)[0] if "/" in rel else ".")
        pai["filhos"].append({"nome": rel.rsplit("/", 1)[-1], "caminho": rel, "tipo": "arquivo",
                              "marcado": "sim" if acomp else "nao", "estado": estado,
                              "existe": existe, "excecao": rel in cfg["except"]})

    def completar(n: dict) -> tuple[int, int]:
        acomp = total = 0
        for f in n["filhos"]:
            if f["tipo"] == "pasta":
                a, t = completar(f)
            else:
                a, t = (1 if f["marcado"] == "sim" else 0), (1 if f["existe"] else 0)
            acomp, total = acomp + a, total + t
        n["filhos"].sort(key=lambda f: (f["tipo"] == "arquivo", f["nome"].lower()))
        n["acompanhados"], n["total"] = acomp, total
        n["marcado"] = "nao" if acomp == 0 else ("sim" if acomp == total else "misto")
        # `+ novos`: would a Markdown file created here tomorrow be tracked?
        n["novos"] = decisao(("" if n["caminho"] == "." else n["caminho"] + "/") + "\0novo.md", cfg)
        n["regra_propria"] = n["caminho"] in cfg["folders"]
        n["excecoes"] = sum(1 for e in cfg["except"] if _abaixo(n["caminho"], e))
        return acomp, total

    completar(raiz)
    return {"raiz": raiz, "sha": sha_config(cfg), "config": cfg, "erro": erro}
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m unittest discover -s tests -t . -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add km/acompanhamento.py tests/test_acompanhamento.py
git commit -m "Tracked files: the tree and what a click does to the three lists"
```

---

### Task 3: The page out of Python, and the server routes

**Files:**
- Create: `km/painel.html` (the current `serve.PAGE` content, byte for byte, decoded)
- Modify: `km/serve.py` (delete `PAGE = """…"""`, `diff_inline`, `diff_palavras`, `_vencida`; read the page from the file; add three routes and three functions)
- Test: `tests/test_chancela.py` (`PainelTest`) and `tests/test_acompanhamento.py` (`RotaTest`)

**Interfaces:**
- Consumes: Task 2's `arvore`, `marcar`, `desmarcar`, `rotulo`, `carregar`, `gravar`, `sha_config`, `normalizar`, `ConfigInvalida`.
- Produces:
  - `serve.arquivos_clicar(root: Path, pedido: dict) -> dict` — pedido `{"caminho", "pasta": bool, "marcar": bool, "sha"}`; returns `{"ok", "msg"|"erro", "passo": {"rotulo", "antes", "depois"}, "arvore"}`
  - `serve.arquivos_trocar(root: Path, pedido: dict) -> dict` — pedido `{"config", "esperado"}`; returns `{"ok", "erro"?, "arvore"}`
  - HTTP: `GET /api/arquivos`, `POST /api/arquivos`, `POST /api/arquivos/desfazer`

- [ ] **Step 1: Move the page to its own file**

```bash
python3 - <<'EOF'
import sys; sys.path.insert(0, ".")
from pathlib import Path
from km import serve
Path("km/painel.html").write_text(serve.PAGE, encoding="utf-8")
EOF
```

Then in `km/serve.py`, delete the `PAGE = """…"""` assignment and add near the top:

```python
PAGINA = Path(__file__).with_name("painel.html")
```

and in `do_GET` serve `PAGINA.read_bytes()` (read per request, so editing the page needs no restart). Delete `diff_inline`, `diff_palavras` and `_vencida` — none has a caller.

- [ ] **Step 2: Write the failing route tests** (append to `tests/test_acompanhamento.py`)

```python
class RotaTest(RepoTest):
    def setUp(self):
        super().setUp()
        from km import serve
        self.serve = serve

    def clicar(self, caminho, pasta, marcar, sha=None):
        sha = sha or ac.arvore(self.dir)["sha"]
        return self.serve.arquivos_clicar(self.dir, {"caminho": caminho, "pasta": pasta,
                                                     "marcar": marcar, "sha": sha})

    def test_a_click_writes_and_returns_the_step(self):
        r = self.clicar("decisoes", True, True)
        self.assertTrue(r["ok"], r)
        self.assertEqual(ac.carregar(self.dir)["folders"], ["decisoes"])
        self.assertIn("passou a ser acompanhada", r["msg"])
        self.assertEqual(r["passo"]["antes"], ac.vazia())

    def test_a_stale_click_is_refused(self):
        sha_velho = ac.arvore(self.dir)["sha"]
        ac.gravar(self.dir, {"folders": [], "files": ["README.md"], "except": []})   # um agente
        r = self.clicar("decisoes", True, True, sha=sha_velho)
        self.assertFalse(r["ok"])
        self.assertEqual(ac.carregar(self.dir)["files"], ["README.md"])

    def test_undo_and_redo(self):
        passo = self.clicar("decisoes", True, True)["passo"]
        r = self.serve.arquivos_trocar(self.dir, {"config": passo["antes"], "esperado": passo["depois"]})
        self.assertTrue(r["ok"], r)
        self.assertEqual(ac.carregar(self.dir), ac.vazia())
        r = self.serve.arquivos_trocar(self.dir, {"config": passo["depois"], "esperado": passo["antes"]})
        self.assertEqual(ac.carregar(self.dir)["folders"], ["decisoes"])

    def test_undo_refuses_when_the_file_changed_from_outside(self):
        passo = self.clicar("decisoes", True, True)["passo"]
        ac.gravar(self.dir, {"folders": ["decisoes"], "files": ["README.md"], "except": []})
        r = self.serve.arquivos_trocar(self.dir, {"config": passo["antes"], "esperado": passo["depois"]})
        self.assertFalse(r["ok"])
        self.assertIn("mudou por fora", r["erro"])
        self.assertEqual(ac.carregar(self.dir)["files"], ["README.md"])
```

- [ ] **Step 3: Run to verify they fail**

Run: `python3 -m unittest tests.test_acompanhamento.RotaTest -v`
Expected: FAIL — `AttributeError: module 'km.serve' has no attribute 'arquivos_clicar'`

- [ ] **Step 4: Implement** (in `km/serve.py`, before `# ---- the server`)

```python
# ---- which files -------------------------------------------------------------------

def arquivos_clicar(root: Path, pedido: dict) -> dict:
    """One click in the tree: written at once, reported in one line, undoable."""
    try:
        antes = ac.carregar(root)
    except ac.ConfigInvalida as e:
        return {"ok": False, "erro": str(e), "arvore": ac.arvore(root)}
    if pedido.get("sha") != ac.sha_config(antes):
        return {"ok": False, "erro": "a configuração mudou por fora — a tela foi atualizada",
                "arvore": ac.arvore(root)}
    caminho, pasta, marcou = pedido["caminho"], bool(pedido.get("pasta")), bool(pedido.get("marcar"))
    depois = (ac.marcar if marcou else ac.desmarcar)(antes, caminho, pasta)
    ac.gravar(root, depois)
    msg = ac.rotulo(root, antes, depois, caminho, pasta, marcou)
    return {"ok": True, "msg": msg,
            "passo": {"rotulo": msg.split(" · ")[0], "antes": antes, "depois": ac.normalizar(depois)},
            "arvore": ac.arvore(root)}


def arquivos_trocar(root: Path, pedido: dict) -> dict:
    """Undo or redo a step: write `config` only if the file is still `esperado`."""
    try:
        atual = ac.carregar(root)
    except ac.ConfigInvalida as e:
        return {"ok": False, "erro": str(e), "arvore": ac.arvore(root)}
    if ac.normalizar(atual) != ac.normalizar(pedido["esperado"]):
        return {"ok": False, "erro": "a configuração mudou por fora — a tela foi atualizada",
                "arvore": ac.arvore(root)}
    ac.gravar(root, pedido["config"])
    return {"ok": True, "arvore": ac.arvore(root)}
```

Routes in `Handler`: in `do_GET`, `/api/arquivos` → `self._json(ac.arvore(self.root))`, checked **before** `/api/state`; in `do_POST`, read the body once, then `/api/arquivos/desfazer` → `arquivos_trocar`, `/api/arquivos` → `arquivos_clicar`, `/api/act` → `agir` as today.

- [ ] **Step 5: Run everything**

Run: `python3 -m unittest discover -s tests -t . -v`
Expected: all pass; `grep -n 'PAGE = \|diff_inline\|diff_palavras\|_vencida' km/serve.py` prints nothing.

- [ ] **Step 6: Commit**

```bash
git add km/painel.html km/serve.py tests/test_acompanhamento.py
git commit -m "Panel page in its own file; routes to click, undo and redo the tracked files"
```

---

### Task 4: The Arquivos view

**Files:**
- Modify: `km/painel.html`

**Interfaces:**
- Consumes: `GET /api/arquivos`, `POST /api/arquivos`, `POST /api/arquivos/desfazer` (Task 3).

- [ ] **Step 1: The switch and the container.** In the top bar, before `no cursor:`, add:

```html
<div class="vistas" role="tablist">
  <button role="tab" id="aba-revisar" aria-selected="true" onclick="mostrar('revisar')">Revisar</button>
  <button role="tab" id="aba-arquivos" aria-selected="false" onclick="mostrar('arquivos')">Arquivos</button>
</div>
```

wrap the review-only controls (`no cursor`, `comparar com`, `texto inteiro`/`só as mudanças`) in `<span id="so-revisar">`, add `<span id="so-arquivos" hidden>` holding the undo controls:

```html
<span id="so-arquivos" hidden>
  <span class="desfazer">
    <button id="btn-desfazer" onclick="desfazer(1)" disabled>↶ Desfazer</button>
    <button id="btn-historico" onclick="abrirHistorico()" disabled aria-haspopup="menu">▾</button>
    <div id="historico" role="menu" hidden></div>
  </span>
  <button id="btn-refazer" onclick="refazer()" disabled title="Refazer (Ctrl+Shift+Z)">↷</button>
</span>
```

and after `<div class="corpo">…</div>` add `<main id="arquivos" class="arquivos" hidden></main>`.

- [ ] **Step 2: The view logic.** Add to the script:

```js
// ---- a vista Arquivos --------------------------------------------------------------
let vista = 'revisar', ARV = null, abertas = new Set(), focoArq = '.';
// Os últimos 5 passos, e o que foi desfeito, para refazer. Vive na página: a árvore
// sempre mostra o estado atual, e cada passo é barato.
let passos = [], refeitos = [];

function mostrar(v){
  vista = v;
  $('aba-revisar').setAttribute('aria-selected', v === 'revisar');
  $('aba-arquivos').setAttribute('aria-selected', v === 'arquivos');
  $('so-revisar').hidden = v !== 'revisar';
  $('so-arquivos').hidden = v !== 'arquivos';
  document.querySelector('.corpo').hidden = v !== 'revisar';
  $('arquivos').hidden = v !== 'arquivos';
  if (v === 'arquivos') carregarArvore(); else carregar();
}

async function carregarArvore(){
  ARV = await (await fetch('/api/arquivos')).json();
  if (!abertas.size) abrirOndeHa(ARV.raiz);
  desenharArvore();
}

function abrirOndeHa(n){
  // Abre as pastas onde há algo acompanhado; o resto começa fechado.
  if (n.tipo !== 'pasta') return;
  if (n.caminho === '.' || n.acompanhados > 0) abertas.add(n.caminho);
  n.filhos.forEach(abrirOndeHa);
}

const CAIXA = {sim: '☑', nao: '☐', misto: '◐'};
const ARIA = {sim: 'true', nao: 'false', misto: 'mixed'};

function linhaArvore(n, nivel){
  const pasta = n.tipo === 'pasta';
  const aberta = abertas.has(n.caminho);
  const info = pasta
    ? (n.total === 0 ? '' : (n.acompanhados === 0 ? 'nenhum' : `${n.acompanhados} de ${n.total}`))
      + (n.excecoes ? ` · ${n.excecoes} exceç${n.excecoes > 1 ? 'ões' : 'ão'}` : '')
    : (n.excecao ? 'exceção' : n.estado);
  const novos = pasta && n.novos
    ? `<span class="novos ${n.regra_propria ? '' : 'herdado'}" title="${n.regra_propria
        ? 'arquivos novos nesta pasta entram sozinhos' : 'entram sozinhos, pela regra de uma pasta acima'}">+ novos</span>` : '';
  let html = `<div class="no ${foco(n)}" role="treeitem" aria-level="${nivel + 1}"
      aria-checked="${ARIA[n.marcado]}" ${pasta ? `aria-expanded="${aberta}"` : ''}
      data-caminho="${esc(n.caminho)}" tabindex="${n.caminho === focoArq ? 0 : -1}"
      style="padding-left:${12 + nivel * 20}px">
    <span class="seta" onclick="alternar('${esc(n.caminho)}')">${pasta ? (aberta ? '▾' : '▸') : ''}</span>
    <span class="caixa ${n.marcado}" onclick="clicar('${esc(n.caminho)}')">${CAIXA[n.marcado]}</span>
    <span class="nome ${pasta ? 'pasta' : ''}" onclick="${pasta ? `alternar('${esc(n.caminho)}')` : `clicar('${esc(n.caminho)}')`}">${esc(n.caminho === '.' ? n.nome + '/' : n.nome + (pasta ? '/' : ''))}</span>
    ${novos}<span class="info ${estadoClasse(n)}">${esc(info)}</span></div>`;
  if (pasta && aberta) html += `<div role="group">${n.filhos.map(f => linhaArvore(f, nivel + 1)).join('')}</div>`;
  return html;
}
const foco = (n) => n.caminho === focoArq ? 'foco' : '';
function estadoClasse(n){
  if (n.tipo === 'pasta') return '';
  if (n.estado === 'em dia') return 'e-ok';
  if (n.estado.endsWith('a aprovar')) return 'e-ace';
  if (n.estado.startsWith('pausado') || n.estado === 'não existe mais') return 'e-mut';
  return '';
}

function desenharArvore(){
  const a = $('arquivos');
  const erro = ARV.erro ? `<div class="recado ruim">✕ ${esc(ARV.erro)}</div>` : '';
  a.innerHTML = erro + `<div class="arvore" role="tree" aria-multiselectable="true"
    aria-label="arquivos acompanhados">${linhaArvore(ARV.raiz, 0)}</div>`;
  $('btn-desfazer').disabled = $('btn-historico').disabled = !passos.length;
  $('btn-refazer').disabled = !refeitos.length;
  const f = a.querySelector(`[data-caminho="${CSS.escape(focoArq)}"]`);
  if (f && document.activeElement?.closest('.arvore')) f.focus();
}

function acharNo(caminho, n = ARV.raiz){
  if (n.caminho === caminho) return n;
  for (const f of (n.filhos || [])) { const r = acharNo(caminho, f); if (r) return r; }
  return null;
}
function alternar(caminho){
  abertas.has(caminho) ? abertas.delete(caminho) : abertas.add(caminho);
  focoArq = caminho; desenharArvore();
}

async function clicar(caminho){
  const n = acharNo(caminho); if (!n) return;
  focoArq = caminho;
  const r = await (await fetch('/api/arquivos', {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({caminho, pasta: n.tipo === 'pasta', marcar: n.marcado !== 'sim', sha: ARV.sha})})).json();
  ARV = r.arvore;
  recado = r.ok ? '✓ ' + r.msg : '✕ ' + r.erro;
  if (r.ok) { passos.push(r.passo); passos = passos.slice(-5); refeitos = []; }
  desenharRecado(); desenharArvore();
}

async function trocar(config, esperado){
  const r = await (await fetch('/api/arquivos/desfazer', {method: 'POST',
    headers: {'Content-Type': 'application/json'}, body: JSON.stringify({config, esperado})})).json();
  ARV = r.arvore;
  if (!r.ok) { recado = '✕ ' + r.erro; passos = []; refeitos = []; }
  return r.ok;
}
async function desfazer(quantos){
  // Desfaz de trás para frente, um passo de cada vez: cada um confere o anterior.
  for (let k = 0; k < quantos && passos.length; k++) {
    const p = passos[passos.length - 1];
    if (!(await trocar(p.antes, p.depois))) break;
    refeitos.push(passos.pop());
    recado = '↶ desfeito: ' + p.rotulo;
  }
  $('historico').hidden = true;
  desenharRecado(); desenharArvore();
}
async function refazer(){
  const p = refeitos[refeitos.length - 1]; if (!p) return;
  if (await trocar(p.depois, p.antes)) { passos.push(refeitos.pop()); recado = '↷ refeito: ' + p.rotulo; }
  desenharRecado(); desenharArvore();
}
function abrirHistorico(){
  const h = $('historico');
  h.innerHTML = passos.slice().reverse().map((p, i) =>
    `<button role="menuitem" onclick="desfazer(${i + 1})">${esc(p.rotulo)}</button>`).join('');
  h.hidden = !h.hidden;
}
function desenharRecado(){
  const r = $('recado'); r.hidden = !recado; r.textContent = recado;
  r.className = 'recado' + (recado.startsWith('✕') ? ' ruim' : '');
}

// O teclado da árvore é o padrão WAI-ARIA: ↑ ↓ andam, ← → fecham e abrem, espaço marca.
function visiveisArvore(){ return [...document.querySelectorAll('.arvore [role="treeitem"]')].map(e => e.dataset.caminho); }
document.addEventListener('keydown', (e) => {
  if (vista !== 'arquivos') return;
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
    e.preventDefault(); return e.shiftKey ? refazer() : desfazer(1);
  }
  if (!e.target.closest || !e.target.closest('.arvore')) return;
  const vis = visiveisArvore(), i = vis.indexOf(focoArq), n = acharNo(focoArq);
  const ir = (c) => { focoArq = c; desenharArvore(); };
  if (e.key === 'ArrowDown' && i < vis.length - 1) { e.preventDefault(); ir(vis[i + 1]); }
  else if (e.key === 'ArrowUp' && i > 0) { e.preventDefault(); ir(vis[i - 1]); }
  else if (e.key === 'ArrowRight' && n?.tipo === 'pasta' && !abertas.has(focoArq)) { e.preventDefault(); alternar(focoArq); }
  else if (e.key === 'ArrowLeft' && n?.tipo === 'pasta' && abertas.has(focoArq)) { e.preventDefault(); alternar(focoArq); }
  else if (e.key === ' ') { e.preventDefault(); clicar(focoArq); }
});
```

In the existing review keydown handler, return early when `vista !== 'revisar'`; in the automatic reload, skip when `vista !== 'revisar'`.

- [ ] **Step 3: Styles.** Add to the `<style>`:

```css
.vistas{display:flex;border:1px solid var(--rule);border-radius:7px;overflow:hidden}
.vistas button{border:0;border-radius:0;padding:4px 12px}
.vistas button[aria-selected=true]{background:var(--ink);color:var(--bg)}
.arquivos{padding:12px 18px 60px;max-width:1100px}
.arvore{font:13px/1.5 ui-monospace,Menlo,monospace}
.arvore .no{display:flex;gap:8px;align-items:center;padding:3px 10px;border-radius:5px;outline:0}
.arvore .no:hover{background:var(--card)}
.arvore .no.foco{box-shadow:inset 0 0 0 1px var(--acc)}
.arvore .seta{width:12px;color:var(--mut);cursor:pointer;user-select:none}
.arvore .caixa{cursor:pointer;font-size:15px;user-select:none}
.arvore .caixa.sim{color:var(--ok)}.arvore .caixa.misto{color:var(--ace)}.arvore .caixa.nao{color:var(--mut)}
.arvore .nome{cursor:pointer}.arvore .nome.pasta{color:#EDF2F7;font-weight:600}
.arvore .novos{font-size:10.5px;padding:0 7px;border-radius:999px;color:var(--ok);background:var(--ok-bg)}
.arvore .novos.herdado{background:transparent;border:1px dashed var(--ok-bg)}
.arvore .info{margin-left:auto;color:var(--mut);font-size:12px;white-space:nowrap}
.arvore .info.e-ok{color:var(--ok)}.arvore .info.e-ace{color:var(--ace)}.arvore .info.e-mut{opacity:.7}
.desfazer{position:relative;display:inline-flex}
.desfazer #btn-desfazer{border-radius:6px 0 0 6px}.desfazer #btn-historico{border-radius:0 6px 6px 0;border-left:0}
#historico{position:absolute;top:30px;right:0;z-index:30;min-width:280px;display:flex;flex-direction:column;
background:var(--card);border:1px solid var(--rule);border-radius:8px;padding:4px;box-shadow:0 8px 24px #0008}
#historico[hidden]{display:none}
#historico button{text-align:left;border:0;padding:6px 10px;background:transparent;color:var(--ink);cursor:pointer}
#historico button:hover{background:var(--bg)}
```

- [ ] **Step 4: Verify in the browser** (demo repo with `decisoes/`, `design/`, a `.gitignore`d `node_modules`)

Run a CDP script against `km serve` that: opens *Arquivos*; checks the root shows "0 de N"; clicks `decisoes/` and expects `+ novos` and "N de N"; unticks `decisoes/README.md` and expects ◐ with "1 exceção"; ticks one file in `design/` and expects ◐ without `+ novos`; undoes 2 via the ▾ menu and redoes 1; edits `.km/config.json` from outside and expects the undo to be refused. Take a screenshot.
Expected: every check true, console clean.

- [ ] **Step 5: Commit**

```bash
git add km/painel.html
git commit -m "The Arquivos view: a tri-state tree, + novos, and one undo over the last five steps"
```

---

### Task 5: Legacy out, config converted, words and docs

**Files:**
- Modify: `km/cli.py` (`cmd_init`, every "fora do `include`" message, `--novos` help)
- Modify: `vscode/extension.js` (the comment "fora do include")
- Modify: `README.md`, `docs/chancel.md`
- Modify: `~/demo-sla-project/.km/config.json` (converted by hand — not versioned, `.km/` is ignored there)

- [ ] **Step 1: `km init` writes empty lists**

```python
def cmd_init(args) -> int:
    root = _root(args)
    cfg = root / ac.KM_DIR / ac.CONFIG
    if cfg.exists():
        print(f"{cfg} já existe")
        return 0
    ac.gravar(root, ac.vazia())
    print(f"criado {cfg} — nada é acompanhado ainda")
    print("escolha os arquivos no painel: km serve, aba Arquivos")
    return 0
```

- [ ] **Step 2: Vocabulary.** Replace every "está fora do `include` do .km/config.json" with "não é acompanhado — escolha no painel, aba Arquivos"; the extension comment becomes "arquivo não acompanhado: o km não tem nada a dizer". `grep -rn "include" km/ vscode/ README.md docs/chancel.md` prints nothing.

- [ ] **Step 3: Convert the one existing config**

```bash
cat > ~/demo-sla-project/.km/config.json <<'EOF'
{
  "folders": [],
  "files": ["REGISTRO-tasks.md", "contrato-sla-demo.md", "painel-atual.md",
            "painel-monitoramento-chamados.md", "painel-status-vale.md",
            "regras-de-sla.md", "requisitos.md"],
  "except": []
}
EOF
cd ~/demo-sla-project && km pendente --short
```

Expected: the same 7 files as before (`painel-*.md` matched 3), no error.

- [ ] **Step 4: Docs.** README: *Which documents it covers* becomes a short paragraph on the three lists and the *Arquivos* view, linking `docs/tracked-files.md`; the command list's `km init` comment becomes "creates .km/config.json with nothing tracked". `docs/chancel.md`: the line about the `include` opt-in points to `docs/tracked-files.md`. `docs/tracked-files.md`: status becomes **built**.

- [ ] **Step 5: Run everything and commit**

Run: `python3 -m unittest discover -s tests -t . -v`
Expected: all pass.

```bash
git add km/cli.py vscode/extension.js README.md docs/
git commit -m "Tracked files: km init starts empty, the include vocabulary is gone"
```
