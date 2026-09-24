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
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")

#: The writing convention: three marks, each one a line of its own, a blockquote in the
#: document itself — an agent reads them with no tooling and a human sees them when opening
#: the file, which no sidecar store achieves. The forms are exact so they can be grepped:
#: ❓ to_validate carries a deadline, 📌 to_do the day it was written and is meant for an
#: agent to find and address, 💬 comment is for whoever reads the passage later.
MARCAS = {
    "to_validate": re.compile(r"^> ❓ \*\*to_validate by (\d{4}-\d{2}-\d{2})\*\* — (.+)$"),
    "to_do": re.compile(r"^> 📌 \*\*to_do · (\d{4}-\d{2}-\d{2})\*\* — (.+)$"),
    "comment": re.compile(r"^> 💬 ()(\S.*)$"),
}
#: What the surfaces write for you to replace; left as is, `km lint` reports it.
PLACEHOLDER = "add your comment here"

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
    """Advance the ref, with plumbing only: each path gets this text, or leaves (None)."""
    def aplicar(env: dict) -> None:
        for rel, texto in mudancas.items():
            if texto is None:
                _ok(root, "update-index", "--force-remove", "--", rel, env=env)
                continue
            sha = _ok(root, "hash-object", "-w", "--stdin", entrada=texto).strip()
            _ok(root, "update-index", "--add", "--cacheinfo",
                f"100644,{sha},{rel}", env=env)
    return _avancar(root, aplicar, mensagem)


def mover(root: Path, pares: dict[str, str], mensagem: str) -> str:
    """Re-key chancelled files to new paths, in one commit on the ref.

    The blob is carried as it is, not read and written back as text, so the chancel of a
    moved file is byte for byte the chancel it had.
    """
    def aplicar(env: dict) -> None:
        for de, para in pares.items():
            sha = _ok(root, "rev-parse", f"{REF}:{de}").strip()
            _ok(root, "update-index", "--force-remove", "--", de, env=env)
            _ok(root, "update-index", "--add", "--cacheinfo", f"100644,{sha},{para}", env=env)
    return _avancar(root, aplicar, mensagem)


def _avancar(root: Path, aplicar, mensagem: str) -> str:
    """A commit on the ref: its tree, changed by `aplicar`, with the previous one as parent.

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
        aplicar(env)
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


def pendencia_do_arquivo(s: "Situacao") -> tuple[int, int]:
    """(characters to decide, characters in the file). A file never chancelled is all of it."""
    if not s.tem_chancela:
        n = _conta(s.depois)
        return n, n
    return pendencia(s.antes, s.depois, s.mudancas)


def unidades_por_sha(ms: list[Mudanca], shas: set[str]) -> list[Unidade]:
    return [u for m in ms for u in m.unidades if u.sha in shas]


# ---- the convention ------------------------------------------------------------------

@dataclass
class Marca:
    linha: int                  # 1-based
    tipo: str                   # to_validate · to_do · comment
    data: str                   # the deadline, the day it was written, or "" for a comment
    texto: str
    cru: str                    # the whole line, as in the file

    @property
    def placeholder(self) -> bool:
        return self.texto.strip() == PLACEHOLDER


def marca_da_linha(linha: str, n: int = 0) -> Marca | None:
    for tipo, rx in MARCAS.items():
        m = rx.match(linha)
        if m and m.group(2).strip():
            return Marca(linha=n, tipo=tipo, data=m.group(1), texto=m.group(2).strip(), cru=linha)
    return None


def marcas(texto: str) -> list[Marca]:
    """Every mark in a text, in the order it appears."""
    out = []
    for n, linha in enumerate(texto.splitlines(), start=1):
        m = marca_da_linha(linha, n)
        if m:
            out.append(m)
    return out


def sumidas(antes: list[str], depois: list[str]) -> list[str]:
    """Marks the change removes.

    An agent rewrites the paragraph and drops the mark. Nothing lies, and the tool would see
    a fully endorsed passage — so this specific change gets its own flag instead of
    travelling with ordinary edits.
    """
    # Reescrever a marca — trocar a data, afinar o texto — não é removê-la, e a mudança já
    # aparece no diff. O que precisa de aviso próprio é o tipo de marca que sumiu do bloco.
    ficaram = {m.tipo for m in (marca_da_linha(l) for l in depois) if m}
    return [m.cru.strip() for m in (marca_da_linha(l) for l in antes)
            if m and m.tipo not in ficaram]


def vencidas(texto: str, hoje: str | None = None) -> list[tuple[int, str, str]]:
    """❓ to_validate whose deadline is before today (the local date)."""
    agora = hoje or date.today().isoformat()
    return [(m.linha, m.data, m.cru) for m in marcas(texto)
            if m.tipo == "to_validate" and m.data < agora]


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


# ---- writing in the document ---------------------------------------------------------
#
# Two writes, both asked for explicitly: putting back text you had chancelled, and saving a
# passage you edited in the panel — the marks go in that way, as text. Everything else
# `km` does is read-only.

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
