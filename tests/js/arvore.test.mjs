import { test } from 'node:test';
import assert from 'node:assert/strict';
import { montarArvore, visiveis, abertasPadrao, ancestrais, estadoArquivo, estadoPasta }
  from '../../km/painel/arvore.js';

const doc = (file, extra = {}) => ({ file, rastreado: true, pendente: false, pct: '0%', ...extra });
const nomes = (nos) => nos.map((n) => n.nome);

test('files and their ancestor folders become a tree; folders first, then files', () => {
  const r = montarArvore([doc('b.md'), doc('docs/x.md'), doc('a.md'), doc('docs/y/z.md')]);
  assert.deepEqual(nomes(r.filhos), ['docs', 'a.md', 'b.md']);
  const docs = r.filhos[0];
  assert.equal(docs.tipo, 'pasta');
  assert.equal(docs.caminho, 'docs');
  assert.deepEqual(nomes(docs.filhos), ['y', 'x.md']);
  assert.equal(r.filhos[1].i, 2, 'a file keeps its index in D.docs');
  assert.equal(r.filhos[1].caminho, 'a.md');
});

test('sorting is alphabetical, pt locale, case-insensitive, with numbers in order', () => {
  const r = montarArvore([doc('Zeta.md'), doc('ação.md'), doc('abc.md'), doc('b10.md'), doc('b9.md'), doc('Beta.md')]);
  assert.deepEqual(nomes(r.filhos), ['abc.md', 'ação.md', 'b9.md', 'b10.md', 'Beta.md', 'Zeta.md']);
});

test('a chain of single-folder folders collapses into one row, like compact folders', () => {
  const r = montarArvore([doc('a/b/c/file.md')]);
  assert.equal(r.filhos.length, 1);
  const p = r.filhos[0];
  assert.equal(p.nome, 'a/b/c');
  assert.equal(p.caminho, 'a/b/c');
  assert.deepEqual(nomes(p.filhos), ['file.md']);
});

test('the chain stops where a folder has a file or a second child', () => {
  const r = montarArvore([doc('descoberta/guides/um.md'), doc('descoberta/guides/dois.md'),
                          doc('x/y/a.md'), doc('x/y/z/b.md'), doc('x/y/z/c.md')]);
  assert.deepEqual(nomes(r.filhos), ['descoberta/guides', 'x/y']);
  const xy = r.filhos[1];
  assert.deepEqual(nomes(xy.filhos), ['z', 'a.md']);
  assert.equal(xy.filhos[0].caminho, 'x/y/z');
});

test('no tracked files gives an empty root', () => {
  assert.deepEqual(montarArvore([]).filhos, []);
});

test('folders add up what is below them, at any depth', () => {
  const r = montarArvore([doc('p/a.md', { pendente: true, pct: '21%' }), doc('p/q/b.md', { pendente: true, pct: '3%' }),
                          doc('p/q/c.md'), doc('p/novo.md', { rastreado: false })]);
  const p = r.filhos[0];
  assert.equal(p.pendentes, 2);
  assert.equal(p.novos, 1);
  assert.equal(p.total, 4);
  assert.equal('vencidas' in p, false);
});

test('file status: pending, up to date, never chancelled', () => {
  assert.deepEqual(estadoArquivo(doc('a', { pendente: true, pct: '21%' })), { classe: 'ace', texto: '21%' });
  assert.deepEqual(estadoArquivo(doc('a')), { classe: 'ok', texto: '✓' });
  assert.deepEqual(estadoArquivo(doc('a', { rastreado: false })), { classe: 'novo', texto: 'novo' });
});

test('folder status: ●N when something is pending, ✓ when all is up to date, novo when nothing has a chancel', () => {
  const st = (docs) => estadoPasta(montarArvore(docs).filhos[0]);
  assert.deepEqual(st([doc('p/a', { pendente: true, pct: '1%' }), doc('p/b', { pendente: true, pct: '1%' }), doc('p/c')]),
                   { classe: 'ace', texto: '●2' });
  assert.deepEqual(st([doc('p/a'), doc('p/b')]), { classe: 'ok', texto: '✓' });
  assert.deepEqual(st([doc('p/a', { rastreado: false })]), { classe: 'novo', texto: 'novo' });
  assert.deepEqual(st([doc('p/a'), doc('p/b', { rastreado: false })]), { classe: 'novo', texto: '' },
                   'a mix of up to date and never chancelled says nothing');
});

test('folders holding a pending file start open; the others closed', () => {
  const r = montarArvore([doc('a/b/x.md', { pendente: true, pct: '2%' }), doc('a/c/y.md'), doc('d/z.md')]);
  assert.deepEqual([...abertasPadrao(r)].sort(), ['a', 'a/b']);
});

test('ancestors of a file are the folder rows above it, compact rows included', () => {
  const r = montarArvore([doc('a/b/c/f.md'), doc('a/b/c/g/h.md'), doc('a/b/c/g/i.md'), doc('top.md')]);
  assert.deepEqual(ancestrais(r, 'a/b/c/g/h.md'), ['a/b/c', 'a/b/c/g']);
  assert.deepEqual(ancestrais(r, 'top.md'), []);
  assert.deepEqual(ancestrais(r, 'nao/existe.md'), []);
});

test('visible rows follow the open folders, with level, set size and position', () => {
  const r = montarArvore([doc('a/x.md'), doc('a/y.md'), doc('b/z.md'), doc('top.md')]);
  const v = visiveis(r, new Set(['a']));
  assert.deepEqual(v.map((l) => [l.no.caminho, l.nivel, l.pos, l.de]),
    [['a', 1, 1, 3], ['a/x.md', 2, 1, 2], ['a/y.md', 2, 2, 2], ['b', 1, 2, 3], ['top.md', 1, 3, 3]]);
  assert.equal(v[0].pai, null);
  assert.equal(v[1].pai, 'a');
});
