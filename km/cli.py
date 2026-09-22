"""Command line. Read-only except for `init`, `approve` and `carry`, which touch `.km/`."""

from __future__ import annotations

import argparse
import difflib
import json
import os
from collections import Counter
from datetime import date
from pathlib import Path

from . import blocks as blk
from . import core

MARK = {
    "approved": "OK ",
    "to-validate": "TV ",
    "expired": "EXP",
    "changed": "CHG",
    "proposed": "-- ",
    "superseded": "SUP",
}


def _root(args) -> Path:
    return Path(args.repo).expanduser().resolve()


def _scan(root: Path):
    config = core.load_config(root)
    return config, core.scan(root, config)


def cmd_init(args) -> int:
    root = _root(args)
    d = root / core.KM_DIR
    d.mkdir(parents=True, exist_ok=True)
    cfg = d / core.CONFIG
    if cfg.exists():
        print(f"{cfg} already exists")
        return 0
    cfg.write_text(json.dumps(core.DEFAULT_CONFIG, indent=2) + "\n", encoding="utf-8")
    (d / ".gitignore").write_text("last-listing.json\n", encoding="utf-8")
    print(f"created {d}")
    print("nothing else in this repository was touched — `km scan` next")
    return 0


def cmd_scan(args) -> int:
    root = _root(args)
    config, claims = _scan(root)
    if args.json:
        print(json.dumps([c.__dict__ for c in claims], ensure_ascii=False, indent=2))
        return 0
    per_file = Counter(c.file for c in claims)
    for f, n in sorted(per_file.items()):
        print(f"{n:5d}  {f}")
    ids = sum(1 for c in claims if c.kind == "id")
    questions = sum(1 for c in claims if c.is_question)
    print(f"\n{len(claims) - questions} claims in {len(per_file)} documents"
          f" · {ids} with a stable ID · {questions} open questions (not approvable)")
    return 0


def cmd_status(args) -> int:
    root = _root(args)
    config, claims = _scan(root)
    store = core.Store(root)
    counts: Counter[str] = Counter()
    per_file: dict[str, Counter] = {}
    for c in claims:
        s = "question" if c.is_question else core.status_of(c, store)
        counts[s] += 1
        per_file.setdefault(c.file, Counter())[s] += 1

    if getattr(args, "short", False):
        # The one line printed after every commit. It has to agree with `km list`, so it is
        # built from the same queue — triage, ignored and deferrals included.
        deferrals = core.KeyedLog(root, core.DEFERRALS)
        ignored = core.KeyedLog(root, core.IGNORED)
        triage = core.KeyedLog(root, core.TRIAGE)
        conflicts = core.KeyedLog(root, core.CONFLICTS)
        queue = core.build_queue(claims, store, config, {"proposed", "changed", "expired"},
                                 deferrals, ignored=ignored, triage=triage)
        norms = [c for c in claims
                 if not c.is_question and c.key not in ignored.records
                 and (triage.records.get(c.key, {}).get("kind", "norma") == "norma"
                      or triage.records.get(c.key, {}).get("text_hash") != c.text_hash)]
        approved = sum(1 for c in norms
                       if core.status_of(c, store) in ("approved", "to-validate"))
        live = {c.key for c in claims}
        open_conflicts = sum(1 for r in conflicts.records.values() if r.get("claim") in live)
        sampled = sum(1 for row in queue if row.sampled)
        bits = [f"km: {approved}/{len(norms)} normas aprovadas", f"{len(queue)} na fila"]
        if sampled:
            # Otherwise the two numbers read as a contradiction on the line seen after
            # every commit, and a number nobody trusts is worse than no number.
            bits.append(f"{sampled} são amostras da triagem")
        if counts["changed"]:
            bits.append(f"{counts['changed']} mexidas depois de aprovadas")
        if counts["expired"]:
            bits.append(f"{counts['expired']} com prazo vencido")
        if open_conflicts:
            bits.append(f"⚠ {open_conflicts} conflitam com algo aprovado")
        print(" · ".join(bits))
        return 0

    width = max((len(f) for f in per_file), default=10)
    print(f"{'document'.ljust(width)}  appr  valid  chgd  prop  ques")
    for f in sorted(per_file):
        c = per_file[f]
        print(f"{f.ljust(width)}  {c['approved']:4d}  {c['to-validate'] + c['expired']:5d}"
              f"  {c['changed']:4d}  {c['proposed']:4d}  {c['question']:4d}")
    total = sum(counts.values()) - counts["question"]
    approved = counts["approved"] + counts["to-validate"]
    pct = (approved / total * 100) if total else 0
    print(f"\n{total} claims · {approved} approved ({pct:.0f}%) · {counts['proposed']} proposed"
          f" · {counts['changed']} changed after approval · {counts['expired']} past due"
          f" · {counts['question']} open questions")
    missing = core.gone(claims, store)
    if missing:
        print(f"{len(missing)} approvals no longer match any claim (`km gone`)")
    return 0


