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

import fnmatch
import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

REF = "refs/km/chancela"
KM_DIR = ".km"
CONFIG = "config.json"

#: Which files the chancel covers. Opt-in: a document outside `include` never appears.
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
}

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


def conteudo_em(root: Path, rev: str, rel: str) -> str | None:
    """The file as it was in any revision — a branch, a tag, a commit, or the chancel."""
    r = _git(root, "show", f"{rev}:{rel}")
    return r.stdout if r.returncode == 0 else None


def revisoes(root: Path, limite: int = 15) -> list[dict]:
    """What you can compare against: the chancel, the branches, the last commits."""
    out = [{"rev": REF, "label": "a chancela", "tipo": "chancela"}] if existe(root) else []
    for linha in _ok(root, "for-each-ref", "--sort=-committerdate",
                     "--format=%(refname:short)", "refs/heads").splitlines():
        if linha.strip():
            out.append({"rev": linha.strip(), "label": linha.strip(), "tipo": "branch"})
    for linha in _ok(root, "log", f"-{limite}", "--format=%h\t%ad\t%s",
                     "--date=short", "HEAD").splitlines():
        if not linha.strip():
            continue
        sha, data, assunto = linha.split("\t", 2)
        out.append({"rev": sha, "label": f"{sha} · {data} · {assunto[:48]}", "tipo": "commit"})
    return out


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


# ---- the diff, in Markdown blocks -----------------------------------------------------
#
# The unit you approve is a Markdown block: a paragraph, a list item, a table, a heading,
# a quote, a code fence. Nobody needs to approve half a paragraph, and a line diff kept
# offering exactly that. A *change* is a run of blocks that differ, between two runs that
# do not; it is what the page shows as one row, and it can be approved whole or block by
# block.

CERCA_MD = re.compile(r"^\s*(```|~~~)")
ITEM_MD = re.compile(r"^\s*(?:[-*+]|\d{1,3}[.)])\s+")
REGUA_MD = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
TABELA_MD = re.compile(r"^\s*\|")
CITACAO_MD = re.compile(r"^\s*>")


def _abre_bloco(linha: str) -> bool:
    return bool(HEADING.match(linha) or CERCA_MD.match(linha) or ITEM_MD.match(linha)
                or REGUA_MD.match(linha) or TABELA_MD.match(linha)
                or CITACAO_MD.match(linha))


@dataclass
class Bloco:
    """One Markdown block, with the blank lines that follow it kept apart."""

    tipo: str           # titulo · paragrafo · item · tabela · citacao · codigo · regua
    texto: str          # the block's own lines, no trailing blank lines
    cru: str            # the same plus the blank lines after it — for exact reassembly
    linha: int          # 1-based
    fim: int            # 1-based, exclusive, of `texto`

    @property
    def chave(self) -> str:
        """What counts as the same block: a re-aligned table is the same table."""
        return normalise_md(self.texto).strip()


def blocos(texto: str) -> tuple[str, list[Bloco]]:
    """Split a document into blocks. Returns the leading blank lines and the blocks."""
    linhas = texto.splitlines(keepends=True)
    n = len(linhas)
    vazia = lambda i: not linhas[i].strip()
    i = 0
    while i < n and vazia(i):
        i += 1
    prefixo = "".join(linhas[:i])
    out: list[Bloco] = []
    while i < n:
        ini, l = i, linhas[i]
        if CERCA_MD.match(l):
            tipo, i = "codigo", i + 1
            while i < n and not CERCA_MD.match(linhas[i]):
                i += 1
            i = min(i + 1, n)
        elif HEADING.match(l):
            tipo, i = "titulo", i + 1
        elif REGUA_MD.match(l):
            tipo, i = "regua", i + 1
        elif TABELA_MD.match(l):
            tipo, i = "tabela", i + 1
            while i < n and TABELA_MD.match(linhas[i]):
                i += 1
        elif CITACAO_MD.match(l):
            tipo, i = "citacao", i + 1
            while i < n and CITACAO_MD.match(linhas[i]):
                i += 1
        elif ITEM_MD.match(l):
            tipo, i = "item", i + 1
            while i < n and not vazia(i) and not _abre_bloco(linhas[i]):
                i += 1
        else:
            tipo, i = "paragrafo", i + 1
            while i < n and not vazia(i) and not _abre_bloco(linhas[i]):
                i += 1
        fim = i
        while i < n and vazia(i):
            i += 1
        out.append(Bloco(tipo=tipo, texto="".join(linhas[ini:fim]).rstrip("\n"),
                         cru="".join(linhas[ini:i]), linha=ini + 1, fim=fim + 1))
    return prefixo, out


