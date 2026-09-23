import { test } from 'node:test';
import assert from 'node:assert/strict';
import { EditorState, EditorSelection } from '../../km/vendor/cm.js';
import { vistaViva, decorar, inline } from '../../km/painel/preview.js';

const doc = '## Título\n\nUm **forte** e um `código`.\nSegunda linha do parágrafo.\n';

function ranges(state, editavel) {
  const out = [];
  decorar(state, editavel).between(0, state.doc.length, (from, to, d) => { out.push([from, to, d.spec]); });
  return out;
}

test('markers are hidden off the cursor line and shown on it', () => {
  const longe = EditorState.create({ doc, selection: EditorSelection.cursor(doc.length),
                                     extensions: vistaViva() });
  const escondidos = ranges(longe, true).filter(([f, t, s]) => t > f && !s.widget && !s.class).map(([f, t]) => doc.slice(f, t));
  assert.ok(escondidos.includes('## '), escondidos.join('|'));
  assert.ok(escondidos.includes('**'));
  const perto = EditorState.create({ doc, selection: EditorSelection.cursor(3), extensions: vistaViva() });
  const agora = ranges(perto, true).filter(([f, t, s]) => t > f && !s.widget && !s.class).map(([f, t]) => doc.slice(f, t));
  assert.ok(!agora.includes('## '));
});

test('the paragraph away from the cursor flows', () => {
  const s = EditorState.create({ doc, selection: EditorSelection.cursor(0), extensions: vistaViva() });
  const quebras = ranges(s, true).filter(([f, t, sp]) => sp.widget && doc.slice(f, t) === '\n');
  assert.equal(quebras.length, 1);
});

test('the editor never changes the text', () => {
  const s = EditorState.create({ doc, extensions: vistaViva() });
  assert.equal(s.doc.toString(), doc);
});

test('cell HTML escapes and formats', () => {
  assert.equal(inline('**a** <b>'), '<b>a</b> &lt;b&gt;');
});
