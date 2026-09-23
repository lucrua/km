// The panel's editors: one per unchanged stretch, a MergeView per change. They hold the
// file's text and nothing else; the page asks them for text, dirtiness and selection.
import { EditorView, EditorState, MergeView, keymap, history, historyKeymap, defaultKeymap,
         drawSelection } from '../vendor/cm.js';
import { vistaViva } from './preview.js';
import { emPontos } from './pontos.js';

const vivos = new Map();

function extensoes(editavel, aoMudar, aoSelecionar) {
  const ext = [vistaViva({ editavel }), drawSelection()];
  if (editavel) {
    ext.push(history(), keymap.of([...defaultKeymap, ...historyKeymap]),
      EditorView.updateListener.of((u) => {
        if (u.docChanged && aoMudar) aoMudar(u.state.doc.toString());
        if (u.selectionSet && aoSelecionar) aoSelecionar();
      }));
  }
  return ext;
}

export function destruirTodos() { for (const v of vivos.values()) v.destruir(); vivos.clear(); }

export function editorSimples(lugar, chave, texto, editavel, aoMudar, aoSelecionar) {
  const view = new EditorView({ parent: lugar,
    state: EditorState.create({ doc: texto, extensions: extensoes(editavel, aoMudar, aoSelecionar) }) });
  vivos.set(chave, { view, destruir: () => view.destroy() });
}

export function editorMudanca(lugar, chave, antes, agora, editavel, aoMudar, aoSelecionar) {
  // Quem chama decide se o lado de hoje é editável (um trecho que só saiu não é); o texto
  // não decide: um trecho que você esvaziou continua seu para escrever.
  const mv = new MergeView({ parent: lugar, gutter: false,
    a: { doc: antes, extensions: extensoes(false) },
    b: { doc: agora, extensions: extensoes(editavel, aoMudar, aoSelecionar) } });
  vivos.set(chave, { view: mv.b, destruir: () => mv.destroy() });
}

export const texto = (chave) => vivos.get(chave)?.view.state.doc.toString();

export function selecao(chave) {
  const v = vivos.get(chave)?.view;
  const r = v && v.state.selection.main;
  if (!r || r.empty) return null;
  // Em code points, como o servidor conta as unidades.
  const doc = v.state.doc.toString();
  return { a: emPontos(doc, r.from), b: emPontos(doc, r.to), rect: v.coordsAtPos(r.from) };
}

export function focado() {
  for (const [chave, v] of vivos) if (v.view.hasFocus) return chave;
  return null;
}

export function inserirMarca(chave, modelo) {
  const v = vivos.get(chave)?.view;
  if (!v) return false;
  // A marca é um bloco próprio: no fim da linha do cursor, com linha em branco antes e depois.
  const l = v.state.doc.lineAt(v.state.selection.main.head);
  v.dispatch({ changes: { from: l.to, insert: '\n\n' + modelo + '\n' },
               selection: { anchor: l.to + 2 + modelo.length } });
  v.focus();
  return true;
}

export function focarFim(chave) {
  const v = vivos.get(chave)?.view;
  if (!v) return;
  v.dispatch({ selection: { anchor: v.state.doc.length } });
  v.focus();
}

window.km = { editorSimples, editorMudanca, destruirTodos, texto, selecao, focado, inserirMarca, focarFim };
window.dispatchEvent(new Event('km-pronto'));
