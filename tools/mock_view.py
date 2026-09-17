#!/usr/bin/env python3
"""Mock of the first review surface, generated from a real repository.

Not a product: a static page, no server, no state, regenerated on demand. It exists to
answer whether the view is legible at real volume before any application is written.

The baseline ("what you vouched for") is the git index: a range staged by hand is a human
gesture, block by block. Everything else — block boundaries, claim counts, triage kinds,
notes — is read from the repository as it stands.
"""

from __future__ import annotations

import html
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from km import core  # noqa: E402

HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def blocks_of(text: str) -> list[dict]:
    """A block runs from a heading to the next heading of the same or higher level."""
    lines = text.splitlines()
    heads = [(i, len(m.group(1)), m.group(2).strip())
             for i, l in enumerate(lines) if (m := HEADING.match(l))]
    if not heads:
        return [{"heading": "(sem título)", "path": "(sem título)", "start": 1,
                 "lines": len(lines), "text": "\n".join(lines)}]
    out, stack = [], []
    for n, (i, level, title) in enumerate(heads):
        end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        body = "\n".join(lines[i:end])
        out.append({"heading": title, "path": " › ".join(t for _, t in stack),
                    "start": i + 1, "lines": end - i, "text": body})
    return out


def git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def build(repo: Path, baseline: str = ":") -> dict:
    cfg = core.load_config(repo)
    triage = core.KeyedLog(repo, core.TRIAGE)
    notes = core.KeyedLog(repo, core.NOTES)
    claims = [c for c in core.scan(repo, cfg) if not c.is_question]
    by_file: dict[str, list] = {}
    for c in claims:
        by_file.setdefault(c.file, []).append(c)

    docs = []
    for path in sorted(by_file):
        current = (repo / path).read_text(encoding="utf-8", errors="replace")
        ref = f":{path}" if baseline == ":" else f"{baseline}:{path}"
        base = git(repo, "show", ref) or git(repo, "show", f"HEAD:{path}")
        base_blocks = {b["path"]: b for b in blocks_of(base)} if base else {}

        blocks = []
        for b in blocks_of(current):
            old = base_blocks.get(b["path"])
            same = old and core.normalise(old["text"]) == core.normalise(b["text"])
            state = "chancelado" if same else ("mexido" if old else "novo")
            inside = [c for c in by_file[path]
                      if b["start"] <= c.line < b["start"] + b["lines"]]
            kinds = [triage.records.get(c.key, {}).get("kind", "?") for c in inside]
            block_notes = [n["text"] for c in inside
                           for n in notes.records.get(c.key, {}).get("notes", [])]
            blocks.append({
                "heading": b["heading"], "path": b["path"], "line": b["start"],
                "lines": b["lines"], "state": state, "text": b["text"],
                "old": old["text"] if (old and not same) else None,
                "claims": len(inside), "norms": sum(1 for k in kinds if k == "norma"),
                "notes": block_notes,
            })
        done = sum(1 for b in blocks if b["state"] == "chancelado")
        docs.append({"file": path, "blocks": blocks, "done": done, "total": len(blocks),
                     "claims": len(by_file[path])})
    return {"repo": repo.name, "docs": docs, "baseline": baseline}


