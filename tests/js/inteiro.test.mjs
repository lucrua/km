import { test } from 'node:test';
import assert from 'node:assert/strict';
import { arquivoInteiro, perguntaDasMarcas } from '../../km/painel/inteiro.js';

const mudanca = (shas, sumidas = []) => ({ unidades: shas.map((sha) => ({ sha })), sumidas });

test('with one change or none there is no whole-file button: its own Aprovar is the file', () => {
  assert.equal(arquivoInteiro([]), null);
  assert.equal(arquivoInteiro([mudanca(['a', 'b'])]), null);
});

test('every block of every change on the screen goes in, each sha once', () => {
  const x = arquivoInteiro([mudanca(['a', 'b']), mudanca(['c']), mudanca(['a'])]);
  assert.deepEqual(x.shas, ['a', 'b', 'c']);
  assert.deepEqual(x.sumidas, []);
});

test('the marks the approval would take away are gathered from every change', () => {
  const x = arquivoInteiro([mudanca(['a'], ['> 💬 um']), mudanca(['b']), mudanca(['c'], ['> ❓ **to_validate by 2026-10-08** — dois'])]);
  assert.deepEqual(x.sumidas, ['> 💬 um', '> ❓ **to_validate by 2026-10-08** — dois']);
});

test('no removed mark asks nothing; removed marks are named in the question', () => {
  assert.equal(perguntaDasMarcas([]), null);
  const p = perguntaDasMarcas(['> 💬 um', '  > 📌 **to_do · 2026-09-24** — dois']);
  assert.match(p, /2 marcas/);
  assert.match(p, /💬 um/);
  assert.match(p, /📌 \*\*to_do · 2026-09-24\*\* — dois/);
  assert.doesNotMatch(p, /^\s*>/m);
  assert.match(perguntaDasMarcas(['> 💬 só esta']), /1 marca /);
});
