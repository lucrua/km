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
from km import blocks as blk  # noqa: E402
from km import core  # noqa: E402

PALAVRA = re.compile(r"\s+|\w+|[^\w\s]")


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
    ledger = blk.Ledger(root)
    arquivos = sorted({c.file for c in core.scan(root, cfg) if not c.is_question})
    docs = []
    for rel in arquivos:
        vivos = blk.of_file(root, rel)
        if not vivos:
            continue
        blocos = []
        for b in vivos:
            rec = ledger.records.get(b.key, {})
            estado = ledger.status_of(b)
            antes = rec.get("body")
            esq = dir_ = None
            if antes is not None and rec.get("hash") != b.hash:
                esq, dir_ = diff_palavras(antes, b.body)
            blocos.append({
                "heading": b.heading, "line": b.line, "lines": b.lines,
                "estado": estado, "base": rec.get("state"), "em": rec.get("at"),
                "por": (rec.get("by") or "").replace("human:", ""),
                "origem": rec.get("from"), "expira": rec.get("expires"),
                "validar": rec.get("validate"), "prazo": rec.get("due"),
                "notas": rec.get("notes", []),
                "texto": b.body.strip(), "chancelado": (antes or "").strip(),
                "esq": esq, "dir": dir_, "simulado": False,
            })
        docs.append({"file": rel, "blocos": blocos,
                     "rastreado": any(b["base"] for b in blocos),
                     "linhas": sum(x["lines"] for x in blocos)})

    docs.sort(key=lambda d: (not d["rastreado"], d["file"]))

    if simular:
        alvo = next((d for d in docs if d["file"] == "regras-de-sla.md"), docs[0])
        for i, (estado, extra) in enumerate((
            ("mexido depois de aprovado", {}),
            ("reprovado", {"notas": [{"at": date.today().isoformat(), "by": "lucas",
                                      "text": "o Delta não é lido de chamado aberto; isto "
                                              "contradiz a decisão 0001"}]}),
            ("a-validar", {"validar": "confirmar o limite com o gestor do contrato",
                           "prazo": "2026-10-15"}),
        )):
            b = dict(alvo["blocos"][i + 1])
            b.update({"estado": estado, "simulado": True, "em": date.today().isoformat(),
                      "por": "lucas", "notas": b.get("notas", [])})
            b.update(extra)
            if not b["esq"]:
                velho = b["texto"].replace("chamado", "ticket", 3)
                b["esq"], b["dir"] = diff_palavras(velho, b["texto"])
                b["chancelado"] = velho
            alvo["blocos"].insert(i + 1, b)
    return {"repo": root.name, "docs": docs, "hoje": date.today().isoformat()}


