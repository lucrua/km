import { test } from 'node:test';
import assert from 'node:assert/strict';
import { EditorState, EditorSelection, EditorView } from '../../km/vendor/cm.js';
import { editorMarkdown, trocarModo, decorar, inline, mudouFoco } from '../../km/painel/preview.js';

const doc = '## Título\n\nUm **forte** e um `código`.\nSegunda linha do parágrafo.\n';

const focar = (s) => s.update({ effects: mudouFoco.of(true) }).state;

function ranges(state, editavel) {
  const out = [];
  decorar(state, editavel).between(0, state.doc.length, (from, to, d) => { out.push([from, to, d.spec]); });
  return out;
}

test('markers are hidden off the cursor line and shown on it', () => {
  const longe = EditorState.create({ doc, selection: EditorSelection.cursor(doc.length),
                                     extensions: editorMarkdown() });
  const escondidos = ranges(longe, true).filter(([f, t, s]) => t > f && !s.widget && !s.class).map(([f, t]) => doc.slice(f, t));
  assert.ok(escondidos.includes('## '), escondidos.join('|'));
  assert.ok(escondidos.includes('**'));
  const perto = focar(EditorState.create({ doc, selection: EditorSelection.cursor(3), extensions: editorMarkdown() }));
  const agora = ranges(perto, true).filter(([f, t, s]) => t > f && !s.widget && !s.class).map(([f, t]) => doc.slice(f, t));
  assert.ok(!agora.includes('## '));
});

test('the paragraph away from the cursor flows', () => {
  const s = focar(EditorState.create({ doc, selection: EditorSelection.cursor(0), extensions: editorMarkdown() }));
  const quebras = ranges(s, true).filter(([f, t, sp]) => sp.widget && doc.slice(f, t) === '\n');
  assert.equal(quebras.length, 1);
});

test('the editor never changes the text', () => {
  const s = EditorState.create({ doc, extensions: editorMarkdown() });
  assert.equal(s.doc.toString(), doc);
});

test('cell HTML escapes and formats', () => {
  assert.equal(inline('**a** <b>'), '<b>a</b> &lt;b&gt;');
});

test('an editor without focus hides every marker and every paragraph flows', () => {
  // Todo editor nasce com o cursor em 0: sem foco, isso não pode mostrar a linha 1 crua.
  const s = EditorState.create({ doc, selection: EditorSelection.cursor(3), extensions: editorMarkdown() });
  const escondidos = ranges(s, true).filter(([f, t, sp]) => t > f && !sp.widget && !sp.class).map(([f, t]) => doc.slice(f, t));
  assert.ok(escondidos.includes('## '), escondidos.join('|'));
  const quebras = ranges(s, true).filter(([f, t, sp]) => sp.widget && doc.slice(f, t) === '\n');
  assert.equal(quebras.length, 1);
});

// O modo Código: o mesmo editor, sem a camada do live preview.
function decoracoes(state) {
  const out = [];
  for (const fonte of state.facet(EditorView.decorations)) {
    const set = typeof fonte === 'function' ? null : fonte;
    if (set) set.between(0, state.doc.length, (from, to, d) => { out.push([from, to, d.spec]); });
  }
  return out;
}
const escondem = (state) => decoracoes(state).filter(([f, t, sp]) => t > f && !sp.class);

const tabelaDoc = '# Um\n\n| a | b |\n|---|---|\n| 1 | **2** |\n\nlinha um\nlinha dois\n';

test('Código mode shows every marker, every line break and the table as source', () => {
  const s = EditorState.create({ doc: tabelaDoc, extensions: editorMarkdown({ codigo: true }) });
  assert.equal(escondem(s).length, 0);
  assert.equal(s.doc.toString(), tabelaDoc);
});

test('switching modes swaps the decorations and never the text', () => {
  const s0 = EditorState.create({ doc: tabelaDoc, extensions: editorMarkdown() });
  assert.ok(escondem(s0).length > 0, 'Formatado esconde marcas');
  const s1 = s0.update({ effects: trocarModo(s0, true) }).state;
  assert.equal(escondem(s1).length, 0);
  assert.equal(s1.doc.toString(), tabelaDoc);
  const s2 = s1.update({ effects: trocarModo(s1, false) }).state;
  assert.deepEqual(escondem(s2).map(([f, t]) => [f, t]), escondem(s0).map(([f, t]) => [f, t]));
  assert.equal(s2.doc.toString(), tabelaDoc);
});

test('switching keeps the editor read-only or editable', () => {
  const s0 = EditorState.create({ doc: tabelaDoc, extensions: editorMarkdown({ editavel: false }) });
  const s1 = s0.update({ effects: trocarModo(s0, true) }).state;
  const s2 = s1.update({ effects: trocarModo(s1, false) }).state;
  for (const s of [s1, s2]) { assert.equal(s.readOnly, true); assert.equal(s.facet(EditorView.editable), false); }
});

// As duas marcas viram caixas; nenhuma data vence.
const classes = (state) => {
  const out = [];
  decorar(state, true).between(0, state.doc.length, (from, to, d) => { if (d.spec.class) out.push([from, d.spec.class]); });
  return out;
};

test('each mark is a box of its own kind, and the old marks are plain quotes', () => {
  const texto = ['> 📌 **to_do · 2026-09-24** — a', '', '> ❓ **to_validate by 2999-01-01** — b', '',
                 '> 💬 c', '', '> ⚠️ **sem certeza** — d', '', '> 🚫 **discordo** — e', ''].join('\n');
  const s = EditorState.create({ doc: texto, extensions: editorMarkdown() });
  const porLinha = (n) => classes(s).filter(([f, c]) => f === s.doc.line(n).from && c.startsWith('cm-cit')).map(([, c]) => c);
  assert.deepEqual(porLinha(1), ['cm-cit cm-cit-fazer']);
  assert.deepEqual(porLinha(3), ['cm-cit'], 'the retired ❓ is a plain quote');
  assert.deepEqual(porLinha(5), ['cm-cit cm-cit-comentario']);
  assert.deepEqual(porLinha(7), ['cm-cit']);
  assert.deepEqual(porLinha(9), ['cm-cit']);
  assert.ok(!classes(s).some(([, c]) => c === 'cm-vencida'));
});

test('no date is ever highlighted as overdue', () => {
  const texto = '> ❓ **to_validate by 2020-01-01** — sobrou\n\n> 📌 **to_do · 2020-01-01** — velho\n';
  const s = EditorState.create({ doc: texto, extensions: editorMarkdown() });
  assert.deepEqual(classes(s).filter(([, c]) => c === 'cm-vencida'), []);
});

test('on today\'s side, a wholly new line on screen gets the bar; a new table, the grid', () => {
  const t = 'velho\nnovo\n\n| a |\n| - |\n| b |\n';
  const s = EditorState.create({ doc: t, extensions: editorMarkdown() });
  const novas = (faixas, lado = 'b') => {
    const out = [];
    decorar(s, true, faixas, lado).between(0, t.length, (f, _, d) => {
      if (d.spec.class === 'cm-nova') out.push(f);
      if (d.spec.widget?.nova) out.push('tabela');
    });
    return out;
  };
  const b = t.indexOf('novo');
  // "novo" se emenda em "velho": a linha da tela é meio velha, então sem barra.
  assert.deepEqual(novas([[b, t.length]]), [t.indexOf('\n| a'), 'tabela']);
  assert.deepEqual(novas([[0, t.length]]), [0, t.indexOf('\n| a'), 'tabela']);
  assert.deepEqual(novas([[0, t.length]], 'a'), []);   // a chancela não leva barra
});
