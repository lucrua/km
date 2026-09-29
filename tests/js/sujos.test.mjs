import { test } from 'node:test';
import assert from 'node:assert/strict';
import { realocar } from '../../km/painel/sujos.js';

const INICIO = '# T\n\nUm.\n\n> 💬 comentário\n';
const FIM = '## 9. Fim\n\nDois.\n';

test('an edit whose block did not change stays as it is', () => {
  const r = realocar({ 'g:1': INICIO + 'mais\n' }, { 'g:1': INICIO }, [{ chave: 'g:1', texto: INICIO }]);
  assert.deepEqual(r, { sujos: { 'g:1': INICIO + 'mais\n' }, bases: { 'g:1': INICIO }, perdidas: [] });
});

test('a block that grew under the edit keeps the new end: the edit lands inside it', () => {
  // Aprovar o resto do arquivo junta tudo num bloco igual só, com a mesma chave g:1.
  const editado = INICIO.replace('comentário', 'comentário mudado');
  const r = realocar({ 'g:1': editado }, { 'g:1': INICIO }, [{ chave: 'g:1', texto: INICIO + '\n' + FIM }]);
  assert.equal(r.sujos['g:1'], editado.replace(/\s+$/, '') + '\n\n' + FIM);
  assert.equal(r.bases['g:1'], INICIO + '\n' + FIM);
  assert.deepEqual(r.perdidas, []);
});

test('an edit whose block moved to another key follows its text', () => {
  const r = realocar({ 'g:5': 'Um. mudado' }, { 'g:5': 'Um.' },
                     [{ chave: 'g:1', texto: '# T' }, { chave: 'g:3', texto: 'Um.\n\nDois.' }]);
  assert.deepEqual(r.sujos, { 'g:3': 'Um. mudado\n\nDois.' });
  assert.deepEqual(r.bases, { 'g:3': 'Um.\n\nDois.' });
});

test('two edits that end up in the same block both land', () => {
  const r = realocar({ 'g:1': 'A mudado', 'g:5': 'C mudado' }, { 'g:1': 'A', 'g:5': 'C' },
                     [{ chave: 'g:1', texto: 'A\n\nB\n\nC' }]);
  assert.deepEqual(r.sujos, { 'g:1': 'A mudado\n\nB\n\nC mudado' });
});

test('when the edited text is gone or is found twice, the edit is handed back, never pasted', () => {
  const sumiu = realocar({ 'g:1': 'Um. mudado' }, { 'g:1': 'Um.' }, [{ chave: 'g:1', texto: 'Outro.' }]);
  assert.deepEqual(sumiu, { sujos: {}, bases: {}, perdidas: ['Um. mudado'] });
  const duas = realocar({ 'g:1': 'x mudado' }, { 'g:1': 'x' },
                        [{ chave: 'g:3', texto: 'x' }, { chave: 'g:7', texto: 'x' }]);
  assert.deepEqual(duas.perdidas, ['x mudado']);
});

test('an edit with no base (made before bases existed) is kept only where it was', () => {
  const r = realocar({ 'g:1': 'Um. mudado' }, {}, [{ chave: 'g:1', texto: 'Um.' }]);
  assert.deepEqual(r.perdidas, ['Um. mudado']);
});
