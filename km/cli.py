"""Command line. Read-only except for `init`, `approve` and `carry`, which touch `.km/`."""

from __future__ import annotations

import argparse
import difflib
import json
import os
from collections import Counter
from datetime import date
from pathlib import Path

from . import chancela as ch
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

    if getattr(args, "short", False):
        # The one line printed after every commit. It is about the chancel, because that is
        # what review means now; the claim queue keeps its own commands. The only thing
        # borrowed from there is a clash with something already approved, which is the one
        # finding you cannot see by reading the diff — and the documents are only parsed
        # when there is a clash recorded, so the hook stays under a second.
        linha = _resumo_chancela(root)
        conflicts = core.KeyedLog(root, core.CONFLICTS)
        if conflicts.records:
            live = {c.key for c in _scan(root)[1]}
            abertos = sum(1 for r in conflicts.records.values() if r.get("claim") in live)
            if abertos:
                linha += f" · ⚠ {abertos} conflitam com algo aprovado"
        print(linha)
        return 0

    config, claims = _scan(root)
    store = core.Store(root)
    counts: Counter[str] = Counter()
    per_file: dict[str, Counter] = {}
    for c in claims:
        s = "question" if c.is_question else core.status_of(c, store)
        counts[s] += 1
        per_file.setdefault(c.file, Counter())[s] += 1

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
    """Which files the chancel covers: the documents `km` already tracks, plus anything
    that has a chancel and is no longer on disk."""
    if arg:
        return [arg]
    config = core.load_config(root)
    vivos = [p.relative_to(root).as_posix() for p in core.documents(root, config)]
    return sorted(set(vivos) | set(ch.arquivos(root)))


def _hunks_por_ref(root: Path, rel: str, ref: str, hs: list[ch.Hunk]) -> list[ch.Hunk]:
    """`--hunk` takes the number printed by `km pendente`, or part of a heading.

    A heading takes every pending change under it, not the first one: endorsing a passage
    is endorsing the passage, and picking one of its changes is what the number is for.
    """
    if ref.isdigit():
        n = int(ref)
        achados = [h for h in hs if h.n == n]
        if not achados:
            raise SystemExit(f"{rel}: não há trecho {n} — rode `km pendente {rel}`")
        return achados

    import unicodedata

    def sem_acento(t: str) -> str:
        return "".join(c for c in unicodedata.normalize("NFD", t.lower())
                       if unicodedata.category(c) != "Mn")

    alvo = sem_acento(ref)
    achados = [h for h in hs if alvo in sem_acento(h.titulo)]
    if not achados:   # o título pode estar acima, se o trecho é filho de outro
        achados = [h for h in hs if alvo in sem_acento(h.caminho)]
    if not achados:
        raise SystemExit(f"{rel}: nenhuma mudança pendente em um título com {ref!r}")
    return achados


def _resumo_chancela(root: Path) -> str:
    """One line: what the chancel covers, what moved, what it never saw."""
    if not (root / ".git").exists():
        return "km: fora de um repositório git — a chancela é um ref"
    situacoes = [ch.situacao(root, rel) for rel in _tracked_files(root, None)]
    em_dia = sum(1 for s in situacoes if s.em_dia)
    mexidos = sum(len(s.hunks) for s in situacoes if s.tem_chancela)
    nunca = sum(1 for s in situacoes if not s.tem_chancela)
    vencidas = sum(len(s.vencidas) for s in situacoes)
    bits = [f"km: {em_dia} arquivos em dia com a chancela"]
    if mexidos:
        bits.append(f"{mexidos} trechos mexidos")
    if nunca:
        bits.append(f"{nunca} sem chancela")
    if vencidas:
        bits.append(f"❓ {vencidas} com prazo vencido")
    return " · ".join(bits)


def cmd_pendente(args) -> int:
    """The two questions: what changed since the chancel, and what never had one."""
    root = _root(args)
    hoje = date.today().isoformat()
    situacoes = [ch.situacao(root, rel, hoje) for rel in _tracked_files(root, args.file)]

    if args.json:
        print(json.dumps([e for s in situacoes for e in ch.estados(s)], ensure_ascii=False))
        return 0

    sem_chancela = [s for s in situacoes if not s.tem_chancela]
    mexidos = [s for s in situacoes if s.tem_chancela and s.hunks]
    total = 0
    for s in mexidos:
        # The number is the hunk's own, inside its file: `km chancela <arquivo> --hunk 2`.
        # A list numbered across files would need a sidecar to be resolved again, and a
        # sidecar is what this design just removed.
        print(f"\n{s.arquivo}")
        for h in s.hunks:
            total += 1
            sinal = "🚫" if h.bloqueio else ("⚠️" if h.sumidas else "  ")
            print(f"  {h.n:>3} {sinal} -{len(h.antes):<3} +{len(h.depois):<3}"
                  f" {h.titulo[:40]:<40} {h.resumo(38)}")
            for l in h.sumidas:
                print(f"       ressalva removida: {l[:70]}")
            if h.bloqueio:
                print(f"       trecho bloqueado: {h.bloqueio[:70]}")

    if sem_chancela:
        print(f"\nsem chancela nenhuma ({len(sem_chancela)}):")
        for s in sem_chancela[:args.limit]:
            print(f"      {s.arquivo}  ·  {len(s.depois.splitlines())} linhas")
        if len(sem_chancela) > args.limit:
            print(f"      … e mais {len(sem_chancela) - args.limit}")

    vencidas = [(s.arquivo, l, prazo, txt) for s in situacoes for l, prazo, txt in s.vencidas]
    if vencidas:
        print(f"\n❓ com prazo vencido ({len(vencidas)}):")
        for arquivo, l, prazo, txt in vencidas[:args.limit]:
            print(f"      {arquivo}:{l}  desde {prazo}  {txt[:60]}")

    em_dia = sum(1 for s in situacoes if s.em_dia)
    print(f"\n{total} trechos mexidos em {len(mexidos)} arquivos"
          f" · {em_dia} arquivos em dia · {len(sem_chancela)} sem chancela")
    if total:
        print("chancelar: km chancela <arquivo> --hunk <n|título>   ·   tudo: --all")
    return 0


