"""A local review page: one claim at a time, keyboard first.

No build step, no dependencies, no network: plain HTML served from this file, bound to
localhost. It writes only inside `.km/`, exactly like the CLI.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import core

WANTED = {"proposed", "changed", "expired"}


def _context(root: Path, claim: core.Claim, span: int = 2) -> tuple[list[str], list[str]]:
    """The neighbouring lines. A claim read alone is often unreadable."""
    try:
        lines = (root / claim.file).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return [], []
    i = claim.line - 1
    before = [ln.strip() for ln in lines[max(0, i - 6):i] if ln.strip()][-span:]
    after = [ln.strip() for ln in lines[i + 1:i + 7] if ln.strip()][:span]
    return before, after


def _state(root: Path, limit: int = 60) -> dict:
    config = core.load_config(root)
    claims = core.scan(root, config)
    store = core.Store(root)
    deferrals = core.KeyedLog(root, core.DEFERRALS)
    discussions = core.KeyedLog(root, core.DISCUSSIONS)
    ignored = core.KeyedLog(root, core.IGNORED)
    notes = core.KeyedLog(root, core.NOTES)
    triage = core.KeyedLog(root, core.TRIAGE)
    rows = core.build_queue(claims, store, config, WANTED, deferrals, ignored=ignored,
                            triage=triage)

    approved = sum(1 for c in claims
                   if not c.is_question and core.status_of(c, store) in ("approved", "to-validate"))
    total = sum(1 for c in claims if not c.is_question)
    per_file: dict[str, dict[str, int]] = {}
    for c in claims:
        if c.is_question:
            continue
        bucket = per_file.setdefault(c.file, {"done": 0, "total": 0})
        bucket["total"] += 1
        if core.status_of(c, store) in ("approved", "to-validate"):
            bucket["done"] += 1

    cards = []
    for row in rows[:limit]:
        claim, status = row.claim, row.status
        rec = store.records.get(claim.key, {})
        before, after = _context(root, claim)
        siblings = [
            {"key": s.key, "text": s.text, "status": core.status_of(s, store),
             "target": s.key == claim.key}
            for s in core.section_of(claim, claims)
        ]
        pending = [s for s in siblings
                   if not s["target"] and s["status"] in ("proposed", "changed", "expired")]
        cards.append({
            "key": claim.key,
            "risk": row.risk,
            "kind": row.kind,
            "sampled": row.sampled,
            "siblings": siblings[:12],
            "pending_in_section": len(pending),
            "status": status,
            "file": claim.file,
            "line": claim.line,
            "heading": claim.heading,
            "text": claim.text,
            "before": before,
            "after": after,
            "previous": rec.get("preview") if status == "changed" else None,
            "in_discussion": claim.key in discussions.records,
            "notes": [n["text"] for n in notes.records.get(claim.key, {}).get("notes", [])],
            "done": per_file[claim.file]["done"],
            "of": per_file[claim.file]["total"],
        })
    return {
        "cards": cards,
        "queue": len(rows),
        "approved": approved,
        "total": total,
        "today": date.today().isoformat(),
        "repo": root.name,
    }


def _act(root: Path, by: str, payload: dict) -> dict:
    config = core.load_config(root)
    claims = core.scan(root, config)
    claim = next((c for c in claims if c.key == payload.get("key")), None)
    if claim is None:
        return {"error": "claim not found — it was edited or removed since the page loaded"}

    action = payload.get("action")
    store = core.Store(root)
    deferrals = core.KeyedLog(root, core.DEFERRALS)
    discussions = core.KeyedLog(root, core.DISCUSSIONS)
    message = ""

    if action == "approve":
        store.approve(claim, by=by, origin=payload.get("origin"))
        store.save()
        deferrals.drop(claim.key)
        message = "aprovado"
    elif action == "approve_section":
        n = 0
        for sibling in core.section_of(claim, claims):
            if core.status_of(sibling, store) in ("proposed", "changed", "expired"):
                store.approve(sibling, by=by, origin=payload.get("origin"),
                              lot=sibling.key != claim.key)
                deferrals.drop(sibling.key)
                n += 1
        store.save()
        message = f"{n} afirmações desta seção aprovadas (as outras marcadas como lote)"
    elif action == "validate":
        due = payload.get("due") or (date.today() + timedelta(days=30)).isoformat()
        store.approve(claim, by=by, origin=payload.get("origin"),
                      validate=payload.get("validate") or "confirmar", due=due)
        store.save()
        deferrals.drop(claim.key)
        message = f"a validar até {due}"
    elif action == "defer":
        until = payload.get("until") or (date.today() + timedelta(days=14)).isoformat()
        deferrals.put(claim.key, until=until, at=date.today().isoformat())
        message = f"adiado até {until}"
    elif action == "discuss":
        prompt = (f"Sobre esta afirmação em {claim.file}:{claim.line}"
                  f"{' (seção ' + claim.heading + ')' if claim.heading else ''}:\n\n"
                  f"{claim.text}\n\n"
                  "Ela está proposta, não aprovada. Me ajude a decidir: o que a sustenta, "
                  "o que a contradiz, e o que eu precisaria saber para fechar.")
        discussions.put(claim.key, at=date.today().isoformat(), file=claim.file, line=claim.line)
        message = "em conversa"
        return {"ok": True, "message": message, "prompt": prompt, "state": _state(root)}
    elif action == "note":
        text = (payload.get("text") or "").strip()
        if not text:
            return {"error": "nota vazia"}
        notes = core.KeyedLog(root, core.NOTES)
        existing = notes.records.get(claim.key, {}).get("notes", [])
        notes.put(claim.key, file=claim.file, line=claim.line,
                  notes=existing + [{"at": date.today().isoformat(), "text": text}])
        message = "anotado — a afirmação continua proposta"
    elif action == "ignore":
        ignored = core.KeyedLog(root, core.IGNORED)
        ignored.put(claim.key, at=date.today().isoformat(), file=claim.file,
                    preview=claim.preview(), reason=payload.get("reason") or "not a claim")
        message = "fora da fila — não é afirmação"
    elif action == "undo":
        store.unapprove(claim.key)
        store.save()
        deferrals.drop(claim.key)
        discussions.drop(claim.key)
        core.KeyedLog(root, core.IGNORED).drop(claim.key)
        message = "desfeito"
    else:
        return {"error": f"unknown action: {action}"}

    return {"ok": True, "message": message, "state": _state(root)}


PAGE = """<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>km · revisão</title>
<style>
:root{--bg:#F4F5F2;--card:#FBFBF9;--ink:#1C2421;--muted:#5A6660;--rule:#D6DBD6;
--ok:#2B6647;--ok-bg:#DDEDE3;--warn:#94600F;--warn-bg:#F5E9D2;--bad:#8B4E4E;--bad-bg:#F1E1DF;--accent:#2A4B6E;}
@media(prefers-color-scheme:dark){:root{--bg:#131715;--card:#1A1F1D;--ink:#E3E7E4;--muted:#9AA5A0;--rule:#2E3532;
--ok:#86C9A2;--ok-bg:#1C3226;--warn:#E3B665;--warn-bg:#352A17;--bad:#D9A0A0;--bad-bg:#352222;--accent:#8FB3D9;}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif;
padding:24px 16px 60px}
.wrap{max-width:720px;margin:0 auto}
.bar{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;font-size:13px;color:var(--muted);
font-family:ui-monospace,Menlo,monospace}
.card{background:var(--card);border:1px solid var(--rule);border-radius:10px;padding:20px 22px;margin:14px 0}
.top{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;font-size:12px;color:var(--muted);
font-family:ui-monospace,Menlo,monospace}
.text{font-size:19px;line-height:1.45;margin:14px 0 10px;white-space:pre-wrap}
.sec{font-size:13px;color:var(--muted)}
.prev{margin-top:12px;padding:10px 12px;border-left:3px solid var(--warn);background:var(--warn-bg);
font-size:14px;border-radius:0 4px 4px 0}
.ctx{font-size:13.5px;color:var(--muted);line-height:1.45}
.ctx div{padding:2px 0}
.sib{margin-top:14px;border-top:1px dashed var(--rule);padding-top:10px;font-size:14px}
.sib div{padding:3px 0;color:var(--muted)}
.sib div.t{color:var(--ink);font-weight:600}
.sib .ok{color:var(--ok)}
.note{margin-top:10px;padding:8px 12px;border-left:3px solid var(--accent);font-size:14px}
.badge{padding:1px 8px;border-radius:999px;font-size:11px}
.b-chg{color:var(--warn);background:var(--warn-bg)}.b-exp{color:var(--bad);background:var(--bad-bg)}
.b-dis{color:var(--accent);background:transparent;border:1px solid var(--accent)}
.acts{display:flex;gap:8px;flex-wrap:wrap;margin-top:18px}
button{font:inherit;font-size:14px;padding:8px 14px;border-radius:6px;border:1px solid var(--rule);
background:var(--bg);color:var(--ink);cursor:pointer}
button:hover{border-color:var(--accent)}
button.ok{background:var(--ok-bg);border-color:var(--ok-bg);color:var(--ok)}
kbd{font-family:ui-monospace,Menlo,monospace;font-size:11px;opacity:.7}
.prog{height:6px;background:var(--rule);border-radius:3px;overflow:hidden;margin:6px 0 0}
.prog i{display:block;height:100%;background:var(--ok)}
.msg{min-height:1.5em;font-size:14px;color:var(--ok);margin-top:10px}
.done{text-align:center;padding:40px 0;color:var(--muted)}
textarea{width:100%;min-height:60px;font:inherit;font-size:14px;padding:8px;border-radius:6px;
border:1px solid var(--rule);background:var(--bg);color:var(--ink);margin-top:10px}
</style></head><body><div class="wrap">
<div class="bar"><span id="repo"></span><span id="counts"></span></div>
<div id="root"></div>
<div class="msg" id="msg"></div>
<div class="bar" style="margin-top:20px">
<span><kbd>A</kbd> aprovar · <kbd>V</kbd> a validar · <kbd>N</kbd> anotar · <kbd>D</kbd> adiar · <kbd>C</kbd> discutir · <kbd>X</kbd> não é afirmação · <kbd>U</kbd> desfazer</span>
<span id="hoje"></span></div>
</div><script>
let S={cards:[]}, last=null, doneToday=0;
const el=id=>document.getElementById(id);
async function load(){ S=await (await fetch('/api/state')).json(); render(); }
function render(){
  el('repo').textContent=S.repo+' · fila '+S.queue;
  el('counts').textContent=S.approved+'/'+S.total+' aprovadas · hoje '+doneToday+' ✓';
  el('hoje').textContent=S.today;
  const c=S.cards[0];
  if(!c){ el('root').innerHTML='<div class="done">Fila vazia. Nada pede você agora.</div>'; return; }
  const badge=c.status==='changed'?'<span class="badge b-chg">mexido depois de aprovado</span>'
    :c.status==='expired'?'<span class="badge b-exp">prazo vencido</span>':'';
  const dis=c.in_discussion?'<span class="badge b-dis">em conversa</span>':'';
  const tri=c.sampled?`<span class="badge b-dis">amostra · triado como ${esc(c.kind)}</span>`
    :(c.kind&&c.kind!=='?'&&c.kind!=='norma'?`<span class="badge b-dis">${esc(c.kind)}</span>`:'');
  const pct=Math.round(100*c.done/c.of);
  el('root').innerHTML=`<div class="card">
    <div class="top"><span>${c.file}:${c.line}</span><span>risco ${'●'.repeat(c.risk)}${'○'.repeat(Math.max(0,5-c.risk))} ${badge} ${dis} ${tri}</span></div>
    <div class="prog"><i style="width:${pct}%"></i></div>
    ${c.heading?`<div class="sec">${esc(c.file)} · seção: ${esc(c.heading)}</div>`:''}
    ${c.before.length?`<div class="ctx">${c.before.map(l=>`<div>${esc(l)}</div>`).join('')}</div>`:''}
    <div class="text">${esc(c.text)}</div>
    ${c.after.length?`<div class="ctx">${c.after.map(l=>`<div>${esc(l)}</div>`).join('')}</div>`:''}
    ${c.previous?`<div class="prev"><b>texto aprovado antes:</b> ${esc(c.previous)}</div>`:''}
    ${c.notes.map(n=>`<div class="note"><b>sua nota:</b> ${esc(n)}</div>`).join('')}
    ${c.siblings.length>1?`<div class="sib"><b>na mesma seção:</b>
      ${c.siblings.map(s=>`<div class="${s.target?'t':''}">${s.status==='approved'||s.status==='to-validate'?'<span class="ok">✓</span> ':'· '}${esc(s.text.length>110?s.text.slice(0,109)+'…':s.text)}</div>`).join('')}</div>`:''}
    <div class="acts">
      <button class="ok" onclick="act('approve')">Aprovar <kbd>A</kbd></button>
      ${c.pending_in_section?`<button class="ok" onclick="act('approve_section')">Aprovar as ${c.pending_in_section+1} da seção <kbd>S</kbd></button>`:''}
      <button onclick="validar()">A validar <kbd>V</kbd></button>
      <button onclick="anotar()">Anotar <kbd>N</kbd></button>
      <button onclick="act('defer')">Adiar 14d <kbd>D</kbd></button>
      <button onclick="act('discuss')">Discutir <kbd>C</kbd></button>
      <button onclick="ignorar()">Não é afirmação <kbd>X</kbd></button>
      <button onclick="undo()">Desfazer <kbd>U</kbd></button>
    </div></div>`;
}
function esc(s){return (s||'').replace(/[&<>]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[m]));}
async function act(action,extra){
  const c=S.cards[0]; if(!c) return;
  const r=await (await fetch('/api/act',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({key:c.key,action,...(extra||{})})})).json();
  if(r.error){ el('msg').textContent=r.error; return; }
  last=c.key; if(action==='approve'||action==='validate') doneToday++;
  if(r.prompt && navigator.clipboard) navigator.clipboard.writeText(r.prompt).catch(()=>{});
  el('msg').textContent=r.message+(r.prompt?' · contexto copiado, cole no chat':'');
  S=r.state; render();
}
function validar(){ const q=prompt('O que confirmaria isso?','confirmar com quem decide'); if(q!==null) act('validate',{validate:q}); }
function anotar(){ const n=prompt('Nota para corrigir ou completar (fica no .km/, para você ou um agente tratar depois):'); if(n) act('note',{text:n}); }
function ignorar(){ act('ignore',{reason:'not a claim'}); }
function undo(){ if(!last){el('msg').textContent='nada para desfazer';return;}
  fetch('/api/act',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({key:last,action:'undo'})}).then(r=>r.json()).then(r=>{
      if(r.state){S=r.state; if(doneToday>0)doneToday--; last=null; el('msg').textContent='desfeito'; render();}});}