def _queue(root: Path, config: dict, claims, store, wanted: set[str]):
    deferrals = core.KeyedLog(root, core.DEFERRALS)
    ignored = core.KeyedLog(root, core.IGNORED)
    triage = core.KeyedLog(root, core.TRIAGE)
    kinds = {args_kind} if (args_kind := getattr(_queue, "kind", None)) else None
    rows = core.build_queue(claims, store, config, wanted, deferrals, ignored=ignored,
                            triage=triage, kinds=kinds)
    core.save_listing(root, [r.claim.key for r in rows])
    return rows


def cmd_list(args) -> int:
    root = _root(args)
    config, claims = _scan(root)
    store = core.Store(root)
    wanted = {"proposed"} if args.proposed else {"proposed", "changed", "expired"}
    if args.all:
        wanted = set(MARK)
    _queue.kind = args.kind
    rows = _queue(root, config, claims, store, wanted)
    if args.file:
        rows = [r for r in rows if r.claim.file.startswith(args.file)]
    for i, row in enumerate(rows[: args.limit], start=1):
        c = row.claim
        stars = "!" * row.risk
        tag = f"  [{row.kind}]" if row.kind not in ("?", "norma") else ""
        tag += "  (amostra)" if row.sampled else ""
        print(f"{i:4d}  {MARK[row.status]}  {c.file}:{c.line}  {stars}{tag}")
        print(f"      {c.preview()}")
    shown = min(len(rows), args.limit)
    print(f"\n{shown} of {len(rows)} · `km show N` for one, `km approve N` to record your approval")
    return 0


_queue.kind = None  # type: ignore[attr-defined]


def _claim_by_index(root: Path, claims, index: int):
    keys = core.load_listing(root)
    if not keys:
        raise SystemExit("no listing yet — run `km list` first")
    if index < 1 or index > len(keys):
        raise SystemExit(f"index out of range: 1..{len(keys)}")
    key = keys[index - 1]
    for c in claims:
        if c.key == key:
            return c
    raise SystemExit(f"claim {key} is no longer on disk — run `km list` again")


def cmd_show(args) -> int:
    root = _root(args)
    config, claims = _scan(root)
    store = core.Store(root)
    c = _claim_by_index(root, claims, args.index)
    s = core.status_of(c, store)
    print(f"{c.file}:{c.line}")
    if c.heading:
        print(f"section: {c.heading}")
    print(f"status:  {s}   risk: {core.risk(c, config)}   key: {c.key}")
    rec = store.records.get(c.key)
    if rec:
        print(f"approved {rec['approved_at']} by {rec['by']}"
              + (f" · origin {rec['origin']}" if rec.get("origin") else "")
              + (" · in a lot" if rec.get("lot") else ""))
        if rec.get("validate"):
            print(f"to validate: {rec['validate']} (due {rec.get('due', '—')})")
        if s == "changed":
            print(f"approved text: {rec['preview']}")
    print()
    print(c.text)
    return 0