@dataclass
class Unidade:
    """One block that changed: new, gone, or edited. The smallest thing you approve."""

    id: str                     # "2.1": change 2, block 1
    tipo: str                   # novo · sumiu · mexido
    antes: Bloco | None
    depois: Bloco | None
    titulo: str = ""
    sumidas: list[str] = field(default_factory=list)
    bloqueio: str = ""

    @property
    def sha(self) -> str:
        """Identifies this change by its content, not its position: a page that asks to
        approve "2.1" after the file moved would approve something else."""
        a = self.antes.texto if self.antes else ""
        d = self.depois.texto if self.depois else ""
        return sha_do(a + "\x00" + d)

    def resumo(self, largura: int = 60) -> str:
        b = self.depois or self.antes
        t = " ".join(b.texto.split()) if b else ""
        return t[:largura - 1] + "…" if len(t) > largura else t


@dataclass
class Mudanca:
    """A run of changed blocks between two runs of unchanged ones: one row on the page."""

    n: int
    unidades: list[Unidade]
    titulo: str
    caminho: str
    linha: int                  # where it sits in the file today, 1-based
    fim: int

    @property
    def sumidas(self) -> list[str]:
        return [s for u in self.unidades for s in u.sumidas]

    @property
    def bloqueio(self) -> str:
        return next((u.bloqueio for u in self.unidades if u.bloqueio), "")

    def contagem(self) -> tuple[int, int]:
        return (sum(1 for u in self.unidades if u.antes),
                sum(1 for u in self.unidades if u.depois))


def _parecido(a: str, b: str, piso: float) -> float:
    """How alike two blocks are, cheaply: the upper bounds first, and line by line when
    the blocks are large — a table compared character by character costs seconds."""
    if max(len(a), len(b)) <= 2000:
        sm = SequenceMatcher(None, a, b, autojunk=False)
    elif min(a.count("\n"), b.count("\n")) >= 10:
        # muitas linhas — uma tabela: compara linha a linha
        sm = SequenceMatcher(None, a.splitlines(), b.splitlines(), autojunk=False)
    else:
        # um parágrafo longo numa linha só: palavra a palavra, que é barato e diz o certo
        sm = SequenceMatcher(None, PALAVRA.findall(a), PALAVRA.findall(b))
    if sm.real_quick_ratio() < piso or sm.quick_ratio() < piso:
        return 0.0
    return sm.ratio()


def _parear(velhos: list[Bloco], novos: list[Bloco], corte: float = 0.45) -> list[tuple]:
    """Which old block became which new one, in reading order.

    Pairing by similarity, not position: two unrelated paragraphs in the same place are one
    that left and one that arrived, not an "edit" to be read word by word.
    """
    usados: set[int] = set()
    casos: dict[int, int] = {}
    for j, nb in enumerate(novos):
        melhor, nota = None, corte
        for i, vb in enumerate(velhos):
            # Só se casa bloco do mesmo tipo: um parágrafo que "virou" título porque os dois
            # começam com a mesma palavra é um que saiu e outro que entrou.
            if i in usados or vb.tipo != nb.tipo:
                continue
            r = _parecido(vb.texto, nb.texto, nota)
            if r >= nota:
                melhor, nota = i, r
        if melhor is not None:
            usados.add(melhor)
            casos[j] = melhor
    saida, pos = [], 0
    for j, nb in enumerate(novos):
        alvo = casos.get(j)
        limite = alvo if alvo is not None else len(velhos)
        while pos < limite:
            if pos not in usados:
                saida.append(("sumiu", velhos[pos], None))
            pos += 1
        if alvo is not None:
            saida.append(("mexido", velhos[alvo], nb))
            pos = alvo + 1
        else:
            saida.append(("novo", None, nb))
    while pos < len(velhos):
        if pos not in usados:
            saida.append(("sumiu", velhos[pos], None))
        pos += 1
    return saida


def _alinhar(antes: str, depois: str):
    """The block-level alignment both `mudancas` and `aplicar` walk — computed once, the
    same way, so an id means the same block to both."""
    pa, ba = blocos(antes)
    pd, bd = blocos(depois)
    sm = SequenceMatcher(None, [b.chave for b in ba], [b.chave for b in bd], autojunk=False)
    return pd, ba, bd, sm.get_opcodes()


