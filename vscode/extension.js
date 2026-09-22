// A thin surface over the km CLI: the model lives there, the editor only shows it.
//
// The chancel is a reviewed copy of the file in refs/km/chancela, so the left-hand column
// is `km baseline` (which is `git show refs/km/chancela:<file>`) and the state of each
// passage comes from `km pendente --json`. Reservations are not stored here: they are
// written into the document as blockquotes, and this extension exists partly to insert
// them in the agreed form.
const vscode = require('vscode');
const cp = require('child_process');
const fs = require('fs');
const path = require('path');
const os = require('os');
const http = require('http');

const SCHEME = 'km-baseline';
const CORES = {
  'com chancela': '#2B6647',
  'mexido': '#E3B665',
  'sem chancela': '#5A6660',
};
const MARCAS = {
  '⚠️': { rotulo: 'sem certeza', modelo: '> ⚠️ **sem certeza** — ' },
  '❓': { rotulo: 'a confirmar', modelo: '> ❓ **a confirmar até DATA** — ' },
  '🚫': { rotulo: 'discordo', modelo: '> 🚫 **discordo** — ' },
};
const hoje = () => new Date().toISOString().slice(0, 10);
const emDias = (n) => new Date(Date.now() + n * 864e5).toISOString().slice(0, 10);

function km(args, cwd) {
  const bin = vscode.workspace.getConfiguration('km').get('path')
    || path.join(os.homedir(), 'knowledge-manager', 'bin', 'km');
  return cp.execFileSync(bin, args, { cwd, encoding: 'utf8', maxBuffer: 32 * 1024 * 1024 });
}
const raiz = (doc) => vscode.workspace.getWorkspaceFolder(doc.uri)?.uri.fsPath;
const rel = (doc) => vscode.workspace.asRelativePath(doc.uri, false);

// ---- o painel: um servidor local sob demanda, aberto na propria janela ----------
let painel = null;   // o processo do `km serve`, preso a esta janela

function porta() {
  return vscode.workspace.getConfiguration('km').get('port') || 8431;
}

// Responde, e responde sobre ESTE repositorio: um painel de outra pasta na mesma porta
// mostraria arquivos que nao sao os que voce esta olhando.
function quemAtende(p) {
  return new Promise((ok) => {
    const req = http.get({ host: '127.0.0.1', port: p, path: '/api/state' }, (res) => {
      if (res.statusCode !== 200) { res.resume(); return ok(null); }
      let corpo = '';
      res.on('data', (d) => { corpo += d; });
      res.on('end', () => { try { ok(JSON.parse(corpo).root || ''); } catch (e) { ok(null); } });
    });
    req.on('error', () => ok(null));
    req.setTimeout(1500, () => { req.destroy(); ok(null); });
  });
}

async function abrirPainel() {
  const doc = vscode.window.activeTextEditor?.document;
  const pasta = (doc && vscode.workspace.getWorkspaceFolder(doc.uri))
    || (vscode.workspace.workspaceFolders || [])[0];
  if (!pasta) { vscode.window.showWarningMessage('km: abra uma pasta primeiro'); return; }
  const dir = pasta.uri.fsPath;
  const inicial = porta();

  let p = null, jaEsta = false;
  for (let tentativa = 0; tentativa < 10; tentativa++) {
    const quem = await quemAtende(inicial + tentativa);
    if (quem === null || quem === dir) { p = inicial + tentativa; jaEsta = quem === dir; break; }
  }
  if (p === null) { vscode.window.showErrorMessage('km: não achei porta livre'); return; }

  if (!jaEsta) {
    const bin = vscode.workspace.getConfiguration('km').get('path')
      || path.join(os.homedir(), 'knowledge-manager', 'bin', 'km');
    // Preso a esta janela de proposito: fechar o VS Code encerra o servidor, e ninguem
    // fica com um processo esquecido escutando numa porta.
    painel = cp.spawn(bin, ['serve', '--port', String(p)], { cwd: dir });
    let erro = '';
    painel.stderr?.on('data', (d) => { erro += d; });
    painel.on('error', (e) => vscode.window.showErrorMessage('km: ' + e.message));
    let subiu = false;
    for (let i = 0; i < 25 && !subiu; i++) {
      await new Promise((r) => setTimeout(r, 150));
      subiu = (await quemAtende(p)) === dir;
    }
    if (!subiu) {
      vscode.window.showErrorMessage('km: o painel não subiu. ' + (erro.trim() || 'veja o comando `km serve` no terminal'));
      return;
    }
  }
  // O VS Code aqui roda no WSL e a janela no Windows: sem asExternalUri, o 127.0.0.1 do
  // webview seria o do Windows, e o painel nao apareceria.
  const externo = await vscode.env.asExternalUri(
    vscode.Uri.parse('http://127.0.0.1:' + p + '/'));
  await vscode.commands.executeCommand('simpleBrowser.show', externo.toString(true));
}

