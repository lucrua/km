// A thin surface over the km CLI: the model lives there, the editor only shows it.
const vscode = require('vscode');
const cp = require('child_process');
const fs = require('fs');
const path = require('path');
const os = require('os');

const SCHEME = 'km-baseline';
const CORES = {
  'aprovado': '#2B6647', 'aceite': '#94600F', 'a-validar': '#2A4B6E',
  'reprovado': '#8B4E4E', 'suposicao': '#8A5A0B', 'nao revisado': '#5A6660',
};
const mexido = (e) => e.startsWith('mexido');
const chave = (e) => e.normalize('NFD').replace(/[̀-ͯ]/g, '');

function km(args, cwd) {
  const bin = vscode.workspace.getConfiguration('km').get('path')
    || path.join(os.homedir(), 'knowledge-manager', 'bin', 'km');
  return cp.execFileSync(bin, args, { cwd, encoding: 'utf8', maxBuffer: 32 * 1024 * 1024 });
}
const raiz = (doc) => vscode.workspace.getWorkspaceFolder(doc.uri)?.uri.fsPath;
const rel = (doc) => vscode.workspace.asRelativePath(doc.uri, false);

function raizDe(arquivo) {
  for (const f of vscode.workspace.workspaceFolders || []) {
    if (fs.existsSync(path.join(f.uri.fsPath, arquivo))) return f.uri.fsPath;
  }
  return null;
}

function blocos(doc) {
  const r = raiz(doc);
  if (!r || doc.languageId !== 'markdown') return [];
  try { return JSON.parse(km(['blocks', rel(doc), '--json'], r)); } catch (e) { return []; }
}

// ---- a coluna da esquerda: o documento como voce o chancelou -------------------
class Baseline {
  constructor() {
    this.emissor = new vscode.EventEmitter();
    this.onDidChange = this.emissor.event;   // sem isto o diff nunca redesenha
  }
  invalidar(arquivo) {
    this.emissor.fire(vscode.Uri.parse(SCHEME + ':' + arquivo).with({ query: arquivo }));
  }
  provideTextDocumentContent(uri) {
    const arquivo = uri.query;
    const dir = raizDe(arquivo);
    if (!dir) return '# km\n\nArquivo fora do workspace.';
    try { return km(['baseline', arquivo], dir); }
    catch (e) { return '# km\n\nNao consegui montar a baseline:\n\n' + e.message; }
  }
}

// ---- o aviso no topo do arquivo ------------------------------------------------
class Aviso {
  constructor() {
    this.mudou = new vscode.EventEmitter();
    this.onDidChangeCodeLenses = this.mudou.event;
  }
  provideCodeLenses(doc) {
    const bs = blocos(doc);
    if (!bs.length) return [];
    const m = bs.filter(b => mexido(b.state)).length;
    const nunca = bs.filter(b => chave(b.state) === 'nao revisado').length;
    const faixa = new vscode.Range(0, 0, 0, 0);
    if (!m && !nunca) {
      return [new vscode.CodeLens(faixa,
        { title: 'km · ' + bs.length + ' blocos, todos com a sua chancela', command: 'km.review' })];
    }
    const partes = [];
    if (m) partes.push(m + ' mexidos desde a sua chancela');
    if (nunca) partes.push(nunca + ' nunca revisados');
    return [new vscode.CodeLens(faixa,
      { title: 'km · ' + partes.join(' · ') + ' — revisar', command: 'km.review' })];
  }
}

// ---- a fronteira de bloco, desenhada sem tocar no texto ------------------------
const fronteira = vscode.window.createTextEditorDecorationType({
  isWholeLine: true,
  borderWidth: '1px 0 0 0', borderStyle: 'dashed',
  borderColor: new vscode.ThemeColor('editorIndentGuide.background'),
});
const porEstado = {};
for (const estado of Object.keys(CORES)) {
  porEstado[estado] = vscode.window.createTextEditorDecorationType({
    isWholeLine: true, overviewRulerColor: CORES[estado],
    overviewRulerLane: vscode.OverviewRulerLane.Right,
    borderWidth: '0 0 0 2px', borderStyle: 'solid', borderColor: CORES[estado],
  });
}
const mexidoDeco = vscode.window.createTextEditorDecorationType({
  isWholeLine: true, overviewRulerColor: '#E3B665',
  overviewRulerLane: vscode.OverviewRulerLane.Right,
  borderWidth: '0 0 0 2px', borderStyle: 'solid', borderColor: '#E3B665',
  after: { contentText: '   mexido depois da sua chancela', color: '#94600F', fontStyle: 'italic' },
});

