#!/usr/bin/env python3
"""Mock of the first review surface, generated from a real repository.

Not a product: a static page, no server, no state, regenerated on demand. It exists to
answer whether the view is legible at real volume before any application is written.

The baseline ("what you vouched for") is the git index: a range staged by hand is a human
gesture, block by block. Everything else — block boundaries, claim counts, triage kinds,
notes — is read from the repository as it stands.
"""

from __future__ import annotations

import difflib
import json
import re
import subprocess
import sys
from collections import Counter
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


def diff_rows(a: list[str], b: list[str]) -> list[dict]:
    """Line-aligned rows: the vouched version on the left, the current one on the right."""
    rows: list[dict] = []
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                rows.append({"k": "eq", "a": a[i1 + k], "b": b[j1 + k],
                             "an": i1 + k + 1, "bn": j1 + k + 1})
        elif tag == "replace":
            for k in range(max(i2 - i1, j2 - j1)):
                ia, jb = i1 + k, j1 + k
                rows.append({"k": "chg",
                             "a": a[ia] if ia < i2 else None, "b": b[jb] if jb < j2 else None,
                             "an": ia + 1 if ia < i2 else None, "bn": jb + 1 if jb < j2 else None})
        elif tag == "delete":
            for k in range(i1, i2):
                rows.append({"k": "del", "a": a[k], "b": None, "an": k + 1, "bn": None})
        else:
            for k in range(j1, j2):
                rows.append({"k": "add", "a": None, "b": b[k], "an": None, "bn": k + 1})
    return rows


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
                "heading": b["heading"], "line": b["start"], "lines": b["lines"],
                "state": state, "claims": len(inside),
                "norms": sum(1 for k in kinds if k == "norma"),
                "kinds": dict(Counter(kinds)), "notes": block_notes,
            })

        rows = diff_rows(base.splitlines() if base else [], current.splitlines())
        at_line = {b["line"]: b for b in blocks}
        for r in rows:
            r["block"] = at_line.get(r["bn"]) if r["bn"] else None

        done = sum(1 for b in blocks if b["state"] == "chancelado")
        docs.append({"file": path, "blocks": blocks, "rows": rows, "done": done,
                     "total": len(blocks), "claims": len(by_file[path])})
    return {"repo": repo.name, "docs": docs, "baseline": baseline}


