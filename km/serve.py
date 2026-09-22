"""The review surface: the chancel, in a page you can act on.

Plain HTML served from this file, bound to localhost, no build step and no dependencies.
It reads `refs/km/chancela` and the files on disk, and every action goes through the same
functions the CLI uses — the page is a surface, not a second implementation.

It is started when you sit down to review and stopped with Ctrl-C. Nothing runs in the
background, nothing is written except what you ask for: the ref, a reservation in the text,
or a passage you edited here.
"""

from __future__ import annotations

import difflib
import html
import json
import re
import webbrowser
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import chancela as ch
from . import cli

PALAVRA = re.compile(r"\s+|\w+|[^\w\s]")


def diff_inline(antes: str, agora: str) -> tuple[str, float, int]:
    """One stream, in reading order — the Word-like view.

    Prose is read in sequence, and side by side makes the eye jump. But interleaved marks
    turn a heavily rewritten paragraph into soup, so the caller gets the share of words that
    moved and can fall back to two columns when the change is wholesale.
    """
    a, b = PALAVRA.findall(antes), PALAVRA.findall(agora)
    # The share is measured against the longer side: a paragraph that shrinks by half
    # would otherwise report more than 100% of its words moved.
    saida, mexidas, total = [], 0, max(len(a), len(b), 1)
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        ta, tb = html.escape("".join(a[i1:i2])), html.escape("".join(b[j1:j2]))
        if tag == "equal":
            saida.append(tb)
        elif tag == "delete":
            saida.append(f"<del>{ta}</del>"); mexidas += i2 - i1
        elif tag == "insert":
            saida.append(f"<ins>{tb}</ins>"); mexidas += j2 - j1
        else:
            saida.append(f"<del>{ta}</del><ins>{tb}</ins>"); mexidas += max(i2 - i1, j2 - j1)
    return "".join(saida), round(mexidas / total, 3), mexidas


def diff_palavras(antes: str, agora: str) -> tuple[str, str]:
    """Word-level, because prose changes a word and a line diff paints the paragraph."""
    a, b = PALAVRA.findall(antes), PALAVRA.findall(agora)
    esq, dir_ = [], []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        ta, tb = html.escape("".join(a[i1:i2])), html.escape("".join(b[j1:j2]))
        if tag == "equal":
            esq.append(ta); dir_.append(tb)
        elif tag == "delete":
            esq.append(f"<del>{ta}</del>")
        elif tag == "insert":
            dir_.append(f"<ins>{tb}</ins>")
        else:
            esq.append(f"<del>{ta}</del>"); dir_.append(f"<ins>{tb}</ins>")
    return "".join(esq), "".join(dir_)


def _corpo(trecho) -> str:
    """The passage without its own heading — the heading is already the card's title."""
    if trecho is None:
        return ""
    if trecho.titulo_bruto:
        return trecho.texto.split("\n", 1)[1] if "\n" in trecho.texto else ""
    return trecho.texto


def _vencida(linha: str, hoje: str) -> bool:
    m = ch.PRAZO.search(linha)
    return bool(m and m.group(1) < hoje)


def _ultima(root: Path, rel: str) -> str:
    if not ch.existe(root):
        return ""
    linhas = ch.historico(root, rel, None, limite=1).strip().splitlines()
    partes = linhas[0].split(" ") if linhas else []
    return partes[1] if len(partes) > 1 else ""


def estado(root: Path, by: str = "") -> dict:
    """Everything the page needs, straight from the ref and the disk."""
    hoje = date.today().isoformat()
    docs = []
    for rel in ch.documentos(root):
        s = ch.situacao(root, rel, hoje)
        if not s.depois.strip():
            continue
        chancelados = {t.caminho: t for t in (ch.trechos(s.antes) if s.tem_chancela else [])}
        agora = {t.caminho: t for t in ch.trechos(s.depois)}
        blocos = []
        for e in ch.estados(s):
            atual = _corpo(agora.get(e["path"]))
            base = _corpo(chancelados.get(e["path"]))
            esq = dir_ = inline = None
            proporcao, mexidas = 0.0, 0
            if e["state"] == "mexido" and base:
                esq, dir_ = diff_palavras(base, atual)
                inline, proporcao, mexidas = diff_inline(base, atual)
            blocos.append({
                "heading": e["heading"], "path": e["path"], "line": e["line"],
                "lines": e["lines"], "estado": e["state"], "bloqueado": e["blocked"],
                "ressalvas": [{"mark": c["mark"], "text": c["text"].lstrip("> ").strip(),
                               "vencida": c["mark"] == "❓" and _vencida(c["text"], hoje)}
                              for c in e["caveats"]],
                "sumidas": e["dropped"], "hunks": e["hunks"],
                "texto": atual, "chancelado": base,
                # The sha of what the page is showing: saving sends it back, and the server
                # refuses if the passage moved meanwhile.
                "sha": ch.sha_do(agora[e["path"]].texto) if e["path"] in agora else "",
                "esq": esq, "dir": dir_, "inline": inline,
                "proporcao": proporcao, "mexidas": mexidas,
            })
        docs.append({"file": rel, "blocos": blocos, "rastreado": s.tem_chancela,
                     "em": _ultima(root, rel), "linhas": len(s.depois.splitlines())})
    docs.sort(key=lambda d: (not d["rastreado"], d["file"]))
    return {"repo": root.name, "root": str(root), "docs": docs, "hoje": hoje, "by": by}