def cmd_approve(args) -> int:
    root = _root(args)
    config, claims = _scan(root)
    store = core.Store(root)
    c = _claim_by_index(root, claims, args.index)
    carried = None
    if args.carry:
        carried = _suggest_carry(c, claims, store)
        if not carried:
            raise SystemExit("no previous approval looks like a reworded version of this claim")
    rec = store.approve(c, by=args.by, origin=args.origin, validate=args.validate,
                        due=args.due, lot=args.lot, carried_from=carried)
    store.save()
    print(f"approved {c.key}  {c.file}:{c.line}")
    if carried:
        print(f"carried from {carried} · original approval date kept ({rec['approved_at']})")
    if rec.get("validate"):
        print(f"to validate: {rec['validate']} (due {rec.get('due', '—')})")
    print(f"recorded in {store.path.relative_to(root)} — no document was modified")
    return 0


def _suggest_carry(claim, claims, store) -> str | None:
    live = {c.key for c in claims}
    best, score = None, 0.0
    for key, rec in store.records.items():
        if key in live:
            continue
        ratio = difflib.SequenceMatcher(None, core.normalise(rec["preview"]),
                                        core.normalise(claim.text)).ratio()
        if ratio > score:
            best, score = key, ratio
    return best if score >= 0.6 else None


def cmd_gone(args) -> int:
    root = _root(args)
    config, claims = _scan(root)
    store = core.Store(root)
    missing = core.gone(claims, store)
    for rec in missing:
        print(f"{rec['key']}  {rec['file']}  approved {rec['approved_at']}")
        print(f"      {rec['preview']}")
    print(f"\n{len(missing)} approvals without a matching claim"
          " — reworded, moved or removed. `km list` then `km approve N --carry`")
    return 0


def cmd_notes(args) -> int:
    """The list an agent reads to act on what you wrote while reviewing."""
    root = _root(args)
    config, claims = _scan(root)
    store = core.Store(root)
    notes = core.KeyedLog(root, core.NOTES)
    by_key = {c.key: c for c in claims}
    shown = 0
    for key, rec in sorted(notes.records.items(), key=lambda kv: (kv[1].get("file", ""), kv[1].get("line", 0))):
        claim = by_key.get(key)
        status = core.status_of(claim, store) if claim else "gone"
        if args.open and status in ("approved", "to-validate"):
            continue
        shown += 1
        where = f"{rec.get('file')}:{rec.get('line')}" if rec.get("file") else key
        print(f"{where}  [{status}]")
        if claim:
            print(f"      {claim.preview()}")
        for note in rec.get("notes", []):
            print(f"  note  {note['at']}  {note['text']}")
    print(f"\n{shown} claims with notes — fix the document, then the claim comes back to the queue")
    return 0


def cmd_triage(args) -> int:
    """Classification is judgement, so it is a model's job — and it only hides and orders.

    export → the claims with no current classification, as JSON
    import → what the model answered: key, kind, risk, reason
    """
    root = _root(args)
    config, claims = _scan(root)
    triage = core.KeyedLog(root, core.TRIAGE)

    if args.action == "status":
        fresh = sum(1 for c in claims
                    if triage.records.get(c.key, {}).get("text_hash") == c.text_hash)
        kinds = Counter(rec.get("kind") for rec in triage.records.values())
        print(f"{fresh} of {sum(1 for c in claims if not c.is_question)} claims classified")
        for kind, n in kinds.most_common():
            print(f"{n:5d}  {kind}")
        return 0

    if args.action == "export":
        todo = [{"key": c.key, "file": c.file, "line": c.line, "heading": c.heading,
                 "text": c.text}
                for c in claims
                if not c.is_question
                and triage.records.get(c.key, {}).get("text_hash") != c.text_hash]
        body = json.dumps({"kinds": list(core.KINDS), "claims": todo},
                          ensure_ascii=False, indent=2)
        if args.path:
            Path(args.path).write_text(body, encoding="utf-8")
            print(f"{len(todo)} claims to classify → {args.path}")
        else:
            print(body)
        return 0

    if not args.path:
        raise SystemExit("import needs a path")
    answers = json.loads(Path(args.path).read_text(encoding="utf-8"))
    if isinstance(answers, dict):
        answers = answers.get("claims", [])
    by_key = {c.key: c for c in claims}
    written = 0
    for a in answers:
        claim = by_key.get(a.get("key"))
        if not claim or a.get("kind") not in core.KINDS:
            continue
        triage.records[claim.key] = {
            "key": claim.key, "kind": a["kind"], "text_hash": claim.text_hash,
            "risk": int(a.get("risk", 0)), "reason": (a.get("reason") or "")[:200],
            "at": date.today().isoformat(), "by": args.by,
        }
        written += 1
    triage.save()
    print(f"{written} classifications recorded in {triage.path.relative_to(root)}")
    print("triage only hides and orders — nothing here approves anything")
    return 0