function pintar(editor) {
  if (!editor || editor.document.languageId !== 'markdown') return;
  const bs = blocos(editor.document);
  const linhas = [], porCor = {}, mex = [];
  for (const b of bs) {
    const l = Math.max(0, b.line - 1);
    const faixa = new vscode.Range(l, 0, l, 0);
    linhas.push(faixa);
    if (mexido(b.state)) mex.push(faixa);
    else {
      const k = chave(b.state);
      (porCor[k] = porCor[k] || []).push(faixa);
    }
  }
  editor.setDecorations(fronteira, linhas);
  editor.setDecorations(mexidoDeco, mex);
  for (const estado of Object.keys(CORES)) {
    editor.setDecorations(porEstado[estado], porCor[estado] || []);
  }
}

// ---- as conversas -------------------------------------------------------------
// Uma thread so aparece onde ha algo a dizer: nota escrita, reprovacao ou pergunta
// em aberto. Bloco apenas mexido ja tem a marca na margem; virar thread seria ruido.
let conversas = null;
const abertas = new Map();

function precisaDeThread(b) {
  const notas = b.notes || [];
  return notas.length > 0 || b.state === 'reprovado' || b.state === 'a-validar';
}

function rotulo(b) {
  if (b.state === 'a-validar') {
    return 'a validar' + (b.due ? ' ate ' + b.due : '') + (b.at ? ' · desde ' + b.at : '');
  }
  if (mexido(b.state)) return b.state + (b.at ? ' em ' + b.at : '');
  return b.state + (b.at ? ' · ' + b.at : '');
}

function montarThreads(doc) {
  if (!conversas || doc.languageId !== 'markdown') return;
  const chaveDoc = doc.uri.toString();
  (abertas.get(chaveDoc) || []).forEach(t => t.dispose());
  abertas.set(chaveDoc, []);

  for (const b of blocos(doc)) {
    if (!precisaDeThread(b)) continue;
    const l = Math.max(0, b.line - 1);
    const comentarios = [];
    if (b.state === 'a-validar' && b.validate) {
      comentarios.push({
        author: { name: 'a validar' },
        body: new vscode.MarkdownString('**' + b.validate + '**'
          + (b.due ? '\n\nate ' + b.due : '')),
        mode: vscode.CommentMode.Preview,
      });
    }
    for (const n of (b.notes || [])) {
      comentarios.push({
        author: { name: n.by ? n.by.replace('human:', '') : 'voce' },
        body: new vscode.MarkdownString(n.text),
        mode: vscode.CommentMode.Preview,
        label: n.at,
      });
    }
    const t = conversas.createCommentThread(doc.uri, new vscode.Range(l, 0, l, 0), comentarios);
    t.label = b.heading + '  ·  ' + rotulo(b);
    t.contextValue = b.state;
    const resolvida = b.state === 'aprovado' || b.state === 'aceite';
    t.state = resolvida ? vscode.CommentThreadState.Resolved : vscode.CommentThreadState.Unresolved;
    t.collapsibleState = (b.state === 'reprovado' || b.state === 'a-validar')
      ? vscode.CommentThreadCollapsibleState.Expanded
      : vscode.CommentThreadCollapsibleState.Collapsed;
    abertas.get(chaveDoc).push(t);
  }
}

function blocoDaThread(thread) {
  const doc = vscode.workspace.textDocuments.find(d => d.uri.toString() === thread.uri.toString());
  if (!doc) return null;
  const linha = thread.range.start.line + 1;
  return blocos(doc).slice().reverse().find(b => b.line <= linha) || null;
}