# ---- the actions ---------------------------------------------------------------------

def _alvos(root: Path, rel: str, caminho: str) -> tuple[ch.Situacao, list, list[str]]:
    s = ch.situacao(root, rel)
    est = next((e for e in ch.estados(s) if e["path"] == caminho), None)
    if est is None:
        raise KeyError(caminho)
    alvos = [h for h in s.hunks if h.n in est["hunks"]]
    titulos = list(dict.fromkeys(h.titulo for h in alvos))
    return s, alvos, titulos


def agir(root: Path, pedido: dict, by: str) -> dict:
    """One place for every verdict, so the page and the CLI cannot drift apart."""
    acao = pedido.get("acao")
    rel = pedido.get("file", "")
    caminho = pedido.get("path", "")
    texto = (pedido.get("texto") or "").strip()

    if acao == "salvar":
        try:
            ch.substituir_trecho(root, rel, caminho, pedido.get("texto", ""),
                                 pedido.get("sha", ""))
        except ch.Conflito as e:
            return {"ok": False, "erro": "o texto mudou desde que você abriu",
                    "conflito": {"atual": e.atual}}
        return {"ok": True, "msg": "salvo no arquivo"}

    if acao == "marca":
        if not ch.inserir_marca(root, rel, caminho, pedido.get("marca", "⚠️"), texto,
                                pedido.get("prazo")):
            return {"ok": False, "erro": "não consegui escrever a marca"}
        return {"ok": True, "msg": "escrito no texto"}

    try:
        s, alvos, titulos = _alvos(root, rel, caminho)
    except KeyError:
        return {"ok": False, "erro": "esse trecho não está mais no arquivo"}

    if acao == "reverter":
        if not alvos:
            return {"ok": False, "erro": "nada mudou aqui desde a chancela"}
        cli.reverter(root, rel, alvos, s)
        return {"ok": True, "msg": "de volta ao texto chancelado: " + ", ".join(titulos)}

    if acao in ("aprovar", "validar"):
        if acao == "validar":
            if not ch.inserir_marca(root, rel, caminho, "❓", texto, pedido.get("prazo")):
                return {"ok": False, "erro": "não consegui escrever o prazo no texto"}
            s, alvos, titulos = _alvos(root, rel, caminho)   # o arquivo acabou de mudar
        if not alvos:
            return {"ok": False, "erro": "nada pendente neste trecho"}
        barrados = [h for h in alvos if h.bloqueio]
        if barrados and not pedido.get("force"):
            return {"ok": False, "erro": "🚫 " + barrados[0].bloqueio.lstrip("> ")}
        commit = cli.chancelar(root, rel, alvos, s, pedido.get("motivo"), by)
        extra = [l for h in alvos for l in h.sumidas]
        msg = f"na chancela ({commit[:8]}): " + ", ".join(titulos)
        if extra:
            msg += f" · {len(extra)} ressalva(s) saíram junto"
        return {"ok": True, "msg": msg}

    return {"ok": False, "erro": f"ação desconhecida: {acao}"}


