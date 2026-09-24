// Live preview: the document is always the file's exact text; formatting is decoration.
// Off the cursor's line the Markdown markers are hidden, paragraphs flow, the 📌 ❓ 💬 marks
// become coloured boxes and tables become a grid with row and column controls. All of it
// lives in one StateField: hidden line breaks and block widgets are decorations CodeMirror
// accepts only from the state, never from a plugin. The Código mode swaps that layer out for
// plain highlighting in a monospace font — the same text, every marker and line break shown.
import { EditorView, Decoration, WidgetType, StateField, StateEffect, EditorState, Compartment,
         syntaxTree, ensureSyntaxTree, markdown, markdownLanguage, syntaxHighlighting,
         HighlightStyle, tags, getChunks } from '../vendor/cm.js';
import { quebrasOcultas } from './paragrafo.js';
import * as tabela from './tabela.js';
import { hoje, marcaDaLinha } from './marcas.js';

export { hoje };
// Cada marca, a sua caixa.
const CAIXA = { to_do: 'fazer', to_validate: 'validar', comment: 'comentario' };
const esc = (s) => s.replace(/[&<>"]/g, (m) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[m]));

// Markdown inline, só para ler as células da tabela — nunca usado para escrever nada.
export function inline(t) {
  return esc(t)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*|__([^_]+)__/g, (_, a, b) => `<b>${a || b}</b>`)
    .replace(/(^|[^*\w])\*([^*\s][^*]*)\*/g, '$1<i>$2</i>')
    // A URL some; uma marca que estava nela fica, vazia, para não desequilibrar a célula.
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, t, url) => `<span class="cm-link-texto">${t}</span>${url.replace(/[^\uE000\uE001]/g, '')}`)
    .replace(/\\\|/g, '|');
}

// As marcas da MergeView sobre a grade. Dentro da faixa que a grade substitui, as marcas de
// palavra do CodeMirror (`.cm-changedText`) não aparecem; a grade as desenha nas células, com
// a mesma classe, e o tema da MergeView pinta igual à prosa: riscado à esquerda, sublinhado
// à direita. Só exibição: o texto do editor não muda.
const ABRE = '\uE000', FECHA = '\uE001';
const MARCA = '<span class="cm-changedText">';

// As faixas mudadas deste lado, em posições do documento — as mesmas que a MergeView marca.
// Um editor fora de uma MergeView não tem faixas.
export function faixasDoLado(state) {
  const r = getChunks(state);
  if (!r || !r.side) return [];
  const a = r.side === 'a', out = [];
  for (const ch of r.chunks) {
    const ini = a ? ch.fromA : ch.fromB;
    for (const c of ch.changes) {
      const de = ini + (a ? c.fromA : c.fromB), ate = ini + (a ? c.toA : c.toB);
      if (ate > de) out.push([de, ate]);
    }
  }
  return out;
}

// Faixas do documento → faixas de cada linha da tabela, em posições da linha.
export function faixasDasLinhas(linhas, from, faixas) {
  let p = from;
  return linhas.map((l) => {
    const ini = p, fim = p + l.length;
    p = fim + 1;
    const out = [];
    for (const [a, b] of faixas) {
      const de = Math.max(a, ini), ate = Math.min(b, fim);
      if (ate > de) out.push([de - ini, ate - ini]);
    }
    return out;
  });
}

// Os trechos de uma célula em HTML: o Markdown inline de `inline`, com a marca por dentro da
// formatação — ela fecha e reabre em volta de cada tag, então o HTML continua bem aninhado.
export function celulaHTML(segs) {
  const bruto = segs.map((s) => {
    const t = s.t.replace(/[\uE000\uE001]/g, '');
    return s.m ? ABRE + t + FECHA : t;
  }).join('');
  let dentro = false, out = '';
  for (const peca of inline(bruto).split(/(<[^>]*>|[\uE000\uE001])/)) {
    if (peca === ABRE) { if (!dentro) out += MARCA; dentro = true; }
    else if (peca === FECHA) { if (dentro) out += '</span>'; dentro = false; }
    else if (peca.startsWith('<') && dentro) out += '</span>' + peca + MARCA;
    else out += peca;
  }
  if (dentro) out += '</span>';
  return out.split(MARCA + '</span>').join('');
}

class Texto extends WidgetType {
  constructor(t, cls) { super(); this.t = t; this.cls = cls; }
  eq(o) { return o.t === this.t && o.cls === this.cls; }
  toDOM() { const s = document.createElement('span'); s.textContent = this.t; if (this.cls) s.className = this.cls; return s; }
}