function raizDe(arquivo) {
  for (const f of vscode.workspace.workspaceFolders || []) {
    if (fs.existsSync(path.join(f.uri.fsPath, arquivo))) return f.uri.fsPath;
  }
  return null;
}

// Um trecho: titulo, estado contra a chancela, ressalvas e o que o diff comeu.
function trechos(doc) {
  const r = raiz(doc);
  if (!r || doc.languageId !== 'markdown') return [];
  try { return JSON.parse(km(['pendente', rel(doc), '--json'], r)); } catch (e) { return []; }
}

const vencida = (c) => {
  const m = /(\d{4}-\d{2}-\d{2})/.exec(c.text);
  return c.mark === '❓' && m && m[1] < hoje();
};

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
    catch (e) { return '# km\n\nNao consegui ler a chancela:\n\n' + e.message; }
  }
}

// ---- o aviso no topo do arquivo ------------------------------------------------
class Aviso {
  constructor() {
    this.mudou = new vscode.EventEmitter();
    this.onDidChangeCodeLenses = this.mudou.event;
  }
  provideCodeLenses(doc) {
    const ts = trechos(doc);
    if (!ts.length) return [];
    const faixa = new vscode.Range(0, 0, 0, 0);
    const m = ts.filter(t => t.state === 'mexido').length;
    const nunca = ts.filter(t => t.state === 'sem chancela').length;
    const partes = [];
    if (m) partes.push(m + ' mexidos desde a sua chancela');
    if (nunca) partes.push(nunca + ' sem chancela');
    const titulo = partes.length
      ? 'km · ' + partes.join(' · ') + ' — abrir o painel'
      : 'km · ' + ts.length + ' trechos, todos com a sua chancela';
    // O painel e onde se revisa. O diff do editor continua no menu de contexto, para
    // quando voce quer so olhar as linhas sem sair do arquivo.
    return [new vscode.CodeLens(faixa, { title: titulo, command: 'km.abrirPainel' })];
  }
}

// ---- as marcas, desenhadas sem tocar no texto ----------------------------------
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
    after: estado === 'mexido'
      ? { contentText: '   mexido depois da sua chancela', color: '#94600F', fontStyle: 'italic' }
      : undefined,
  });
}
const bloqueado = vscode.window.createTextEditorDecorationType({
  isWholeLine: true, overviewRulerColor: '#8B4E4E',
  overviewRulerLane: vscode.OverviewRulerLane.Right,
  borderWidth: '0 0 0 2px', borderStyle: 'solid', borderColor: '#8B4E4E',
  after: { contentText: '   bloqueado por 🚫', color: '#8B4E4E', fontStyle: 'italic' },
});

function pintar(editor) {
  if (!editor || editor.document.languageId !== 'markdown') return;
  const ts = trechos(editor.document);
  const linhas = [], porCor = {}, travados = [];
  for (const t of ts) {
    const l = Math.max(0, t.line - 1);
    const faixa = new vscode.Range(l, 0, l, 0);
    linhas.push(faixa);
    if (t.blocked) travados.push(faixa);
    else (porCor[t.state] = porCor[t.state] || []).push(faixa);
  }
  editor.setDecorations(fronteira, linhas);
  editor.setDecorations(bloqueado, travados);
  for (const estado of Object.keys(CORES)) {
    editor.setDecorations(porEstado[estado], porCor[estado] || []);
  }
}

