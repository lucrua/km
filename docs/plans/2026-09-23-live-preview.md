# Live preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the panel's `contenteditable` columns with CodeMirror 6 editors that hold the file's exact text and show it formatted — markers hidden off the cursor line, paragraphs flowing, ⚠️ ❓ 🚫 as boxes, tables as an editable grid — with a MergeView per change.

**Architecture:** CodeMirror is bundled once into `km/vendor/cm.js` (committed). Our code lives in `km/painel/` as ES modules served by `km serve` under `/static/`: two pure modules (`tabela.js`, `paragrafo.js`), the live-preview extension (`preview.js`) and the glue (`editores.js`). The server sends segments as plain text and stops rendering HTML.

**Tech Stack:** CodeMirror 6 (`@codemirror/*`, `@lezer/highlight`), esbuild (build time only), Node's `node --test` for the pure modules, Python 3.11 stdlib `unittest`, Chrome DevTools Protocol on 9225 for the browser checks.

**Spec:** `docs/live-preview.md`

## Global Constraints

- All work in the worktree `~/knowledge-manager/.worktrees/live-preview`, branch `live-preview`; never touch `master` (the author uses it daily). Try the panel on port **8451**, started from the worktree: `cd ~/demo-sla-project && python3 ~/knowledge-manager/.worktrees/live-preview/bin/km serve --port 8451`.
- The editors hold the file's exact text; no decoration, widget or control may change bytes except the table controls, which rewrite only the table's lines.
- Python stays standard-library only; npm/esbuild run only to build `km/vendor/cm.js`, which is committed.
- Code, identifiers and docs in English; everything shown on screen in Portuguese.
- Paragraph joining (spec "B") has a fallback: if it makes the cursor jump, misplaces a selection or misaligns the two columns and that is not fixed within half a day, ship the file's own lines ("A") and record the ruling.

## Review Focus

1. **Markdown the preview does not know** (setext headings `===`, HTML blocks, footnotes) — shown as plain text, never altered; the byte-identity check in Task 6 runs on a fixture containing them.
2. **Long documents** (`regras-de-sla.md`, ~280 lines, ~20 editors) — the page opens in under 1.5 s, and the 8-second refresh does not rebuild editors when nothing changed (Task 5).
3. **Typing while the refresh fires** — nothing typed is lost (Task 5 browser check).
4. **Ragged tables** (rows with fewer cells than the header), escaped `\|`, and `|` inside inline code — the controls keep the column count consistent and escaped pipes intact (Task 2 tests).
5. **Selecting across hidden markers or a joined paragraph and approving the selection** — the offsets are the document's, so exactly the selected characters are taken (Task 6 browser check).

---

## File Structure

| File | Responsibility |
|---|---|
| `tools/build-cm/package.json`, `tools/build-cm/entrada.js`, `tools/build-cm/README.md` (new) | pinned CodeMirror versions and the one-line build |
| `km/vendor/cm.js` (new, built) | the bundle: every CodeMirror export the panel uses |
| `km/painel/tabela.js` (new) | table source lines: split cells, add/remove row and column |
| `km/painel/paragrafo.js` (new) | the newline ranges to show as spaces |
| `km/painel/preview.js` (new) | the live-preview extension |
| `km/painel/editores.js` (new) | creates the editors and exposes `window.km` to the page |
| `km/painel.html` | loads the modules; mounts editors instead of `contenteditable`; sticky actions |
| `km/serve.py` | serves `/static/…`; segments as plain text; loses the HTML highlighting and diff |
| `tests/js/*.test.mjs` (new) | `node --test` for the bundle exports and the pure modules |
| `tests/test_chancela.py`, `tests/test_acompanhamento.py` | segment shape; static route |

Tasks 1, 2 and 3 touch disjoint files and can run in parallel. Task 4 needs 1 and 2; Task 5 needs 3 and 4; Task 6 needs all.

---

### Task 1: The CodeMirror bundle

**Files:**
- Create: `tools/build-cm/package.json`, `tools/build-cm/entrada.js`, `tools/build-cm/README.md`, `km/vendor/cm.js`
- Test: `tests/js/cm.test.mjs`

**Interfaces:**
- Produces: `km/vendor/cm.js`, an ES module exporting exactly: `EditorState, EditorSelection, StateField, StateEffect, RangeSetBuilder, Compartment, Transaction, Prec` (state); `EditorView, Decoration, ViewPlugin, WidgetType, keymap, drawSelection` (view); `defaultKeymap, history, historyKeymap, indentWithTab` (commands); `syntaxTree, ensureSyntaxTree, syntaxHighlighting, HighlightStyle` (language); `markdown, markdownLanguage` (lang-markdown); `tags` (@lezer/highlight); `MergeView` (merge).

- [ ] **Step 1: Write the failing test** — `tests/js/cm.test.mjs`

```js
// Run: node --test tests/js/
import { test } from 'node:test';
import assert from 'node:assert/strict';

const ESPERADOS = ['EditorState', 'EditorSelection', 'StateField', 'StateEffect', 'RangeSetBuilder',
  'Compartment', 'Transaction', 'Prec', 'EditorView', 'Decoration', 'ViewPlugin', 'WidgetType',
  'keymap', 'drawSelection', 'defaultKeymap', 'history', 'historyKeymap', 'indentWithTab',
  'syntaxTree', 'ensureSyntaxTree', 'syntaxHighlighting', 'HighlightStyle', 'markdown',
  'markdownLanguage', 'tags', 'MergeView'];

test('the bundle exports what the panel uses', async () => {
  const cm = await import('../../km/vendor/cm.js');
  for (const nome of ESPERADOS) assert.ok(cm[nome], `falta ${nome}`);
});

test('the Markdown parser in the bundle knows GFM tables', async () => {
  const { EditorState, markdown, markdownLanguage, ensureSyntaxTree } = await import('../../km/vendor/cm.js');
  const doc = '| a | b |\n|---|---|\n| 1 | 2 |\n';
  const state = EditorState.create({ doc, extensions: [markdown({ base: markdownLanguage })] });
  const nomes = [];
  ensureSyntaxTree(state, doc.length, 1000).iterate({ enter: (n) => { nomes.push(n.name); } });
  assert.ok(nomes.includes('Table'), nomes.join(','));
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `node --test tests/js/`
Expected: FAIL — `Cannot find module …/km/vendor/cm.js`

- [ ] **Step 3: The build recipe**

`tools/build-cm/entrada.js`:

```js
// Everything the panel imports from CodeMirror, in one place. Rebuild with
// `npm install && npm run build` here; the output is committed as km/vendor/cm.js.
export { EditorState, EditorSelection, StateField, StateEffect, RangeSetBuilder, Compartment,
         Transaction, Prec } from '@codemirror/state';
