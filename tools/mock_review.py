#!/usr/bin/env python3
"""Mock of a review surface that is not bound by the editor's shape.

Three columns, a word-level diff instead of a line-level one, every tracked file on one
screen, and the conversation beside the block rather than in a popup. Generated from a real
repository; nothing here is a product.
"""

from __future__ import annotations

import difflib
import html
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from km import chancela as ch  # noqa: E402
from km import core  # noqa: E402

PALAVRA = re.compile(r"\s+|\w+|[^\w\s]")


FRASE = re.compile(r"[^.!?\n]+[.!?\n]*")


def diff_inline(antes: str, agora: str) -> tuple[str, float, int]:
    """One stream, in reading order — the Word-like view.

    Prose is read in sequence, and side by side makes the eye jump. But interleaved marks
    turn a heavily rewritten paragraph into soup, so the caller gets the share of words that
    moved and can fall back to two columns when the change is wholesale.
    """
    a, b = PALAVRA.findall(antes), PALAVRA.findall(agora)
    saida, mexidas, total = [], 0, max(len(b), 1)
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


def montar(root: Path, simular: bool = True) -> dict:
    cfg = core.load_config(root)
    arquivos = sorted({p.relative_to(root).as_posix() for p in core.documents(root, cfg)}
                      | set(ch.arquivos(root)))
    hoje = date.today().isoformat()
    docs = []
    for rel in arquivos:
        s = ch.situacao(root, rel, hoje)
        if not s.depois.strip():
            continue
        chancelados = {t.caminho: t for t in (ch.trechos(s.antes) if s.tem_chancela else [])}
        blocos = []
        for e in ch.estados(s):
            agora = next((x for x in ch.trechos(s.depois) if x.caminho == e["path"]), None)
            antigo = chancelados.get(e["path"])
            texto = _corpo(agora)
            base = _corpo(antigo)
            esq = dir_ = inline = None
            proporcao, mexidas = 0.0, 0
            if e["state"] == "mexido" and base:
                esq, dir_ = diff_palavras(base, texto)
                inline, proporcao, mexidas = diff_inline(base, texto)
            blocos.append({
                "heading": e["heading"], "line": e["line"], "lines": e["lines"],
                "estado": e["state"], "bloqueado": e["blocked"],
                "ressalvas": [{"mark": c["mark"],
                               "text": c["text"].lstrip("> ").strip(),
                               "vencida": c["mark"] == "❓" and _vencida(c["text"], hoje)}
                              for c in e["caveats"]],
                "sumidas": e["dropped"],
                "texto": texto.strip(), "chancelado": base.strip(),
                "esq": esq, "dir": dir_, "inline": inline,
                "proporcao": proporcao, "mexidas": mexidas, "simulado": False,
            })
        docs.append({"file": rel, "blocos": blocos, "rastreado": s.tem_chancela,
                     "em": _ultima_chancela(root, rel),
                     "linhas": len(s.depois.splitlines())})

    docs.sort(key=lambda d: (not d["rastreado"], d["file"]))
    if simular and docs:
        _simular(docs)
    return {"repo": root.name, "docs": docs, "hoje": hoje}


def _corpo(trecho) -> str:
    """The passage without its own heading — the heading is already the card's title."""
    if trecho is None:
        return ""
    if trecho.titulo_bruto:
        return trecho.texto.split("\n", 1)[1] if "\n" in trecho.texto else ""
    return trecho.texto


def _vencida(linha: str, hoje: str) -> bool:
    m = re.search(r"(\d{4}-\d{2}-\d{2})", linha)
    return bool(m and m.group(1) < hoje)


def _ultima_chancela(root: Path, rel: str) -> str:
    if not ch.existe(root):
        return ""
    saida = ch.historico(root, rel, None, limite=1).strip().splitlines()
    return saida[0].split(" ")[1] if saida and len(saida[0].split(" ")) > 1 else ""