function controle(rotulo, titulo, fazer) {
  const b = document.createElement('button');
  b.className = 'cm-tab-ctl'; b.textContent = rotulo; b.title = titulo;
  b.addEventListener('mousedown', (e) => {
    e.preventDefault(); e.stopPropagation();
    try { fazer(); } catch (err) { b.title = err.message; b.classList.add('recusado'); }
  });
  return b;
}

export class Tabela extends WidgetType {
  // `realce`: por linha da tabela, as faixas mudadas em posições da linha.
  constructor(linhas, from, editavel, realce = linhas.map(() => [])) {
    super(); this.linhas = linhas; this.from = from; this.editavel = editavel; this.realce = realce;
  }
  eq(o) {
    return o.from === this.from && o.editavel === this.editavel && o.linhas.join('\n') === this.linhas.join('\n')
      && JSON.stringify(o.realce) === JSON.stringify(this.realce);
  }
  ignoreEvent() { return true; }
  trocar(view, novas) {
    view.dispatch({ changes: { from: this.from, to: this.from + this.linhas.join('\n').length, insert: novas.join('\n') } });
  }
  toDOM(view) {
    const caixa = document.createElement('div');
    caixa.className = 'cm-tabela';
    const t = document.createElement('table');
    const inicio = [];
    let p = this.from;
    for (const l of this.linhas) { inicio.push(p); p += l.length + 1; }
    this.linhas.forEach((linha, i) => {
      if (i === 1) return;                                   // o separador não aparece
      const tr = document.createElement('tr');
      tabela.segmentos(linha, this.realce[i]).forEach((segs, j) => {
        const td = document.createElement(i === 0 ? 'th' : 'td');
        const conteudo = document.createElement('span');
        conteudo.innerHTML = celulaHTML(segs);
        td.append(conteudo);
        td.addEventListener('mousedown', (e) => {           // clicar na célula abre o texto
          if (e.target.closest('.cm-tab-ctl') || !this.editavel) return;
          e.preventDefault(); view.focus();
          view.dispatch({ selection: { anchor: inicio[i] } });
        });
        if (this.editavel && i === 0) {
          td.append(controle('+', 'inserir coluna à direita', () => this.trocar(view, tabela.inserirColuna(this.linhas, j))),
                    controle('×', 'remover esta coluna', () => this.trocar(view, tabela.removerColuna(this.linhas, j))));
        }
        tr.append(td);
      });
      if (this.editavel) {
        const ctl = document.createElement('td');
        ctl.className = 'cm-tab-linha';
        ctl.append(controle('+', 'inserir linha abaixo', () => this.trocar(view, tabela.inserirLinha(this.linhas, Math.max(i, 1)))));
        if (i >= 2) ctl.append(controle('×', 'remover esta linha', () => this.trocar(view, tabela.removerLinha(this.linhas, i))));
        tr.append(ctl);
      }
      t.append(tr);
    });
    caixa.append(t);
    return caixa;
  }
}

// O foco entra no estado: todo editor nasce com o cursor em 0, e sem isto a primeira linha
// de cada trecho apareceria crua numa página em que ninguém clicou.
export const mudouFoco = StateEffect.define();
const foco = StateField.define({
  create: () => false,
  update: (v, tr) => { for (const e of tr.effects) if (e.is(mudouFoco)) return e.value; return v; },
});

const OCULTAVEIS = new Set(['EmphasisMark', 'CodeMark', 'LinkMark', 'StrikethroughMark']);

