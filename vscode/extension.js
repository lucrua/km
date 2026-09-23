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
// O que o editor sabe do arquivo: onde estão as mudanças pendentes e quanto do conteúdo
// elas são. A unidade é a mudança, a medida é o %: nada de contagem por título.
function estado(doc) {
  const r = raiz(doc);
  if (!r || doc.languageId !== 'markdown') return null;
  try { return JSON.parse(km(['pendente', rel(doc), '--json'], r))[0] || null; }
  catch (e) { return null; }
}

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
    const e = estado(doc);
    if (!e) return [];
    const titulo = !e.tem_chancela ? 'km · sem chancela — abrir o painel'
      : (e.pendente ? 'km · ' + e.pct + ' a aprovar — abrir o painel'
                    : 'km · em dia com a chancela');
    return [new vscode.CodeLens(new vscode.Range(0, 0, 0, 0),
      { title: titulo, command: 'km.abrirPainel' })];
  }
}

// ---- onde estão as mudanças, na margem ------------------------------------------
const pendenteDeco = vscode.window.createTextEditorDecorationType({
  isWholeLine: true, overviewRulerColor: '#E3B665',
  overviewRulerLane: vscode.OverviewRulerLane.Right,
  borderWidth: '0 0 0 2px', borderStyle: 'solid', borderColor: '#E3B665',
});
const bloqueadoDeco = vscode.window.createTextEditorDecorationType({
  isWholeLine: true, overviewRulerColor: '#8B4E4E',
  overviewRulerLane: vscode.OverviewRulerLane.Right,
  borderWidth: '0 0 0 2px', borderStyle: 'solid', borderColor: '#8B4E4E',
});

function faixa(m) {
  return new vscode.Range(Math.max(0, m.linha - 1), 0, Math.max(0, m.fim - 2), 0);
}

function pintar(editor) {
  if (!editor || editor.document.languageId !== 'markdown') return;
  const e = estado(editor.document);
  const ms = e ? e.mudancas : [];
  editor.setDecorations(pendenteDeco, ms.filter(m => !m.bloqueio).map(faixa));
  editor.setDecorations(bloqueadoDeco, ms.filter(m => m.bloqueio).map(faixa));
}

// ---- o painel de problemas e a barra -------------------------------------------
const avisos = new Aviso();
const baseline = new Baseline();
const problemas = vscode.languages.createDiagnosticCollection('km');
const barra = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
barra.command = 'km.abrirPainel';

function marcarProblemas(doc) {
  if (!doc || doc.languageId !== 'markdown' || !raiz(doc)) return;
  const e = estado(doc);
  if (!e) {   // arquivo não acompanhado: o km não tem nada a dizer
    problemas.set(doc.uri, []);
    barra.hide();
    return;
  }
  const achados = [];
  const sev = vscode.DiagnosticSeverity;
  for (const m of e.mudancas) {
    const r = faixa(m);
    if (m.bloqueio) achados.push(new vscode.Diagnostic(r, '🚫 ' + m.bloqueio.replace(/^\s*>\s*/, ''), sev.Warning));
    for (const s of m.sumidas) achados.push(new vscode.Diagnostic(r, 'ressalva removida desde a chancela: ' + s, sev.Warning));
    if (!m.bloqueio && !m.sumidas.length) {
      achados.push(new vscode.Diagnostic(r, 'mudança pendente de chancela' + (m.titulo ? ' — ' + m.titulo : ''), sev.Information));
    }
  }
  for (const v of e.vencidas) {
    const l = Math.max(0, v.linha - 1);
    achados.push(new vscode.Diagnostic(new vscode.Range(l, 0, l, 200), '❓ prazo vencido em ' + v.prazo, sev.Warning));
  }
  for (const d of achados) d.source = 'km';
  problemas.set(doc.uri, achados);
  barra.text = !e.tem_chancela ? '$(circle-outline) km sem chancela'
    : (e.pendente ? '$(alert) km ' + e.pct : '$(check) km');
  barra.tooltip = !e.tem_chancela ? 'este arquivo nunca teve chancela'
    : (e.pendente ? e.pct + ' do conteúdo a aprovar — clique para abrir o painel' : 'em dia com a chancela');
  barra.show();
}

function atualizar(doc) {
  if (!doc || doc.languageId !== 'markdown') return;
  const ed = vscode.window.visibleTextEditors.find(x => x.document === doc);
  if (ed) pintar(ed);
  marcarProblemas(doc);
  avisos.mudou.fire();
  if (raiz(doc)) baseline.invalidar(rel(doc));
}

// ---- a mudança sob o cursor ------------------------------------------------------
async function veredicto() {
  const ed = vscode.window.activeTextEditor;
  if (!ed) return;
  const e = estado(ed.document);
  const linha = ed.selection.active.line + 1;
  const m = e && e.mudancas.find(x => x.linha <= linha && linha < Math.max(x.fim, x.linha + 1));
  if (!m) {
    const abrir = await vscode.window.showInformationMessage(
      'km: nada pendente nesta linha.', 'Abrir o painel');
    if (abrir) abrirPainel();
    return;
  }
  const escolha = await vscode.window.showQuickPick([
    { label: 'Aprovar', detail: 'a mudança inteira entra na chancela' },
    { label: 'Reverter', detail: 'o texto volta ao que você chancelou' },
    { label: 'Abrir o painel', detail: 'aprovar parte, a validar com prazo, ver lado a lado' },
  ], { title: (m.titulo || 'mudança') + ' — pendente' });
  if (!escolha) return;
  if (escolha.label === 'Abrir o painel') return void abrirPainel();
  const args = escolha.label === 'Aprovar'
    ? ['chancela', rel(ed.document), '--hunk', String(m.n)]
    : ['restore', rel(ed.document), '--hunk', String(m.n)];
  try {
    km(args, raiz(ed.document));
    vscode.window.showInformationMessage('km: ' + (m.titulo || 'mudança') + ' → ' + escolha.label.toLowerCase());
    atualizar(ed.document);
  } catch (err) { vscode.window.showErrorMessage('km: ' + (err.stdout || err.message)); }
}

function activate(ctx) {
  ctx.subscriptions.push(
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
      if (ed && ed.document.languageId === 'markdown') { pintar(ed); marcarProblemas(ed.document); }
      else { barra.hide(); }
    }),
    vscode.workspace.onDidSaveTextDocument(atualizar)
  );
  const ativo = vscode.window.activeTextEditor;
  if (ativo) { pintar(ativo); marcarProblemas(ativo.document); }
}

module.exports = {
  activate: activate,
  deactivate: function () { if (painel) { painel.kill(); painel = null; } },
};
