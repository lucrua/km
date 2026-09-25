import { test } from 'node:test';
import assert from 'node:assert/strict';
import { escolherInicial, situacao } from '../../km/painel/projetos.js';

const lista = [{ nome: 'alfa' }, { nome: 'beta' }, { nome: 'work/app' }];

test('the URL wins, then the last one used here, then where km serve was started', () => {
  assert.deepEqual(escolherInicial(lista, { param: 'beta', lembrado: 'alfa', inicial: 'work/app' }), { nome: 'beta', aviso: '' });
  assert.deepEqual(escolherInicial(lista, { param: null, lembrado: 'alfa', inicial: 'work/app' }), { nome: 'alfa', aviso: '' });
  assert.deepEqual(escolherInicial(lista, { param: null, lembrado: null, inicial: 'work/app' }), { nome: 'work/app', aviso: '' });
});

test('with nothing to go on, the first project; with no project, none', () => {
  assert.deepEqual(escolherInicial(lista, {}), { nome: 'alfa', aviso: '' });
  assert.deepEqual(escolherInicial([], {}), { nome: null, aviso: '' });
});

test('a remembered project that left the list is ignored quietly', () => {
  assert.deepEqual(escolherInicial(lista, { lembrado: 'sumiu', inicial: 'beta' }), { nome: 'beta', aviso: '' });
});

test('a URL naming an unknown project selects nothing and says so', () => {
  const r = escolherInicial(lista, { param: 'gama', lembrado: 'alfa' });
  assert.equal(r.nome, null);
  assert.match(r.aviso, /gama/);
});

test('what a project row says', () => {
  assert.deepEqual(situacao({ pct: '12%', n: 3, erro: '' }), { texto: '12% a aprovar', classe: 'ace' });
  assert.deepEqual(situacao({ pct: '', n: 3, erro: '' }), { texto: 'em dia', classe: 'ok' });
  assert.deepEqual(situacao({ pct: '', n: 0, erro: '' }), { texto: 'nada acompanhado', classe: 'mut' });
  assert.deepEqual(situacao({ pct: '', n: 0, erro: 'a pasta não existe mais' }), { texto: 'a pasta não existe mais', classe: 'ruim' });
});

test('the tab title starts with the repository folder, then " · "', async () => {
  const { tituloDaAba } = await import('../../km/painel/projetos.js');
  assert.equal(tituloDaAba('alfa'), 'alfa · km chancela');
  assert.equal(tituloDaAba('work/app'), 'app · km chancela');     // a pasta, não o nome desambiguado
  assert.equal(tituloDaAba(null), 'km · projetos');
});
