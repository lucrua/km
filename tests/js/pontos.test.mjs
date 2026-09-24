import { test } from 'node:test';
import assert from 'node:assert/strict';
import { emPontos } from '../../km/painel/pontos.js';

// O servidor mede em code points (len do Python); o CodeMirror, em unidades UTF-16.
test('an emoji outside the BMP counts as one position, as the server counts it', () => {
  const s = '📌 x\nabc';
  assert.equal(emPontos(s, s.indexOf('abc')), 4);
  assert.equal(emPontos(s, s.length), 7);
});

test('text without astral characters keeps its offsets', () => {
  assert.equal(emPontos('ação — ok', 6), 6);
});