PAGE = """<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>km · o que já tem a sua chancela</title><style>
:root{--bg:#F4F5F2;--card:#FBFBF9;--ink:#1C2421;--mut:#5A6660;--rule:#D9DDD8;
--ok:#2B6647;--ok-bg:#DDEDE3;--chg:#94600F;--chg-bg:#F5E9D2;--new:#56636E;--new-bg:#E4E8EB;--acc:#2A4B6E}
@media(prefers-color-scheme:dark){:root{--bg:#131715;--card:#1A1F1D;--ink:#E3E7E4;--mut:#9AA5A0;--rule:#2E3532;
--ok:#86C9A2;--ok-bg:#1C3226;--chg:#E3B665;--chg-bg:#352A17;--new:#A9B6C0;--new-bg:#262D32;--acc:#8FB3D9}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
.top{padding:18px 22px;border-bottom:1px solid var(--rule);display:flex;justify-content:space-between;
gap:14px;flex-wrap:wrap;align-items:baseline}
.top b{font-size:17px}.top span{color:var(--mut);font-size:13px}
.mockbar{background:var(--chg-bg);color:var(--chg);padding:7px 22px;font-size:13px;border-bottom:1px solid var(--rule)}
.wrap{display:grid;grid-template-columns:minmax(240px,300px) minmax(0,1fr);min-height:80vh}
.side{border-right:1px solid var(--rule);padding:12px 8px;overflow:auto}
.side button{display:block;width:100%;text-align:left;background:none;border:0;color:inherit;font:inherit;
padding:7px 10px;border-radius:5px;cursor:pointer}
.side button:hover{background:var(--card)}.side button[aria-current=true]{background:var(--card);
box-shadow:inset 2px 0 0 var(--acc)}
.side .f{font-family:ui-monospace,Menlo,monospace;font-size:12.5px;word-break:break-all}
.side .m{color:var(--mut);font-size:11.5px;display:flex;justify-content:space-between;gap:8px;margin-top:3px}
.bar{height:4px;background:var(--rule);border-radius:2px;margin-top:5px;overflow:hidden}
.bar i{display:block;height:100%;background:var(--ok)}
.main{padding:16px 22px 60px;min-width:0}
.blk{background:var(--card);border:1px solid var(--rule);border-radius:7px;padding:13px 16px;margin:0 0 11px}
.blk h3{margin:0;font-size:15px;display:flex;gap:9px;align-items:baseline;flex-wrap:wrap}
.chip{font:11px/1.6 ui-monospace,Menlo,monospace;padding:1px 8px;border-radius:999px;white-space:nowrap}
.s-chancelado{color:var(--ok);background:var(--ok-bg)}.s-mexido{color:var(--chg);background:var(--chg-bg)}
.s-novo{color:var(--new);background:var(--new-bg)}
.meta{color:var(--mut);font-size:12px;font-family:ui-monospace,Menlo,monospace;margin-top:4px}
pre{white-space:pre-wrap;font:12.5px/1.5 ui-monospace,Menlo,monospace;background:var(--bg);
padding:9px 11px;border-radius:5px;margin:9px 0 0;max-height:230px;overflow:auto}
.two{display:grid;grid-template-columns:1fr 1fr;gap:9px}
.two div b{font-size:11px;color:var(--mut);font-family:ui-monospace,Menlo,monospace}
.note{margin-top:9px;padding:7px 10px;border-left:3px solid var(--acc);font-size:13px}
details summary{cursor:pointer;color:var(--mut);font-size:12.5px;margin-top:7px}
@media(max-width:820px){.wrap{grid-template-columns:1fr}.side{border-right:0;border-bottom:1px solid var(--rule);max-height:230px}.two{grid-template-columns:1fr}}
</style></head><body>
<div class="mockbar"><b>Mock</b> — dados reais deste repositório. Base de comparação: <b id="bl"></b>; nada aqui é clicável ainda.</div>
<div class="top"><b id="t"></b><span id="sum"></span></div>
<div class="wrap"><nav class="side" id="side"></nav><section class="main" id="main"></section></div>
<script>
const D = __DATA__; let sel = 0;
const e = (s) => (s||"").replace(/[&<>]/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[m]));
function side(){
  document.getElementById('side').innerHTML = D.docs.map((d,i)=>{
    const pct = d.total ? Math.round(100*d.done/d.total) : 0;
    return `<button aria-current="${i===sel}" onclick="pick(${i})">
      <div class="f">${e(d.file)}</div>
      <div class="m"><span>${d.done}/${d.total} blocos</span><span>${pct}%</span></div>
      <div class="bar"><i style="width:${pct}%"></i></div></button>`;}).join('');
}
function main(){
  const d = D.docs[sel];
  document.getElementById('main').innerHTML = d.blocks.map(b=>`
    <div class="blk"><h3>${e(b.heading)}
      <span class="chip s-${b.state}">${b.state}</span></h3>
      <div class="meta">linha ${b.line} · ${b.lines} linhas · ${b.claims} afirmações (${b.norms} normas)</div>
      ${b.notes.map(n=>`<div class="note"><b>sua nota:</b> ${e(n)}</div>`).join('')}
      ${b.old ? `<div class="two"><div><b>chancelado</b><pre>${e(b.old)}</pre></div>
        <div><b>agora</b><pre>${e(b.text)}</pre></div></div>`
      : `<details><summary>ver texto</summary><pre>${e(b.text)}</pre></details>`}
    </div>`).join('');
}
function pick(i){ sel=i; side(); main(); window.scrollTo(0,0); }
const tot = D.docs.reduce((a,d)=>a+d.total,0), done = D.docs.reduce((a,d)=>a+d.done,0);
const chg = D.docs.reduce((a,d)=>a+d.blocks.filter(b=>b.state==='mexido').length,0);
const nov = D.docs.reduce((a,d)=>a+d.blocks.filter(b=>b.state==='novo').length,0);
document.getElementById('t').textContent = D.repo;
document.getElementById('bl').textContent = D.baseline === ':' ? 'o que está no stage' : 'commit ' + D.baseline;
document.getElementById('sum').textContent =
  `${done}/${tot} blocos com chancela · ${chg} mexidos depois · ${nov} novos sem chancela`;
side(); main();
</script></body></html>"""


def main() -> int:
    repo = Path(sys.argv[1] if len(sys.argv) > 1 else ".").expanduser().resolve()
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("view.html")
    data = build(repo, sys.argv[3] if len(sys.argv) > 3 else ":")
    out.write_text(PAGE.replace("__DATA__", json.dumps(data, ensure_ascii=False)), encoding="utf-8")
    tot = sum(d["total"] for d in data["docs"])
    done = sum(d["done"] for d in data["docs"])
    print(f"{out}  ·  {len(data['docs'])} documentos · {tot} blocos · {done} com chancela")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
