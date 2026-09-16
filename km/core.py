"""Parsing documents into claims, and the approval record.

Nothing here writes outside the `.km/` directory of the target repository.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

KM_DIR = ".km"
APPROVALS = "approvals.jsonl"
DEFERRALS = "deferrals.jsonl"
DISCUSSIONS = "discussions.jsonl"
IGNORED = "ignored.jsonl"
NOTES = "notes.jsonl"
TRIAGE = "triage.jsonl"
CONFLICTS = "conflicts.jsonl"

# Words too common in Portuguese documents to say anything about two claims being related.
STOPWORDS = {
    "para", "como", "esse", "essa", "isso", "aqui", "pelo", "pela", "mais", "menos", "quando",
    "onde", "porque", "entre", "sobre", "cada", "todo", "toda", "todos", "todas", "sem",
    "com", "que", "não", "nao", "uma", "dos", "das", "nos", "nas", "por", "ser", "está",
    "esta", "estão", "estao", "foi", "são", "sao", "tem", "ter", "isto", "aquele", "mesmo",
    "ainda", "depois", "antes", "então", "entao", "pode", "deve", "vale", "fica", "quer",
    "dizer", "caso", "casos", "parte", "lado", "linha", "linhas", "texto", "arquivo",
}

# What a claim is, as judged by a model. Only `norma` reaches the queue by default.
KINDS = ("norma", "procedencia", "contexto", "ponteiro", "pergunta", "duplicada")
SAMPLE_EVERY = 7  # one in seven hidden claims is shown anyway, to catch a wrong triage
CONFIG = "config.json"
LISTING = "last-listing.json"

DEFAULT_CONFIG = {
    "include": ["**/*.md"],
    "exclude": [
        "**/node_modules/**",
        "**/.git/**",
        "**/.km/**",
        "**/sandbox/**",
        "**/CHANGELOG.md",
        "**/LICENSE*",
    ],
    "high_risk_files": [],
    "risk_terms": [],
}

ID_PATTERN = re.compile(r"^\*\*([A-Z][A-Z0-9]{1,9}-\d{1,4})\*\*[\s:.—-]+")
LIST_ITEM = re.compile(r"^(\s*)(?:[-*+]|\d{1,3}[.)])\s+(.*)$")
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
FENCE = re.compile(r"^\s*(```|~~~)")
SKIP_LINE = re.compile(r"^\s*(>|\||<|!\[|\[!|---\s*$|\*\*\*\s*$|___\s*$)")
EMPHASIS = re.compile(r"[*_`~]+")
LINKS = re.compile(r"\[([^\]]*)\]\([^)]*\)")
CHECKBOX = re.compile(r"^\[[ xX]\]\s*")


@dataclass
class Claim:
    key: str
    kind: str  # "id" or "hash"
    claim_id: str | None
    text: str
    text_hash: str
    file: str
    line: int
    heading: str
    is_question: bool = False

    def preview(self, width: int = 90) -> str:
        t = " ".join(self.text.split())
        return t if len(t) <= width else t[: width - 1] + "…"


def normalise(text: str) -> str:
    """Text reduced to what a change of meaning would have to survive.

    Emphasis, link targets, checkbox markers, case and spacing are noise here: a typo fix
    that touches only these keeps the approval alive.
    """
    t = unicodedata.normalize("NFKC", text)
    t = LINKS.sub(r"\1", t)
    t = CHECKBOX.sub("", t)
    t = EMPHASIS.sub("", t)
    t = t.replace("…", "...")
    t = re.sub(r"\s+", " ", t).strip().lower()
    t = t.rstrip(" .;:,")
    return t


def text_hash(text: str) -> str:
    return hashlib.sha256(normalise(text).encode("utf-8")).hexdigest()[:12]


def scoped_key(file: str, text: str) -> str:
    """Identity is the text *in its document*, never the text alone.

    Measured on a real repository: 369 claims produced only 355 distinct text hashes,
    because boilerplate repeats — "**Descartado.**" appears once per decision, seven times.
    Keyed by text alone, approving one of them would silently approve all seven. Changes are
    still detected by `text_hash`, which stays text-only; only identity is scoped.
    """
    return "h:" + hashlib.sha256(f"{file}\n{normalise(text)}".encode("utf-8")).hexdigest()[:12]


def _heading_path(stack: list[tuple[int, str]]) -> str:
    return " > ".join(h for _, h in stack)


def parse_markdown(path: Path, rel: str) -> list[Claim]:
    """Split one document into claims.

    A claim is a list item or a paragraph. Headings, tables, quotes, code and front matter
    are context, not claims — see docs/format.md.
    """
    claims: list[Claim] = []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    stack: list[tuple[int, str]] = []
    in_fence = False
    in_front = False
    buf: list[str] = []
    buf_line = 0

    def flush() -> None:
        nonlocal buf, buf_line
        if buf:
            raw = " ".join(s.strip() for s in buf).strip()
            if raw and normalise(raw):
                claims.append(_make_claim(raw, rel, buf_line, _heading_path(stack)))
        buf = []

    for n, raw_line in enumerate(lines, start=1):
        if n == 1 and raw_line.strip() == "---":
            in_front = True
            continue
        if in_front:
            if raw_line.strip() in ("---", "..."):
                in_front = False
            continue
        if FENCE.match(raw_line):
            flush()
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        heading = HEADING.match(raw_line)
        if heading:
            flush()
            level = len(heading.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, heading.group(2).strip()))
            continue

        if not raw_line.strip():
            flush()
            continue

        if SKIP_LINE.match(raw_line):
            flush()
            continue

        item = LIST_ITEM.match(raw_line)
        if item:
            flush()
            buf = [item.group(2)]
            buf_line = n
            continue

        if buf:
            buf.append(raw_line)
        else:
            buf = [raw_line]
            buf_line = n

    flush()
    return claims


def _make_claim(raw: str, rel: str, line: int, heading: str) -> Claim:
    m = ID_PATTERN.match(raw)
    claim_id = m.group(1) if m else None
    h = text_hash(raw)
    key = claim_id if claim_id else scoped_key(rel, raw)
    kind = "id" if claim_id else "hash"
    # `- [ ] …` is an open question, not something to approve: it states what is missing.
    is_question = bool(CHECKBOX.match(raw.lstrip()))
    return Claim(key=key, kind=kind, claim_id=claim_id, text=raw, text_hash=h,
                 file=rel, line=line, heading=heading, is_question=is_question)


def _matches(rel: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch("/" + rel, p) for p in patterns)


def documents(root: Path, config: dict) -> list[Path]:
    found: list[Path] = []
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root).as_posix()
        if _matches(rel, config.get("exclude", [])):
            continue
        if config.get("include") and not _matches(rel, config["include"]):
            continue
        found.append(path)
    return found


def scan(root: Path, config: dict) -> list[Claim]:
    claims: list[Claim] = []
    for path in documents(root, config):
        claims.extend(parse_markdown(path, path.relative_to(root).as_posix()))
    return claims


class Store:
    """The approval record: one JSON object per line, ordered by key."""

    def __init__(self, root: Path):
        self.root = root
        self.dir = root / KM_DIR
        self.path = self.dir / APPROVALS
        self.records: dict[str, dict] = {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                rec = json.loads(line)
                self.records[rec["key"]] = rec

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        out = [json.dumps(self.records[k], ensure_ascii=False, sort_keys=True)
               for k in sorted(self.records)]
        self.path.write_text("\n".join(out) + ("\n" if out else ""), encoding="utf-8")

    def unapprove(self, key: str) -> dict | None:
        """Undo the last approval. Approving by mistake must cost one keystroke to fix."""
        return self.records.pop(key, None)

    def approve(self, claim: Claim, by: str, origin: str | None = None,
                validate: str | None = None, due: str | None = None,
                lot: bool = False, carried_from: str | None = None,
                approved_at: str | None = None) -> dict:
        prev = self.records.get(carried_from or "", {})
        rec = {
            "key": claim.key,
            "kind": claim.kind,
            "text_hash": claim.text_hash,
            "preview": claim.preview(),
            "file": claim.file,
            "approved_at": approved_at or prev.get("approved_at") or date.today().isoformat(),
            "by": by,
        }
        origin = origin or prev.get("origin")
        if origin:
            rec["origin"] = origin
        if validate or prev.get("validate"):
            rec["validate"] = validate or prev.get("validate")
        if due or prev.get("due"):
            rec["due"] = due or prev.get("due")
        if lot:
            rec["lot"] = True
        if carried_from:
            rec["carried_from"] = carried_from
            rec["reapproved_at"] = date.today().isoformat()
            self.records.pop(carried_from, None)
        self.records[claim.key] = rec
        return rec


def status_of(claim: Claim, store: Store, today: str | None = None) -> str:
    rec = store.records.get(claim.key)
    if not rec:
        return "proposed"
    if rec.get("superseded_by"):
        return "superseded"
    if rec["text_hash"] != claim.text_hash:
        return "changed"
    if rec.get("due"):
        if (today or date.today().isoformat()) > rec["due"]:
            return "expired"
        return "to-validate"
    return "approved"


def gone(claims: list[Claim], store: Store) -> list[dict]:
    """Approvals whose claim is no longer on disk with the same text."""
    live = {c.key for c in claims}
    return [rec for key, rec in sorted(store.records.items()) if key not in live]


def risk(claim: Claim, config: dict) -> int:
    score = 0
    if _matches(claim.file, config.get("high_risk_files", [])):
        score += 2
    low = claim.text.lower()
    if re.search(r"\d", claim.text) or "%" in claim.text:
        score += 1
    if any(term.lower() in low for term in config.get("risk_terms", [])):
        score += 2
    return score


class KeyedLog:
    """A small JSONL sidecar keyed by claim: deferrals, discussions."""

    def __init__(self, root: Path, filename: str):
        self.path = root / KM_DIR / filename
        self.records: dict[str, dict] = {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    rec = json.loads(line)
                    self.records[rec["key"]] = rec

    def put(self, key: str, **fields) -> dict:
        rec = {"key": key, **fields}
        self.records[key] = rec
        self.save()
        return rec

    def drop(self, key: str) -> None:
        if self.records.pop(key, None) is not None:
            self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        out = [json.dumps(self.records[k], ensure_ascii=False, sort_keys=True)
               for k in sorted(self.records)]
        self.path.write_text("\n".join(out) + ("\n" if out else ""), encoding="utf-8")


@dataclass
class QueueRow:
    risk: int
    status: str
    claim: Claim
    kind: str = "?"
    sampled: bool = False


def _sampled(claim: Claim, every: int) -> bool:
    """Deterministic one-in-N, so a wrong triage surfaces instead of hiding forever."""
    return every > 0 and int(claim.text_hash[:8], 16) % every == 0


def build_queue(claims: list[Claim], store: "Store", config: dict, wanted: set[str],
                deferrals: KeyedLog | None = None, today: str | None = None,
                ignored: KeyedLog | None = None, triage: KeyedLog | None = None,
                kinds: set[str] | None = None,
                sample_every: int = SAMPLE_EVERY) -> list[QueueRow]:
    """The review queue: what needs a person, ordered.

    Parsing enumerates; it has no idea what a sentence means. Judging what kind of sentence
    it is belongs to a model (`km triage`) or to you (`X` = not a claim) — never to a regex
    pretending to understand. A triaged kind only hides and orders; it never approves.
    """
    now = today or date.today().isoformat()
    kinds = kinds or {"norma"}
    rows: list[QueueRow] = []
    for claim in claims:
        if claim.is_question:
            continue
        if ignored and claim.key in ignored.records:
            continue
        if deferrals:
            rec = deferrals.records.get(claim.key)
            if rec and rec.get("until", "") > now:
                continue
        status = status_of(claim, store, today=now)
        if status not in wanted:
            continue

        kind, score, sampled = "?", risk(claim, config), False
        rec = triage.records.get(claim.key) if triage else None
        if rec and rec.get("text_hash") == claim.text_hash:  # stale triage is no triage
            kind = rec.get("kind", "?")
            if isinstance(rec.get("risk"), int):
                score = rec["risk"]
            if kind not in kinds:
                if not _sampled(claim, sample_every):
                    continue
                sampled = True
        rows.append(QueueRow(risk=score, status=status, claim=claim, kind=kind, sampled=sampled))
    return order_queue(rows)


def order_queue(rows: list[QueueRow]) -> list[QueueRow]:
    """Most risky first, taking turns between documents at the same risk level.

    Without the round robin, one long document owns the whole first page and the other
    documents are never seen.
    """
    out: list[QueueRow] = []
    for level in sorted({r.risk for r in rows}, reverse=True):
        by_file: dict[str, list[QueueRow]] = {}
        for row in rows:
            if row.risk == level:
                by_file.setdefault(row.claim.file, []).append(row)
        for bucket in by_file.values():
            bucket.sort(key=lambda r: r.claim.line)
        files = sorted(by_file)
        while any(by_file[f] for f in files):
            for f in files:
                if by_file[f]:
                    out.append(by_file[f].pop(0))
    return out


def _tokens(text: str) -> set[str]:
    out = set()
    for token in re.findall(r"[0-9]+(?:[.,][0-9]+)?%?|[a-zà-ÿ]{4,}", normalise(text)):
        if token not in STOPWORDS:
            out.add(token)
    return out


def _is_number(token: str) -> bool:
    return bool(re.fullmatch(r"[0-9]+(?:[.,][0-9]+)?%?", token))


def candidate_pairs(claims: list[Claim], store: "Store", limit_per_claim: int = 3,
                    min_shared: int = 2, min_ratio: float = 0.30,
                    today: str | None = None, triage: KeyedLog | None = None) -> list[dict]:
    """Claims that might contradict something already settled.

    Comparing everything against everything is 69k pairs for 372 claims, and pointless: what
    matters is whether a claim fights something you already approved. So the settled set is
    one side of every pair, and a cheap tf-idf overlap picks the candidates a model then
    judges. Mechanical here, judgement there — the same split as triage.

    The score is the **share** of the smaller claim's term mass that the two have in common,
    never an absolute sum. An absolute cut-off breaks in both directions, as measured: on a
    three-claim corpus nothing reaches it, and on a real one a long changelog paragraph
    matches everything it happens to overlap. Two shared words that are not numbers are
    required as well — bare digits pair a changelog with a decision and mean nothing.
    """
    import math

    def is_norm(claim: Claim) -> bool:
        if not triage:
            return True
        rec = triage.records.get(claim.key)
        if not rec or rec.get("text_hash") != claim.text_hash:
            return True  # not classified yet: better a false candidate than a missed clash
        return rec.get("kind") == "norma"

    live = [c for c in claims if not c.is_question and is_norm(c)]
    settled = [c for c in live if status_of(c, store, today=today) in ("approved", "to-validate")]
    if not settled:
        return []

    docs = {c.key: _tokens(c.text) for c in live}
    df: Counter[str] = Counter()
    for tokens in docs.values():
        df.update(tokens)
    n = len(docs) or 1
    idf = {token: math.log(n / (1 + count)) + 1 for token, count in df.items()}
    mass = {key: sum(idf[t] for t in tokens) or 1.0 for key, tokens in docs.items()}

    by_token: dict[str, list[Claim]] = {}
    for c in settled:
        for token in docs[c.key]:
            by_token.setdefault(token, []).append(c)

    settled_by_key = {c.key: c for c in settled}
    pairs: list[dict] = []
    for claim in live:
        if status_of(claim, store, today=today) in ("approved", "to-validate"):
            continue  # both sides settled is a different question: consistency of the base
        scored: dict[str, tuple[float, float, set[str]]] = {}
        for token in docs[claim.key]:
            for other in by_token.get(token, []):
                if other.key in scored or other.key == claim.key:
                    continue
                shared = docs[claim.key] & docs[other.key]
                if sum(1 for t in shared if not _is_number(t)) < min_shared:
                    continue
                shared_mass = sum(idf[t] for t in shared)
                ratio = shared_mass / min(mass[claim.key], mass[other.key])
                if ratio >= min_ratio:
                    scored[other.key] = (ratio, shared_mass, shared)
        best = sorted(scored.items(), key=lambda kv: -kv[1][0])[:limit_per_claim]
        for other_key, (ratio, shared_mass, shared) in best:
            other = settled_by_key[other_key]
            pairs.append({
                "key": claim.key, "against": other.key,
                "ratio": round(ratio, 2), "score": round(shared_mass, 1),
                "shared": sorted(t for t in shared if not _is_number(t))[:8],
                "text": claim.text, "file": claim.file, "line": claim.line,
                "against_text": other.text, "against_file": other.file,
                "against_line": other.line,
            })
    pairs.sort(key=lambda p: (-p["ratio"], -p["score"]))
    return pairs


def section_of(claim: Claim, claims: list[Claim]) -> list[Claim]:
    """The claims written next to this one, under the same heading of the same document.

    The unit of the record is the claim; the unit of reading is the section. A claim read
    alone was frequently meaningless, and related claims are decided together.
    """
    return [c for c in claims
            if c.file == claim.file and c.heading == claim.heading and not c.is_question]


def load_config(root: Path) -> dict:
    path = root / KM_DIR / CONFIG
    config = dict(DEFAULT_CONFIG)
    if path.exists():
        config.update(json.loads(path.read_text(encoding="utf-8")))
    return config


def save_listing(root: Path, keys: list[str]) -> None:
    d = root / KM_DIR
    d.mkdir(parents=True, exist_ok=True)
    (d / LISTING).write_text(json.dumps(keys, ensure_ascii=False), encoding="utf-8")


def load_listing(root: Path) -> list[str]:
    path = root / KM_DIR / LISTING
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))
