// O Markdown que o live preview não conhece fica como texto: nada escondido, nada estilizado.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { EditorState } from '../../km/vendor/cm.js';
import { editorMarkdown, decorar } from '../../km/painel/preview.js';

const fixture = readFileSync(new URL('../fixtures/markdown-raro.md', import.meta.url), 'utf8');
const estado = () => EditorState.create({ doc: fixture, extensions: editorMarkdown() });

function decos() {
  const out = [];
  decorar(estado(), true).between(0, fixture.length, (from, to, d) => { out.push({ from, to, spec: d.spec }); });
  return out;
}
const toca = (d, a, b) => d.to > a && d.from < b;
const faixa = (trecho, desde = 0) => { const a = fixture.indexOf(trecho, desde); return [a, a + trecho.length]; };

test('the setext underline is left as text', () => {
  const [a, b] = faixa('================');
  assert.deepEqual(decos().filter((d) => toca(d, a, b)), []);
});

test('footnotes are left as text, neither hidden nor styled as links', () => {
  for (const [a, b] of [faixa('[^1]'), faixa('[^1]:', fixture.indexOf('A nota') - 10)]) {
    assert.deepEqual(decos().filter((d) => toca(d, a, b)).map((d) => fixture.slice(d.from, d.to)), []);
  }
});

test('the live preview never changes the fixture\'s bytes', () => {
  const s = estado();
  assert.equal(s.doc.toString(), fixture);
  assert.equal(s.update({ selection: { anchor: 40 } }).state.doc.toString(), fixture);
});

test('only what the spec lists is replaced', () => {
  // Marcadores, a URL de um link, bala, caixa de tarefa, régua e a tabela inteira como grade.
  const permitido = /^(\*\*|_|`|\[|\]|\(|\)|> |-|\[[ x]\]|---|https:\/\/exemplo\.com)$/;
  const tabela = faixa(fixture.slice(fixture.indexOf('| Campo'), fixture.indexOf('| só uma célula |') + 17));
  const intocados = [faixa('================'), faixa('[^1]'), faixa('  \n'), faixa('\\\n'),
                     faixa('<details>'), faixa('Conteúdo que o preview não conhece.'), faixa('[^1]: A nota.')];
  for (const d of decos().filter((x) => x.to > x.from && !x.spec.class)) {
    const texto = fixture.slice(d.from, d.to);
    const ehTabela = d.from === tabela[0] && d.to === tabela[1];
    assert.ok(ehTabela || permitido.test(texto), `substituído sem estar na spec: ${JSON.stringify(texto)}`);
    for (const [a, b] of intocados) assert.ok(!toca(d, a, b), `mexeu em ${JSON.stringify(fixture.slice(a, b))}`);
  }
});