// ---- as conversas: o que esta escrito no texto, lido como conversa -------------
// Nada aqui e armazenado. Uma thread e a projecao das ressalvas do proprio arquivo,
// e responder a ela escreve mais uma ressalva no arquivo, no formato combinado.
let conversas = null;
const abertas = new Map();

function precisaDeThread(t) {
  return (t.caveats || []).length > 0 || (t.dropped || []).length > 0 || !!t.blocked;
}

function montarThreads(doc) {
  if (!conversas || doc.languageId !== 'markdown') return;
  const chaveDoc = doc.uri.toString();
  (abertas.get(chaveDoc) || []).forEach(t => t.dispose());
  abertas.set(chaveDoc, []);

  for (const t of trechos(doc)) {
    if (!precisaDeThread(t)) continue;
    const comentarios = [];
    for (const c of (t.caveats || [])) {
      const corpo = c.text.replace(/^\s*>\s*/, '');
      comentarios.push({
        author: { name: MARCAS[c.mark] ? MARCAS[c.mark].rotulo : c.mark },
        body: new vscode.MarkdownString(vencida(c) ? corpo + '\n\n**prazo vencido**' : corpo),
        mode: vscode.CommentMode.Preview,
      });
    }
    for (const d of (t.dropped || [])) {
      comentarios.push({
        author: { name: 'ressalva removida' },
        body: new vscode.MarkdownString(
          'Esta ressalva estava na chancela e sumiu nesta versão:\n\n' + d
          + '\n\nAprovar aqui aprova também a remoção dela.'),
        mode: vscode.CommentMode.Preview,
      });
    }
    const l = Math.max(0, t.line - 1);
    const thread = conversas.createCommentThread(doc.uri, new vscode.Range(l, 0, l, 0), comentarios);
    thread.label = t.heading + '  ·  ' + t.state;
    thread.contextValue = t.state;
    const resolvida = t.state === 'com chancela' && !t.blocked && !(t.dropped || []).length;
    thread.state = resolvida
      ? vscode.CommentThreadState.Resolved : vscode.CommentThreadState.Unresolved;
    thread.collapsibleState = resolvida
      ? vscode.CommentThreadCollapsibleState.Collapsed
      : vscode.CommentThreadCollapsibleState.Expanded;
    abertas.get(chaveDoc).push(thread);
  }
}

function docDa(uri) {
  return vscode.workspace.textDocuments.find(d => d.uri.toString() === uri.toString());
}

function trechoDaLinha(doc, linha) {
  return trechos(doc).slice().reverse().find(t => t.line <= linha) || null;
}

function trechoDaThread(thread) {
  const doc = docDa(thread.uri);
  return doc ? trechoDaLinha(doc, thread.range.start.line + 1) : null;
}

// ---- escrever a ressalva no proprio texto, no formato combinado ----------------
async function inserirMarca(doc, trecho, marca, texto, prazo) {
  const modelo = MARCAS[marca];
  if (!modelo) return false;
  let linha = modelo.modelo.replace('DATA', prazo || emDias(14)) + texto;
  const alvo = Math.max(0, trecho.line - 1);
  const abaixoDoTitulo = /^#{1,6}\s/.test(doc.lineAt(alvo).text) ? alvo + 1 : alvo;
  const edit = new vscode.WorkspaceEdit();
  edit.insert(doc.uri, new vscode.Position(abaixoDoTitulo, 0), '\n' + linha + '\n');
  await vscode.workspace.applyEdit(edit);
  await doc.save();
  return true;
}

async function comentar(doc, trecho, marca) {
  const texto = await vscode.window.showInputBox({
    title: trecho.heading + ' — ' + MARCAS[marca].rotulo,
    prompt: 'Vai para o texto, como citação. Quem abrir o arquivo vê.',
  });
  if (!texto) return false;
  let prazo;
  if (marca === '❓') {
    prazo = await vscode.window.showInputBox({
      title: 'A confirmar até quando?', value: emDias(14),
      validateInput: (v) => /^\d{4}-\d{2}-\d{2}$/.test(v) ? null : 'AAAA-MM-DD',
    });
    if (!prazo) return false;
  }
  return inserirMarca(doc, trecho, marca, texto, prazo);
}

