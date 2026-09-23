// Run: node --test tests/js/
import { test } from 'node:test';
import assert from 'node:assert/strict';

const ESPERADOS = ['EditorState', 'EditorSelection', 'StateField', 'StateEffect', 'RangeSetBuilder',
  'Compartment', 'Transaction', 'Prec', 'EditorView', 'Decoration', 'ViewPlugin', 'WidgetType',
  'keymap', 'drawSelection', 'defaultKeymap', 'history', 'historyKeymap', 'indentWithTab',
  'syntaxTree', 'ensureSyntaxTree', 'syntaxHighlighting', 'HighlightStyle', 'markdown',
  'markdownLanguage', 'tags', 'MergeView'];

test('the bundle exports what the panel uses', async () => {
  const cm = await import('../../km/vendor/cm.js');
  for (const nome of ESPERADOS) assert.ok(cm[nome], `falta ${nome}`);
});

test('the Markdown parser in the bundle knows GFM tables', async () => {
  const { EditorState, markdown, markdownLanguage, ensureSyntaxTree } = await import('../../km/vendor/cm.js');
  const doc = '| a | b |\n|---|---|\n| 1 | 2 |\n';
  const state = EditorState.create({ doc, extensions: [markdown({ base: markdownLanguage })] });
  const nomes = [];
  ensureSyntaxTree(state, doc.length, 1000).iterate({ enter: (n) => { nomes.push(n.name); } });
  assert.ok(nomes.includes('Table'), nomes.join(','));
});