# ---- the server ----------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    root: Path
    by: str

    def _envia(self, corpo: bytes, tipo: str, codigo: int = 200) -> None:
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def _json(self, dados: dict, codigo: int = 200) -> None:
        self._envia(json.dumps(dados, ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8", codigo)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/api/state"):
            self._json(estado(self.root, self.by))
        elif self.path in ("/", "/index.html"):
            self._envia(PAGE.encode("utf-8"), "text/html; charset=utf-8")
        else:
            self._envia(b"nao encontrado", "text/plain; charset=utf-8", 404)

    def do_POST(self) -> None:  # noqa: N802
        if not self.path.startswith("/api/act"):
            self._envia(b"nao encontrado", "text/plain; charset=utf-8", 404)
            return
        tamanho = int(self.headers.get("Content-Length", 0))
        pedido = json.loads(self.rfile.read(tamanho) or b"{}")
        try:
            resposta = agir(self.root, pedido, self.by)
        except Exception as e:                      # o servidor é local; o erro vai à tela
            resposta = {"ok": False, "erro": f"{type(e).__name__}: {e}"}
        resposta["estado"] = estado(self.root, self.by)
        self._json(resposta)

    def log_message(self, *args) -> None:           # sem ruído no terminal
        return


def run(root: Path, port: int = 8431, by: str = "", abrir: bool = False) -> int:
    Handler.root = root
    Handler.by = by
    try:
        servidor = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as e:
        if e.errno != 98:
            raise
        raise SystemExit(
            f"a porta {port} já está ocupada — provavelmente por um painel que ficou aberto.\n"
            f"abra http://127.0.0.1:{port} para ver de qual repositório ele é,\n"
            f"ou suba este em outra: km serve --port {port + 1}")
    url = f"http://127.0.0.1:{port}"
    print(f"km · {root.name}  ·  {url}  ·  Ctrl-C encerra")
    if abrir:
        webbrowser.open(url)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nencerrado")
    finally:
        servidor.server_close()
    return 0


PAGE = """<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>km · revisão</title><style>
/* Escuro por decisao, nao por preferencia do sistema: e onde o autor trabalha. */
:root{--bg:#0F1419;--card:#161D24;--ink:#DCE3EA;--mut:#8695A2;--rule:#232D36;--acc:#6EA8D8;
--ok:#7BC49A;--ok-bg:#16301F;--ace:#E0B463;--ace-bg:#2E2513;--neg:#E09A9A;--neg-bg:#331F1F;
--val:#6EA8D8;--val-bg:#152433;--pend:#8695A2;--pend-bg:#1C242B}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:14.5px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
.topo{display:flex;gap:14px;align-items:baseline;flex-wrap:wrap;padding:12px 20px;
border-bottom:1px solid var(--rule);position:sticky;top:0;background:var(--bg);z-index:3}
.topo b{font-size:16px}.topo .n{color:var(--mut);font-size:12.5px;font-family:ui-monospace,Menlo,monospace}
.filtros{display:flex;gap:6px;margin-left:auto;flex-wrap:wrap}
.filtros button{font:inherit;font-size:12.5px;padding:3px 11px;border-radius:999px;cursor:pointer;
border:1px solid var(--rule);background:transparent;color:var(--mut)}
.filtros button[aria-pressed=true]{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.grade{display:grid;grid-template-columns:minmax(200px,250px) minmax(0,1fr) minmax(250px,330px)}
.lado{border-right:1px solid var(--rule);padding:10px 8px;position:sticky;top:53px;
max-height:calc(100vh - 53px);overflow:auto}
.lado button{display:block;width:100%;text-align:left;background:none;border:0;color:inherit;
font:inherit;padding:7px 9px;border-radius:6px;cursor:pointer}
.lado button:hover{background:var(--card)}
.lado button[aria-current=true]{background:var(--card);box-shadow:inset 2px 0 0 var(--acc)}
.lado .f{font-family:ui-monospace,Menlo,monospace;font-size:12px;word-break:break-all}
.barra{display:flex;height:5px;border-radius:3px;overflow:hidden;margin-top:5px;background:var(--rule)}
.barra i{display:block;height:100%}
.meio{padding:14px 18px 80px;min-width:0}
.bloco{background:var(--card);border:1px solid var(--rule);border-radius:9px;margin:0 0 12px;
overflow:hidden;scroll-margin-top:64px}
.bloco.foco{border-color:var(--acc);box-shadow:0 0 0 1px var(--acc)}
.cab{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;padding:11px 14px;cursor:pointer}
.cab h3{margin:0;font-size:15px;font-weight:600}
.cab .meta{color:var(--mut);font-size:11.5px;font-family:ui-monospace,Menlo,monospace;margin-left:auto}
.chip{font:11px/1.7 ui-monospace,Menlo,monospace;padding:0 9px;border-radius:999px;white-space:nowrap}
.e-aprovado{color:var(--ok);background:var(--ok-bg)}.e-aceite{color:var(--ace);background:var(--ace-bg)}
.e-reprovado{color:var(--neg);background:var(--neg-bg)}.e-avalidar{color:var(--val);background:var(--val-bg)}
.e-pendente{color:var(--pend);background:var(--pend-bg)}.e-mexido{color:var(--ace);background:var(--ace-bg)}
.sim{color:var(--mut);border:1px dashed var(--rule)}
.marcacao{padding:12px 15px;border-top:1px solid var(--rule);font:13px/1.7 ui-monospace,Menlo,monospace;
white-space:pre-wrap;word-break:break-word;overflow-wrap:anywhere}
.aviso{font-family:system-ui,sans-serif;font-size:11.5px;color:var(--mut);padding:7px 15px 0}
.par{display:grid;grid-template-columns:1fr 1fr;gap:0;border-top:1px solid var(--rule)}
.par>div{padding:11px 14px;font:12.5px/1.5 ui-monospace,Menlo,monospace;white-space:pre-wrap;
word-break:break-word;overflow-wrap:anywhere}
.par>div:first-child{border-right:1px solid var(--rule);background:color-mix(in srgb,var(--bg) 60%,transparent)}
.rot{font-family:system-ui,sans-serif;font-size:10.5px;text-transform:uppercase;letter-spacing:.07em;
color:var(--mut);margin-bottom:6px}
/* fundo preenchido funciona em codigo, onde a linha e curta; em prosa vira mancha */
body.st-sublinhado del{color:var(--neg);text-decoration:line-through;text-decoration-thickness:1px;
  opacity:.75;background:none}
body.st-sublinhado ins{color:var(--ink);text-decoration:none;background:none;
  border-bottom:2px solid var(--ok);padding-bottom:1px}
body.st-margem del{display:none}
body.st-margem ins{color:var(--ink);background:none;text-decoration:none;font-weight:600}
body.st-margem .par>div:last-child{box-shadow:inset 3px 0 0 var(--ok)}
body.st-margem .par>div:first-child{box-shadow:inset 3px 0 0 var(--neg)}
body.st-fundo del{background:var(--neg-bg);color:var(--neg);text-decoration:line-through}
body.st-fundo ins{background:var(--ok-bg);color:var(--ok);text-decoration:none}
.estilos{display:flex;gap:4px;align-items:center;font-size:12px;color:var(--mut)}
.estilos button{font:inherit;font-size:12px;padding:2px 9px;border-radius:5px;cursor:pointer;
  border:1px solid var(--rule);background:transparent;color:var(--mut)}
.estilos button[aria-pressed=true]{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.corpo{padding:11px 14px;font:12.5px/1.5 ui-monospace,Menlo,monospace;white-space:pre-wrap;
border-top:1px solid var(--rule);color:var(--mut)}
.motivo{padding:9px 14px;border-top:1px solid var(--rule);border-left:3px solid var(--neg);
background:var(--neg-bg);font-size:13.5px}
.pergunta{padding:9px 14px;border-top:1px solid var(--rule);border-left:3px solid var(--val);
background:var(--val-bg);font-size:13.5px}
.acoes{display:flex;gap:7px;padding:10px 14px;border-top:1px solid var(--rule);flex-wrap:wrap}
.acoes button{font:inherit;font-size:13px;padding:5px 12px;border-radius:6px;cursor:pointer;
border:1px solid var(--rule);background:var(--bg);color:var(--ink)}
.acoes button.pri{background:var(--ok-bg);border-color:var(--ok-bg);color:var(--ok)}
.dir{border-left:1px solid var(--rule);padding:14px;position:sticky;top:53px;
max-height:calc(100vh - 53px);overflow:auto}
.dir h4{margin:0 0 8px;font-size:12px;text-transform:uppercase;letter-spacing:.07em;color:var(--mut)}
.dl{display:grid;grid-template-columns:auto 1fr;gap:4px 10px;font-size:12.5px;margin-bottom:16px}
.dl dt{color:var(--mut)}.dl dd{margin:0}
.nota{border-left:3px solid var(--acc);padding:7px 10px;margin-bottom:8px;font-size:13px}
.q{color:var(--mut);font-size:11px;font-family:ui-monospace,Menlo,monospace}
textarea{width:100%;min-height:62px;font:inherit;font-size:13px;padding:7px;border-radius:6px;
border:1px solid var(--rule);background:var(--bg);color:var(--ink)}
.vazio{color:var(--mut);font-size:13px;padding:20px 0}
@media(max-width:1100px){.grade{grid-template-columns:minmax(180px,220px) minmax(0,1fr)}.dir{display:none}}
@media(max-width:760px){.grade{grid-template-columns:1fr}.lado{position:static;max-height:170px}
.par{grid-template-columns:1fr}.par>div:first-child{border-right:0;border-bottom:1px solid var(--rule)}}
.recado{padding:8px 20px;font-size:13px;background:var(--ok-bg);color:var(--ok);
border-bottom:1px solid var(--rule)}
.recado.ruim{background:var(--neg-bg);color:var(--neg)}
.form{display:flex;gap:7px;padding:10px 14px;border-top:1px solid var(--rule);flex-wrap:wrap;
align-items:center}
.form input{flex:1 1 240px;font:inherit;font-size:13px;padding:5px 9px;border-radius:6px;
border:1px solid var(--rule);background:var(--bg);color:var(--ink)}
.form button{font:inherit;font-size:13px;padding:5px 12px;border-radius:6px;cursor:pointer;
border:1px solid var(--rule);background:var(--bg);color:var(--ink)}
.form button.pri{background:var(--ok-bg);border-color:var(--ok-bg);color:var(--ok)}
.acoes button[disabled]{opacity:.4;cursor:not-allowed}
</style></head><body>
<div class="topo"><b id="repo">km</b><span class="n" id="resumo"></span>
<div class="estilos" id="estilos"></div>
<div class="filtros" id="filtros"></div></div>
<div class="recado" id="recado" hidden></div>
<div class="grade"><nav class="lado" id="lado"></nav>
<section class="meio" id="meio"></section><aside class="dir" id="dir"></aside></div>
<script>
const $ = (id) => document.getElementById(id);
const esc = s => (s==null?'':String(s)).replace(/[&<>]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[m]));
// A ressalva e markdown no arquivo; na tela ela e so texto com enfase.
const neg = s => esc(s).replace(/\\*\\*(.+?)\\*\\*/g, '<b>$1</b>');
const CH = {'com chancela':'e-aprovado','mexido':'e-mexido','sem chancela':'e-pendente'};
const MARCA = {'⚠️':'e-aceite','❓':'e-avalidar','🚫':'e-reprovado'};
const FILTROS = ['tudo','pede você','mexidos','sem chancela','com ressalva','de pé'];
const ESTILOS = [['st-sublinhado','sublinhado'],['st-margem','margem'],['st-fundo','fundo']];
const VISTAS = [['auto','automática'],['marcacao','marcação'],['lado','lado a lado']];
const emDias = n => new Date(Date.now()+n*864e5).toISOString().slice(0,10);
const mexido = e => e === 'mexido';
const classe = e => CH[e] || 'e-pendente';
// Uma ressalva vencida, ou uma que sumiu, pede voce tanto quanto um trecho mexido.
const pedeVoce = b => mexido(b.estado) || b.estado === 'sem chancela' || !!b.bloqueado
  || (b.sumidas||[]).length > 0 || (b.ressalvas||[]).some(r => r.vencida);
// Acima de 40% das palavras mexidas, marcacao vira sopa: o trecho cai para duas colunas.
const usaMarcacao = b => vista === 'marcacao' || (vista === 'auto' && b.proporcao <= 0.4);

let D = null, doc = 0, filtro = 'pede você', foco = null;
let estilo = 'st-fundo', vista = 'auto';
let form = null, editor = null, recado = '', meuTexto = '';

async function carregar(){
  const r = await fetch('/api/state');
  D = await r.json();
  desenhar();
}

async function agir(corpo){
  const r = await fetch('/api/act', {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify(corpo)});
  const j = await r.json();
  if (j.estado) D = j.estado;
  recado = j.ok ? '✓ ' + (j.msg || 'feito') : '✕ ' + (j.erro || 'não deu');
  if (j.conflito) { editor = {i: editor ? editor.i : 0, conflito: j.conflito.atual}; }
  else { form = null; if (j.ok) editor = null; }
  desenhar();
}

function bloco(i){ return D.docs[doc].blocos[i]; }
function base(i){ const b = bloco(i); return {acao:'', file: D.docs[doc].file, path: b.path}; }

function passa(b){
  if (filtro === 'tudo') return true;
  if (filtro === 'pede você') return pedeVoce(b);
  if (filtro === 'mexidos') return mexido(b.estado);
  if (filtro === 'sem chancela') return b.estado === 'sem chancela';
  if (filtro === 'com ressalva') return (b.ressalvas||[]).length > 0 || (b.sumidas||[]).length > 0;
  return b.estado === 'com chancela' && !b.bloqueado;
}
function contar(d){
  const c = {pe:0, mex:0, pend:0, neg:0, val:0};
  for (const b of d.blocos){
    if (b.bloqueado) c.neg++;
    else if (mexido(b.estado)) c.mex++;
    else if (b.estado === 'sem chancela') c.pend++;
    else if ((b.ressalvas||[]).length) c.val++;
    else c.pe++;
  }
  return c;
}

function lado(){
  let divisor = false;
  $('lado').innerHTML = D.docs.map((d,i)=>{
    let antes = '';
    if (!d.rastreado && !divisor) {
      divisor = true;
      antes = '<div class="rot" style="padding:12px 9px 5px">sem chancela ainda</div>';
    }
    const c = contar(d), t = d.blocos.length || 1;
    const seg = [[c.pe,'var(--ok)'],[c.mex,'var(--ace)'],[c.neg,'var(--neg)'],
                 [c.val,'var(--val)'],[c.pend,'var(--rule)']]
      .map(([n,cor])=>n?`<i style="width:${100*n/t}%;background:${cor}"></i>`:'').join('');
    return antes + `<button aria-current="${i===doc}" onclick="abrir(${i})">
      <div class="f">${esc(d.file)}</div>
      <div class="n q">${c.pe}/${d.blocos.length} de pé${c.mex?' · '+c.mex+' mexidos':''}</div>
      <div class="barra">${seg}</div></button>`;}).join('');
}

function formulario(i){
  if (!form || form.i !== i) return '';
  const b = bloco(i);
  const campos = {
    validar: ['O que falta confirmar?', 'prazo'],
    reverter: ['Por que a mudança não serve?', ''],
    '⚠️': ['A dúvida, como ela vai para o texto', ''],
    '🚫': ['O que está errado — isto bloqueia a chancela deste trecho', ''],
    aprovar: ['Por que você endossa (vai na mensagem do commit)', ''],
  }[form.tipo];
  return `<div class="form">
    <input id="f-texto" placeholder="${esc(campos[0])}" autofocus
      onkeydown="if(event.key==='Enter')enviarForm(${i});if(event.key==='Escape')fechar()">
    ${campos[1]==='prazo'?`<input id="f-prazo" value="${emDias(14)}" size="11"
      onkeydown="if(event.key==='Enter')enviarForm(${i})">`:''}
    <button class="pri" onclick="enviarForm(${i})">${form.tipo==='reverter'?'Reverter':'Escrever'}</button>
    <button onclick="fechar()">cancelar</button>
    <div class="q" style="flex-basis:100%">${form.tipo==='validar'
      ? 'entra na chancela com um ❓ e o prazo, escritos no próprio texto'
      : (form.tipo==='reverter' ? 'o texto volta ao que você chancelou; o motivo vai no commit'
      : (form.tipo==='aprovar' ? 'o trecho entra na chancela'
      : 'vira uma citação no arquivo, visível para quem abrir'))}</div></div>`;
}

function caixaEditor(i){
  if (!editor || editor.i !== i) return '';
  const b = bloco(i);
  if (editor.conflito !== undefined) {
    return `<div class="form" style="display:block">
      <div class="motivo" style="border:0;padding:8px 0">O arquivo mudou enquanto você
      editava — outro agente ou o editor chegaram primeiro. Nada foi sobrescrito.</div>
      <div class="rot">no arquivo agora</div>
      <textarea readonly>${esc(editor.conflito)}</textarea>
      <div class="rot" style="margin-top:8px">o seu texto</div>
      <textarea id="e-texto">${esc(meuTexto)}</textarea>
      <div class="acoes" style="border:0;padding:8px 0">
        <button class="pri" onclick="salvar(${i}, true)">salvar por cima</button>
        <button onclick="fechar()">descartar o meu</button></div></div>`;
  }
  return `<div class="form" style="display:block">
    <textarea id="e-texto" style="min-height:160px"
      onkeydown="if(event.key==='Escape')fechar()">${esc(b.texto)}</textarea>
    <div class="acoes" style="border:0;padding:8px 0">
      <button class="pri" onclick="salvar(${i})">Salvar no arquivo</button>
      <button onclick="fechar()">cancelar</button>
      <span class="q">salva só este trecho; se o arquivo tiver mudado, a tela avisa</span>
    </div></div>`;
}

function cartao(b, i){
  const dif = b.esq && b.dir;
  const acoes = editor && editor.i === i ? '' : `<div class="acoes">
    <button class="pri" ${b.bloqueado?'disabled title="resolva o 🚫 primeiro"':''}
      onclick="aprovar(${i})">Aprovar</button>
    <button onclick="abrirForm(${i},'validar')">A validar…</button>
    ${dif?`<button onclick="abrirForm(${i},'reverter')">Reverter…</button>`:''}
    <span style="width:10px"></span>
    <button onclick="abrirForm(${i},'⚠️')" title="sem certeza">⚠️</button>
    <button onclick="abrirForm(${i},'🚫')" title="discordo — bloqueia a chancela">🚫</button>
    <button onclick="editarBloco(${i})">Editar</button></div>`;
  return `<div class="bloco ${foco===i?'foco':''}" id="b${i}">
    <div class="cab" onclick="focar(${i})">
      <h3>${esc(b.heading)}</h3>
      <span class="chip ${classe(b.estado)}">${esc(b.estado)}</span>
      ${b.bloqueado?'<span class="chip e-reprovado">🚫 bloqueado</span>':''}
      <span class="meta">linha ${b.line} · ${b.lines}l</span></div>
    ${(b.sumidas||[]).map(s=>`<div class="motivo"><b>ressalva removida:</b> ${neg(s.replace(/^\\s*>\\s*/,''))}
      <br><span class="q">estava na chancela. Aprovar aqui aprova a remoção.</span></div>`).join('')}
    ${(b.ressalvas||[]).map(r=>`<div class="pergunta"><span class="chip ${MARCA[r.mark]||'e-pendente'}">${esc(r.mark)}</span>
      ${neg(r.text)}${r.vencida?' <b>— prazo vencido</b>':''}</div>`).join('')}
    ${editor && editor.i === i ? '' : (dif ? (usaMarcacao(b)
      ? `<div class="aviso">marcação · ${b.mexidas} palavras mexidas</div>
         <div class="marcacao">${b.inline}</div>`
      : `<div class="aviso">lado a lado · ${Math.round(b.proporcao*100)}% das palavras mexidas — demais para marcação</div>
         <div class="par"><div><div class="rot">sua chancela${D.docs[doc].em?' · '+esc(D.docs[doc].em):''}</div>${b.esq}</div>
         <div><div class="rot">agora</div>${b.dir}</div></div>`)
      : `<div class="corpo">${esc((b.texto||'').slice(0,600))}${(b.texto||'').length>600?'…':''}</div>`)}
    ${caixaEditor(i)}${formulario(i)}${acoes}</div>`;
}

function meio(){
  const d = D.docs[doc];
  const vis = d.blocos.map((b,i)=>[b,i]).filter(([b])=>passa(b));
  $('meio').innerHTML = vis.length
    ? vis.map(([b,i])=>cartao(b,i)).join('')
    : `<div class="vazio">Nada neste filtro. ${d.blocos.length} trechos neste arquivo.</div>`;
  if ((foco===null || !vis.some(([,i])=>i===foco)) && vis.length) foco = vis[0][1];
  const campo = $('f-texto') || $('e-texto');
  if (campo) campo.focus();
}

function dir(){
  const d = D.docs[doc], b = d.blocos[foco];
  const el = $('dir');
  if (!b) { el.innerHTML = '<div class="vazio">Nenhum trecho em foco.</div>'; return; }
  el.innerHTML = `<h4>${esc(b.heading)}</h4>
    <dl class="dl">
      <dt>estado</dt><dd><span class="chip ${classe(b.estado)}">${esc(b.estado)}</span></dd>
      <dt>chancela</dt><dd>${d.em?'última em '+esc(d.em):'nunca'}</dd>
      <dt>arquivo</dt><dd>${esc(d.file)}</dd>
      <dt>tamanho</dt><dd>${b.lines} linhas · linha ${b.line}</dd>
    </dl>
    <h4>ressalvas, no próprio texto</h4>
    ${(b.ressalvas||[]).length?b.ressalvas.map(r=>`<div class="nota">${esc(r.mark)} ${neg(r.text)}
      <div class="q">${r.vencida?'prazo vencido':'vive no arquivo, não aqui'}</div></div>`).join('')
      :'<div class="vazio" style="padding:0 0 10px">Nenhuma ressalva neste trecho.</div>'}
    <h4>teclas</h4>
    <div class="q">j k andar · a aprovar · v a validar · r reverter · e editar · Esc fecha</div>`;
}

function desenhar(){
  if (!D) return;
  $('repo').textContent = D.repo;
  const tot = D.docs.reduce((a,d)=>a+d.blocos.length,0);
  const c = D.docs.reduce((a,d)=>{const x=contar(d);return {pe:a.pe+x.pe,mex:a.mex+x.mex,pend:a.pend+x.pend};},{pe:0,mex:0,pend:0});
  $('resumo').textContent = `${D.docs.length} arquivos · ${tot} trechos · ${c.pe} de pé · ${c.mex} mexidos · ${c.pend} sem chancela`;
  const r = $('recado');
  r.hidden = !recado; r.textContent = recado;
  r.className = 'recado' + (recado.startsWith('✕') ? ' ruim' : '');
  lado(); meio(); dir();
}

function focar(i){ foco = i; document.querySelectorAll('.bloco').forEach(e=>e.classList.remove('foco'));
  $('b'+i)?.classList.add('foco'); dir(); }
function abrir(i){ doc = i; foco = null; form = null; editor = null; desenhar(); scrollTo(0,0); }
function fechar(){ form = null; editor = null; desenhar(); }
function abrirForm(i, tipo){ editor = null; form = {i, tipo}; focar(i); desenhar(); }
function editarBloco(i){ form = null; editor = {i}; meuTexto = bloco(i).texto; focar(i); desenhar(); }
function aprovar(i){ agir({...base(i), acao:'aprovar'}); }
function enviarForm(i){
  const texto = ($('f-texto')||{}).value || '';
  const prazo = ($('f-prazo')||{}).value || '';
  if (form.tipo === 'validar') return agir({...base(i), acao:'validar', texto, prazo});
  if (form.tipo === 'reverter') return agir({...base(i), acao:'reverter', motivo: texto});
  if (form.tipo === 'aprovar') return agir({...base(i), acao:'aprovar', motivo: texto});
  return agir({...base(i), acao:'marca', marca: form.tipo, texto});
}
function salvar(i, porCima){
  const t = ($('e-texto')||{}).value || '';
  meuTexto = t;
  agir({...base(i), acao:'salvar', texto: t, sha: porCima ? '' : bloco(i).sha});
}

$('estilos').innerHTML = 'vista: ' + VISTAS.map(([c,n])=>
  `<button aria-pressed="${c===vista}" onclick="mudarVista('${c}')">${n}</button>`).join('')
  + '<span style="width:12px"></span>marcas: ' + ESTILOS.map(([c,n])=>
  `<button aria-pressed="${c===estilo}" onclick="mudarEstilo('${c}')">${n}</button>`).join('');
function mudarVista(v){ vista = v;
  document.querySelectorAll('.estilos button').forEach(b=>{
    const alvo = b.getAttribute('onclick');
    if (alvo.includes('mudarVista')) b.setAttribute('aria-pressed', alvo.includes("'"+v+"'"));
  });
  meio(); }
function mudarEstilo(c){ estilo = c; document.body.className = c;
  document.querySelectorAll('.estilos button').forEach(b=>
    b.setAttribute('aria-pressed', b.getAttribute('onclick').includes(c))); }
document.body.className = estilo;
$('filtros').innerHTML = FILTROS.map(f=>
  `<button aria-pressed="${f===filtro}" onclick="filtrar('${f}')">${f}</button>`).join('');
function filtrar(f){ filtro = f; foco = null;
  document.querySelectorAll('.filtros button').forEach(b=>b.setAttribute('aria-pressed', b.textContent===f));
  meio(); dir(); }

document.addEventListener('keydown', (e)=>{
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
    if (e.key === 'Escape') fechar();
    return;
  }
  const d = D && D.docs[doc]; if (!d) return;
  const vis = d.blocos.map((b,i)=>[b,i]).filter(([b])=>passa(b)).map(([,i])=>i);
  const pos = vis.indexOf(foco);
  if (e.key === 'j' && pos < vis.length-1) { focar(vis[pos+1]); $('b'+foco)?.scrollIntoView({block:'nearest'}); }
  else if (e.key === 'k' && pos > 0) { focar(vis[pos-1]); $('b'+foco)?.scrollIntoView({block:'nearest'}); }
  else if (e.key === 'a' && foco!==null) aprovar(foco);
  else if (e.key === 'v' && foco!==null) abrirForm(foco,'validar');
  else if (e.key === 'r' && foco!==null) abrirForm(foco,'reverter');
  else if (e.key === 'e' && foco!==null) editarBloco(foco);
  else if (e.key === 'Escape') fechar();
});

// O arquivo muda por fora: um agente escreve, o editor salva. A tela se atualiza sozinha
// quando voce nao esta no meio de escrever nada.
setInterval(()=>{ if (!form && !editor) carregar(); }, 8000);
carregar();
</script></body></html>"""
