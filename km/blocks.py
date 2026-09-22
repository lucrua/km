"""Blocks: the unit of review.

A block runs from a heading to the next heading of the same or higher level — Markdown's
own structure, so nothing is written into the document. Identity is the heading path, which
carried 99.8% of re-anchoring steps when measured over a real repository's history; a
content hash rides alongside and says whether what was vouched for still stands.

Branches and commits do not appear here on purpose. A block is vouched at a content hash,
so the same text is vouched wherever it lives.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from . import core

BLOCKS = "blocks.jsonl"
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")

#: A state earns its place only by changing what happens next.
STATES = {
    "aprovado": "lido e endossado",
    "aceite": "endossado sem leitura real; expira",
    "a-validar": "depende de alguém de fora, com prazo",
    "reprovado": "errado; o comentário é a instrução de conserto",
}
ACCEPT_EXPIRES_DAYS = 14


ROW = re.compile(r"^\s*\|.*\|\s*$")
SEP = re.compile(r"^[\s:|-]+$")


def normalise_md(text: str) -> str:
    """`core.normalise`, plus the one thing it gets wrong on Markdown: tables.

    Re-aligning a table pads every cell and stretches the separator row. Nothing about the
    content changed, but the text did — and the promise is that a cosmetic edit keeps the
    chancel. Measured on a real document: one of five blocks reported as changed was only a
    table being re-aligned by an editor.
    """
    out = []
    for line in text.splitlines():
        if ROW.match(line):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if all(SEP.match(c or "-") for c in cells):
                cells = ["-" for _ in cells]          # separator row: width is decoration
            out.append("|".join(cells))
        else:
            out.append(line)
    return core.normalise("\n".join(out))


@dataclass
class Block:
    file: str
    heading: str
    path: str
    line: int
    lines: int
    body: str

    @property
    def key(self) -> str:
        return f"{self.file}#{self.path}"

    @property
    def hash(self) -> str:
        return hashlib.sha256(normalise_md(self.body).encode("utf-8")).hexdigest()[:12]

    def preview(self, width: int = 70) -> str:
        t = " ".join(normalise_md(self.body).split())
        return (t[: width - 1] + "…") if len(t) > width else t


def split(text: str, file: str = "") -> list[Block]:
    lines = text.splitlines()
    heads = [(i, len(m.group(1)), m.group(2).strip())
             for i, l in enumerate(lines) if (m := HEADING.match(l))]
    if not heads:
        return [Block(file, "(sem título)", "(sem título)", 1, len(lines), text)]
    out: list[Block] = []
    stack: list[tuple[int, str]] = []
    for n, (i, level, title) in enumerate(heads):
        end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        out.append(Block(file=file, heading=title, path=" › ".join(t for _, t in stack),
                         line=i + 1, lines=end - i, body="\n".join(lines[i + 1:end])))
    return out


def of_file(root: Path, rel: str, rev: str | None = None) -> list[Block]:
    """Blocks of a file, from the working tree or from any git revision."""
    if rev:
        r = subprocess.run(["git", "show", f"{rev}:{rel}"], cwd=root,
                           capture_output=True, text=True)
        if r.returncode != 0:
            return []
        text = r.stdout
    else:
        p = root / rel
        if not p.exists():
            return []
        text = p.read_text(encoding="utf-8", errors="replace")
    return split(text, rel)


class Ledger(core.KeyedLog):
    """What has your chancel, and at which content."""

    def __init__(self, root: Path):
        super().__init__(root, BLOCKS)

    def vouch(self, block: Block, state: str, by: str, note: str | None = None,
              validate: str | None = None, due: str | None = None,
              source: str | None = None) -> dict:
        if state not in STATES:
            raise ValueError(f"estado desconhecido: {state}")
        rec = {
            "key": block.key, "file": block.file, "path": block.path,
            "hash": block.hash, "state": state, "at": date.today().isoformat(), "by": by,
            # The vouched text itself, not just its hash: the left-hand column of a review
            # has to show what you approved, and git cannot always recover it — a block
            # vouched against a dirty working tree exists in no commit.
            "body": block.body,
        }
        if state == "aceite":
            rec["expires"] = (date.today() + timedelta(days=ACCEPT_EXPIRES_DAYS)).isoformat()
        anterior = self.records.get(block.key, {})
        rec["notes"] = list(anterior.get("notes", []))
        if note:
            rec["notes"].append({"at": rec["at"], "text": note, "by": by})
        for k, v in (("validate", validate), ("due", due), ("from", source)):
            if v:
                rec[k] = v
        self.records[block.key] = rec
        return rec

    def note(self, block: Block, text: str, by: str) -> dict:
        """A note accumulates: a thread is a conversation, not a field that gets overwritten."""
        rec = self.records.get(block.key)
        if not rec:
            rec = {"key": block.key, "file": block.file, "path": block.path,
                   "hash": block.hash, "state": "a-validar", "at": date.today().isoformat(),
                   "by": by, "body": block.body, "notes": []}
            self.records[block.key] = rec
        rec.setdefault("notes", []).append(
            {"at": date.today().isoformat(), "text": text, "by": by})
        return rec

    def status_of(self, block: Block, today: str | None = None) -> str:
        rec = self.records.get(block.key)
        if not rec:
            return "não revisado"
        if rec["hash"] != block.hash:
            return f"mexido depois de {rec['state']}"
        if rec.get("expires") and (today or date.today().isoformat()) > rec["expires"]:
            return "suposição"
        return rec["state"]

    def vouched_body(self, block: Block) -> str | None:
        rec = self.records.get(block.key)
        return rec.get("body") if rec else None

    def vouched_file(self, root: Path, rel: str) -> str:
        """The document as you last vouched it: your text where you vouched, current where not."""
        out = []
        for b in of_file(root, rel):
            body = self.vouched_body(b)
            head = "#" * (b.path.count(" › ") + 1) + " " + b.heading
            out.append(head + "\n" + (body if body is not None else b.body))
        return "\n".join(out)

    def orphans(self, live: list[Block]) -> list[dict]:
        keys = {b.key for b in live}
        return [r for k, r in sorted(self.records.items()) if k not in keys]