document.addEventListener('keydown',e=>{
  if(e.target.tagName==='TEXTAREA'||e.target.tagName==='INPUT')return;
  const k=e.key.toLowerCase();
  if(k==='a')act('approve'); else if(k==='v')validar(); else if(k==='d')act('defer');
  else if(k==='c')act('discuss'); else if(k==='u')undo();
  else if(k==='n')anotar(); else if(k==='x')ignorar();
  else if(k==='s'&&S.cards[0]&&S.cards[0].pending_in_section)act('approve_section');
});
load();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    root: Path
    by: str

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/api/state"):
            self._send(200, json.dumps(_state(self.root)).encode("utf-8"), "application/json")
        elif self.path in ("/", "/index.html"):
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:  # noqa: N802
        if not self.path.startswith("/api/act"):
            self._send(404, b"not found", "text/plain")
            return
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        result = _act(self.root, self.by, payload)
        self._send(200, json.dumps(result).encode("utf-8"), "application/json")

    def log_message(self, *args) -> None:  # keep the terminal quiet
        return


def make_server(root: Path, port: int, by: str) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"root": root, "by": by})
    return ThreadingHTTPServer(("127.0.0.1", port), handler)


def run(root: Path, port: int = 8431, by: str = "human:unknown") -> int:
    server = make_server(root, port, by)
    state = _state(root)
    print(f"km · {state['queue']} claims waiting · {state['approved']}/{state['total']} approved")
    print(f"http://127.0.0.1:{port}  (ctrl-c to stop; writes only .km/)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
    return 0
