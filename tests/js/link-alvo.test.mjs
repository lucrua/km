import { test } from 'node:test';
import assert from 'node:assert/strict';
import { EditorState, EditorSelection } from '../../km/vendor/cm.js';
import { editorMarkdown, decorar, mudouFoco, alvosMudados, celulaHTML } from '../../km/painel/preview.js';
import { segmentos } from '../../km/painel/tabela.js';

// Um link cuja única mudança está no alvo escondido: o texto visível leva a marca.

test('a change inside the hidden target marks the link text', () => {
  const links = [{ texto: [1, 6], alvo: [6, 20], url: 'x/y.md' }];
  assert.deepEqual(alvosMudados(links, [[9, 11]]), [{ de: 1, ate: 6, url: 'x/y.md' }]);
  // uma remoção deste lado é um ponto: dentro do alvo, conta
  assert.deepEqual(alvosMudados(links, [[9, 9]]), [{ de: 1, ate: 6, url: 'x/y.md' }]);
  // o ponto na borda de fora não é do alvo
  assert.deepEqual(alvosMudados(links, [[6, 6]]), []);
  assert.deepEqual(alvosMudados(links, [[20, 20]]), []);
  // mudou só o texto: a MergeView já marca, nada a acrescentar
  assert.deepEqual(alvosMudados(links, [[2, 4]]), []);
  // o link inteiro é novo: o texto já está marcado, sem marca em dobro
  assert.deepEqual(alvosMudados(links, [[0, 25]]), []);
  assert.deepEqual(alvosMudados(links, []), []);
});

const doc = 'Veja [painel-atual.md](descoberta/painel-atual.md) aqui.\n\nOutra linha.\n';
const alvo = doc.indexOf('descoberta/'), texto = doc.indexOf('painel-atual.md');

function marcas(state, faixas) {
  const out = [];
  decorar(state, true, faixas).between(0, state.doc.length, (from, to, d) => {
    if ((d.spec.class || '').includes('cm-alvo-mudou')) out.push({ t: state.doc.sliceString(from, to), d: d.spec });
  });
  return out;
}
const longe = () => EditorState.create({ doc, selection: EditorSelection.cursor(doc.length), extensions: editorMarkdown() });

test('prose: only the target changed, the visible text is marked with the url in the title', () => {
  const [m, ...resto] = marcas(longe(), [[alvo, alvo + 11]]);
  assert.equal(resto.length, 0);
  assert.equal(m.t, 'painel-atual.md');
  assert.match(m.d.class, /\bcm-changedText\b/);
  assert.equal(m.d.attributes.title, 'alvo mudou: descoberta/painel-atual.md');
  // do outro lado, a mudança é uma remoção: um ponto dentro do alvo
  assert.equal(marcas(longe(), [[alvo, alvo]]).length, 1);
});

test('prose: a change in the text, nothing changed, or the url on screen — no extra mark', () => {
  assert.deepEqual(marcas(longe(), [[texto + 7, texto + 12]]), []);
  assert.deepEqual(marcas(longe(), []), []);
  // o cursor na linha mostra a URL, e a marca da MergeView com ela
  const perto = EditorState.create({ doc, selection: EditorSelection.cursor(2), extensions: editorMarkdown() })
    .update({ effects: mudouFoco.of(true) }).state;
  assert.deepEqual(marcas(perto, [[alvo, alvo + 11]]), []);
});

test('prose: footnotes and autolinks are left alone', () => {
  const d = 'Nota[^1] e <http://x.y/z> e [ref][r].\n\n[r]: http://a.b\n';
  const s = EditorState.create({ doc: d, selection: EditorSelection.cursor(d.length), extensions: editorMarkdown() });
  assert.deepEqual(marcas(s, [[0, d.length]]), []);
  assert.deepEqual(marcas(s, [[d.indexOf('x.y'), d.indexOf('x.y') + 3]]), []);
});

const TIT = 'title="alvo mudou: descoberta/a.md"';

test('table cell: a change only in the target marks the link text, with the title', () => {
  const l = '| x | [a.md](descoberta/a.md) fim |';
  const i = l.indexOf('descoberta/');
  const [, cel] = segmentos(l, [[i, i + 11]]);
  assert.equal(celulaHTML(cel),
    `<span class="cm-link-texto cm-changedText cm-alvo-mudou" ${TIT}>a.md</span> fim`);
});

test('table cell: a removal inside the target is a point, and still marks', () => {
  const l = '| x | [a.md](descoberta/a.md) |';
  const i = l.indexOf('/a.md)');
  const [, cel] = segmentos(l, [[i, i]]);
  assert.ok(cel.some((s) => s.t === '' && s.m), JSON.stringify(cel));
  assert.equal(celulaHTML(cel), `<span class="cm-link-texto cm-changedText cm-alvo-mudou" ${TIT}>a.md</span>`);
  // um ponto fora de qualquer alvo não aparece
  assert.equal(celulaHTML(segmentos(l, [[l.indexOf('x') + 1, l.indexOf('x') + 1]])[0]), 'x');
});

test('table cell: a change in the link text marks just those chars, as before', () => {
  assert.equal(celulaHTML([{ t: '[te', m: false }, { t: 'xto', m: true }, { t: '](http://x) fim', m: false }]),
               '<span class="cm-link-texto">te<span class="cm-changedText">xto</span></span> fim');
  assert.equal(celulaHTML([{ t: '[texto](http://x) fim', m: false }]), '<span class="cm-link-texto">texto</span> fim');
});