def mudancas(antes: str, depois: str) -> list[Mudanca]:
    pd, ba, bd, ops = _alinhar(antes, depois)
    ts = trechos(depois) or trechos(antes)
    out: list[Mudanca] = []
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            continue
        n = len(out) + 1
        linha = bd[j1].linha if j1 < len(bd) else (bd[-1].fim if bd else 1)
        fim = bd[j2 - 1].fim if j2 > j1 else linha
        t = trecho_da_linha(ts, linha) if ts else None
        unidades = []
        for k, (tipo, vb, nb) in enumerate(_parear(ba[i1:i2], bd[j1:j2]), start=1):
            u = Unidade(id=f"{n}.{k}", tipo=tipo, antes=vb, depois=nb)
            onde = trecho_da_linha(ts, nb.linha if nb else linha) if ts else None
            u.titulo = onde.titulo if onde else ""
            u.bloqueio = bloqueio_de(onde.texto) if onde else ""
            u.sumidas = sumidas(vb.texto.splitlines() if vb else [],
                                nb.texto.splitlines() if nb else [])
            unidades.append(u)
        # A change that opens with its own heading names itself; otherwise it is named by
        # the section it starts in, even if it runs on into the next one.
        primeiro = unidades[0].depois if unidades else None
        proprio = (primeiro.texto.lstrip("# ").strip()
                   if primeiro is not None and primeiro.tipo == "titulo" else "")
        out.append(Mudanca(n=n, unidades=unidades,
                           titulo=proprio or (t.titulo if t else ""),
                           caminho=t.caminho if t else "", linha=linha, fim=fim))
    return out


def aplicar(antes: str, depois: str, escolhidas: set[str],
            parciais: dict[str, tuple[int, int, bool]] | None = None) -> str:
    """The chancel you had, plus the blocks you accepted. `git add -p`, by block.

    `escolhidas` holds unit ids ("2.1") or whole changes ("2"). Unchanged blocks and
    accepted ones come from today's file byte for byte, so accepting everything gives
    exactly the file; refused ones keep the chancel's text.
    """
    pd, ba, bd, ops = _alinhar(antes, depois)
    partes = [pd]
    n = 0
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            partes += [b.cru for b in bd[j1:j2]]
            continue
        n += 1
        for k, (tipo, vb, nb) in enumerate(_parear(ba[i1:i2], bd[j1:j2]), start=1):
            uid = f"{n}.{k}"
            if parciais and uid in parciais and nb is not None:
                # Parte de um bloco: só as mudanças dentro da seleção — aceitas, se é a
                # chancela que se escreve; desfeitas, se é o arquivo.
                ini, fim, aceitar = parciais[uid]
                texto = mesclar(vb.texto if vb else "", nb.texto, ini, fim, aceitar)
                if texto.strip():
                    resto = nb.cru[len(nb.texto):] if nb.cru.startswith(nb.texto) else "\n"
                    partes.append(texto + resto)
                continue
            aceita = uid in escolhidas or str(n) in escolhidas
            escolhido = nb if aceita else vb
            if escolhido is not None:
                partes.append(escolhido.cru)
    texto = ""
    for p in partes:
        if texto and p and not texto.endswith("\n"):
            texto += "\n"           # nunca colar duas linhas ao misturar os dois lados
        texto += p
    return texto


PALAVRA = re.compile(r"\d{4}-\d{2}-\d{2}|\s+|\w+|[^\w\s]")


def mesclar(a: str, b: str, ini: int, fim: int, aceitar: bool = True) -> str:
    """Take part of an edit: the changes that fall inside [ini, fim) of the new text.

    Like staging half a hunk in a code review, at the grain of a word — a selection that
    touches part of a word takes the whole word, because a word half-changed is not a
    sentence anyone wrote. With `aceitar`, the selected changes are applied to the old
    text (what goes into the chancel); without it, they are undone in the new text (what
    goes back into the file).
    """
    pa, pb = PALAVRA.findall(a), PALAVRA.findall(b)
    out, pos = [], 0
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, pa, pb, autojunk=False).get_opcodes():
        ta = "".join(pa[i1:i2])
        if tag == "equal":
            tb = "".join(pb[j1:j2])
            out.append(tb)
            pos += len(tb)
            continue
        if j1 == j2:                                    # só saiu: decide pela posição
            dentro = ini <= pos <= fim
            out.append("" if dentro == aceitar else ta)
            continue
        # Uma troca é decidida palavra a palavra: o que saiu vai junto com a primeira palavra
        # que entrou no lugar, e cada palavra seguinte é uma inclusão por si. Sem isso,
        # "horas úteis" → "dias corridos, sempre" seria uma peça só, e aceitar "dias
        # corridos" levaria ", sempre" junto.
        for k, grupo in enumerate(_grupos(pb[j1:j2])):
            dentro = pos < fim and pos + len(grupo) > ini
            if k == 0:
                out.append(grupo if dentro == aceitar else ta)
            else:
                out.append(grupo if dentro == aceitar else "")
            pos += len(grupo)
    return "".join(out)