def cmd_conflicts(args) -> int:
    """Does this claim fight something already settled? Candidates by overlap, verdict by a model."""
    root = _root(args)
    config, claims = _scan(root)
    store = core.Store(root)
    conflicts = core.KeyedLog(root, core.CONFLICTS)

    if args.action == "export":
        pairs = core.candidate_pairs(claims, store,
                                     triage=core.KeyedLog(root, core.TRIAGE))
        fresh = []
        for pair in pairs:
            seen = conflicts.records.get(f"{pair['key']}|{pair['against']}")
            if seen and seen.get("text_hash") == next(
                    (c.text_hash for c in claims if c.key == pair["key"]), None):
                continue
            fresh.append(pair)
        body = json.dumps({"verdicts": ["contradiz", "sobrepoe", "duplica", "independente"],
                           "pairs": fresh[: args.limit]}, ensure_ascii=False, indent=2)
        if args.path:
            Path(args.path).write_text(body, encoding="utf-8")
            print(f"{len(fresh[: args.limit])} candidate pairs → {args.path}")
        else:
            print(body)
        return 0

    if args.action == "import":
        if not args.path:
            raise SystemExit("import needs a path")
        answers = json.loads(Path(args.path).read_text(encoding="utf-8"))
        if isinstance(answers, dict):
            answers = answers.get("pairs", [])
        by_key = {c.key: c for c in claims}
        written = 0
        for a in answers:
            claim = by_key.get(a.get("key"))
            if not claim or a.get("verdict") not in ("contradiz", "sobrepoe", "duplica"):
                continue  # "independente" is a non-finding: nothing to record
            conflicts.records[f"{claim.key}|{a['against']}"] = {
                "key": f"{claim.key}|{a['against']}", "claim": claim.key,
                "against": a["against"], "verdict": a["verdict"],
                "reason": (a.get("reason") or "")[:240], "text_hash": claim.text_hash,
                "at": date.today().isoformat(), "by": args.by,
            }
            written += 1
        conflicts.save()
        print(f"{written} conflicts recorded · a conflict never approves or rejects anything")
        return 0

    by_key = {c.key: c for c in claims}
    shown = 0
    for rec in sorted(conflicts.records.values(), key=lambda r: r.get("verdict", "")):
        claim = by_key.get(rec["claim"])
        other = by_key.get(rec["against"])
        if not claim or not other:
            continue
        shown += 1
        print(f"[{rec['verdict']}] {claim.file}:{claim.line}  ⟷  {other.file}:{other.line}")
        print(f"      novo:      {claim.preview(80)}")
        print(f"      aprovado:  {other.preview(80)}")
        if rec.get("reason"):
            print(f"      {rec['reason']}")
    print(f"\n{shown} conflicts against settled claims")
    return 0


