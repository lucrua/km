"""The chancel: a reviewed copy of each file, kept in a git ref.

`refs/km/chancela` holds every tracked file as it was last endorsed. Reviewing is
`git diff` against it; endorsing a passage is writing that passage into it. There is no
per-block identity, no anchor and no hash to maintain — the design and the measurements
behind it are in docs/chancel.md.

The ref is written with plumbing and never checked out, so the branch, the index and the
working tree are untouched by everything here. The one exception is `reverter`, which is
supposed to rewrite a file on disk.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

REF = "refs/km/chancela"

HEADING = re.compile(r"^(#{1,6})\s+(.*)$")

#: The writing convention, three marks, because each one changes what happens next.
#: They live in the document as blockquotes — an agent reads them with no tooling and a
#: human sees the reservation when opening the file, which no sidecar store achieves.
MARCAS = {
    "⚠": "sem certeza — entra na chancela e continua visível",
    "❓": "a confirmar — vira pendência com data",
    "🚫": "discordo — bloqueia a chancela deste trecho",
}
RESSALVA = re.compile(r"^\s*>.*?([⚠❓🚫])")
PRAZO = re.compile(r"(\d{4}-\d{2}-\d{2})")

ROW = re.compile(r"^\s*\|.*\|\s*$")
SEP = re.compile(r"^[\s:|-]+$")


# ---- git -----------------------------------------------------------------------------

def _git(root: Path, *args: str, entrada: str | None = None,
         env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, input=entrada,
                          capture_output=True, text=True, env=env)


def _ok(root: Path, *args: str, entrada: str | None = None, env: dict | None = None) -> str:
    r = _git(root, *args, entrada=entrada, env=env)
    if r.returncode != 0:
        raise SystemExit(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout


def existe(root: Path) -> bool:
    return _git(root, "rev-parse", "--verify", "--quiet", REF).returncode == 0


def arquivos(root: Path) -> list[str]:
    """Every file that has a chancel."""
    if not existe(root):
        return []
    return [l for l in _ok(root, "ls-tree", "-r", "--name-only", REF).splitlines() if l]


def chancelado(root: Path, rel: str) -> str | None:
    """The file as you last endorsed it, or None if it never had a chancel."""
    r = _git(root, "show", f"{REF}:{rel}")
    return r.stdout if r.returncode == 0 else None


def atual(root: Path, rel: str) -> str | None:
    p = root / rel
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8", errors="replace")


def escrever(root: Path, mudancas: dict[str, str | None], mensagem: str) -> str:
    """Advance the ref, with plumbing only.

    A temporary index file is used so that the repository's own index — which a routine
    `git add -A` from another session can forge — is never involved.
    """
    git_dir = Path(_ok(root, "rev-parse", "--absolute-git-dir").strip())
    indice = git_dir / "km-chancela-index"
    env = {**os.environ, "GIT_INDEX_FILE": str(indice)}
    try:
        if indice.exists():
            indice.unlink()
        pais: list[str] = []
        if existe(root):
            _ok(root, "read-tree", REF, env=env)
            pais = ["-p", REF]
        for rel, texto in mudancas.items():
            if texto is None:
                _ok(root, "update-index", "--force-remove", "--", rel, env=env)
                continue
            sha = _ok(root, "hash-object", "-w", "--stdin", entrada=texto).strip()
            _ok(root, "update-index", "--add", "--cacheinfo",
                f"100644,{sha},{rel}", env=env)
        arvore = _ok(root, "write-tree", env=env).strip()
        commit = _ok(root, "commit-tree", arvore, *pais, "-m", mensagem).strip()
        _ok(root, "update-ref", REF, commit)
        return commit
    finally:
        if indice.exists():
            indice.unlink()


def historico(root: Path, rel: str, trecho: "Trecho | None" = None,
              limite: int = 5) -> str:
    """When this passage last had a chancel — a per-passage answer, no per-passage storage."""
    if not existe(root):
        return ""
    if trecho is None or not trecho.titulo_bruto:
        return _ok(root, "log", f"-{limite}", "--format=%h %ad %s", "--date=short",
                   REF, "--", rel)
    faixa = f"/^{re.escape(trecho.titulo_bruto)}$/,/^#/:{rel}"
    r = _git(root, "log", f"-{limite}", "--format=%h %ad %s", "--date=short",
             "-L", faixa, REF)
    if r.returncode != 0:                       # -L is picky; the file log still answers
        return _ok(root, "log", f"-{limite}", "--format=%h %ad %s", "--date=short",
                   REF, "--", rel)
    return "\n".join(l for l in r.stdout.splitlines() if not l.startswith(("diff ", "---", "+++", "@@", "+", "-", " ")))


# ---- passages ------------------------------------------------------------------------

@dataclass
class Trecho:
    """A passage: a heading and everything under it, up to the next heading.

    Markdown's own structure, so nothing is written into the document. Nesting is not a
    boundary — it is the path, which is what `git log -L` delimits on.
    """

    titulo: str
    caminho: str
    linha: int          # 1-based, the heading line
    fim: int            # 1-based, exclusive
    texto: str
    titulo_bruto: str = ""

    @property
    def linhas(self) -> int:
        return self.fim - self.linha


def trechos(texto: str) -> list[Trecho]:
    linhas = texto.splitlines()
    cabecas = [(i, len(m.group(1)), m.group(2).strip(), linhas[i])
               for i, l in enumerate(linhas) if (m := HEADING.match(l))]
    out: list[Trecho] = []
    if not cabecas or cabecas[0][0] > 0:
        fim = cabecas[0][0] if cabecas else len(linhas)
        if any(l.strip() for l in linhas[:fim]):
            out.append(Trecho("(início do arquivo)", "(início do arquivo)", 1, fim + 1,
                              "\n".join(linhas[:fim])))
    pilha: list[tuple[int, str]] = []
    for n, (i, nivel, titulo, bruto) in enumerate(cabecas):
        fim = cabecas[n + 1][0] if n + 1 < len(cabecas) else len(linhas)
        while pilha and pilha[-1][0] >= nivel:
            pilha.pop()
        pilha.append((nivel, titulo))
        out.append(Trecho(titulo=titulo, caminho=" › ".join(t for _, t in pilha),
                          linha=i + 1, fim=fim + 1, texto="\n".join(linhas[i:fim]),
                          titulo_bruto=bruto))
    return out


def trecho_da_linha(ts: list[Trecho], linha: int) -> Trecho | None:
    """The passage a 1-based line falls into."""
    achado = None
    for t in ts:
        if t.linha <= linha < t.fim:
            achado = t
    return achado or (ts[-1] if ts and linha >= ts[-1].fim else None)


def normalise_md(texto: str) -> str:
    """Canonicalise a Markdown table so re-aligning it is not a change.

    It no longer protects a hash; it keeps a cosmetic re-alignment out of the diff.
    """
    out = []
    for linha in texto.splitlines():
        if ROW.match(linha):
            celulas = [c.strip() for c in linha.strip().strip("|").split("|")]
            if all(SEP.match(c or "-") for c in celulas):
                celulas = ["-" for _ in celulas]     # separator row: width is decoration
            out.append("|" + "|".join(celulas) + "|")
        else:
            out.append(linha)
    return "\n".join(out) + ("\n" if texto.endswith("\n") else "")


# ---- the diff, in passages -----------------------------------------------------------

@dataclass
class Hunk:
    """One change, as `git add -p` would offer it."""

    n: int
    i1: int
    i2: int
    j1: int
    j2: int
    antes: list[str]
    depois: list[str]
    titulo: str = ""
    caminho: str = ""
    linha: int = 1
    sumidas: list[str] = field(default_factory=list)   # caveats the change removes
    bloqueio: str = ""                                 # the 🚫 line holding it back

    @property
    def novo(self) -> bool:
        return not self.antes

    def resumo(self, largura: int = 60) -> str:
        alvo = self.depois or self.antes
        for l in alvo:
            t = " ".join(l.split())
            if t and not HEADING.match(l):
                return t[:largura - 1] + "…" if len(t) > largura else t
        return " ".join((alvo[0] if alvo else "").split())[:largura]


def hunks(antes: str, depois: str, juntar: int = 2) -> list[Hunk]:
    """The changes between the chancel and the file, grouped the way a reviewer reads them.

    Two changes separated by at most `juntar` untouched lines become one: asking twice about
    the same sentence is the fragmentation that made blocks-by-hunk unusable (measured:
    1.7 lines per hunk on a real repository).
    """
    a, b = antes.splitlines(), depois.splitlines()
    grupos: list[list[int]] = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        if grupos and i1 - grupos[-1][1] <= juntar and j1 - grupos[-1][3] <= juntar:
            grupos[-1][1], grupos[-1][3] = i2, j2
        else:
            grupos.append([i1, i2, j1, j2])

    ts = trechos(depois) or trechos(antes)
    out: list[Hunk] = []
    for n, (i1, i2, j1, j2) in enumerate(grupos, start=1):
        h = Hunk(n=n, i1=i1, i2=i2, j1=j1, j2=j2,
                 antes=a[i1:i2], depois=b[j1:j2], linha=j1 + 1)
        # A change that brings its own heading names itself; anything else belongs to the
        # passage it lands in. Without this an appended section is filed under the section
        # above it, which is where it starts but not what it is.
        proprio = next((m.group(2).strip() for l in h.depois if (m := HEADING.match(l))), "")
        t = trecho_da_linha(ts, j1 + 1)
        if proprio:
            t = next((x for x in ts if x.titulo == proprio and x.linha >= j1), t)
        if t:
            h.titulo, h.caminho = t.titulo, t.caminho
            h.bloqueio = bloqueio_de(t.texto)
        h.sumidas = sumidas(h.antes, h.depois)
        out.append(h)
    return out


def aplicar(antes: str, depois: str, escolhidos: set[int], hs: list[Hunk] | None = None) -> str:
    """The chancel you had, plus the changes you accepted. `git add -p`, in one function."""
    a, b = antes.splitlines(), depois.splitlines()
    hs = hs if hs is not None else hunks(antes, depois)
    out: list[str] = []
    i = 0
    for h in hs:
        out.extend(a[i:h.i1])
        out.extend(b[h.j1:h.j2] if h.n in escolhidos else a[h.i1:h.i2])
        i = h.i2
    out.extend(a[i:])
    texto = "\n".join(out)
    return texto + "\n" if texto and (depois.endswith("\n") or antes.endswith("\n")) else texto


# ---- the convention ------------------------------------------------------------------

def ressalvas(texto: str) -> list[tuple[int, str, str]]:
    """Every caveat in a text: (1-based line, mark, line)."""
    out = []
    for n, linha in enumerate(texto.splitlines(), start=1):
        m = RESSALVA.match(linha)
        if m:
            out.append((n, m.group(1), linha.strip()))
    return out


def sumidas(antes: list[str], depois: list[str]) -> list[str]:
    """Caveats the change removes.

    An agent rewrites the paragraph and drops the reservation. Nothing lies, and the tool
    would see a fully endorsed passage — so this specific change gets its own mark instead
    of travelling with ordinary edits.
    """
    tinha = [l.strip() for l in antes if RESSALVA.match(l)]
    ficou = {l.strip() for l in depois if RESSALVA.match(l)}
    return [l for l in tinha if l not in ficou]


def bloqueio_de(texto: str) -> str:
    for _, marca, linha in ressalvas(texto):
        if marca == "🚫":
            return linha
    return ""


def vencidas(texto: str, hoje: str | None = None) -> list[tuple[int, str, str]]:
    """`❓ a confirmar até AAAA-MM-DD` whose date has passed."""
    agora = hoje or date.today().isoformat()
    out = []
    for n, marca, linha in ressalvas(texto):
        if marca != "❓":
            continue
        m = PRAZO.search(linha)
        if m and m.group(1) < agora:
            out.append((n, m.group(1), linha))
    return out


# ---- what is pending -----------------------------------------------------------------

@dataclass
class Situacao:
    """One file, against its chancel."""

    arquivo: str
    tem_chancela: bool
    antes: str
    depois: str
    hunks: list[Hunk]
    vencidas: list[tuple[int, str, str]]

    @property
    def em_dia(self) -> bool:
        return self.tem_chancela and not self.hunks


def situacao(root: Path, rel: str, hoje: str | None = None) -> Situacao:
    antes = chancelado(root, rel)
    depois = atual(root, rel) or ""
    base = normalise_md(antes) if antes is not None else ""
    agora = normalise_md(depois)
    return Situacao(arquivo=rel, tem_chancela=antes is not None, antes=base, depois=agora,
                    hunks=hunks(base, agora), vencidas=vencidas(depois, hoje))


def estados(s: Situacao) -> list[dict]:
    """Passage by passage, for a review surface: what stands, what moved, what is new.

    Compared by heading path against the chancelled copy, at read time. Nothing is stored
    per passage; the path is recomputed on both sides, exactly as `git log -L` delimits.
    """
    novos = trechos(s.depois)
    velhos: dict[str, list[Trecho]] = {}
    for t in trechos(s.antes) if s.tem_chancela else []:
        velhos.setdefault(t.caminho, []).append(t)
    vistos: dict[str, int] = {}

    out = []
    for t in novos:
        i = vistos.get(t.caminho, 0)
        vistos[t.caminho] = i + 1
        iguais = velhos.get(t.caminho, [])
        antigo = iguais[i] if i < len(iguais) else (iguais[0] if iguais else None)
        if not s.tem_chancela or antigo is None:
            estado = "sem chancela"
        elif antigo.texto.strip() == t.texto.strip():
            estado = "com chancela"
        else:
            estado = "mexido"
        meus = [h for h in s.hunks
                if h.j1 <= t.fim - 1 and max(h.j2, h.j1 + 1) > t.linha - 1]
        out.append({
            "file": s.arquivo, "heading": t.titulo, "path": t.caminho,
            "line": t.linha, "lines": t.linhas, "state": estado,
            "hunks": [h.n for h in meus],
            "blocked": bloqueio_de(t.texto),
            "caveats": [{"mark": m, "line": t.linha + n - 1, "text": l}
                        for n, m, l in ressalvas(t.texto)],
            "dropped": [l for h in meus for l in h.sumidas],
        })
    return out