function rodarNoBloco(thread, args, msg) {
  const b = blocoDaThread(thread);
  if (!b) { vscode.window.showWarningMessage('km: bloco nao encontrado'); return; }
  const doc = vscode.workspace.textDocuments.find(d => d.uri.toString() === thread.uri.toString());
  try {
    km(['vouch', b.file, '--block', b.heading].concat(args), raiz(doc));
    if (msg) vscode.window.showInformationMessage('km: ' + b.heading + ' → ' + msg);
    thread.dispose();
    atualizar(doc);
  } catch (err) { vscode.window.showErrorMessage('km: ' + err.message); }
}

function atualizar(doc) {
  if (!doc || doc.languageId !== 'markdown') return;
  const ed = vscode.window.visibleTextEditors.find(x => x.document === doc);
  if (ed) pintar(ed);
  montarThreads(doc);
  marcarProblemas(doc);
  avisos.mudou.fire();
  if (raiz(doc)) baseline.invalidar(rel(doc));
}

// ---- dar status ao bloco sob o cursor -----------------------------------------
const avisos = new Aviso();
const baseline = new Baseline();
const problemas = vscode.languages.createDiagnosticCollection('km');
const barra = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
barra.command = 'km.review';

const GRAVIDADE = {
  'reprovado': vscode.DiagnosticSeverity.Warning,
  'a-validar': vscode.DiagnosticSeverity.Information,
  'nao revisado': vscode.DiagnosticSeverity.Information,
};

function marcarProblemas(doc) {
  if (!doc || doc.languageId !== 'markdown' || !raiz(doc)) return;
  const bs = blocos(doc);
  const achados = [];
  let mexidos = 0, pendentes = 0;
  for (const b of bs) {
    const l = Math.max(0, b.line - 1);
    const faixa = new vscode.Range(l, 0, l, Math.max(1, b.heading.length + 2));
    if (mexido(b.state)) {
      mexidos += 1;
      achados.push(new vscode.Diagnostic(faixa,
        b.heading + ' — ' + b.state, vscode.DiagnosticSeverity.Warning));
    } else if (GRAVIDADE[chave(b.state)] !== undefined) {
      pendentes += 1;
      const extra = b.validate ? ' — ' + b.validate + (b.due ? ' (ate ' + b.due + ')' : '') : '';
      achados.push(new vscode.Diagnostic(faixa,
        b.heading + ' — ' + b.state + extra, GRAVIDADE[chave(b.state)]));
    }
  }
  for (const d of achados) d.source = 'km';
  problemas.set(doc.uri, achados);

  const comChancela = bs.length - mexidos - pendentes;
  barra.text = mexidos || pendentes
    ? '$(alert) km ' + comChancela + '/' + bs.length
    : '$(check) km ' + bs.length;
  barra.tooltip = mexidos + ' mexidos desde a sua chancela, ' + pendentes + ' pendentes';
  barra.show();
}

async function vouch() {
  const ed = vscode.window.activeTextEditor;
  if (!ed) return;
  const bs = blocos(ed.document);
  const linha = ed.selection.active.line + 1;
  const alvo = bs.slice().reverse().find(b => b.line <= linha);
  if (!alvo) { vscode.window.showWarningMessage('km: nenhum bloco aqui'); return; }
  const escolha = await vscode.window.showQuickPick([
    { label: 'aprovado', detail: 'li e endosso' },
    { label: 'aceite', detail: 'passei o olho; expira em 14 dias' },
    { label: 'a-validar', detail: 'depende de alguem de fora' },
    { label: 'reprovado', detail: 'esta errado; a nota e a instrucao' },
  ], { title: alvo.heading + ' — hoje: ' + alvo.state });
  if (!escolha) return;
  const args = ['vouch', alvo.file, '--block', alvo.heading, '--state', escolha.label];
  if (escolha.label === 'reprovado' || escolha.label === 'a-validar') {
    const nota = await vscode.window.showInputBox({
      title: escolha.label === 'reprovado' ? 'O que esta errado?' : 'O que confirmaria isso?' });
    if (nota) args.push(escolha.label === 'reprovado' ? '--note' : '--validate', nota);
  }
  try {
    km(args, raiz(ed.document));
    vscode.window.showInformationMessage('km: ' + alvo.heading + ' → ' + escolha.label);
    atualizar(ed.document);
  } catch (e) { vscode.window.showErrorMessage('km: ' + e.message); }
}

