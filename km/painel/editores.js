// The panel's editors: one per unchanged stretch, a MergeView per change. They hold the
// file's text and nothing else; the page asks them for text, dirtiness and selection.
import { EditorView, EditorState, MergeView, keymap, history, historyKeymap, defaultKeymap,
         drawSelection } from '../vendor/cm.js';
import { editorMarkdown, trocarModo } from './preview.js';
import { emPontos } from './pontos.js';
import { modelo, insercao } from './marcas.js';

const vivos = new Map();
let codigo = false;                    // o modo da página: Formatado ou Código

function extensoes(editavel, aoMudar, aoSelecionar) {
  const ext = [editorMarkdown({ editavel, codigo }), drawSelection()];
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
  vivos.set(chave, { view, todas: [view], destruir: () => view.destroy() });
}

export function editorMudanca(lugar, chave, antes, agora, editavel, aoMudar, aoSelecionar) {
  // Quem chama decide se o lado de hoje é editável (um trecho que só saiu não é); o texto
  // não decide: um trecho que você esvaziou continua seu para escrever.
  const mv = new MergeView({ parent: lugar, gutter: false,
    a: { doc: antes, extensions: extensoes(false) },
    b: { doc: agora, extensions: extensoes(editavel, aoMudar, aoSelecionar) } });
  vivos.set(chave, { view: mv.b, todas: [mv.a, mv.b], destruir: () => mv.destroy() });
}

// Troca o modo de todos os editores sem refazê-los; os que nascerem depois já nascem nele.
export function modo(emCodigo) {
  codigo = !!emCodigo;
  for (const v of vivos.values()) for (const view of v.todas) view.dispatch({ effects: trocarModo(view.state, codigo) });
}

// A coluna do texto mudou de largura (a régua da esquerda foi arrastada): cada editor mede de novo.
// O CodeMirror já observa o próprio tamanho, mas ignora o que chega logo depois de uma atualização.
export function medirTodos() { for (const v of vivos.values()) for (const view of v.todas) view.requestMeasure(); }

// Onde se lia, para voltar a ler ali depois que as larguras mudam: o editor na altura y da
// janela, a linha dele ali, e quanto dela já tinha passado — em fração, porque um parágrafo é
// uma linha só e muda de altura quando quebra noutra largura.
export function ancora(y) {
  for (const [chave, v] of vivos) {
    const r = v.view.dom.getBoundingClientRect();
    if (!r.height || r.bottom <= y) continue;
    const linha = v.view.lineBlockAtHeight(Math.max(0, y - v.view.documentTop));
    const [ini, fim] = extremos(v.view, linha);
    return { chave, pos: linha.from, frac: fim > ini ? Math.min(1, Math.max(0, (y - ini) / (fim - ini))) : 0 };
  }
  return null;
}
// Quanto rolar para a mesma fração daquela linha voltar à altura y.
export function desvioDaAncora(a, y) {
  const v = vivos.get(a.chave)?.view;
  if (!v) return 0;
  const [ini, fim] = extremos(v, v.lineBlockAt(Math.min(a.pos, v.state.doc.length)));
  return ini + a.frac * (fim - ini) - y;
}
// O alto e o baixo de uma linha na janela, pelo DOM quando ela está desenhada.
function extremos(view, linha) {
  const c0 = view.coordsAtPos(linha.from, 1), c1 = view.coordsAtPos(linha.to, -1);
  if (c0 && c1) return [c0.top, Math.max(c0.top, c1.bottom)];
  return [view.documentTop + linha.top, view.documentTop + linha.bottom];
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

// A marca entra depois do bloco do cursor, como bloco próprio, com o texto de exemplo
// selecionado: o que você digitar toma o lugar dele. Nada é aprovado: a marca é texto seu,
// salvo como qualquer edição, e sai na chancela junto com o trecho.
export function inserirMarca(chave, tipo) {
  const v = vivos.get(chave)?.view;
  if (!v) return false;
  const i = insercao(v.state.doc.toString(), v.state.selection.main.head, modelo(tipo));
  v.dispatch({ changes: { from: i.from, insert: i.insert },
               selection: { anchor: i.anchor, head: i.head }, scrollIntoView: true });
  v.focus();
  return true;
}

export function focarFim(chave) {
  const v = vivos.get(chave)?.view;
  if (!v) return;
  v.dispatch({ selection: { anchor: v.state.doc.length } });
  v.focus();
}

window.km = { editorSimples, editorMudanca, destruirTodos, modo, medirTodos, ancora, desvioDaAncora, texto, selecao, focado, inserirMarca, focarFim };
window.dispatchEvent(new Event('km-pronto'));
