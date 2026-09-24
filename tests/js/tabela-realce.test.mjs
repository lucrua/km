import { test } from 'node:test';
import assert from 'node:assert/strict';
import { segmentos } from '../../km/painel/tabela.js';
import { celulaHTML, faixasDasLinhas, Tabela } from '../../km/painel/preview.js';

// As faixas mudadas de uma linha, em posições da linha, viram trechos de cada célula.
const marcados = (segs) => segs.map((c) => c.filter((s) => s.m).map((s) => s.t));

test('a word changed mid-cell marks only that word', () => {
  const l = '| Delta | o prazo corre | QA |';
  const a = l.indexOf('corre');
  assert.deepEqual(segmentos(l, [[a, a + 5]]), [
    [{ t: 'Delta', m: false }],
    [{ t: 'o prazo ', m: false }, { t: 'corre', m: true }],
    [{ t: 'QA', m: false }],
  ]);
});

test('a change that spills into padding and pipes marks only the cell text', () => {
  const l = '| a | bb |';
  assert.deepEqual(marcados(segmentos(l, [[3, 9]])), [[], ['bb']]);
});

test('an escaped pipe stays inside its cell and keeps its offsets', () => {
  const l = '| a \\| b | novo |';
  const a = l.indexOf('b |');
  assert.deepEqual(segmentos(l, [[a, a + 1]]), [
    [{ t: 'a \\| ', m: false }, { t: 'b', m: true }],
    [{ t: 'novo', m: false }],
  ]);
  const n = l.indexOf('novo');
  assert.deepEqual(marcados(segmentos(l, [[n, n + 4]])), [[], ['novo']]);
});

test('a whole new row marks every cell whole', () => {
  const l = '| x | y z |';
  assert.deepEqual(marcados(segmentos(l, [[0, l.length + 1]])), [['x'], ['y z']]);
});

test('a ragged row without the closing pipe maps its cells', () => {
  const l = '| a | b | c';
  const c = l.indexOf('c');
  assert.deepEqual(marcados(segmentos(l, [[c, c + 1]])), [[], [], ['c']]);
  assert.deepEqual(segmentos('| a |  |', []), [[{ t: 'a', m: false }], []]);
});

test('no ranges, no marks', () => {
  assert.deepEqual(segmentos('| a | b |', []), [[{ t: 'a', m: false }], [{ t: 'b', m: false }]]);
});

test('document ranges become ranges of each table line', () => {
  const linhas = ['| a | b |', '|---|---|', '| 1 | 2 |'];
  const from = 10;                                   // a tabela começa no 10 do documento
  const l3 = from + 20;                              // início da 3ª linha
  assert.deepEqual(faixasDasLinhas(linhas, from, [[0, 5], [l3 + 2, l3 + 3], [l3 + 8, l3 + 40]]),
                   [[], [], [[2, 3], [8, 9]]]);
  assert.deepEqual(faixasDasLinhas(linhas, from, [[from + 4, from + 25]]), [[[4, 9]], [[0, 9]], [[0, 5]]]);
});

test('cell HTML marks the changed text and keeps formatting and escaping', () => {
  assert.equal(celulaHTML([{ t: 'um ', m: false }, { t: '<novo>', m: true }]),
               'um <span class="cm-changedText">&lt;novo&gt;</span>');
  // A marca fica por dentro da formatação: o HTML continua bem aninhado.
  assert.equal(celulaHTML([{ t: '**forte ', m: false }, { t: 'novo', m: true }, { t: '** e `x`', m: false }]),
               '<b>forte <span class="cm-changedText">novo</span></b> e <code>x</code>');
  assert.equal(celulaHTML([{ t: '**a', m: true }, { t: 'b**', m: false }]),
               '<b><span class="cm-changedText">a</span>b</b>');
  assert.equal(celulaHTML([{ t: 'a \\| b', m: true }]), '<span class="cm-changedText">a | b</span>');
  // Uma mudança só na URL de um link marca o texto dele, sem desequilibrar o HTML.
  assert.equal(celulaHTML([{ t: '[texto](http://', m: false }, { t: 'x', m: true }, { t: ') fim', m: false }]),
               '<span class="cm-link-texto cm-changedText cm-alvo-mudou" title="alvo mudou: http://x">texto</span> fim');
  // Mudaram o texto e o alvo: o texto leva as duas marcas.
  assert.equal(celulaHTML([{ t: '[te', m: false }, { t: 'xto](http://x', m: true }, { t: ') fim', m: false }]),
               '<span class="cm-link-texto cm-changedText cm-alvo-mudou" title="alvo mudou: http://x">te<span class="cm-changedText">xto</span></span> fim');
});

test('the table widget re-renders when its marks change', () => {
  const linhas = ['| a | b |', '|---|---|', '| 1 | 2 |'];
  const sem = new Tabela(linhas, 0, true, [[], [], []]);
  const com = new Tabela(linhas, 0, true, [[], [], [[2, 3]]]);
  assert.ok(!sem.eq(com));
  assert.ok(com.eq(new Tabela(linhas, 0, true, [[], [], [[2, 3]]])));
  assert.ok(sem.eq(new Tabela(linhas, 0, true)));      // sem MergeView: nenhuma marca
});