def cmd_install_hooks(args) -> int:
    """So nothing has to be memorised: the repository tells you where it stands."""
    root = _root(args)
    hooks = root / ".git" / "hooks"
    if not hooks.parent.exists():
        raise SystemExit("not a git repository")
    hooks.mkdir(parents=True, exist_ok=True)
    km = Path(__file__).resolve().parent.parent / "bin" / "km"
    body = f"""#!/bin/sh
# knowledge-manager: report only. Never blocks a commit, always exits 0.
"{km}" status --short 2>/dev/null || true
exit 0
"""
    target = hooks / "post-commit"
    if target.exists() and "knowledge-manager" not in target.read_text(encoding="utf-8"):
        print(f"{target} already exists and is not ours — left untouched")
        return 1
    target.write_text(body, encoding="utf-8")
    target.chmod(0o755)
    print(f"installed {target.relative_to(root)} — prints the state after every commit, blocks nothing")
    return 0



def _tracked_files(root: Path, arg: str | None) -> list[str]:
    if arg:
        return [arg]
    config, claims = _scan(root)
    return sorted({c.file for c in claims})


def _block_by_ref(root: Path, rel: str, ref: str) -> blk.Block:
    """`--block` takes the number printed by `km blocks`, or part of the heading."""
    live = blk.of_file(root, rel)
    if ref.isdigit():
        path = Path(root / core.KM_DIR / "last-blocks.json")
        if not path.exists():
            raise SystemExit("rode `km blocks` antes de usar número")
        listagem = json.loads(path.read_text(encoding="utf-8"))
        i = int(ref)
        if not 1 <= i <= len(listagem):
            raise SystemExit(f"fora da faixa: 1..{len(listagem)}")
        chave = listagem[i - 1]
        for b in live:
            if b.key == chave:
                return b
        raise SystemExit("esse bloco já não está no arquivo — rode `km blocks` de novo")
    def sem_acento(t: str) -> str:
        import unicodedata
        return "".join(ch for ch in unicodedata.normalize("NFD", t.lower())
                       if unicodedata.category(ch) != "Mn")

    alvo = sem_acento(ref)
    achados = [b for b in live if alvo in sem_acento(b.heading)]
    if len(achados) != 1:
        raise SystemExit(f"{len(achados)} blocos casam com {ref!r}; seja mais específico")
    return achados[0]


def cmd_vouch(args) -> int:
    """Seed the truth from a review that already happened, at the commit where it happened."""
    root = _root(args)
    ledger = blk.Ledger(root)

    if args.block:
        b = _block_by_ref(root, args.file, args.block)
        antes = ledger.status_of(b)
        ledger.vouch(b, state=args.state, by=args.by, note=args.note,
                     validate=args.validate, due=args.due)
        ledger.save()
        print(f"{b.heading}  ·  {antes} → {args.state}")
        if args.note:
            print(f"   nota: {args.note}")
        restantes = [x for x in blk.of_file(root, args.file)
                     if ledger.status_of(x) not in ("aprovado", "aceite")]
        print(f"faltam {len(restantes)} blocos neste arquivo")
        return 0

    found = blk.of_file(root, args.file, args.source)
    if not found:
        raise SystemExit(f"{args.file} não existe em {args.source or 'disco'}")
    for b in found:
        ledger.vouch(b, state=args.state, by=args.by, note=args.note, source=args.source)
    ledger.save()
    print(f"{len(found)} blocos de {args.file} marcados como {args.state}"
          + (f", no conteúdo de {args.source}" if args.source else ""))
    live = blk.of_file(root, args.file)
    mexidos = sum(1 for b in live if ledger.status_of(b).startswith("mexido"))
    novos = sum(1 for b in live if ledger.status_of(b) == "não revisado")
    print(f"no disco agora: {len(live)} blocos · {mexidos} mexidos desde então · {novos} novos")
    return 0


