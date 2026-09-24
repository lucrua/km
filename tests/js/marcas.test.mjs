// As três marcas: o formato exato que a tela escreve, a data local e onde a marca entra.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { hoje, emDias, modelo, marcaDaLinha, insercao, PLACEHOLDER } from '../../km/painel/marcas.js';

test('today and today + n are local dates, not UTC', () => {
  process.env.TZ = 'America/Sao_Paulo';
  // 22:30 em Brasília já é o dia seguinte em UTC.
  const noite = new Date('2026-09-23T22:30:00-03:00');
  assert.equal(hoje(noite), '2026-09-23');
  assert.equal(emDias(7, noite), '2026-09-30');
  assert.equal(emDias(7, new Date('2026-12-28T23:50:00-03:00')), '2027-01-04');
});

test('the three templates, exactly', () => {
  process.env.TZ = 'America/Sao_Paulo';
  const d = new Date('2026-09-24T22:00:00-03:00');
  assert.equal(modelo('to_validate', d), '> ❓ **to_validate by 2026-10-01** — add your comment here');
  assert.equal(modelo('comment', d), '> 💬 add your comment here');
  assert.equal(modelo('to_do', d), '> 📌 **to_do · 2026-09-24** — add your comment here');
  assert.equal(PLACEHOLDER, 'add your comment here');
});

test('a line is read as a mark only in the exact form', () => {
  assert.deepEqual(marcaDaLinha('> ❓ **to_validate by 2026-10-01** — x'), { tipo: 'to_validate', data: '2026-10-01', texto: 'x' });
  assert.deepEqual(marcaDaLinha('> 📌 **to_do · 2026-09-24** — y'), { tipo: 'to_do', data: '2026-09-24', texto: 'y' });
  assert.deepEqual(marcaDaLinha('> 💬 z'), { tipo: 'comment', data: '', texto: 'z' });
  for (const l of ['> ❓ **to_validate** — x', '> 📌 **to_do 2026-09-24** — y', '>💬 z', '💬 fora da citação',
                   '> ⚠️ **sem certeza** — a', '> 🚫 **discordo** — b', '> ❓ **a confirmar até 2026-01-01** — c',
                   '> 💬 ', '> 💬  espaço antes']) {
    assert.equal(marcaDaLinha(l), null, l);
  }
});

// Aplica a inserção e devolve o texto e o que ficou selecionado.
function inserir(doc, pos, linha) {
  const i = insercao(doc, pos, linha);
  const novo = doc.slice(0, i.from) + i.insert + doc.slice(i.from);
  return { novo, sel: novo.slice(i.anchor, i.head) };
}
const L = '> 💬 add your comment here';

test('at the end of a passage the mark is its own block and the placeholder is selected', () => {
  const doc = 'Um parágrafo.';
  const r = inserir(doc, doc.length, L);
  assert.equal(r.novo, 'Um parágrafo.\n\n' + L);
  assert.equal(r.sel, 'add your comment here');
});

test('in the middle of a document there is exactly one blank line on each side', () => {
  const doc = 'um\n\ndois\n\ntrês';
  assert.equal(inserir(doc, 1, L).novo, 'um\n\n' + L + '\n\ndois\n\ntrês');
  const colado = 'um\ndois';                      // o cursor numa linha seguida de texto
  assert.equal(inserir(colado, 1, L).novo, 'um\ndois\n\n' + L);
  assert.equal(inserir('a\n\nb', 2, L).novo, 'a\n\n' + L + '\n\nb');   // numa linha em branco
});

test('a hard-wrapped paragraph is not split: the mark goes after the block', () => {
  const doc = 'linha um\nlinha dois\n\nfim';
  assert.equal(inserir(doc, 3, L).novo, 'linha um\nlinha dois\n\n' + L + '\n\nfim');
});