export function decorar(state, editavel) {
  const doc = state.doc;
  const arvore = ensureSyntaxTree(state, doc.length, 500) || syntaxTree(state);
  const ativo = editavel && state.field(foco, false) === true;
  const ativas = new Set();
  if (ativo) {
    for (const r of state.selection.ranges) {
      for (let n = doc.lineAt(r.from).number; n <= doc.lineAt(r.to).number; n++) ativas.add(n);
    }
  }
  const ativa = (pos) => ativas.has(doc.lineAt(pos).number);
  const cursor = ativo ? state.selection.main.head : -1;

  // 1ª passada: parágrafos e tabelas — o que decide as linhas que se juntam ou somem.
  const paragrafos = [], tabelas = [];
  arvore.iterate({ enter: (n) => {
    if (n.name === 'Table') { tabelas.push({ from: n.from, to: n.to }); return false; }
    if (n.name === 'Paragraph') paragrafos.push({ from: n.from, to: n.to });
  } });
  const deco = [];
  const juntas = new Set();                       // inícios de linha que ficam emendados
  for (const q of quebrasOcultas(doc.toString(), paragrafos, cursor)) {
    deco.push(Decoration.replace({ widget: new Texto(' ', 'cm-junta') }).range(q.from, q.to));
    juntas.add(q.to);
  }
  const blocos = [];                              // faixas que viraram grade
  const mudadas = tabelas.length ? faixasDoLado(state) : [];
  for (const tb of tabelas) {
    if (ativo && cursor >= tb.from && cursor <= tb.to) continue;
    const l1 = doc.lineAt(tb.from), l2 = doc.lineAt(tb.to);
    const linhas = doc.sliceString(l1.from, l2.to).split('\n');
    deco.push(Decoration.replace({ widget: new Tabela(linhas, l1.from, editavel, faixasDasLinhas(linhas, l1.from, mudadas)), block: true }).range(l1.from, l2.to));
    blocos.push([l1.from, l2.to]);
  }
  const numaGrade = (pos) => blocos.some(([a, b]) => pos >= a && pos <= b);
  const linha = (from, to, cls) => {
    for (let n = doc.lineAt(from).number; n <= doc.lineAt(to).number; n++) {
      const l = doc.line(n);
      if (!juntas.has(l.from) && !numaGrade(l.from)) deco.push(Decoration.line({ class: cls }).range(l.from));
    }
  };
  const esconder = (from, to) => { if (to > from && !numaGrade(from)) deco.push(Decoration.replace({}).range(from, to)); };
  const depoisEspaco = (to) => (doc.sliceString(to, to + 1) === ' ' ? to + 1 : to);

  // 2ª passada: o resto.
  arvore.iterate({ enter: (n) => {
    const nome = n.name;
    if (nome === 'Table') return false;
    // Sem URL não é link que o preview conheça — uma nota de rodapé `[^1]`, uma referência:
    // fica como está no arquivo, com os colchetes.
    if (nome === 'Link' && !n.node.getChild('URL')) return false;
    const pai = n.node.parent ? n.node.parent.name : '';
    const m = /^ATXHeading(\d)$/.exec(nome);
    if (m) linha(n.from, n.to, 'cm-h cm-h' + m[1]);
    else if (nome === 'HeaderMark' && pai.startsWith('ATXHeading') && !ativa(n.from)) esconder(n.from, depoisEspaco(n.to));
    else if (nome === 'CodeMark' && pai === 'FencedCode') { /* cercas: tratadas em FencedCode */ }
    else if (OCULTAVEIS.has(nome) && !ativa(n.from)) esconder(n.from, n.to);
    else if (nome === 'URL' && pai === 'Link' && !ativa(n.from)) esconder(n.from, n.to);
    else if (nome === 'Link' && !numaGrade(n.from)) deco.push(Decoration.mark({ class: 'cm-link-texto' }).range(n.from, n.to));
    else if (nome === 'QuoteMark' && !ativa(n.from)) esconder(n.from, depoisEspaco(n.to));
    else if (nome === 'Blockquote') {
      // Uma citação é marca só no formato exato; a primeira linha que for dá a cor da caixa.
      let tipo = '';
      for (let k = doc.lineAt(n.from).number; k <= doc.lineAt(n.to).number; k++) {
        const l = doc.line(k), m = marcaDaLinha(l.text);
        if (!m) continue;
        tipo = tipo || m.tipo;
        if (m.tipo === 'to_validate' && m.data < hoje()) {
          const d = l.from + l.text.indexOf(m.data);
          deco.push(Decoration.mark({ class: 'cm-vencida' }).range(d, d + 10));
        }
      }
      linha(n.from, n.to, 'cm-cit' + (tipo ? ' cm-cit-' + CAIXA[tipo] : ''));
    }
    else if (nome === 'ListMark' && !ativa(n.from) && n.node.parent?.parent?.name === 'BulletList') {
      deco.push(Decoration.replace({ widget: new Texto('•', 'cm-bala') }).range(n.from, n.to));
    }
    else if (nome === 'TaskMarker' && !ativa(n.from)) {
      const feito = /x/i.test(doc.sliceString(n.from, n.to));
      deco.push(Decoration.replace({ widget: new Texto(feito ? '☑' : '☐', 'cm-tarefa') }).range(n.from, n.to));
    }
    else if (nome === 'HorizontalRule') { linha(n.from, n.to, 'cm-hr'); if (!ativa(n.from)) esconder(n.from, n.to); }
    else if (nome === 'FencedCode') {
      linha(n.from, n.to, 'cm-codigo');
      const primeira = doc.lineAt(n.from), ultima = doc.lineAt(n.to);
      for (const l of [primeira, ultima]) if (!ativa(l.from)) deco.push(Decoration.line({ class: 'cm-cerca' }).range(l.from));
    }
  } });
  return Decoration.set(deco, true);
}

