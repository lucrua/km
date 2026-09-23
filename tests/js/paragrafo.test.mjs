import { test } from 'node:test';
import assert from 'node:assert/strict';
import { quebrasOcultas } from '../../km/painel/paragrafo.js';

const texto = 'linha um\nlinha dois\n\noutro um\noutro dois\n';
const paras = [{ from: 0, to: 19 }, { from: 21, to: 40 }];      // "linha um\nlinha dois" e "outro um\noutro dois"

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