def cmd_blocks(args) -> int:
    root = _root(args)
    ledger = blk.Ledger(root)

    if args.json:
        saida = []
        for rel in _tracked_files(root, args.file):
            for b in blk.of_file(root, rel):
                rec = ledger.records.get(b.key, {})
                saida.append({"file": b.file, "heading": b.heading, "path": b.path,
                              "line": b.line, "lines": b.lines,
                              "state": ledger.status_of(b), "at": rec.get("at"),
                              "notes": rec.get("notes", []), "validate": rec.get("validate"),
                              "due": rec.get("due"), "vouched": rec.get("body")})
        print(json.dumps(saida, ensure_ascii=False))
        return 0
    total: Counter[str] = Counter()
    todos: list[blk.Block] = []
    listagem: list[str] = []
    for rel in _tracked_files(root, args.file):
        live = blk.of_file(root, rel)
        if not live:
            continue
        todos.extend(live)
        linhas = []
        for b in live:
            st = ledger.status_of(b)
            total[st] += 1
            if args.changed and st in ("aprovado", "aceite"):
                continue
            listagem.append(f"{b.file}#{b.path}")
            linhas.append(f"  {len(listagem):>3}  {st:<26} {b.lines:>3}l  {b.heading[:54]}")
        if linhas:
            print(f"\n{rel}")
            print("\n".join(linhas))
    (root / core.KM_DIR / "last-blocks.json").write_text(
        json.dumps(listagem, ensure_ascii=False), encoding="utf-8")
    orfas = ledger.orphans(todos)
    print("\n" + " · ".join(f"{n} {st}" for st, n in total.most_common()))
    if orfas:
        print(f"{len(orfas)} com chancela e sem bloco correspondente (órfãs):")
        for r in orfas[:5]:
            print(f"  {r['file']} › {r['path'][:60]}")
    return 0


def cmd_note(args) -> int:
    """Add to the conversation on a block without changing its state."""
    root = _root(args)
    ledger = blk.Ledger(root)
    b = _block_by_ref(root, args.file, args.block)
    rec = ledger.note(b, args.text, by=args.by)
    ledger.save()
    print(f"{b.heading}  ·  {len(rec['notes'])} nota(s)  ·  estado: {rec['state']}")
    return 0


def cmd_baseline(args) -> int:
    print(blk.Ledger(_root(args)).vouched_file(_root(args), args.file), end="")
    return 0


def cmd_review(args) -> int:
    """What changed since you vouched, block by block."""
    import difflib

    root = _root(args)
    ledger = blk.Ledger(root)
    vistos = 0
    for rel in _tracked_files(root, args.file):
        for b in blk.of_file(root, rel):
            st = ledger.status_of(b)
            if not st.startswith("mexido"):
                continue
            rec = ledger.records[b.key]
            antes = blk.of_file(root, rel, rec.get("from") or "HEAD")
            old = next((x for x in antes if x.key == b.key), None)
            vistos += 1
            print(f"\n── {rel} › {b.heading}  [{st}]")
            if rec.get("note"):
                print(f"   sua nota: {rec['note']}")
            if old:
                d = difflib.unified_diff(old.body.splitlines(), b.body.splitlines(),
                                         lineterm="", n=args.context)
                for line in list(d)[2:]:
                    print("   " + line)
            if vistos >= args.limit:
                print(f"\n… parando em {args.limit}; use --limit para ver mais")
                return 0
    print(f"\n{vistos} blocos mexidos desde a sua chancela")
    return 0