def _grupos(tokens: list[str]) -> list[str]:
    """Words with the spaces around them: a space is never decided on its own, or taking
    "vigente" would leave "vigentedo" behind."""
    grupos: list[str] = []
    for tok in tokens:
        if tok.isspace() and grupos and not grupos[-1].isspace():
            grupos[-1] += tok
        elif grupos and grupos[-1].isspace():
            grupos[-1] += tok
        else:
            grupos.append(tok)
    return grupos


def _conta(texto: str) -> int:
    return sum(1 for c in texto if not c.isspace())


def pendencia(antes: str, depois: str, ms: list["Mudanca"] | None = None) -> tuple[int, int]:
    """How much of the file still needs you: (characters to decide, characters in the file).

    Counted in characters that changed, not in blocks or changes — a one-word fix and a new
    section are not "one change" each. The denominator is the file as it is today, which is
    what the chancel would hold if everything were approved. Whitespace does not count.
    """
    ms = ms if ms is not None else mudancas(antes, depois)
    pend = 0
    for u in (u for m in ms for u in m.unidades):
        if u.tipo == "novo":
            pend += _conta(u.depois.texto)
        elif u.tipo == "sumiu":
            pend += _conta(u.antes.texto)
        else:
            pend += _mudou(u.antes.texto, u.depois.texto)
    return pend, _conta(depois)


def _mudou(a: str, b: str) -> int:
    """Characters that differ between two versions of one block.

    Line first, then words inside the lines that changed: a table is one block, and
    comparing a thousand-row table word by word is quadratic — it took the page from half a
    second to twenty.
    """
    la, lb = a.splitlines(), b.splitlines()
    total = 0
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, la, lb, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        va, vb = "\n".join(la[i1:i2]), "\n".join(lb[j1:j2])
        if tag != "replace":
            total += _conta(va) + _conta(vb)
            continue
        pa, pb = PALAVRA.findall(va), PALAVRA.findall(vb)
        # Em textos longos, o espaço e a vírgula são "populares" e o difflib os põe de lado
        # (autojunk) — para contar o que mudou isso não altera nada e evita o custo quadrático.
        for t2, x1, x2, y1, y2 in SequenceMatcher(None, pa, pb,
                                                  autojunk=len(pa) + len(pb) > 400).get_opcodes():
            if t2 != "equal":
                total += _conta("".join(pa[x1:x2])) + _conta("".join(pb[y1:y2]))
    return total


def percentual(pend: int, total: int) -> str:
    """"12%", or "<1%" — a file with something to decide never reads as 0%."""
    if not pend:
        return "0%"
    if not total:
        return "100%"
    v = min(100.0, 100.0 * pend / total)
    return "<1%" if v < 1 else f"{v:.0f}%"


def unidades_por_sha(ms: list[Mudanca], shas: set[str]) -> list[Unidade]:
    return [u for m in ms for u in m.unidades if u.sha in shas]


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
    def marca(linha: str) -> str:
        m = RESSALVA.match(linha)
        return m.group(1) if m else ""

    # Reescrever a ressalva — trocar a data, afinar a dúvida — não é removê-la, e a
    # mudança já aparece no diff. O que precisa de marca própria é a marca que sumiu.
    ficaram = {marca(l) for l in depois if RESSALVA.match(l)}
    return [l.strip() for l in antes if RESSALVA.match(l) and marca(l) not in ficaram]


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
    """One file, against its chancel.

    `antes` and `depois` are the texts as they are — the chancel's and the file's. The
    canonical form that makes a re-aligned table the same table is used to decide what
    moved, and never to write: writing it would reformat the author's file.
    """

    arquivo: str
    tem_chancela: bool
    antes: str
    depois: str
    mudancas: list[Mudanca]
    vencidas: list[tuple[int, str, str]]

    @property
    def em_dia(self) -> bool:
        return self.tem_chancela and not self.mudancas

    @property
    def unidades(self) -> list[Unidade]:
        return [u for m in self.mudancas for u in m.unidades]


