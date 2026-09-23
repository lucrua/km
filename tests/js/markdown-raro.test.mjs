// O Markdown que o live preview não conhece fica como texto: nada escondido, nada estilizado.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { EditorState } from '../../km/vendor/cm.js';
import { vistaViva, decorar } from '../../km/painel/preview.js';

const fixture = readFileSync(new URL('../fixtures/markdown-raro.md', import.meta.url), 'utf8');
const estado = () => EditorState.create({ doc: fixture, extensions: vistaViva() });

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
