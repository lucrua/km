import { test } from 'node:test';
import assert from 'node:assert/strict';
import { coberto, linhasNovas } from '../../km/painel/novas.js';

// Os inícios das linhas da tela que são inteiras novas.
const todo = (t) => [[0, t.length]];

test('a document that is all new: every line on screen is new, blank ones included', () => {
  const t = '# A\n\num\n';
  assert.deepEqual(linhasNovas(t, new Set(), todo(t)), [0, 4, 5]);
});

test('nothing changed, nothing new', () => {
  assert.deepEqual(linhasNovas('# A\n\num\n', new Set(), []), []);
});

test('a word changed inside an old line is not a new line', () => {
  const t = 'um dois três\n';
  const a = t.indexOf('dois');
  assert.deepEqual(linhasNovas(t, new Set(), [[a, a + 4]]), []);
});

test('a new paragraph after an old one: only its lines', () => {
  const t = 'velho\n\nnovo\n';
  const a = t.indexOf('\nnovo');   // o diff costuma levar a quebra de antes junto
  assert.deepEqual(linhasNovas(t, new Set(), [[a - 1, t.length]]), [6, 7]);
});

test('a joined paragraph is one line on screen: new only if all of it is', () => {
  const t = 'velho\nnovo\n';
  const juntas = new Set([6]);     // a linha 2 se emenda na 1
  const b = t.indexOf('novo');
  assert.deepEqual(linhasNovas(t, juntas, [[b - 1, t.length]]), []);
  assert.deepEqual(linhasNovas(t, juntas, todo(t)), [0]);
  // Sem emendar (o Código, ou o cursor no parágrafo), a linha nova é nova sozinha.
  assert.deepEqual(linhasNovas(t, new Set(), [[b - 1, t.length]]), [6]);
});

test('spaces the diff left out do not make a line old', () => {
  const t = '  - item\n';
  assert.deepEqual(linhasNovas(t, new Set(), [[2, t.length]]), [0]);
});

test('a blank line between an old and a new paragraph stays old', () => {
  const t = 'velho\n\nnovo\n';
  const b = t.indexOf('novo');
  assert.deepEqual(linhasNovas(t, new Set(), [[b, t.length]]), [7]);
});

test('a range is covered when (almost) every visible character in it changed', () => {
  const t = '| a |\n| b |';
  assert.equal(coberto(t, 0, t.length, todo(t)), true);
  assert.equal(coberto(t, 0, t.length, [[0, 6]]), false);
  // Um buraco solto do diff (o ponto final casado com o de outro parágrafo) não faz velha.
  const p = 'Um parágrafo acrescentado depois, inteiro novo.';
  assert.equal(coberto(p, 0, p.length, [[0, p.length - 1]]), true);
  assert.equal(coberto(p, 0, p.length, [[0, 20]]), false);
  assert.equal(coberto('ok', 0, 2, [[0, 1]]), false);
  assert.equal(coberto(t, 0, t.length, []), false);
});
