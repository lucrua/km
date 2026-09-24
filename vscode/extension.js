// A thin surface over the km CLI: the model lives there, the editor only shows it.
//
// The chancel is a reviewed copy of the file in refs/km/chancela, so the left-hand column
// is `km baseline` (which is `git show refs/km/chancela:<file>`) and the state of each
// passage comes from `km pendente --json`. The marks (❓ to_validate, 💬 comment, 📌 to_do)
// are not stored here: they are blockquotes in the document, written in the panel.
const vscode = require('vscode');
const cp = require('child_process');
const fs = require('fs');
const path = require('path');
const os = require('os');
const http = require('http');
const { uriDaAba } = require('./aba');

const SCHEME = 'km-baseline';

function km(args, cwd) {
  const bin = vscode.workspace.getConfiguration('km').get('path')
    || path.join(os.homedir(), 'knowledge-manager', 'bin', 'km');
  return cp.execFileSync(bin, args, { cwd, encoding: 'utf8', maxBuffer: 32 * 1024 * 1024 });
}
const raiz = (uri) => vscode.workspace.getWorkspaceFolder(uri)?.uri.fsPath;
const rel = (uri) => vscode.workspace.asRelativePath(uri, false);
const ehMarkdown = (uri) => /\.md$/i.test(uri.path);

// O arquivo em foco, aberto como texto ou num editor customizado (um webview de outra
// extensão, onde nem decoração nem CodeLens chegam).
const arquivoAtivo = () =>
  uriDaAba(vscode.window.tabGroups.activeTabGroup.activeTab, vscode)
  || vscode.window.activeTextEditor?.document.uri;

// ---- o painel: um servidor local sob demanda, aberto no navegador ----------------
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
  const uri = arquivoAtivo();
  const pasta = (uri && vscode.workspace.getWorkspaceFolder(uri))
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
  // O VS Code aqui roda no WSL e o navegador no Windows: asExternalUri encaminha a porta,
  // sem ele o 127.0.0.1 seria o do Windows e o painel nao apareceria.
  const externo = await vscode.env.asExternalUri(
    vscode.Uri.parse('http://127.0.0.1:' + p + '/'));
  await vscode.env.openExternal(externo);
}

function raizDe(arquivo) {
  for (const f of vscode.workspace.workspaceFolders || []) {
    if (fs.existsSync(path.join(f.uri.fsPath, arquivo))) return f.uri.fsPath;
  }
  return null;
}

// O que o editor sabe do arquivo: onde estão as mudanças pendentes e quanto do conteúdo
// elas são. A unidade é a mudança, a medida é o %: nada de contagem por título.
function estado(uri) {
  const r = raiz(uri);
  if (!r || !ehMarkdown(uri)) return null;
  try { return JSON.parse(km(['pendente', rel(uri), '--json'], r))[0] || null; }
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
    const e = estado(doc.uri);
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

function faixa(m) {
  return new vscode.Range(Math.max(0, m.linha - 1), 0, Math.max(0, m.fim - 2), 0);
}

function pintar(editor) {
  if (!editor || editor.document.languageId !== 'markdown') return;
  const e = estado(editor.document.uri);
  const ms = e ? e.mudancas : [];
  editor.setDecorations(pendenteDeco, ms.map(faixa));
}

// ---- a barra: o arquivo em foco, também quando aberto num editor customizado -----
const avisos = new Aviso();
const baseline = new Baseline();
const barra = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
barra.command = 'km.abrirPainel';

function mostrarBarra() {
  const uri = arquivoAtivo();
  const e = uri && estado(uri);
  if (!e) { barra.hide(); return; }   // arquivo não acompanhado: o km não tem nada a dizer
  barra.text = !e.tem_chancela ? '$(circle-outline) km sem chancela'
    : (e.pendente ? '$(alert) km ' + e.pct + ' a aprovar' : '$(check) km');
  barra.tooltip = !e.tem_chancela ? 'este arquivo nunca teve chancela — clique para abrir o painel'
    : (e.pendente ? e.pct + ' do conteúdo a aprovar — clique para abrir o painel' : 'em dia com a chancela');
  barra.show();
}

let emFoco = '';
function seTrocouDeArquivo() {
  const agora = arquivoAtivo()?.toString() || '';
  if (agora === emFoco) return;
  emFoco = agora;
  mostrarBarra();
}

function atualizar(doc) {
  if (!doc || doc.languageId !== 'markdown') return;
  const ed = vscode.window.visibleTextEditors.find(x => x.document === doc);
  if (ed) pintar(ed);
  mostrarBarra();
  avisos.mudou.fire();
  if (raiz(doc.uri)) baseline.invalidar(rel(doc.uri));
}

// ---- a mudança sob o cursor ------------------------------------------------------
async function veredicto() {
  const ed = vscode.window.activeTextEditor;
  if (!ed) return;
  const e = estado(ed.document.uri);
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
    { label: 'Abrir o painel', detail: 'aprovar parte, 📌 ❓ 💬 depois do trecho, ver lado a lado' },
  ], { title: (m.titulo || 'mudança') + ' — pendente' });
  if (!escolha) return;
  if (escolha.label === 'Abrir o painel') return void abrirPainel();
  const args = escolha.label === 'Aprovar'
    ? ['chancela', rel(ed.document.uri), '--hunk', String(m.n)]
    : ['restore', rel(ed.document.uri), '--hunk', String(m.n)];
  try {
    km(args, raiz(ed.document.uri));
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
      const arquivo = rel(ed.document.uri);
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
        km(['chancela', rel(ed.document.uri), '--all'].concat(motivo ? ['-m', motivo] : []),
          raiz(ed.document.uri));
        atualizar(ed.document);
        vscode.window.showInformationMessage('km: arquivo inteiro na chancela');
      } catch (e) { vscode.window.showErrorMessage('km: ' + (e.stdout || e.message)); }
    }),
    barra,
    vscode.window.onDidChangeActiveTextEditor(function (ed) {
      if (ed) pintar(ed);
      mostrarBarra();
    }),
    // Trocar para uma aba de editor customizado não muda o editor de texto ativo. As abas
    // também avisam a cada tecla (o sujo muda): só refaz quando o arquivo em foco é outro.
    vscode.window.tabGroups.onDidChangeTabs(seTrocouDeArquivo),
    vscode.window.tabGroups.onDidChangeTabGroups(seTrocouDeArquivo),
    vscode.workspace.onDidSaveTextDocument(atualizar)
  );
  const ativo = vscode.window.activeTextEditor;
  if (ativo) pintar(ativo);
  mostrarBarra();
}

module.exports = {
  activate: activate,
  deactivate: function () { if (painel) { painel.kill(); painel = null; } },
};
