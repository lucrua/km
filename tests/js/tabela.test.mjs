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