PAGE = """<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>km · revisão</title><style>
:root{--bg:#F5F6F3;--card:#FCFCFA;--ink:#1B2320;--mut:#5C6862;--rule:#DCE0DB;--acc:#2A4B6E;
--ok:#2B6647;--ok-bg:#E3F0E8;--ace:#8A5A0B;--ace-bg:#FAF0DA;--neg:#8B4E4E;--neg-bg:#F8E7E5;
--val:#2A4B6E;--val-bg:#E4EAF1;--pend:#5C6862;--pend-bg:#E9ECE8}
@media(prefers-color-scheme:dark){:root{--bg:#121614;--card:#191E1C;--ink:#E4E8E5;--mut:#98A39E;
--rule:#2B3230;--acc:#8FB3D9;--ok:#86C9A2;--ok-bg:#152A1F;--ace:#E3B665;--ace-bg:#2B2314;
--neg:#D9A0A0;--neg-bg:#2E1D1D;--val:#8FB3D9;--val-bg:#1B2734;--pend:#98A39E;--pend-bg:#212927}}
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
body.st-fundo del{background:color-mix(in srgb,var(--neg) 12%,transparent);color:inherit;
  text-decoration:line-through;text-decoration-color:var(--neg)}
body.st-fundo ins{background:color-mix(in srgb,var(--ok) 14%,transparent);color:inherit;
  text-decoration:none}
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
.nota .q{color:var(--mut);font-size:11px;font-family:ui-monospace,Menlo,monospace}
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
const CH = {'aprovado':'e-aprovado','aceite':'e-aceite','reprovado':'e-reprovado',
  'a-validar':'e-avalidar','não revisado':'e-pendente','suposição':'e-aceite'};
const FILTROS = ['tudo','pede você','mexidos','negados','a validar','pendentes','de pé'];
const ESTILOS = [['st-sublinhado','sublinhado'],['st-margem','margem'],['st-fundo','fundo']];
let estilo = 'st-sublinhado';
let doc = 0, filtro = 'pede você', foco = null;
const esc = s => (s==null?'':String(s)).replace(/[&<>]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[m]));
const mexido = e => e.startsWith('mexido');
const classe = e => mexido(e) ? 'e-mexido' : (CH[e] || 'e-pendente');

function passa(b){
  if (filtro === 'tudo') return true;
  if (filtro === 'pede você') return mexido(b.estado) || ['não revisado','reprovado','a-validar','suposição'].includes(b.estado);
  if (filtro === 'mexidos') return mexido(b.estado);
  if (filtro === 'negados') return b.estado === 'reprovado';
  if (filtro === 'a validar') return b.estado === 'a-validar';
  if (filtro === 'pendentes') return b.estado === 'não revisado';
  return b.estado === 'aprovado' || b.estado === 'aceite';
}
function contar(d){
  const c = {pe:0, mex:0, pend:0, neg:0, val:0};
  for (const b of d.blocos){
    if (mexido(b.estado)) c.mex++;
    else if (b.estado === 'reprovado') c.neg++;
    else if (b.estado === 'a-validar') c.val++;
    else if (b.estado === 'não revisado') c.pend++;
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
      ${b.expira?`<span class="chip e-aceite">expira ${esc(b.expira)}</span>`:''}
      <span class="meta">linha ${b.line} · ${b.lines}l</span></div>
    ${b.estado==='reprovado'&&b.notas.length?`<div class="motivo"><b>motivo:</b> ${esc(b.notas[b.notas.length-1].text)}</div>`:''}
    ${b.validar?`<div class="pergunta"><b>a validar:</b> ${esc(b.validar)}${b.prazo?' · até '+esc(b.prazo):''}</div>`:''}
    ${dif?`<div class="par"><div><div class="rot">sua chancela${b.em?' · '+esc(b.em):''}</div>${b.esq}</div>
      <div><div class="rot">agora</div>${b.dir}</div></div>`
      :`<div class="corpo">${esc(b.texto.slice(0,600))}${b.texto.length>600?'…':''}</div>`}
    <div class="acoes">
      <button class="pri">Aprovar</button><button>Adiar</button><button>Recusar</button>
      <span style="width:10px"></span>
      <button title="mock">+ comentário</button>
      ${dif?'<button>Devolver o meu texto</button>':''}</div></div>`;
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
      <dt>chancela</dt><dd>${b.base?esc(b.base)+(b.em?' em '+esc(b.em):''):'nunca'}</dd>
      <dt>por</dt><dd>${esc(b.por||'—')}</dd>
      <dt>origem</dt><dd>${b.origem?'commit '+esc(b.origem):'conteúdo do dia'}</dd>
      <dt>tamanho</dt><dd>${b.lines} linhas · linha ${b.line}</dd>
    </dl>
    <h4>conversa</h4>
    ${b.notas.length?b.notas.map(n=>`<div class="nota">${esc(n.text)}
      <div class="q">${esc(n.by||'você')} · ${esc(n.at)}</div></div>`).join('')
      :'<div class="vazio" style="padding:0 0 10px">Nada dito ainda.</div>'}
    <textarea placeholder="escrever… (mock)"></textarea>`;
}
function focar(i){ foco = i; document.querySelectorAll('.bloco').forEach(e=>e.classList.remove('foco'));
  document.getElementById('b'+i)?.classList.add('foco'); dir(); }
function abrir(i){ doc = i; foco = null; lado(); meio(); scrollTo(0,0); }
document.getElementById('estilos').innerHTML = 'diff: ' + ESTILOS.map(([c,n])=>
  `<button aria-pressed="${c===estilo}" onclick="mudarEstilo('${c}')">${n}</button>`).join('');
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
  `${D.docs.reduce((a,d)=>a+contar(d).pend,0)} nunca revisados`;
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
