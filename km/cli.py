"""Command line. Read-only except for `init`, `approve` and `carry`, which touch `.km/`."""

from __future__ import annotations

import argparse
import difflib
import json
import os
from collections import Counter
from pathlib import Path

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
    rows = core.build_queue(claims, store, config, wanted, deferrals)
    core.save_listing(root, [c.key for _, _, c in rows])
    return rows


def cmd_list(args) -> int:
    root = _root(args)
    config, claims = _scan(root)
    store = core.Store(root)
    wanted = {"proposed"} if args.proposed else {"proposed", "changed", "expired"}
    if args.all:
        wanted = set(MARK)
    rows = _queue(root, config, claims, store, wanted)
    if args.file:
        rows = [r for r in rows if r[2].file.startswith(args.file)]
    for i, (risk, s, c) in enumerate(rows[: args.limit], start=1):
        stars = "!" * risk
        print(f"{i:4d}  {MARK[s]}  {c.file}:{c.line}  {stars}")
        print(f"      {c.preview()}")
    shown = min(len(rows), args.limit)
    print(f"\n{shown} of {len(rows)} · `km show N` for one, `km approve N` to record your approval")
    return 0


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

    sub.add_parser("status", help="counts per document").set_defaults(func=cmd_status)

    s = sub.add_parser("list", help="the review queue, most risky first")
    s.add_argument("--proposed", action="store_true", help="only claims never approved")
    s.add_argument("--all", action="store_true", help="every claim, whatever the status")
    s.add_argument("--file", help="only this path prefix")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cmd_list)

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

    s = sub.add_parser("serve", help="review the queue in a local page, one claim at a time")
    s.add_argument("--port", type=int, default=8431)
    s.add_argument("--by", default="human:" + os.environ.get("USER", "unknown"))
    s.set_defaults(func=cmd_serve)

    args = p.parse_args(argv)
    return args.func(args)