function activate(ctx) {
  conversas = vscode.comments.createCommentController('km', 'km · chancela');
  // O '+' so aparece onde comeca um bloco: comentar linha solta criaria conversa
  // presa a um ponto que o proximo agente reescreve sem saber que ela existia.
  conversas.commentingRangeProvider = {
    provideCommentingRanges(doc) {
      if (doc.languageId !== 'markdown' || !raiz(doc)) return [];
      return blocos(doc).map(function (b) {
        const ini = Math.max(0, b.line - 1);
        const fim = Math.max(ini, ini + b.lines - 1);
        return new vscode.Range(ini, 0, fim, 0);   // hover em qualquer linha do bloco
      });
    },
  };

  ctx.subscriptions.push(
    conversas,
    vscode.commands.registerCommand('km.reply', (reply) => {
      const b = blocoDaThread(reply.thread);
      const doc = vscode.workspace.textDocuments.find(
        d => d.uri.toString() === reply.thread.uri.toString());
      if (!b || !reply.text) return;
      try {
        km(['note', b.file, '--block', b.heading, reply.text], raiz(doc));
        reply.thread.dispose();   // a interface criou esta; quem redesenha somos nos
        atualizar(doc);
      } catch (err) { vscode.window.showErrorMessage('km: ' + err.message); }
    }),
    vscode.commands.registerCommand('km.aprovarThread',
      (t) => rodarNoBloco(t, ['--state', 'aprovado'], 'aprovado')),
    vscode.commands.registerCommand('km.reprovarThread', async (t) => {
      const nota = await vscode.window.showInputBox({ title: 'O que esta errado?' });
      if (nota !== undefined) {
        rodarNoBloco(t, ['--state', 'reprovado'].concat(nota ? ['--note', nota] : []), 'reprovado');
      }
    }),
    vscode.commands.registerCommand('km.validarThread', async (t) => {
      const q = await vscode.window.showInputBox({ title: 'O que confirmaria isso?' });
      if (q === undefined) return;
      const prazo = await vscode.window.showInputBox({
        title: 'Ate quando? (AAAA-MM-DD, vazio = sem prazo)' });
      const extra = ['--state', 'a-validar'].concat(q ? ['--validate', q] : [])
        .concat(prazo ? ['--due', prazo] : []);
      rodarNoBloco(t, extra, 'a validar');
    }),
    vscode.workspace.registerTextDocumentContentProvider(SCHEME, baseline),
    vscode.languages.registerCodeLensProvider({ language: 'markdown' }, avisos),
    vscode.commands.registerCommand('km.vouch', vouch),
    vscode.commands.registerCommand('km.review', async () => {
      const ed = vscode.window.activeTextEditor;
      if (!ed) return;
      const arquivo = rel(ed.document);
      const esq = vscode.Uri.parse(SCHEME + ':' + arquivo).with({ query: arquivo });
      await vscode.commands.executeCommand('vscode.diff', esq, ed.document.uri,
        path.basename(arquivo) + ' · chancela ↔ agora');
    }),
    problemas, barra,
    vscode.window.onDidChangeActiveTextEditor(function (ed) {
      if (ed && ed.document.languageId === 'markdown') {
        pintar(ed); montarThreads(ed.document); marcarProblemas(ed.document);
      } else { barra.hide(); }
    }),
    vscode.workspace.onDidSaveTextDocument(atualizar),
    vscode.workspace.onDidOpenTextDocument(montarThreads)
  );
  const ativo = vscode.window.activeTextEditor;
  if (ativo) { pintar(ativo); montarThreads(ativo.document); marcarProblemas(ativo.document); }
}

module.exports = { activate: activate, deactivate: function () {} };