def _simular(docs: list[dict]) -> None:
    """Three cards the real data does not have today, so the shapes can be judged.

    Marked `simulado` on screen: a mock that cannot be told from the truth is a lie.
    """
    alvo = next((d for d in docs if d["blocos"]), None)
    if not alvo or len(alvo["blocos"]) < 3:
        return
    exemplos = [
        ("mexido", {}, lambda txt: txt.replace("chamado", "ticket", 3)),
        ("mexido", {"sumidas": ["> ⚠️ **sem certeza** — a ordem veio de um print, "
                                "não do export."]},
         lambda txt: "> ⚠️ **sem certeza** — a ordem veio de um print, não do export.\n\n" + txt),
        ("com chancela", {"ressalvas": [{"mark": "❓", "vencida": True,
                                         "text": "**a confirmar até 2026-09-15** — "
                                                 "o limite do contrato, com quem assina"}]},
         None),
    ]
    for i, (estado, extra, mexer) in enumerate(exemplos):
        b = dict(alvo["blocos"][min(i + 1, len(alvo["blocos"]) - 1)])
        b.update({"estado": estado, "simulado": True, "ressalvas": [], "sumidas": []})
        b.update(extra)
        if mexer:
            velho = mexer(b["texto"])
            b["chancelado"] = velho
            b["esq"], b["dir"] = diff_palavras(velho, b["texto"])
            b["inline"], b["proporcao"], b["mexidas"] = diff_inline(velho, b["texto"])
        alvo["blocos"].insert(i + 1, b)


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
</style></head><body>
<div class="topo"><b id="repo"></b><span class="n" id="resumo"></span>
<div class="estilos" id="estilos"></div>
<div class="filtros" id="filtros"></div></div>
<div class="grade"><nav class="lado" id="lado"></nav>
<section class="meio" id="meio"></section><aside class="dir" id="dir"></aside></div>
<script>
const D = __DATA__;
const CH = {'com chancela':'e-aprovado','mexido':'e-mexido','sem chancela':'e-pendente'};
const MARCA = {'⚠️':'e-aceite','❓':'e-avalidar','🚫':'e-reprovado'};
const FILTROS = ['tudo','pede você','mexidos','sem chancela','com ressalva','de pé'];
const ESTILOS = [['st-sublinhado','sublinhado'],['st-margem','margem'],['st-fundo','fundo']];
const VISTAS = [['auto','automática'],['marcacao','marcação'],['lado','lado a lado']];
let estilo = 'st-fundo', vista = 'auto';
// Acima de 40% das palavras mexidas, marcacao vira sopa: o bloco cai para duas colunas.
const usaMarcacao = b => vista === 'marcacao' || (vista === 'auto' && b.proporcao <= 0.4);
let doc = 0, filtro = 'pede você', foco = null;
const esc = s => (s==null?'':String(s)).replace(/[&<>]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[m]));
const mexido = e => e === 'mexido';
const classe = e => CH[e] || 'e-pendente';
// Uma ressalva vencida ou uma ressalva que sumiu pedem voce tanto quanto um trecho mexido.
const pedeVoce = b => mexido(b.estado) || b.estado === 'sem chancela' || !!b.bloqueado
  || (b.sumidas||[]).length > 0 || (b.ressalvas||[]).some(r => r.vencida);

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
  document.getElementById('lado').innerHTML = D.docs.map((d,i)=>{
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
      <div class="n" style="color:var(--mut);font-size:11px">${c.pe}/${d.blocos.length} de pé${c.mex?' · '+c.mex+' mexidos':''}</div>
      <div class="barra">${seg}</div></button>`;}).join('');
}
function cartao(b, i){
  const dif = b.esq && b.dir;
  return `<div class="bloco ${foco===i?'foco':''}" id="b${i}">
    <div class="cab" onclick="focar(${i})">
      <h3>${esc(b.heading)}</h3>
      <span class="chip ${classe(b.estado)}">${esc(b.estado)}</span>
      ${b.simulado?'<span class="chip sim">simulado</span>':''}
      ${b.bloqueado?'<span class="chip e-reprovado">🚫 bloqueado</span>':''}
      <span class="meta">linha ${b.line} · ${b.lines}l</span></div>
    ${(b.sumidas||[]).map(s=>`<div class="motivo"><b>ressalva removida:</b> ${esc(s.replace(/^\\s*>\\s*/,''))}
      <br><span class="q">estava na chancela. Aprovar aqui aprova a remoção.</span></div>`).join('')}
    ${(b.ressalvas||[]).map(r=>`<div class="pergunta"><span class="chip ${MARCA[r.mark]||'e-pendente'}">${esc(r.mark)}</span>
      ${esc(r.text)}${r.vencida?' <b>— prazo vencido</b>':''}</div>`).join('')}
    ${dif ? (usaMarcacao(b)
      ? `<div class="aviso">marcação · ${b.mexidas} palavras mexidas de ${Math.round(b.mexidas/(b.proporcao||1))}${vista==='auto'?'':' · escolha sua'}</div>
         <div class="marcacao">${b.inline}</div>`
      : `<div class="aviso">lado a lado · ${Math.round(b.proporcao*100)}% das palavras mexidas — demais para marcação</div>
         <div class="par"><div><div class="rot">sua chancela${b.em?' · '+esc(b.em):''}</div>${b.esq}</div>
         <div><div class="rot">agora</div>${b.dir}</div></div>`)
      : `<div class="corpo">${esc(b.texto.slice(0,600))}${b.texto.length>600?'…':''}</div>`}
    <div class="acoes">
      <button class="pri" ${b.bloqueado?'disabled title="resolva o 🚫 primeiro"':''}>Aprovar</button>
      <button>A validar…</button>
      ${dif?'<button>Reverter…</button>':''}
      <span style="width:10px"></span><button title="mock">+ ressalva ⚠️</button></div></div>`;
}
function meio(){
  const d = D.docs[doc];
  const vis = d.blocos.map((b,i)=>[b,i]).filter(([b])=>passa(b));
  document.getElementById('meio').innerHTML = vis.length
    ? vis.map(([b,i])=>cartao(b,i)).join('')
    : `<div class="vazio">Nada neste filtro. ${d.blocos.length} blocos neste arquivo.</div>`;
  if (foco===null && vis.length) foco = vis[0][1];
  dir();
}
function dir(){
  const d = D.docs[doc], b = d.blocos[foco];
  const el = document.getElementById('dir');
  if (!b) { el.innerHTML = '<div class="vazio">Nenhum bloco em foco.</div>'; return; }
  el.innerHTML = `<h4>${esc(b.heading)}</h4>
    <dl class="dl">
      <dt>estado</dt><dd><span class="chip ${classe(b.estado)}">${esc(b.estado)}</span></dd>
      <dt>chancela</dt><dd>${d.em?'última em '+esc(d.em):'nunca'}</dd>
      <dt>arquivo</dt><dd>${esc(d.file)}</dd>
      <dt>tamanho</dt><dd>${b.lines} linhas · linha ${b.line}</dd>
    </dl>
    <h4>ressalvas, no próprio texto</h4>
    ${(b.ressalvas||[]).length?b.ressalvas.map(r=>`<div class="nota">${esc(r.mark)} ${esc(r.text)}
      <div class="q">${r.vencida?'prazo vencido':'vive no arquivo, não aqui'}</div></div>`).join('')
      :'<div class="vazio" style="padding:0 0 10px">Nenhuma ressalva neste trecho.</div>'}
    <textarea placeholder="⚠️ sem certeza — … (mock: iria para o texto)"></textarea>`;
}
function focar(i){ foco = i; document.querySelectorAll('.bloco').forEach(e=>e.classList.remove('foco'));
  document.getElementById('b'+i)?.classList.add('foco'); dir(); }
function abrir(i){ doc = i; foco = null; lado(); meio(); scrollTo(0,0); }
document.getElementById('estilos').innerHTML = 'vista: ' + VISTAS.map(([c,n])=>
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
document.getElementById('filtros').innerHTML = FILTROS.map(f=>
  `<button aria-pressed="${f===filtro}" onclick="filtrar('${f}')">${f}</button>`).join('');
function filtrar(f){ filtro = f; foco = null;
  document.querySelectorAll('.filtros button').forEach(b=>b.setAttribute('aria-pressed', b.textContent===f));
  meio(); }
const tot = D.docs.reduce((a,d)=>a+d.blocos.length,0);
const pede = D.docs.reduce((a,d)=>a+d.blocos.filter(b=>passa.call({},b)||false).length,0);
document.getElementById('repo').textContent = D.repo;
document.getElementById('resumo').textContent =
  `${D.docs.length} arquivos · ${tot} blocos · ` +
  `${D.docs.reduce((a,d)=>a+contar(d).pe,0)} de pé · ` +
  `${D.docs.reduce((a,d)=>a+contar(d).mex,0)} mexidos · ` +
  `${D.docs.reduce((a,d)=>a+contar(d).pend,0)} sem chancela`;
lado(); meio();
</script></body></html>"""


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").expanduser().resolve()
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("review.html")
    dados = montar(root)
    # Any of `</script`, `<script` or `<!--` inside block text confuses the HTML tokenizer
    # and the page dies mid-JSON. Escaping every angle bracket kills all three at once, and
    # \u003c is just "<" once the string is parsed, so the data is untouched.
    corpo = (json.dumps(dados, ensure_ascii=False)
             .replace("<", "\\u003c").replace(">", "\\u003e"))
    out.write_text(PAGE.replace("__DATA__", corpo), encoding="utf-8")
    n = sum(len(d["blocos"]) for d in dados["docs"])
    print(f"{out} · {len(dados['docs'])} arquivos · {n} blocos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