const campo = (editavel) => StateField.define({
  create: (s) => decorar(s, editavel),
  // A MergeView troca as mudanças por um efeito dela, sem mudar o texto deste lado (quem
  // digitou foi o outro, ou o diff ficou pronto depois): compara-se o valor, não o efeito.
  update: (valor, tr) => (tr.docChanged || tr.selection || tr.effects.some((e) => e.is(mudouFoco))
    || getChunks(tr.state)?.chunks !== getChunks(tr.startState)?.chunks
    ? decorar(tr.state, editavel) : valor),
  provide: (f) => EditorView.decorations.from(f),
});

// Cores e pesos do Markdown, nos dois modos; os tamanhos e a fonte do código inline só no
// Formatado — no Código tudo tem a mesma largura, para as tabelas alinharem.
const cores = [
  { tag: [tags.heading1, tags.heading2, tags.heading3, tags.heading4, tags.heading5, tags.heading6], fontWeight: '700' },
  { tag: tags.strong, fontWeight: '700' },
  { tag: tags.emphasis, fontStyle: 'italic' },
  { tag: tags.strikethrough, textDecoration: 'line-through' },
  { tag: tags.link, color: 'var(--acc)' },
  { tag: tags.url, color: 'var(--mut)' },
  { tag: tags.processingInstruction, color: 'var(--mut)' },
];
const estiloFormatado = HighlightStyle.define([
  ...cores,
  { tag: tags.heading1, fontSize: '1.5em' },
  { tag: tags.heading2, fontSize: '1.3em' },
  { tag: tags.heading3, fontSize: '1.15em' },
  { tag: tags.monospace, fontFamily: 'ui-monospace, Menlo, monospace', fontSize: '0.92em' },
]);
const estiloCodigo = HighlightStyle.define([...cores, { tag: tags.monospace, color: 'var(--ace)' }]);

// O painel é escuro: o cursor e a seleção vêm das cores da página, não do tema claro do
// CodeMirror, que desenha um cursor preto e uma seleção quase branca.
const tema = EditorView.theme({
  '.cm-scroller': { lineHeight: '1.62' },
  '.cm-content': { caretColor: 'var(--acc)' },
  '.cm-cursor, .cm-dropCursor': { borderLeftColor: 'var(--acc)', borderLeftWidth: '2px' },
  '&.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection':
    { background: 'color-mix(in srgb, var(--acc) 32%, transparent)' },
}, { dark: true });

// Texto de documento no Formatado (o CodeMirror vem com fonte monoespaçada por padrão);
// monoespaçada no Código.
const fonte = (familia) => EditorView.theme({ '.cm-scroller, .cm-content': { fontFamily: familia } });

// O live preview: a camada que esconde marcas, junta parágrafos e desenha a grade.
function vistaViva(editavel) {
  return [syntaxHighlighting(estiloFormatado), fonte('inherit'), foco,
          EditorView.focusChangeEffect.of((s, focando) => mudouFoco.of(focando)), campo(editavel)];
}
const vistaCodigo = () => [syntaxHighlighting(estiloCodigo), fonte('ui-monospace, Menlo, monospace')];

// O modo mora num Compartment: trocar reconfigura o editor em vez de refazê-lo, e o cursor,
// o histórico e o que foi digitado continuam onde estavam.
const modo = new Compartment();
const camada = (codigo, editavel) => (codigo ? vistaCodigo() : vistaViva(editavel));

export function editorMarkdown({ editavel = true, codigo = false } = {}) {
  return [markdown({ base: markdownLanguage }), tema, EditorView.lineWrapping,
          EditorState.readOnly.of(!editavel), EditorView.editable.of(editavel),
          modo.of(camada(codigo, editavel))];
}

// O efeito que põe um estado criado por editorMarkdown no modo pedido.
export function trocarModo(state, codigo) {
  return modo.reconfigure(camada(codigo, state.facet(EditorView.editable)));
}