def cmd_chancela(args) -> int:
    """Write the accepted passages into the ref. The act is per passage; the ref holds files."""
    root = _root(args)
    rel = args.file
    s = ch.situacao(root, rel)
    if ch.atual(root, rel) is None:
        raise SystemExit(f"{rel} não existe no disco")
    if not s.hunks:
        print(f"{rel}: nada pendente — a chancela já é o arquivo de hoje")
        return 0

    if args.all:
        escolhidos = [h for h in s.hunks]
    elif args.hunk:
        escolhidos = [h for r in args.hunk for h in _hunks_por_ref(root, rel, r, s.hunks)]
    else:
        raise SystemExit("diga o que entra: --hunk <n|título> (um ou mais) ou --all")

    barrados = [h for h in escolhidos if h.bloqueio and not args.force]
    escolhidos = [h for h in escolhidos if h not in barrados]
    if not escolhidos:
        for h in barrados:
            print(f"🚫 {h.titulo}: {h.bloqueio}")
        raise SystemExit("nada entrou: resolva o 🚫 (ou --force, que o deixa no texto)")

    novo = ch.aplicar(s.antes, s.depois, {h.n for h in escolhidos}, s.hunks)
    titulos = ", ".join(dict.fromkeys(h.titulo for h in escolhidos))
    corpo = args.message or ""
    cabeca = (f"chancela: {rel} · {len(escolhidos)} trecho(s)"
              if not args.all or len(escolhidos) != len(s.hunks)
              else f"chancela: {rel} · arquivo inteiro")
    mensagem = f"{cabeca}\n\n{titulos}\n"
    if corpo:
        mensagem += f"\n{corpo}\n"
    mensagem += f"\npor: {args.by}\n"
    commit = ch.escrever(root, {rel: novo}, mensagem)

    print(f"{rel}  ·  {len(escolhidos)} trecho(s) na chancela  ·  {commit[:8]}")
    por_titulo: dict[str, list[ch.Hunk]] = {}
    for h in escolhidos:
        por_titulo.setdefault(h.titulo, []).append(h)
    for titulo, dela in por_titulo.items():
        quantos = f"  ({len(dela)} mudanças)" if len(dela) > 1 else ""
        print(f"   ✓ {titulo}{quantos}")
        for l in (s for h in dela for s in h.sumidas):
            print(f"     (a ressalva {l[:56]} saiu junto)")
    for h in barrados:
        print(f"   🚫 {h.titulo} — ficou de fora: {h.bloqueio[:60]}")
    resto = ch.situacao(root, rel).hunks
    print(f"faltam {len(resto)} trecho(s) neste arquivo")
    if resto:
        # The numbers come from the diff, and the diff just moved. Acting on a number from
        # the previous listing would chancel a passage you did not look at.
        print("os números mudaram — rode `km pendente` de novo"
              " (ou passe vários --hunk de uma vez)")
    return 0


def cmd_lint(args) -> int:
    """Mechanical checks on the convention. No judgement, no model."""
    root = _root(args)
    hoje = date.today().isoformat()
    achados = 0
    for rel in _tracked_files(root, args.file):
        s = ch.situacao(root, rel, hoje)
        texto = ch.atual(root, rel)
        if texto is None:
            print(f"{rel}: tem chancela e não está mais no disco")
            achados += 1
            continue
        linhas = []
        for n, prazo, txt in s.vencidas:
            linhas.append(f"  ❓ :{n} venceu em {prazo} — {txt[:60]}")
        for _, marca, txt in ch.ressalvas(texto):
            if marca == "🚫":
                linhas.append(f"  🚫 bloqueia a chancela do trecho — {txt[:60]}")
        for h in s.hunks:
            for l in h.sumidas:
                linhas.append(f"  ⚠️ ressalva removida em {h.titulo[:30]} — {l[:50]}")
        if linhas:
            print(f"\n{rel}")
            print("\n".join(linhas))
            achados += len(linhas)
    print(f"\n{achados} apontamento(s)")
    return 1 if achados and args.strict else 0


