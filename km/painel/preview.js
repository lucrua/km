// Live preview: the document is always the file's exact text; formatting is decoration.
// Off the cursor's line the Markdown markers are hidden, paragraphs flow, ⚠️ ❓ 🚫 quotes
// become coloured boxes and tables become a grid with row and column controls. All of it
// lives in one StateField: hidden line breaks and block widgets are decorations CodeMirror
// accepts only from the state, never from a plugin.
import { EditorView, Decoration, WidgetType, StateField, StateEffect, EditorState, syntaxTree,
         ensureSyntaxTree, markdown, markdownLanguage, syntaxHighlighting, HighlightStyle,
         tags } from '../vendor/cm.js';
import { quebrasOcultas } from './paragrafo.js';
import * as tabela from './tabela.js';

const hoje = () => new Date().toISOString().slice(0, 10);
const esc = (s) => s.replace(/[&<>"]/g, (m) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[m]));

// Markdown inline, só para ler as células da tabela — nunca usado para escrever nada.
export function inline(t) {
  return esc(t)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*|__([^_]+)__/g, (_, a, b) => `<b>${a || b}</b>`)
    .replace(/(^|[^*\w])\*([^*\s][^*]*)\*/g, '$1<i>$2</i>')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<span class="cm-link-texto">$1</span>')
    .replace(/\\\|/g, '|');
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

class Tabela extends WidgetType {
  constructor(linhas, from, editavel) { super(); this.linhas = linhas; this.from = from; this.editavel = editavel; }
  eq(o) { return o.from === this.from && o.editavel === this.editavel && o.linhas.join('\n') === this.linhas.join('\n'); }
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
      tabela.celulas(linha).forEach((c, j) => {
        const td = document.createElement(i === 0 ? 'th' : 'td');
        const conteudo = document.createElement('span');
        conteudo.innerHTML = inline(c);
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
  for (const tb of tabelas) {
    if (ativo && cursor >= tb.from && cursor <= tb.to) continue;
    const l1 = doc.lineAt(tb.from), l2 = doc.lineAt(tb.to);
    const linhas = doc.sliceString(l1.from, l2.to).split('\n');
    deco.push(Decoration.replace({ widget: new Tabela(linhas, l1.from, editavel), block: true }).range(l1.from, l2.to));
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
    const pai = n.node.parent ? n.node.parent.name : '';
    const m = /^ATXHeading(\d)$/.exec(nome);
    if (m) linha(n.from, n.to, 'cm-h cm-h' + m[1]);
    else if (nome === 'HeaderMark' && !ativa(n.from)) esconder(n.from, depoisEspaco(n.to));
    else if (nome === 'CodeMark' && pai === 'FencedCode') { /* cercas: tratadas em FencedCode */ }
    else if (OCULTAVEIS.has(nome) && !ativa(n.from)) esconder(n.from, n.to);
    else if (nome === 'URL' && pai === 'Link' && !ativa(n.from)) esconder(n.from, n.to);
    else if (nome === 'Link' && !numaGrade(n.from)) deco.push(Decoration.mark({ class: 'cm-link-texto' }).range(n.from, n.to));
    else if (nome === 'QuoteMark' && !ativa(n.from)) esconder(n.from, depoisEspaco(n.to));
    else if (nome === 'Blockquote') {
      const texto = doc.sliceString(n.from, n.to);
      const tipo = /🚫/.test(texto) ? 'veto' : /❓/.test(texto) ? 'pergunta' : /⚠/.test(texto) ? 'alerta' : '';
      linha(n.from, n.to, 'cm-cit' + (tipo ? ' cm-cit-' + tipo : ''));
      if (tipo === 'pergunta') {
        for (const d of texto.matchAll(/\d{4}-\d{2}-\d{2}/g)) {
          if (d[0] < hoje()) deco.push(Decoration.mark({ class: 'cm-vencida' }).range(n.from + d.index, n.from + d.index + 10));
        }
      }
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
  update: (valor, tr) => (tr.docChanged || tr.selection || tr.effects.some((e) => e.is(mudouFoco))
    ? decorar(tr.state, editavel) : valor),
  provide: (f) => EditorView.decorations.from(f),
});

const estilo = HighlightStyle.define([
  { tag: tags.heading1, fontSize: '1.5em', fontWeight: '700' },
  { tag: tags.heading2, fontSize: '1.3em', fontWeight: '700' },
  { tag: tags.heading3, fontSize: '1.15em', fontWeight: '700' },
  { tag: [tags.heading4, tags.heading5, tags.heading6], fontWeight: '700' },
  { tag: tags.strong, fontWeight: '700' },
  { tag: tags.emphasis, fontStyle: 'italic' },
  { tag: tags.strikethrough, textDecoration: 'line-through' },
  { tag: tags.monospace, fontFamily: 'ui-monospace, Menlo, monospace', fontSize: '0.92em' },
  { tag: tags.link, color: 'var(--acc)' },
  { tag: tags.url, color: 'var(--mut)' },
  { tag: tags.processingInstruction, color: 'var(--mut)' },
]);

// Texto de documento, não de código: o CodeMirror vem com fonte monoespaçada por padrão.
const tema = EditorView.theme({
  '.cm-scroller': { fontFamily: 'inherit', lineHeight: '1.62' },
  '.cm-content': { fontFamily: 'inherit' },
});

export function vistaViva({ editavel = true } = {}) {
  return [markdown({ base: markdownLanguage }), syntaxHighlighting(estilo), foco,
          EditorView.focusChangeEffect.of((s, focando) => mudouFoco.of(focando)), campo(editavel),
          tema, EditorView.lineWrapping, EditorState.readOnly.of(!editavel), EditorView.editable.of(editavel)];
}