PAGE = """<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>km · o que mudou desde a sua chancela</title><style>
:root{--bg:#F6F7F5;--card:#FBFBF9;--ink:#1C2421;--mut:#5E6A64;--rule:#DCE0DB;--acc:#2A4B6E;
--ok:#2B6647;--ok-bg:#E2F0E7;--chg:#8A5A0B;--chg-bg:#FAF0DA;--add:#2B6647;--add-bg:#E4F2E8;
--del:#8B4E4E;--del-bg:#F7E6E4;--new:#4E5A64;--new-bg:#E6EAED}
@media(prefers-color-scheme:dark){:root{--bg:#131715;--card:#1A1F1D;--ink:#E3E7E4;--mut:#98A39E;--rule:#2C3330;
--acc:#8FB3D9;--ok:#86C9A2;--ok-bg:#16291F;--chg:#E3B665;--chg-bg:#2C2415;--add:#86C9A2;--add-bg:#16291F;
--del:#D9A0A0;--del-bg:#2E1E1E;--new:#A9B6C0;--new-bg:#222A2E}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
.mockbar{background:var(--chg-bg);color:var(--chg);padding:6px 20px;font-size:12.5px;border-bottom:1px solid var(--rule)}
.top{padding:14px 20px;border-bottom:1px solid var(--rule);display:flex;gap:16px;align-items:baseline;flex-wrap:wrap}
.top b{font-size:16px}.top span{color:var(--mut);font-size:12.5px}
label{font-size:12.5px;color:var(--mut);cursor:pointer;user-select:none}
.wrap{display:grid;grid-template-columns:minmax(220px,270px) minmax(0,1fr)}
.side{border-right:1px solid var(--rule);padding:10px 7px;max-height:calc(100vh - 92px);overflow:auto;position:sticky;top:0}
.side button{display:block;width:100%;text-align:left;background:none;border:0;color:inherit;font:inherit;
padding:6px 9px;border-radius:5px;cursor:pointer}
.side button:hover{background:var(--card)}
.side button[aria-current=true]{background:var(--card);box-shadow:inset 2px 0 0 var(--acc)}
.side .f{font-family:ui-monospace,Menlo,monospace;font-size:12px;word-break:break-all}
.side .m{color:var(--mut);font-size:11px;display:flex;justify-content:space-between;margin-top:2px}
.bar{height:3px;background:var(--rule);border-radius:2px;margin-top:4px;overflow:hidden}
.bar i{display:block;height:100%;background:var(--ok)}
.main{min-width:0;padding-bottom:60px}
table{border-collapse:collapse;width:100%;table-layout:fixed}
col.n{width:44px}col.t{width:calc(50% - 44px)}
td{vertical-align:top;padding:1px 8px;font:12.5px/1.45 ui-monospace,Menlo,monospace;
white-space:pre-wrap;word-break:break-word;overflow-wrap:anywhere}
td.n{color:var(--mut);text-align:right;user-select:none;font-size:11px;padding-top:2px}
tr.chg td.b,tr.chg td.a{background:var(--chg-bg)}
tr.add td.b{background:var(--add-bg)}tr.del td.a{background:var(--del-bg)}
tr.add td.a,tr.del td.b{background:repeating-linear-gradient(135deg,transparent,transparent 5px,var(--rule) 5px,var(--rule) 6px)}
.band td{background:var(--card);border-top:1px solid var(--rule);border-bottom:1px solid var(--rule);
padding:9px 12px;font-family:system-ui,sans-serif;white-space:normal}
.band h4{margin:0 0 3px;font-size:14px;display:flex;gap:9px;align-items:baseline;flex-wrap:wrap}
.chip{font:11px/1.6 ui-monospace,Menlo,monospace;padding:0 8px;border-radius:999px}
.s-chancelado{color:var(--ok);background:var(--ok-bg)}
.s-mexido{color:var(--chg);background:var(--chg-bg)}
.s-novo{color:var(--new);background:var(--new-bg)}
.band .meta{color:var(--mut);font-size:11.5px;font-family:ui-monospace,Menlo,monospace}
.band .note{margin-top:6px;padding:6px 10px;border-left:3px solid var(--acc);font-size:13px}
.fold td{color:var(--mut);font-size:11.5px;text-align:center;cursor:pointer;padding:3px}
.fold td:hover{color:var(--acc)}
.hdr{position:sticky;top:0;background:var(--bg);z-index:2}
.hdr td{font-family:system-ui,sans-serif;font-size:11px;color:var(--mut);text-transform:uppercase;
letter-spacing:.06em;padding:6px 8px;border-bottom:1px solid var(--rule)}
@media(max-width:860px){.wrap{grid-template-columns:1fr}.side{position:static;max-height:200px;border-right:0;border-bottom:1px solid var(--rule)}}
</style></head><body>
<div class="mockbar"><b>Mock</b> — dados reais deste repositório, nada é clicável ainda. Base de comparação: <b id="bl"></b></div>
<div class="top"><b id="t"></b><span id="sum"></span>
<label><input type="checkbox" id="only"> só o que mudou</label></div>
<div class="wrap"><nav class="side" id="side"></nav><section class="main" id="main"></section></div>
<script>
const D = __DATA__; let sel = 0, only = false, open = new Set();
const e = s => (s==null?"":String(s)).replace(/[&<>]/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[m]));
function side(){
  document.getElementById('side').innerHTML = D.docs.map((d,i)=>{
    const pct = d.total ? Math.round(100*d.done/d.total) : 0;
    return `<button aria-current="${i===sel}" onclick="pick(${i})"><div class="f">${e(d.file)}</div>
      <div class="m"><span>${d.done}/${d.total} blocos</span><span>${pct}%</span></div>
      <div class="bar"><i style="width:${pct}%"></i></div></button>`;}).join('');
}
function band(b){
  const k = Object.entries(b.kinds||{}).filter(([x])=>x!=='norma'&&x!=='?')
            .map(([x,n])=>`${n} ${x}`).join(' · ');
  return `<tr class="band"><td colspan="4"><h4>${e(b.heading)}
    <span class="chip s-${b.state}">${b.state}</span></h4>
    <div class="meta">linha ${b.line} · ${b.lines} linhas · ${b.norms} normas${k?' · '+e(k):''}</div>
    ${(b.notes||[]).map(n=>`<div class="note"><b>sua nota:</b> ${e(n)}</div>`).join('')}</td></tr>`;
}
function main(){
  const d = D.docs[sel]; const out = [];
  out.push('<table><colgroup><col class="n"><col class="t"><col class="n"><col class="t"></colgroup>');
  out.push('<tr class="hdr"><td></td><td>chancelado</td><td></td><td>agora</td></tr>');
  let run = [];
  const flush = (idx) => {
    if(!run.length) return;
    const big = run.length > 8 && !open.has(idx);
    if(big){
      out.push(`<tr class="fold" onclick="unfold(${idx})"><td colspan="4">▾ ${run.length} linhas iguais</td></tr>`);
    } else run.forEach(r => out.push(r));
    run = [];
  };
  d.rows.forEach((r,i)=>{
    if(r.block){ flush(i); out.push(band(r.block)); }
    const row = `<tr class="${r.k}"><td class="n">${r.an||''}</td><td class="a">${e(r.a)}</td>`
              + `<td class="n">${r.bn||''}</td><td class="b">${e(r.b)}</td></tr>`;
    if(r.k==='eq'){ if(only) return; run.push(row); } else { flush(i); out.push(row); }
  });
  flush(d.rows.length);
  out.push('</table>');
  document.getElementById('main').innerHTML = out.join('');
}
function unfold(i){ open.add(i); main(); }
function pick(i){ sel=i; open=new Set(); side(); main(); scrollTo(0,0); }
document.getElementById('only').onchange = ev => { only = ev.target.checked; main(); };
const tot=D.docs.reduce((a,d)=>a+d.total,0), done=D.docs.reduce((a,d)=>a+d.done,0);
const chg=D.docs.reduce((a,d)=>a+d.blocks.filter(b=>b.state==='mexido').length,0);
const nov=D.docs.reduce((a,d)=>a+d.blocks.filter(b=>b.state==='novo').length,0);
document.getElementById('t').textContent = D.repo;
document.getElementById('bl').textContent = D.baseline===':' ? 'o que está no stage' : 'commit '+D.baseline;
document.getElementById('sum').textContent = `${done}/${tot} blocos com chancela · ${chg} mexidos · ${nov} novos`;
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