export { EditorView, Decoration, ViewPlugin, WidgetType, keymap, drawSelection } from '@codemirror/view';
export { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands';
export { syntaxTree, ensureSyntaxTree, syntaxHighlighting, HighlightStyle } from '@codemirror/language';
export { markdown, markdownLanguage } from '@codemirror/lang-markdown';
export { tags } from '@lezer/highlight';
export { MergeView } from '@codemirror/merge';
```

`tools/build-cm/package.json` — pin each dependency to the exact version `npm view <pkg> version` prints today (no `^`), e.g.:

```json
{
  "name": "km-build-cm",
  "private": true,
  "type": "module",
  "scripts": {
    "build": "esbuild entrada.js --bundle --format=esm --minify --legal-comments=eof --outfile=../../km/vendor/cm.js"
  },
  "devDependencies": {
    "@codemirror/commands": "<exact>",
    "@codemirror/lang-markdown": "<exact>",
    "@codemirror/language": "<exact>",
    "@codemirror/merge": "<exact>",
    "@codemirror/state": "<exact>",
    "@codemirror/view": "<exact>",
    "@lezer/highlight": "<exact>",
    "esbuild": "<exact>"
  }
}
```

(`<exact>` means: run `npm view <package> version` and write that string. This is a lookup, not a design choice.)

`tools/build-cm/README.md`: three lines — what the bundle is, `npm install && npm run build`, and that `node_modules/` is not committed. Add `tools/build-cm/node_modules/` to the repo's `.gitignore`.

- [ ] **Step 4: Build and run**

Run: `cd tools/build-cm && npm install && npm run build && cd ../.. && ls -l km/vendor/cm.js && node --test tests/js/`
Expected: `cm.js` exists (a few hundred KB); both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/build-cm/package.json tools/build-cm/package-lock.json tools/build-cm/entrada.js tools/build-cm/README.md km/vendor/cm.js tests/js/cm.test.mjs .gitignore
git commit -m "Vendor CodeMirror 6 as one ES module, with the recipe to rebuild it"
```

---

### Task 2: The pure modules — tables and paragraphs

**Files:**
- Create: `km/painel/tabela.js`, `km/painel/paragrafo.js`
- Test: `tests/js/tabela.test.mjs`, `tests/js/paragrafo.test.mjs`

**Interfaces:**
- Produces:
  - `tabela.partes(linha: string) -> {pre, inicial: bool, celulas: string[], final: bool, fim}` and `tabela.montar(p) -> string` (round trip is byte-identical)
  - `tabela.celulas(linha) -> string[]` (trimmed, for display)
  - `tabela.ehSeparador(linha) -> bool`
  - `tabela.inserirLinha(linhas: string[], depoisDe: number) -> string[]` (`depoisDe` ≥ 1: index into `linhas`; 1 = after the separator)
  - `tabela.removerLinha(linhas, i) -> string[]` (throws `Error('o cabeçalho e o separador não saem')` for i < 2)
  - `tabela.inserirColuna(linhas, depoisDe: number) -> string[]` (column index)
  - `tabela.removerColuna(linhas, j) -> string[]` (throws `Error('a última coluna não sai')` when one column is left)
  - `paragrafo.quebrasOcultas(texto: string, paragrafos: {from,to}[], cursor: number) -> {from,to}[]`

- [ ] **Step 1: Write the failing tests**

`tests/js/tabela.test.mjs`:

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as t from '../../km/painel/tabela.js';

const TAB = ['| Coluna | Origem |', '|--------|--------|', '| Delta  | Tasks  |', '| SLA    | QA     |'];

test('split and rebuild are byte-identical', () => {
  for (const l of ['| a | b |', 'a | b', '  | a \\| b | c |  ', '|a|b|', '| `x|y` | z |', '| a | b |   ']) {
    assert.equal(t.montar(t.partes(l)), l);
  }
});

test('an escaped pipe stays inside its cell', () => {
  assert.deepEqual(t.celulas('| a \\| b | c |'), ['a \\| b', 'c']);
});

test('the separator row is recognised', () => {
  assert.ok(t.ehSeparador('|--------|:------:|'));
  assert.ok(!t.ehSeparador('| a | b |'));
});

test('a row inserted after the separator has one empty cell per column', () => {
  const n = t.inserirLinha(TAB, 1);
  assert.equal(n.length, 5);
  assert.deepEqual(t.celulas(n[2]), ['', '']);
  assert.equal(n[3], TAB[2]);                                  // o resto não muda
});

test('the header and the separator cannot be removed, a data row can', () => {
  assert.throws(() => t.removerLinha(TAB, 0), /cabeçalho/);
  assert.throws(() => t.removerLinha(TAB, 1), /cabeçalho/);
  assert.deepEqual(t.removerLinha(TAB, 2), [TAB[0], TAB[1], TAB[3]]);
});

test('a column inserted adds a cell to every row and --- to the separator', () => {
  const n = t.inserirColuna(TAB, 0);
  assert.deepEqual(n.map((l) => t.partes(l).celulas.length), [3, 3, 3, 3]);
  assert.ok(t.ehSeparador(n[1]));
  assert.equal(t.partes(n[2]).celulas[0], t.partes(TAB[2]).celulas[0]);   // célula intocada, bytes iguais
});

test('a column removed leaves the others; the last one cannot go', () => {
  assert.deepEqual(t.removerColuna(TAB, 1).map(t.celulas), [['Coluna'], ['--------'], ['Delta'], ['SLA']]);
  assert.throws(() => t.removerColuna(['| a |', '|---|', '| 1 |'], 0), /última coluna/);
});

test('a ragged row is padded when a column is inserted after its end', () => {
  const rag = ['| a | b | c |', '|---|---|---|', '| 1 |'];
  const n = t.inserirColuna(rag, 2);
  assert.equal(t.partes(n[2]).celulas.length, 4);
});
```

`tests/js/paragrafo.test.mjs`:

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { quebrasOcultas } from '../../km/painel/paragrafo.js';

const texto = 'linha um\nlinha dois\n\noutro um\noutro dois\n';
const paras = [{ from: 0, to: 19 }, { from: 21, to: 39 }];      // "linha um\nlinha dois" e "outro um\noutro dois"

test('newlines inside paragraphs away from the cursor are joined', () => {
  assert.deepEqual(quebrasOcultas(texto, paras, -1), [{ from: 8, to: 9 }, { from: 29, to: 30 }]);
});

test('the paragraph with the cursor shows its real breaks', () => {
  assert.deepEqual(quebrasOcultas(texto, paras, 3), [{ from: 29, to: 30 }]);
});

test('a Markdown hard break is never joined', () => {
  const duro = 'um  \ndois\\\ntrês';
  assert.deepEqual(quebrasOcultas(duro, [{ from: 0, to: duro.length }], -1), []);
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `node --test tests/js/tabela.test.mjs tests/js/paragrafo.test.mjs`
Expected: FAIL — cannot find the modules.

- [ ] **Step 3: Implement** — `km/painel/tabela.js`

```js
// A table as its source lines. Every operation returns new lines; a cell no control
// touched keeps its bytes, padding included, so the file changes only where asked.

export function partes(linha) {
  let ini = 0;
  while (ini < linha.length && (linha[ini] === ' ' || linha[ini] === '\t')) ini++;
  const pre = linha.slice(0, ini);
  let corpo = linha.slice(ini);
  const inicial = corpo.startsWith('|');
  if (inicial) corpo = corpo.slice(1);
  const celulas = [];
  let atual = '';
  for (let k = 0; k < corpo.length; k++) {
    const c = corpo[k];
    if (c === '\\' && k + 1 < corpo.length) { atual += c + corpo[k + 1]; k++; continue; }
    if (c === '|') { celulas.push(atual); atual = ''; continue; }
    atual += c;
  }
  // Terminou numa barra (fora espaços)? Então `atual` é só o que sobra depois dela.
  const final = celulas.length > 0 && atual.trim() === '' && /\|\s*$/.test(corpo);
  if (!final) celulas.push(atual);
  return { pre, inicial, celulas, final, fim: final ? atual : '' };
}

export function montar(p) {
  return p.pre + (p.inicial ? '|' : '') + p.celulas.join('|') + (p.final ? '|' + p.fim : '');
}

export const celulas = (linha) => partes(linha).celulas.map((c) => c.trim());

export const ehSeparador = (linha) => {
  const cs = celulas(linha);
  return cs.length > 0 && cs.every((c) => /^:?-+:?$/.test(c));
};

const colunas = (linhas) => partes(linhas[0]).celulas.length;

function vazia(modelo, n) {
  const p = partes(modelo);
  return montar({ ...p, celulas: Array.from({ length: n }, () => ' '), final: true, fim: '' });
}

export function inserirLinha(linhas, depoisDe) {
  const i = Math.max(1, depoisDe);
  return [...linhas.slice(0, i + 1), vazia(linhas[0], colunas(linhas)), ...linhas.slice(i + 1)];
}

export function removerLinha(linhas, i) {
  if (i < 2) throw new Error('o cabeçalho e o separador não saem');
  return linhas.filter((_, k) => k !== i);
}

export function inserirColuna(linhas, depoisDe) {
  return linhas.map((l, k) => {
    const p = partes(l);
    const cs = [...p.celulas];
    while (cs.length < depoisDe + 1) cs.push(' ');
    cs.splice(depoisDe + 1, 0, k === 1 ? ' --- ' : ' ');
    return montar({ ...p, celulas: cs });
  });
}

export function removerColuna(linhas, j) {
  if (colunas(linhas) <= 1) throw new Error('a última coluna não sai');
  return linhas.map((l) => {
    const p = partes(l);
    if (j >= p.celulas.length) return l;
    return montar({ ...p, celulas: p.celulas.filter((_, k) => k !== j) });
  });
}
```

`km/painel/paragrafo.js`:

```js
// Which line breaks inside paragraphs to show as a space. Pure: the caller gives the
// paragraph ranges (from the Markdown syntax tree) and the cursor; -1 means no cursor,
// as in the read-only chancel column, where every paragraph flows.

export function quebrasOcultas(texto, paragrafos, cursor) {
  const out = [];
  for (const { from, to } of paragrafos) {
    if (cursor >= from && cursor <= to) continue;          // onde você está, as quebras reais
    for (let i = texto.indexOf('\n', from); i !== -1 && i < to; i = texto.indexOf('\n', i + 1)) {
      const antes = texto.slice(Math.max(from, i - 2), i);
      if (antes.endsWith('  ') || antes.endsWith('\\')) continue;   // quebra dura do Markdown
      out.push({ from: i, to: i + 1 });
    }
  }
  return out;
}
```

- [ ] **Step 4: Run to verify they pass**

Run: `node --test tests/js/tabela.test.mjs tests/js/paragrafo.test.mjs`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add km/painel/tabela.js km/painel/paragrafo.js tests/js/tabela.test.mjs tests/js/paragrafo.test.mjs
git commit -m "Tables and paragraphs as pure functions over the source text"
```

---

### Task 3: The server — static modules and plain-text segments

**Files:**
- Modify: `km/serve.py`
- Test: `tests/test_chancela.py` (`PainelTest`), `tests/test_acompanhamento.py` (new `EstaticoTest`)

**Interfaces:**
- Produces:
  - `serve.arquivo_estatico(caminho: str, raizes: dict[str, Path] | None = None) -> Path | None` — `/static/<raiz>/<arquivo>` mapped to `km/vendor` or `km/painel`; `None` for anything else, for `..`, and for files that do not exist
  - segments: `{"tipo": "igual", "linha", "texto", "n_linhas"}` and `{"tipo": "mudanca", "n", "titulo", "linha", "chave", "antes", "agora", "unidades", "bloqueio", "sumidas"}` — no `linhas` key, no HTML anywhere

- [ ] **Step 1: Write the failing tests**

In `tests/test_acompanhamento.py`, append:

```python
class EstaticoTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "painel").mkdir()
        (self.dir / "painel" / "a.js").write_text("export const a = 1;\n")
        (self.dir / "segredo.py").write_text("x = 1\n")
        self.raizes = {"painel": self.dir / "painel"}

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_a_module_is_served(self):
        from km import serve
        self.assertEqual(serve.arquivo_estatico("/static/painel/a.js", self.raizes),
                         self.dir / "painel" / "a.js")

    def test_nothing_outside_the_two_folders(self):
        from km import serve
        for ruim in ("/static/painel/../segredo.py", "/static/outra/a.js", "/static/painel/nao.js",
                     "/static/painel/", "/static/painel/%2e%2e/segredo.py"):
            self.assertIsNone(serve.arquivo_estatico(ruim, self.raizes), ruim)
```

In `tests/test_chancela.py`, replace `test_what_left_is_cut_on_the_left_and_the_right_is_the_file` with:

```python
    def test_a_change_carries_both_texts_and_no_html(self):
        self.escrever(DOC.replace("horas úteis", "horas corridas"))
        [m] = self.mudancas()
        self.assertEqual(m["antes"], "O prazo conta em horas úteis.")
        self.assertEqual(m["agora"], "O prazo conta em horas corridas.")
        self.assertNotIn("linhas", m)
        segs = self.doc()["segmentos"]
        self.assertTrue(all("<" not in (s.get("texto") or "") or "<" in DOC for s in segs))
```

and in `test_consecutive_changed_blocks_are_one_passage` and the other `PainelTest` tests, replace every `m["texto"]` with `m["agora"]`.

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m unittest tests.test_acompanhamento.EstaticoTest tests.test_chancela.PainelTest -v`
Expected: FAIL — `arquivo_estatico` missing; `KeyError: 'antes'`.

- [ ] **Step 3: Implement** (in `km/serve.py`)

Static files:

```python
ESTATICOS = {"vendor": Path(__file__).with_name("vendor"),
             "painel": Path(__file__).with_name("painel")}
TIPOS = {".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8"}


def arquivo_estatico(caminho: str, raizes: dict | None = None) -> Path | None:
    """`/static/<raiz>/<arquivo>` → a file inside km/vendor or km/painel, and nothing else."""
    from urllib.parse import unquote, urlparse

    raizes = raizes or ESTATICOS
    partes = unquote(urlparse(caminho).path).split("/")
    if len(partes) != 4 or partes[1] != "static" or partes[2] not in raizes or not partes[3]:
        return None
    base = raizes[partes[2]].resolve()
    alvo = (base / partes[3]).resolve()
    if alvo.parent != base or not alvo.is_file():
        return None
    return alvo
```

In `do_GET`, first branch:

```python
        if self.path.startswith("/static/"):
            alvo = arquivo_estatico(self.path)
            if alvo is None or alvo.suffix not in TIPOS:
                self._envia(b"nao encontrado", "text/plain; charset=utf-8", 404)
            else:
                self._envia(alvo.read_bytes(), TIPOS[alvo.suffix])
            return
```

Segments as plain text: in `segmentos`, the `igual` entry becomes `{"tipo": "igual", "linha": …, "texto": texto, "n_linhas": …}` (drop `"linhas"`); in `_trecho_mudado`, replace `"texto": agora` and `"linhas": …` with `"antes": antes, "agora": agora`.

Remove, with everything only they use: `marcar`, `realcar`, `so_esquerda`, `_casar`, `_palavras`, `realce_linha`, `realce_inline`, `_classe_da_linha`, and the constants `PALAVRA`, `CERCA`, `TITULO`, `CITACAO`, `ITEM`, `TABELA`, `INLINE`, `MARCAS_TXT` from `serve.py`. Drop imports left unused (`html`, `difflib`, `re` if nothing else uses them — check with `grep`).

- [ ] **Step 4: Run everything**

Run: `python3 -m unittest discover -s tests -t . -v`
Expected: all pass; `grep -n "def marcar\|def realcar\|def so_esquerda\|def _casar\|def _palavras\|def realce_" km/serve.py` prints nothing.

- [ ] **Step 5: Commit**

```bash
git add km/serve.py tests/
git commit -m "Serve the panel's modules; segments as plain text, no HTML from the server"
```

---

### Task 4: The live-preview extension

**Files:**
- Create: `km/painel/preview.js`
- Test: `tests/js/preview.test.mjs`

**Interfaces:**
- Consumes: Task 1's `cm.js` exports; Task 2's `quebrasOcultas`, `celulas`, `inserirLinha`, `removerLinha`, `inserirColuna`, `removerColuna`.
- Produces: `vistaViva({ editavel = true } = {}) -> Extension[]`; `inline(texto: string) -> string` (cell HTML); `decorar(state, editavel) -> DecorationSet` (exported for tests).

- [ ] **Step 1: Write the failing test** — `tests/js/preview.test.mjs`

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { EditorState, EditorSelection } from '../../km/vendor/cm.js';
import { vistaViva, decorar, inline } from '../../km/painel/preview.js';

const doc = '## Título\n\nUm **forte** e um `código`.\nSegunda linha do parágrafo.\n';

function ranges(state, editavel) {
  const out = [];
  decorar(state, editavel).between(0, state.doc.length, (from, to, d) => { out.push([from, to, d.spec]); });
  return out;
}

test('markers are hidden off the cursor line and shown on it', () => {
  const longe = EditorState.create({ doc, selection: EditorSelection.cursor(doc.length),
                                     extensions: vistaViva() });
  const escondidos = ranges(longe, true).filter(([f, t, s]) => t > f && !s.widget && !s.class).map(([f, t]) => doc.slice(f, t));
  assert.ok(escondidos.includes('## '), escondidos.join('|'));
  assert.ok(escondidos.includes('**'));
  const perto = EditorState.create({ doc, selection: EditorSelection.cursor(3), extensions: vistaViva() });
  const agora = ranges(perto, true).filter(([f, t, s]) => t > f && !s.widget && !s.class).map(([f, t]) => doc.slice(f, t));
  assert.ok(!agora.includes('## '));
});

test('the paragraph away from the cursor flows', () => {
  const s = EditorState.create({ doc, selection: EditorSelection.cursor(0), extensions: vistaViva() });
  const quebras = ranges(s, true).filter(([f, t, sp]) => sp.widget && doc.slice(f, t) === '\n');
  assert.equal(quebras.length, 1);
});

test('the editor never changes the text', () => {
  const s = EditorState.create({ doc, extensions: vistaViva() });
  assert.equal(s.doc.toString(), doc);
});

test('cell HTML escapes and formats', () => {
  assert.equal(inline('**a** <b>'), '<b>a</b> &lt;b&gt;');
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `node --test tests/js/preview.test.mjs`
Expected: FAIL — cannot find `preview.js`.

- [ ] **Step 3: Implement** — `km/painel/preview.js`

```js
// Live preview: the document is always the file's exact text; formatting is decoration.
// Off the cursor's line the Markdown markers are hidden, paragraphs flow, ⚠️ ❓ 🚫 quotes
// become coloured boxes and tables become a grid with row and column controls. All of it
// lives in one StateField: hidden line breaks and block widgets are decorations CodeMirror
// accepts only from the state, never from a plugin.
import { EditorView, Decoration, WidgetType, StateField, EditorState, syntaxTree,
         ensureSyntaxTree, markdown, markdownLanguage, syntaxHighlighting, HighlightStyle,
         tags } from '../vendor/cm.js';
import { quebrasOcultas } from './paragrafo.js';
import * as tabela from './tabela.js';

const hoje = () => new Date().toISOString().slice(0, 10);
const esc = (s) => s.replace(/[&<>"]/g, (m) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[m]));

// Markdown inline, só para ler as células da tabela — nunca usado para escrever nada.
export function inline(t) {
  return esc(t)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*|__([^_]+)__/g, (_, a, b) => `<b>${a || b}</b>`)
    .replace(/(^|[^*\w])\*([^*\s][^*]*)\*/g, '$1<i>$2</i>')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<span class="cm-link-texto">$1</span>')
    .replace(/\\\|/g, '|');
}

class Texto extends WidgetType {
  constructor(t, cls) { super(); this.t = t; this.cls = cls; }
  eq(o) { return o.t === this.t && o.cls === this.cls; }
  toDOM() { const s = document.createElement('span'); s.textContent = this.t; if (this.cls) s.className = this.cls; return s; }
}

function controle(rotulo, titulo, fazer) {
  const b = document.createElement('button');
  b.className = 'cm-tab-ctl'; b.textContent = rotulo; b.title = titulo;
  b.addEventListener('mousedown', (e) => {
    e.preventDefault(); e.stopPropagation();
    try { fazer(); } catch (err) { b.title = err.message; b.classList.add('recusado'); }
  });
  return b;
}

class Tabela extends WidgetType {
  constructor(linhas, from, editavel) { super(); this.linhas = linhas; this.from = from; this.editavel = editavel; }
  eq(o) { return o.from === this.from && o.editavel === this.editavel && o.linhas.join('\n') === this.linhas.join('\n'); }
  ignoreEvent() { return true; }
  trocar(view, novas) {
    view.dispatch({ changes: { from: this.from, to: this.from + this.linhas.join('\n').length, insert: novas.join('\n') } });
  }
  toDOM(view) {
    const caixa = document.createElement('div');
    caixa.className = 'cm-tabela';
    const t = document.createElement('table');
    const inicio = [];
    let p = this.from;
    for (const l of this.linhas) { inicio.push(p); p += l.length + 1; }
    this.linhas.forEach((linha, i) => {
      if (i === 1) return;                                   // o separador não aparece
      const tr = document.createElement('tr');
      tabela.celulas(linha).forEach((c, j) => {
        const td = document.createElement(i === 0 ? 'th' : 'td');
        const conteudo = document.createElement('span');
        conteudo.innerHTML = inline(c);
        td.append(conteudo);
        td.addEventListener('mousedown', (e) => {           // clicar na célula abre o texto
          if (e.target.closest('.cm-tab-ctl') || !this.editavel) return;
          e.preventDefault(); view.focus();
          view.dispatch({ selection: { anchor: inicio[i] } });
        });
        if (this.editavel && i === 0) {
          td.append(controle('+', 'inserir coluna à direita', () => this.trocar(view, tabela.inserirColuna(this.linhas, j))),
                    controle('×', 'remover esta coluna', () => this.trocar(view, tabela.removerColuna(this.linhas, j))));
        }
        tr.append(td);
      });
      if (this.editavel) {
        const ctl = document.createElement('td');
        ctl.className = 'cm-tab-linha';
        ctl.append(controle('+', 'inserir linha abaixo', () => this.trocar(view, tabela.inserirLinha(this.linhas, Math.max(i, 1)))));
        if (i >= 2) ctl.append(controle('×', 'remover esta linha', () => this.trocar(view, tabela.removerLinha(this.linhas, i))));
        tr.append(ctl);
      }
      t.append(tr);
    });
    caixa.append(t);
    return caixa;
  }
}

const OCULTAVEIS = new Set(['EmphasisMark', 'CodeMark', 'LinkMark', 'StrikethroughMark']);

export function decorar(state, editavel) {
  const doc = state.doc;
  const arvore = ensureSyntaxTree(state, doc.length, 500) || syntaxTree(state);
  const ativas = new Set();
  if (editavel) {
    for (const r of state.selection.ranges) {
      for (let n = doc.lineAt(r.from).number; n <= doc.lineAt(r.to).number; n++) ativas.add(n);
    }
  }
  const ativa = (pos) => ativas.has(doc.lineAt(pos).number);
  const cursor = editavel ? state.selection.main.head : -1;

  // 1ª passada: parágrafos e tabelas — o que decide as linhas que se juntam ou somem.
  const paragrafos = [], tabelas = [];
  arvore.iterate({ enter: (n) => {
    if (n.name === 'Table') { tabelas.push({ from: n.from, to: n.to }); return false; }
    if (n.name === 'Paragraph') paragrafos.push({ from: n.from, to: n.to });
  } });
  const deco = [];
  const juntas = new Set();                       // inícios de linha que ficam emendados
  for (const q of quebrasOcultas(doc.toString(), paragrafos, cursor)) {
    deco.push(Decoration.replace({ widget: new Texto(' ', 'cm-junta') }).range(q.from, q.to));
    juntas.add(q.to);
  }
  const blocos = [];                              // faixas que viraram grade
  for (const tb of tabelas) {
    if (editavel && cursor >= tb.from && cursor <= tb.to) continue;
    const l1 = doc.lineAt(tb.from), l2 = doc.lineAt(tb.to);
    const linhas = doc.sliceString(l1.from, l2.to).split('\n');
    deco.push(Decoration.replace({ widget: new Tabela(linhas, l1.from, editavel), block: true }).range(l1.from, l2.to));
    blocos.push([l1.from, l2.to]);
  }
  const numaGrade = (pos) => blocos.some(([a, b]) => pos >= a && pos <= b);
  const linha = (from, to, cls) => {
    for (let n = doc.lineAt(from).number; n <= doc.lineAt(to).number; n++) {
      const l = doc.line(n);
      if (!juntas.has(l.from) && !numaGrade(l.from)) deco.push(Decoration.line({ class: cls }).range(l.from));
    }
  };
  const esconder = (from, to) => { if (to > from && !numaGrade(from)) deco.push(Decoration.replace({}).range(from, to)); };
  const depoisEspaco = (to) => (doc.sliceString(to, to + 1) === ' ' ? to + 1 : to);

  // 2ª passada: o resto.
  arvore.iterate({ enter: (n) => {
    const nome = n.name;
    if (nome === 'Table') return false;
    const pai = n.node.parent ? n.node.parent.name : '';
    const m = /^ATXHeading(\d)$/.exec(nome);
    if (m) linha(n.from, n.to, 'cm-h cm-h' + m[1]);
    else if (nome === 'HeaderMark' && !ativa(n.from)) esconder(n.from, depoisEspaco(n.to));
    else if (nome === 'CodeMark' && pai === 'FencedCode') { /* cercas: tratadas em FencedCode */ }
    else if (OCULTAVEIS.has(nome) && !ativa(n.from)) esconder(n.from, n.to);
    else if (nome === 'URL' && pai === 'Link' && !ativa(n.from)) esconder(n.from, n.to);
    else if (nome === 'Link' && !numaGrade(n.from)) deco.push(Decoration.mark({ class: 'cm-link-texto' }).range(n.from, n.to));
    else if (nome === 'QuoteMark' && !ativa(n.from)) esconder(n.from, depoisEspaco(n.to));
    else if (nome === 'Blockquote') {
      const texto = doc.sliceString(n.from, n.to);
      const tipo = /🚫/.test(texto) ? 'veto' : /❓/.test(texto) ? 'pergunta' : /⚠/.test(texto) ? 'alerta' : '';
      linha(n.from, n.to, 'cm-cit' + (tipo ? ' cm-cit-' + tipo : ''));
      if (tipo === 'pergunta') {
        for (const d of texto.matchAll(/\d{4}-\d{2}-\d{2}/g)) {
          if (d[0] < hoje()) deco.push(Decoration.mark({ class: 'cm-vencida' }).range(n.from + d.index, n.from + d.index + 10));
        }
      }
    }
    else if (nome === 'ListMark' && !ativa(n.from) && n.node.parent?.parent?.name === 'BulletList') {
      deco.push(Decoration.replace({ widget: new Texto('•', 'cm-bala') }).range(n.from, n.to));
    }
    else if (nome === 'TaskMarker' && !ativa(n.from)) {
      const feito = /x/i.test(doc.sliceString(n.from, n.to));
      deco.push(Decoration.replace({ widget: new Texto(feito ? '☑' : '☐', 'cm-tarefa') }).range(n.from, n.to));
    }
    else if (nome === 'HorizontalRule') { linha(n.from, n.to, 'cm-hr'); if (!ativa(n.from)) esconder(n.from, n.to); }
    else if (nome === 'FencedCode') {
      linha(n.from, n.to, 'cm-codigo');
      const primeira = doc.lineAt(n.from), ultima = doc.lineAt(n.to);
      for (const l of [primeira, ultima]) if (!ativa(l.from)) deco.push(Decoration.line({ class: 'cm-cerca' }).range(l.from));
    }
  } });
  return Decoration.set(deco, true);
}

const campo = (editavel) => StateField.define({
  create: (s) => decorar(s, editavel),
  update: (valor, tr) => (tr.docChanged || tr.selection ? decorar(tr.state, editavel) : valor),
  provide: (f) => EditorView.decorations.from(f),
});

const estilo = HighlightStyle.define([
  { tag: tags.heading1, fontSize: '1.5em', fontWeight: '700' },
  { tag: tags.heading2, fontSize: '1.3em', fontWeight: '700' },
  { tag: tags.heading3, fontSize: '1.15em', fontWeight: '700' },
  { tag: [tags.heading4, tags.heading5, tags.heading6], fontWeight: '700' },
  { tag: tags.strong, fontWeight: '700' },
  { tag: tags.emphasis, fontStyle: 'italic' },
  { tag: tags.strikethrough, textDecoration: 'line-through' },
  { tag: tags.monospace, fontFamily: 'ui-monospace, Menlo, monospace', fontSize: '0.92em' },
  { tag: tags.link, color: 'var(--acc)' },
  { tag: tags.url, color: 'var(--mut)' },
  { tag: tags.processingInstruction, color: 'var(--mut)' },
]);

export function vistaViva({ editavel = true } = {}) {
  return [markdown({ base: markdownLanguage }), syntaxHighlighting(estilo), campo(editavel),
          EditorView.lineWrapping, EditorState.readOnly.of(!editavel), EditorView.editable.of(editavel)];
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `node --test tests/js/`
Expected: all PASS (the DOM is never touched by `decorar`; widgets are only constructed).

- [ ] **Step 5: Commit**

```bash
git add km/painel/preview.js tests/js/preview.test.mjs
git commit -m "Live preview: markers hidden off the cursor line, flowing paragraphs, callouts, tables as a grid"
```

---

### Task 5: Editors in the page

**Files:**
- Create: `km/painel/editores.js`
- Modify: `km/painel.html`

**Interfaces:**
- Consumes: Task 3's segments (`texto`; `antes`/`agora`/`unidades`/`chave`) and `/static/`; Task 4's `vistaViva`.
- Produces: `window.km` with `editorSimples(lugar, chave, texto, editavel, aoMudar, aoSelecionar)`, `editorMudanca(lugar, chave, antes, agora, editavel, aoMudar, aoSelecionar)`, `destruirTodos()`, `texto(chave)`, `selecao(chave) -> {a, b, rect} | null`, `focado() -> chave | null`, `inserirMarca(chave, modelo)`, `focarFim(chave)`; the event `km-pronto` on `window`.

- [ ] **Step 1: `km/painel/editores.js`**

```js
// The panel's editors: one per unchanged stretch, a MergeView per change. They hold the
// file's text and nothing else; the page asks them for text, dirtiness and selection.
import { EditorView, EditorState, MergeView, keymap, history, historyKeymap, defaultKeymap,
         drawSelection } from '../vendor/cm.js';
import { vistaViva } from './preview.js';

const vivos = new Map();

function extensoes(editavel, aoMudar, aoSelecionar) {
  const ext = [vistaViva({ editavel }), drawSelection()];
  if (editavel) {
    ext.push(history(), keymap.of([...defaultKeymap, ...historyKeymap]),
      EditorView.updateListener.of((u) => {
        if (u.docChanged && aoMudar) aoMudar(u.state.doc.toString());
        if (u.selectionSet && aoSelecionar) aoSelecionar();
      }));
  }
  return ext;
}

export function destruirTodos() { for (const v of vivos.values()) v.destruir(); vivos.clear(); }

export function editorSimples(lugar, chave, texto, editavel, aoMudar, aoSelecionar) {
  const view = new EditorView({ parent: lugar,
    state: EditorState.create({ doc: texto, extensions: extensoes(editavel, aoMudar, aoSelecionar) }) });
  vivos.set(chave, { view, destruir: () => view.destroy() });
}

export function editorMudanca(lugar, chave, antes, agora, editavel, aoMudar, aoSelecionar) {
  // Um trecho que só saiu não tem o que editar do lado de hoje.
  const mv = new MergeView({ parent: lugar, gutter: false,
    a: { doc: antes, extensions: extensoes(false) },
    b: { doc: agora, extensions: extensoes(editavel && agora !== '', aoMudar, aoSelecionar) } });
  vivos.set(chave, { view: mv.b, destruir: () => mv.destroy() });
}

export const texto = (chave) => vivos.get(chave)?.view.state.doc.toString();

export function selecao(chave) {
  const v = vivos.get(chave)?.view;
  const r = v && v.state.selection.main;
  if (!r || r.empty) return null;
  return { a: r.from, b: r.to, rect: v.coordsAtPos(r.from) };
}

export function focado() {
  for (const [chave, v] of vivos) if (v.view.hasFocus) return chave;
  return null;
}

export function inserirMarca(chave, modelo) {
  const v = vivos.get(chave)?.view;
  if (!v) return false;
  // A marca é um bloco próprio: no fim da linha do cursor, com linha em branco antes e depois.
  const l = v.state.doc.lineAt(v.state.selection.main.head);
  v.dispatch({ changes: { from: l.to, insert: '\n\n' + modelo + '\n' },
               selection: { anchor: l.to + 2 + modelo.length } });
  v.focus();
  return true;
}

export function focarFim(chave) {
  const v = vivos.get(chave)?.view;
  if (!v) return;
  v.dispatch({ selection: { anchor: v.state.doc.length } });
  v.focus();
}

window.km = { editorSimples, editorMudanca, destruirTodos, texto, selecao, focado, inserirMarca, focarFim };
window.dispatchEvent(new Event('km-pronto'));
```

- [ ] **Step 2: `km/painel.html` — load the modules and wait for them**

Before the main `<script>`: `<script type="module" src="/static/painel/editores.js"></script>`. At the top of the main script:

```js
// Os editores chegam como módulo, depois deste script; tudo que desenha espera por eles.
const kmPronto = new Promise((ok) => window.km ? ok() : window.addEventListener('km-pronto', ok, { once: true }));
```

In `_carregar`, before `desenhar()`: `await kmPronto;` and skip redrawing when nothing changed, so the 8-second refresh does not rebuild editors:

```js
  const antigo = JSON.stringify(D);
  D = nova; doc = i >= 0 ? i : 0;
  if (D.docs[doc] && !D.docs[doc].cheio) return _carregar(D.docs[doc].file);
  await kmPronto;
  if (!arquivo && JSON.stringify(D) === antigo) return;     // nada mudou: não reconstruir editores
  desenhar();
```

- [ ] **Step 3: `km/painel.html` — mount editors instead of `contenteditable`**

In `desenhar()`: call `km.destruirTodos()` before `$('doc').innerHTML = …`. An unchanged stretch renders `<div class="col agora inteiro"><div class="cm-lugar" data-chave="g:${s.linha}" data-linha="${s.linha}"></div></div><div class="col acoes" data-acoes="g:${s.linha}">${salvarCel('g:' + s.linha)}</div>`. A change renders `<div class="col mudanca-cm inicio-m" id="m${s.n}"><div class="cm-lugar" data-chave="c:${s.chave}" data-linha="${s.linha}"></div></div><div class="col acoes inicio-m" data-acoes="c:${s.chave}"><div class="grudado">${acoesDaMudanca(s)}</div></div>`. After setting `innerHTML`:

```js
  originais = {};
  for (const el of document.querySelectorAll('.cm-lugar')) {
    const chave = el.dataset.chave;
    const s = chave.startsWith('c:') ? mudancas().find((m) => 'c:' + m.chave === chave)
                                     : segs().find((x) => 'g:' + x.linha === chave);
    const hojeTexto = chave.startsWith('c:') ? s.agora : s.texto;
    originais[chave] = hojeTexto;
    const atual = sujos[chave] !== undefined ? sujos[chave] : hojeTexto;
    const mudou = (t) => mexeuTexto(chave, t);
    if (chave.startsWith('c:')) km.editorMudanca(el, chave, s.antes, atual, naChancela(), mudou, mostrarBarraSelecao);
    else km.editorSimples(el, chave, atual, true, mudou, null);
  }
```

Replace `mexeu(el)` with:

```js
function mexeuTexto(chave, texto){
  if (mesmo(texto, originais[chave])) delete sujos[chave]; else sujos[chave] = texto;
  const cel = document.querySelector(`[data-acoes="${CSS.escape(chave)}"]`);
  if (!cel) return;
  const m = chave.startsWith('c:') ? mudancas().find((x) => 'c:' + x.chave === chave) : null;
  const html = m ? acoesDaMudanca(m) : salvarCel(chave);
  cel.innerHTML = chave.startsWith('c:') ? `<div class="grudado">${html}</div>` : html;
}
```

`salvar(chave)` reads the line from `document.querySelector(`.cm-lugar[data-chave="${CSS.escape(chave)}"]`).dataset.linha`. The selection bar:

```js
function selecaoAtual(){
  const chave = km.focado();
  if (!chave || !chave.startsWith('c:') || !naChancela()) return null;
  if (sujos[chave] !== undefined) return {erro: 'salve ou descarte a edição deste trecho antes de aprovar parte dele'};
  const sel = km.selecao(chave), m = mudancas().find((x) => 'c:' + x.chave === chave);
  if (!sel || !m) return null;
  const shas = [], parciais = [];
  for (const u of m.unidades) {
    if (u.ini === u.fim) { if (sel.a <= u.ini && u.ini <= sel.b) shas.push(u.sha); continue; }
    if (sel.b <= u.ini || sel.a >= u.fim) continue;
    if (sel.a <= u.ini && sel.b >= u.fim) shas.push(u.sha);
    else parciais.push({sha: u.sha, ini: Math.max(sel.a, u.ini) - u.ini, fim: Math.min(sel.b, u.fim) - u.ini});
  }
  return (shas.length || parciais.length) ? {shas, parciais, rect: sel.rect} : null;
}
function mostrarBarraSelecao(){
  const barra = $('selecao'), sel = selecaoAtual();
  if (!sel || sel.erro) { barra.hidden = true; return; }
  barra.hidden = false;
  barra.style.top = Math.max(50, sel.rect.top - 40) + 'px';
  barra.style.left = Math.min(innerWidth - 300, Math.max(10, sel.rect.left)) + 'px';
}
```

Marks: `noCursor(marca)` → `const chave = km.focado(); if (!chave) { recado = '✕ clique no texto, onde a marca deve entrar, e depois no botão'; return desenhar(); } km.inserirMarca(chave, modeloDe(marca));`; `marcaNaMudanca(chave, marca)` → `km.focarFim(chave); km.inserirMarca(chave, modeloDe(marca));` where `modeloDe` returns the `MODELO` string (calling it for ❓). Keyboard: Ctrl+S and Esc use `km.focado()` instead of `el.dataset.chave`.

Delete, with their CSS: `fantasma`, `coluna`, `textoDaColuna`, `editavel`, `deslocamento`, `inserir`, `mexeu`, `celula`, the `selectionchange` listener, `.ln*`, `.txt.edit`, `.l-*`, `.m-*`, `.ln.g`, and `.ln.l-tab` with the table scrolling rule.

- [ ] **Step 4: Styles for the editors and the preview**

```css
.cm-editor{background:transparent;color:var(--ink);font:14.5px/1.62 system-ui,-apple-system,"Segoe UI",sans-serif}
.cm-editor.cm-focused{outline:0}
.cm-content{padding:2px 0;caret-color:var(--acc)}
.cm-line.cm-h{padding-top:.35em}
.cm-link-texto{color:var(--acc)}
.cm-line.cm-cit{border-left:3px solid var(--rule);padding-left:10px;color:#B9C6D2}
.cm-line.cm-cit-alerta{border-color:var(--ace);background:color-mix(in srgb,var(--ace-bg) 55%,transparent)}
.cm-line.cm-cit-pergunta{border-color:var(--val);background:color-mix(in srgb,var(--val-bg) 55%,transparent)}
.cm-line.cm-cit-veto{border-color:var(--neg);background:color-mix(in srgb,var(--neg-bg) 55%,transparent)}
.cm-vencida{color:var(--neg);font-weight:700}
.cm-line.cm-codigo{font-family:ui-monospace,Menlo,monospace;font-size:.92em;background:var(--card)}
.cm-line.cm-cerca{font-size:0;line-height:6px}
.cm-line.cm-hr{border-bottom:1px solid var(--rule);color:transparent}
.cm-bala{color:var(--mut);padding-right:2px}.cm-tarefa{color:var(--acc)}
.cm-tabela{overflow-x:auto;margin:4px 0}
.cm-tabela table{border-collapse:collapse;font-size:13.5px}
.cm-tabela th,.cm-tabela td{border:1px solid var(--rule);padding:4px 8px;vertical-align:top;position:relative}
.cm-tabela th{background:var(--card);font-weight:700}
.cm-tab-ctl{display:none;font:inherit;font-size:11px;padding:0 5px;margin-left:4px;border-radius:4px;
  border:1px solid var(--rule);background:var(--bg);color:var(--mut);cursor:pointer}
.cm-tabela tr:hover .cm-tab-ctl,.cm-tabela th:hover .cm-tab-ctl{display:inline-block}
.cm-tab-ctl.recusado{border-color:var(--neg);color:var(--neg)}
.cm-tab-linha{border:0 !important;background:transparent;white-space:nowrap}
.col.mudanca-cm{grid-column:1 / 3;padding:0}
.cm-mergeView .cm-editor{padding:10px 14px}
.cm-merge-a{background:color-mix(in srgb,var(--bg) 55%,#000)}
.grudado{position:sticky;top:46px;display:flex;flex-direction:column;gap:4px}
```

- [ ] **Step 5: Browser check** (demo repo, panel on 8451 from the worktree): the page opens with the editors; `## Título` typed on a new line becomes a heading; Ctrl+S saves; a selection in a change shows the bar and approves only that part; ⚠️ at the cursor lands on its own line; typing while the 8-second refresh fires loses nothing; idle refresh does not rebuild the editors (count `EditorView` instances before and after 10 s). Console clean.

- [ ] **Step 6: Commit**

```bash
git add km/painel/editores.js km/painel.html
git commit -m "The panel edits in CodeMirror: one editor per stretch, a MergeView per change"
```

---

### Task 6: Verification on the real documents, and the docs

**Files:**
- Create: `tests/fixtures/markdown-raro.md`
- Modify: `README.md`, `docs/live-preview.md` (status)

- [ ] **Step 1: Fixture for unknown Markdown** — `tests/fixtures/markdown-raro.md` with a setext heading (`Título\n======`), an HTML block (`<details><summary>x</summary>y</details>`), a footnote (`texto[^1]` and `[^1]: nota`), a table with `\|` and a ragged row, a hard break (`linha  ` + newline), and a ❓ with a past date.

- [ ] **Step 2: Byte identity in the browser.** Start the worktree panel on 8451 against `demo-sla-project` and against a demo repo holding the fixture. For every tracked document, open it and assert, for every mounted editor, that `km.texto(chave)` equals the segment's text (`texto` or `agora`) exactly, and that no document is marked dirty after opening, focusing and moving the cursor through it.
Expected: every editor identical; zero dirty.

- [ ] **Step 3: Browser behaviour checks.**
  1. Typing `## Título` → the line gets `cm-h2`.
  2. Approving a selection that crosses a hidden `**` and a joined line break → the chancel gains exactly the selected characters.
  3. Table controls on the fixture: `+` row, `×` row, `+` column, `×` column → the file's table lines are exactly as `tabela.js` computes; removing the last column shows the refusal.
  4. The action column stays under the top bar while a long change scrolls, and leaves with it.
  5. Clicking into a joined paragraph opens its real lines; the caret stays where clicked (compare `state.selection.main.head` with the position under the click). If this fails and is not fixed in half a day: switch `paragrafo.js` off (return `[]`), record the ruling, keep going.
  6. `regras-de-sla.md` opens in under 1.5 s (measure `performance.now()` around `desenhar`).

- [ ] **Step 4: Docs.** README's *The panel* section: the text is edited in CodeMirror with live preview; tables have row/column controls; the action column is sticky. `docs/live-preview.md` status → **built**.

- [ ] **Step 5: Run everything and commit**

Run: `python3 -m unittest discover -s tests -t . && node --test tests/js/`
Expected: all pass.

```bash
git add tests/fixtures/markdown-raro.md README.md docs/live-preview.md
git commit -m "Live preview verified on the real documents; docs"
```