def cmd_restore(args) -> int:
    """Put back the chancelled text of a passage — refusing a change and leaving it in
    place would keep in the document exactly what you just rejected."""
    root = _root(args)
    rel = args.file
    s = ch.situacao(root, rel)
    if not s.tem_chancela:
        raise SystemExit(f"{rel} nunca teve chancela — não há texto para devolver")
    if not s.hunks:
        print(f"{rel}: nada mudou desde a chancela")
        return 0
    alvos = ([h for h in s.hunks] if args.all
             else [h for r in args.hunk for h in _hunks_por_ref(root, rel, r, s.hunks)])
    if not alvos:
        raise SystemExit("diga o que volta: --hunk <n|título> ou --all")
    manter = {h.n for h in s.hunks} - {h.n for h in alvos}
    (root / rel).write_text(ch.aplicar(s.antes, s.depois, manter, s.hunks), encoding="utf-8")
    print(f"{rel}  ·  {len(alvos)} trecho(s) de volta ao texto chancelado")
    for h in alvos:
        print(f"   ↩ {h.titulo}")
    if args.message:
        print(f"   motivo: {args.message}  (escreva-o no commit, ou como ⚠️ no texto)")
    return 0


def cmd_baseline(args) -> int:
    """The left-hand column: the document as you last endorsed it."""
    texto = ch.chancelado(_root(args), args.file)
    if texto is None:
        print(f"<!-- km: {args.file} nunca teve chancela -->")
        return 0
    print(texto, end="")
    return 0


def cmd_quando(args) -> int:
    """When did this passage last have a chancel — the question blocks were storing for."""
    root = _root(args)
    alvo = None
    if args.trecho:
        import unicodedata

        def sem_acento(t: str) -> str:
            return "".join(c for c in unicodedata.normalize("NFD", t.lower())
                           if unicodedata.category(c) != "Mn")

        base = ch.chancelado(root, args.file) or ch.atual(root, args.file) or ""
        ref = sem_acento(args.trecho)
        achados = [t for t in ch.trechos(base) if ref in sem_acento(t.titulo)]
        if not achados:
            raise SystemExit(f"nenhum trecho com {args.trecho!r} em {args.file}")
        alvo = achados[0]
        print(f"{args.file} › {alvo.titulo}")
    saida = ch.historico(root, args.file, alvo, limite=args.limit).strip()
    print(saida or "nunca teve chancela")
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

    s = sub.add_parser("chancela", help="escrever os trechos aceitos na chancela (refs/km/chancela)", aliases=["chancel"])
    s.add_argument("file")
    s.add_argument("--hunk", action="append", default=[],
                   help="número do `km pendente`, ou parte do título; repetível")
    s.add_argument("--all", action="store_true", help="o arquivo inteiro como está hoje")
    s.add_argument("-m", "--message", help="por que você endossa (vai na mensagem do commit)")
    s.add_argument("--force", action="store_true", help="chancelar mesmo com 🚫 no trecho")
    s.add_argument("--by", default="human:" + os.environ.get("USER", "unknown"))
    s.set_defaults(func=cmd_chancela)

    s = sub.add_parser("pendente", help="o que mudou desde a chancela, e o que nunca teve uma", aliases=["pending"])
    s.add_argument("file", nargs="?")
    s.add_argument("--json", action="store_true", help="para o editor")
    s.add_argument("--limit", type=int, default=12)
    s.set_defaults(func=cmd_pendente)

    s = sub.add_parser("lint", help="a convenção das ressalvas: 🚫 pendente, ❓ vencida, ⚠️ sumida")
    s.add_argument("file", nargs="?")
    s.add_argument("--strict", action="store_true", help="sai com erro se houver apontamento")
    s.set_defaults(func=cmd_lint)

    s = sub.add_parser("restore", help="devolver ao texto que você chancelou")
    s.add_argument("file")
    s.add_argument("--hunk", action="append", default=[])
    s.add_argument("--all", action="store_true")
    s.add_argument("-m", "--message", help="por que a mudança não serve")
    s.set_defaults(func=cmd_restore)

    s = sub.add_parser("baseline", help="o documento como você o chancelou (coluna da esquerda)")
    s.add_argument("file")
    s.set_defaults(func=cmd_baseline)

    s = sub.add_parser("quando", help="quando este trecho teve chancela pela última vez", aliases=["when"])
    s.add_argument("file")
    s.add_argument("--trecho", help="parte do título")
    s.add_argument("--limit", type=int, default=5)
    s.set_defaults(func=cmd_quando)

    s = sub.add_parser("serve", help="review the queue in a local page, one claim at a time")
    s.add_argument("--port", type=int, default=8431)
    s.add_argument("--by", default="human:" + os.environ.get("USER", "unknown"))
    s.set_defaults(func=cmd_serve)

    args = p.parse_args(argv)
    return args.func(args)