// ---- os tres veredictos --------------------------------------------------------
async function aprovar(doc, trecho, extra) {
  const args = ['chancela', trecho.file, '--hunk', trecho.heading];
  if (extra) args.push('-m', extra);
  try {
    km(args, raiz(doc));
    vscode.window.showInformationMessage('km: ' + trecho.heading + ' → na chancela');
    atualizar(doc);
    return true;
  } catch (e) {
    vscode.window.showErrorMessage('km: ' + (e.stdout || e.message));
    return false;
  }
}

async function aValidar(doc, trecho) {
  if (!(await comentar(doc, trecho, '❓'))) return;
  const novo = trechoDaLinha(doc, trecho.line) || trecho;
  await aprovar(doc, novo, 'a validar, com prazo no texto');
}

async function reverter(doc, trecho) {
  const motivo = await vscode.window.showInputBox({
    title: trecho.heading + ' — reverter', prompt: 'Por que a mudança não serve?' });
  if (motivo === undefined) return;
  try {
    km(['restore', trecho.file, '--hunk', trecho.heading, '-m', motivo || 'sem motivo'],
      raiz(doc));
    vscode.window.showInformationMessage(
      'km: ' + trecho.heading + ' voltou ao texto chancelado. O motivo vai no commit.');
    atualizar(doc);
  } catch (e) { vscode.window.showErrorMessage('km: ' + (e.stdout || e.message)); }
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

// ---- o painel de problemas e a barra -------------------------------------------
const avisos = new Aviso();
const baseline = new Baseline();
const problemas = vscode.languages.createDiagnosticCollection('km');
const barra = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
barra.command = 'km.abrirPainel';

function marcarProblemas(doc) {
  if (!doc || doc.languageId !== 'markdown' || !raiz(doc)) return;
  const ts = trechos(doc);
  if (!ts.length) {   // fora do include do .km/config.json: o km nao tem nada a dizer
    problemas.set(doc.uri, []);
    barra.hide();
    return;
  }
  const achados = [];
  let mexidos = 0, semChancela = 0;
  for (const t of ts) {
    const l = Math.max(0, t.line - 1);
    const faixa = new vscode.Range(l, 0, l, Math.max(1, t.heading.length + 2));
    const põe = (msg, sev) => achados.push(new vscode.Diagnostic(faixa, msg, sev));
    if (t.state === 'mexido') { mexidos += 1; põe(t.heading + ' — mexido desde a sua chancela', vscode.DiagnosticSeverity.Warning); }
    else if (t.state === 'sem chancela') { semChancela += 1; põe(t.heading + ' — nunca teve chancela', vscode.DiagnosticSeverity.Information); }
    if (t.blocked) põe(t.heading + ' — 🚫 ' + t.blocked.replace(/^\s*>\s*/, ''), vscode.DiagnosticSeverity.Warning);
    for (const c of (t.caveats || [])) {
      if (vencida(c)) põe(t.heading + ' — ❓ prazo vencido: ' + c.text.replace(/^\s*>\s*/, ''), vscode.DiagnosticSeverity.Warning);
    }
    for (const d of (t.dropped || [])) {
      põe(t.heading + ' — ressalva removida nesta versão: ' + d, vscode.DiagnosticSeverity.Warning);
    }
  }
  for (const d of achados) d.source = 'km';
  problemas.set(doc.uri, achados);

  const comChancela = ts.length - mexidos - semChancela;
  barra.text = (mexidos || semChancela)
    ? '$(alert) km ' + comChancela + '/' + ts.length
    : '$(check) km ' + ts.length;
  barra.tooltip = mexidos + ' mexidos desde a sua chancela, ' + semChancela + ' sem chancela';
  barra.show();
}

// ---- o menu do trecho sob o cursor ---------------------------------------------
async function veredicto() {
  const ed = vscode.window.activeTextEditor;
  if (!ed) return;
  const alvo = trechoDaLinha(ed.document, ed.selection.active.line + 1);
  if (!alvo) { vscode.window.showWarningMessage('km: nenhum trecho aqui'); return; }
  const escolha = await vscode.window.showQuickPick([
    { label: 'aprovar', detail: 'entra na chancela como está' },
    { label: 'a validar', detail: 'entra na chancela com um ❓ e um prazo, no texto' },
    { label: 'reverter', detail: 'volta ao texto que você chancelou' },
    { label: 'ressalva ⚠️', detail: 'escreve a dúvida no texto, sem travar nada' },
    { label: 'discordo 🚫', detail: 'escreve no texto e bloqueia a chancela deste trecho' },
  ], { title: alvo.heading + ' — hoje: ' + alvo.state });
  if (!escolha) return;
  if (escolha.label === 'aprovar') return void aprovar(ed.document, alvo);
  if (escolha.label === 'a validar') return void aValidar(ed.document, alvo);
  if (escolha.label === 'reverter') return void reverter(ed.document, alvo);
  const marca = escolha.label.endsWith('🚫') ? '🚫' : '⚠️';
  if (await comentar(ed.document, alvo, marca)) atualizar(ed.document);
}

function naThread(thread, fn) {
  const t = trechoDaThread(thread);
  const doc = docDa(thread.uri);
  if (!t || !doc) { vscode.window.showWarningMessage('km: trecho não encontrado'); return; }
  thread.dispose();          // a interface criou esta; quem redesenha somos nos
  fn(doc, t);
}

function activate(ctx) {
  conversas = vscode.comments.createCommentController('km', 'km · chancela');
  // O '+' aparece em qualquer linha do trecho: a ressalva e do trecho, nao da linha.
  conversas.commentingRangeProvider = {
    provideCommentingRanges(doc) {
      if (doc.languageId !== 'markdown' || !raiz(doc)) return [];
      return trechos(doc).map(function (t) {
        const ini = Math.max(0, t.line - 1);
        return new vscode.Range(ini, 0, Math.max(ini, ini + t.lines - 1), 0);
      });
    },
  };

  ctx.subscriptions.push(
    conversas,
    // Responder a uma conversa escreve uma ressalva no texto, no formato combinado:
    // e por isso que a UI existe — para que a convencao seja a saida natural.
    vscode.commands.registerCommand('km.reply', async (reply) => {
      const t = trechoDaThread(reply.thread);
      const doc = docDa(reply.thread.uri);
      if (!t || !doc || !reply.text) return;
      reply.thread.dispose();
      await inserirMarca(doc, t, '⚠️', reply.text);
      atualizar(doc);
    }),
    vscode.commands.registerCommand('km.aprovarThread', (t) => naThread(t, aprovar)),
    vscode.commands.registerCommand('km.validarThread', (t) => naThread(t, aValidar)),
    vscode.commands.registerCommand('km.reverterThread', (t) => naThread(t, reverter)),
    vscode.workspace.registerTextDocumentContentProvider(SCHEME, baseline),
    vscode.languages.registerCodeLensProvider({ language: 'markdown' }, avisos),
    vscode.commands.registerCommand('km.veredicto', veredicto),
    vscode.commands.registerCommand('km.abrirPainel', abrirPainel),
    vscode.commands.registerCommand('km.review', async () => {
      const ed = vscode.window.activeTextEditor;
      if (!ed) return;
      const arquivo = rel(ed.document);
      const esq = vscode.Uri.parse(SCHEME + ':' + arquivo).with({ query: arquivo });
      await vscode.commands.executeCommand('vscode.diff', esq, ed.document.uri,
        path.basename(arquivo) + ' · chancela ↔ agora');
    }),
    vscode.commands.registerCommand('km.chancelarArquivo', async () => {
      const ed = vscode.window.activeTextEditor;
      if (!ed) return;
      const motivo = await vscode.window.showInputBox({
        title: 'Chancelar o arquivo inteiro', prompt: 'Por que você endossa? (vai no commit da chancela)' });
      if (motivo === undefined) return;
      try {
        km(['chancela', rel(ed.document), '--all'].concat(motivo ? ['-m', motivo] : []),
          raiz(ed.document));
        atualizar(ed.document);
        vscode.window.showInformationMessage('km: arquivo inteiro na chancela');
      } catch (e) { vscode.window.showErrorMessage('km: ' + (e.stdout || e.message)); }
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

module.exports = {
  activate: activate,
  deactivate: function () { if (painel) { painel.kill(); painel = null; } },
};
