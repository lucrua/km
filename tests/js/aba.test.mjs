import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const { uriDaAba } = createRequire(import.meta.url)('../../vscode/aba.js');

class TabInputText { constructor(uri) { this.uri = uri; } }
class TabInputCustom { constructor(uri, viewType) { this.uri = uri; this.viewType = viewType; } }
class TabInputWebview { constructor() { this.viewType = 'simpleBrowser'; } }
const tipos = { TabInputText, TabInputCustom };

test('a text tab and a custom-editor tab both give their file', () => {
  assert.equal(uriDaAba({ input: new TabInputText('a.md') }, tipos), 'a.md');
  assert.equal(uriDaAba({ input: new TabInputCustom('b.md', 'markdown-editor.customEditor') }, tipos), 'b.md');
});

test('no tab, or a tab that is not a file, gives nothing', () => {
  assert.equal(uriDaAba(undefined, tipos), undefined);
  assert.equal(uriDaAba({ input: new TabInputWebview() }, tipos), undefined);
  assert.equal(uriDaAba({ input: { uri: 'falso.md' } }, tipos), undefined);
});