def cmd_serve(args) -> int:
    from . import serve

    return serve.run(_root(args), port=args.port, by=args.by)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="km", description="Which of your documents you actually approved.")
    p.add_argument("--repo", default=os.getcwd(), help="repository root (default: current directory)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create .km/ in this repository").set_defaults(func=cmd_init)

    s = sub.add_parser("scan", help="parse documents and report what was found (writes nothing)")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_scan)

    s = sub.add_parser("status", help="counts per document")
    s.add_argument("--short", action="store_true", help="one line, for hooks")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("list", help="the review queue, most risky first")
    s.add_argument("--proposed", action="store_true", help="only claims never approved")
    s.add_argument("--all", action="store_true", help="every claim, whatever the status")
    s.add_argument("--file", help="only this path prefix")
    s.add_argument("--kind", choices=core.KINDS, help="only this triaged kind")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("triage", help="hand claims to a model for classification, and read the answer back")
    s.add_argument("action", choices=["export", "import", "status"])
    s.add_argument("path", nargs="?", help="JSON file to write (export) or read (import)")
    s.add_argument("--by", default="agent")
    s.set_defaults(func=cmd_triage)

    s = sub.add_parser("show", help="one claim in full")
    s.add_argument("index", type=int)
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("approve", help="record your approval of a claim")
    s.add_argument("index", type=int)
    s.add_argument("--by", default="human:" + os.environ.get("USER", "unknown"))
    s.add_argument("--origin", help="where it came from: stated, measured, inferred, chat…")
    s.add_argument("--validate", help="what would confirm it")
    s.add_argument("--due", help="when it comes back to the queue (YYYY-MM-DD)")
    s.add_argument("--lot", action="store_true", help="approved as part of a batch")
    s.add_argument("--carry", action="store_true", help="reworded claim: keep the old approval's date and origin")
    s.set_defaults(func=cmd_approve)

    sub.add_parser("gone", help="approvals with no matching claim").set_defaults(func=cmd_gone)

    s = sub.add_parser("notes", help="what you wrote on claims while reviewing")
    s.add_argument("--open", action="store_true", help="only notes on claims still not approved")
    s.set_defaults(func=cmd_notes)

    s = sub.add_parser("conflicts", help="claims that fight something already approved")
    s.add_argument("action", nargs="?", default="list", choices=["list", "export", "import"])
    s.add_argument("path", nargs="?")
    s.add_argument("--limit", type=int, default=400)
    s.add_argument("--by", default="agent")
    s.set_defaults(func=cmd_conflicts)

    sub.add_parser("install-hooks",
                   help="report the state after each commit, so no command has to be remembered"
                   ).set_defaults(func=cmd_install_hooks)

    s = sub.add_parser("vouch", help="record blocks of a file as vouched, as of a commit")
    s.add_argument("file")
    s.add_argument("--from", dest="source", help="commit whose content you reviewed")
    s.add_argument("--block", help="número do `km blocks`, ou parte do título")
    s.add_argument("--state", default="aprovado", choices=sorted(blk.STATES))
    s.add_argument("--note")
    s.add_argument("--validate", help="o que confirmaria (estado a-validar)")
    s.add_argument("--due", help="até quando (AAAA-MM-DD)")
    s.add_argument("--by", default="human:" + os.environ.get("USER", "unknown"))
    s.set_defaults(func=cmd_vouch)

    s = sub.add_parser("blocks", help="status of every block against your chancel")
    s.add_argument("file", nargs="?")
    s.add_argument("--changed", action="store_true", help="hide what still stands")
    s.add_argument("--json", action="store_true", help="for the editor extension")
    s.set_defaults(func=cmd_blocks)

    s = sub.add_parser("note", help="add a note to a block, leaving its state alone")
    s.add_argument("file")
    s.add_argument("--block", required=True, help="número do `km blocks`, ou parte do título")
    s.add_argument("text")
    s.add_argument("--by", default="human:" + os.environ.get("USER", "unknown"))
    s.set_defaults(func=cmd_note)

    s = sub.add_parser("baseline", help="the document as you last vouched it (for the left pane)")
    s.add_argument("file")
    s.set_defaults(func=cmd_baseline)

    s = sub.add_parser("review", help="what changed since you vouched, block by block")
    s.add_argument("file", nargs="?")
    s.add_argument("--limit", type=int, default=8)
    s.add_argument("--context", type=int, default=2)
    s.set_defaults(func=cmd_review)

    s = sub.add_parser("serve", help="review the queue in a local page, one claim at a time")
    s.add_argument("--port", type=int, default=8431)
    s.add_argument("--by", default="human:" + os.environ.get("USER", "unknown"))
    s.set_defaults(func=cmd_serve)

    args = p.parse_args(argv)
    return args.func(args)