def situacao(root: Path, rel: str, hoje: str | None = None,
             base: str | None = None) -> Situacao:
    """The file against its chancel — or against any other revision, to read it side by side.

    The verdicts always act on the chancel; `base` only changes what you are comparing with.
    """
    antes = chancelado(root, rel) if base in (None, REF) else conteudo_em(root, base, rel)
    depois = atual(root, rel) or ""
    return Situacao(arquivo=rel, tem_chancela=antes is not None, antes=antes or "",
                    depois=depois, mudancas=mudancas(antes or "", depois),
                    vencidas=vencidas(depois, hoje))


# ---- which files ---------------------------------------------------------------------

def load_config(root: Path) -> dict:
    config = dict(DEFAULT_CONFIG)
    path = root / KM_DIR / CONFIG
    if path.exists():
        config.update(json.loads(path.read_text(encoding="utf-8")))
    return config


def _casa(rel: str, padroes: list[str]) -> bool:
    return any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch("/" + rel, p) for p in padroes)


def documentos(root: Path, config: dict | None = None) -> list[str]:
    """The documents this repository opted in, plus anything that already has a chancel."""
    config = config if config is not None else load_config(root)
    achados = []
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root).as_posix()
        if _casa(rel, config.get("exclude", [])):
            continue
        if config.get("include") and not _casa(rel, config["include"]):
            continue
        achados.append(rel)
    return sorted(set(achados) | set(arquivos(root)))


# ---- writing in the document ---------------------------------------------------------
#
# Two writes, both asked for explicitly: putting back text you had chancelled, and writing
# a reservation in the agreed form. Everything else `km` does is read-only.

def marca_da(marca: str) -> str:
    return {"⚠️": "⚠️ **sem certeza** — ",
            "❓": "❓ **a confirmar até {prazo}** — ",
            "🚫": "🚫 **discordo** — "}.get(marca, "")


def linha_de_marca(marca: str, texto: str, prazo: str | None = None) -> str:
    """The reservation, in the agreed form. The surface writes it so nobody has to remember
    it — the only reason a convention survives contact with a Tuesday."""
    return "> " + marca_da(marca).format(prazo=prazo or "") + texto.strip()


def inserir_apos(root: Path, rel: str, linha: int, bloco: str) -> bool:
    """Insert a block after line `linha` (1-based; 0 is the top), as a block of its own.

    Blank lines on both sides, always: a reservation glued to a quote above it would become
    part of that quote, and the change it annotates would no longer be the same change.
    """
    texto = atual(root, rel)
    if texto is None:
        return False
    linhas = texto.splitlines()
    linha = max(0, min(linha, len(linhas)))
    antes, depois = linhas[:linha], linhas[linha:]
    while antes and not antes[-1].strip():
        antes.pop()
    while depois and not depois[0].strip():
        depois.pop(0)
    novas = antes + ([""] if antes else []) + bloco.splitlines() + ([""] + depois if depois else [])
    (root / rel).write_text("\n".join(novas) + "\n", encoding="utf-8")
    return True


def sha_do(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:12]


class Conflito(Exception):
    """The text you edited is no longer in the file: someone else got there first."""

    def __init__(self, atual: str):
        super().__init__("o texto mudou desde que você abriu")
        self.atual = atual


def substituir_texto(root: Path, rel: str, original: str, novo: str, linha: int) -> None:
    """Save an edited stretch of the file, located by what it said, not where it was.

    An agent inserting a line at the top moves every line below; anchoring by position
    would then write your paragraph over someone else's. The original text is searched
    for, the occurrence nearest to where you saw it wins, and if it is not there any more
    the save is refused and both versions are shown. There is no blind overwrite.
    """
    texto = atual(root, rel)
    if texto is None:
        raise FileNotFoundError(rel)
    linhas = texto.splitlines()
    alvo = original.rstrip("\n").splitlines()
    k = len(alvo)
    achados = [i for i in range(len(linhas) - k + 1) if linhas[i:i + k] == alvo] if k else []
    if not achados:
        ini = max(0, linha - 1)
        raise Conflito("\n".join(linhas[ini:ini + max(k, 1)]))
    i = min(achados, key=lambda x: abs(x - (linha - 1)))
    novas = linhas[:i] + novo.rstrip("\n").splitlines() + linhas[i + k:]
    (root / rel).write_text("\n".join(novas) + "\n", encoding="utf-8")
