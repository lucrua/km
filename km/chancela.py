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
import random
import re
import subprocess
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

REF = "refs/km/chancela"
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")

#: The writing convention: two marks, each one a line of its own, a blockquote in the
#: document itself — an agent reads them with no tooling and a human sees them when opening
#: the file, which no sidecar store achieves. The forms are exact so they can be grepped:
#: 📌 to_do is a review point the author leaves for an agent, with the day it was written;
#: 💬 comment is a caveat on the passage before it, for whoever reads it later.
MARCAS = {
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
    # Um repositório recém-criado ainda não tem HEAD: sem commits para listar, não um erro.
    tem_head = _git(root, "rev-parse", "--verify", "--quiet", "HEAD").returncode == 0
    log = _ok(root, "log", f"-{limite}", "--format=%h\t%ad\t%s",
              "--date=short", "HEAD") if tem_head else ""
    for linha in log.splitlines():
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
    return _avancar(root, aplicar, mensagem, list(mudancas))


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
    return _avancar(root, aplicar, mensagem, [*pares, *pares.values()])


class NaoDesfaz(Exception):
    """That approval cannot be undone as it stands: the file was approved again since."""


def _blob(root: Path, rev: str, rel: str) -> str | None:
    r = _git(root, "rev-parse", "--verify", "--quiet", f"{rev}:{rel}")
    return r.stdout.strip() if r.returncode == 0 else None


def desfazer(root: Path, rel: str, commit: str, mensagem: str) -> str:
    """Undo one approval of `rel`: its chancel goes back to what it was before `commit`.

    A new commit on the ref, not a rewind — approvals of other files made after it stay,
    and the history keeps both. Only if the file's chancel is still exactly what `commit`
    left: if it was approved again since, undoing this one would throw that one away too,
    so the later one has to be undone first. The file on disk is not touched.
    """
    if not existe(root) or _git(root, "merge-base", "--is-ancestor", commit, REF).returncode:
        raise NaoDesfaz(f"{commit[:8]} não é uma aprovação da chancela")
    deixou = _blob(root, commit, rel)
    tinha = _blob(root, f"{commit}^", rel)
    if deixou == tinha:
        raise NaoDesfaz(f"{commit[:8]} não aprovou nada em {rel}")
    if _blob(root, REF, rel) != deixou:
        raise NaoDesfaz(f"{rel} foi aprovado de novo depois — desfaça a aprovação mais nova antes")

    def aplicar(env: dict) -> None:
        if tinha is None:
            _ok(root, "update-index", "--force-remove", "--", rel, env=env)
        else:
            _ok(root, "update-index", "--add", "--cacheinfo", f"100644,{tinha},{rel}", env=env)
    return _avancar(root, aplicar, mensagem, [rel])


class Concorrencia(Exception):
    """Another approval of the same file reached the ref while this one was being written."""


def _ref_em(root: Path) -> str | None:
    r = _git(root, "rev-parse", "--verify", "--quiet", REF)
    return r.stdout.strip() if r.returncode == 0 else None


def _avancar(root: Path, aplicar, mensagem: str, caminhos: list[str]) -> str:
    """A commit on the ref: its tree, changed by `aplicar`, with the previous one as parent.

    A temporary index file is used so that the repository's own index — which a routine
    `git add -A` from another session can forge — is never involved. It has a name of its
    own per call: two approvals at once, from two tabs or two worktrees, would otherwise
    build their trees in the same file.

    The ref only moves if it still points where it was read (`update-ref` with the old
    value). If another approval got there first and touched none of `caminhos`, this one is
    rebuilt on top of it; if it touched one of them, what `aplicar` writes was worked out
    from a chancel that no longer exists, and it is refused rather than written over.
    """
    git_dir = Path(_ok(root, "rev-parse", "--absolute-git-dir").strip())
    indice = git_dir / f"km-chancela-index-{os.getpid()}-{os.urandom(4).hex()}"
    env = {**os.environ, "GIT_INDEX_FILE": str(indice)}
    lido = _ref_em(root)
    for tentativa in range(30):
        try:
            pais: list[str] = []
            if lido:
                _ok(root, "read-tree", lido, env=env)
                pais = ["-p", lido]
            aplicar(env)
            arvore = _ok(root, "write-tree", env=env).strip()
            commit = _ok(root, "commit-tree", arvore, *pais, "-m", mensagem).strip()
            r = _git(root, "update-ref", REF, commit, lido or "0" * len(commit))
            if r.returncode == 0:
                return commit
        finally:
            if indice.exists():
                indice.unlink()
        agora = _ref_em(root)
        # O ref no mesmo lugar e sem trava de outro: não foi corrida, é outro erro do git.
        if agora == lido and "lock" not in r.stderr:
            raise SystemExit(f"git update-ref {REF}: {r.stderr.strip()}")
        if any((_blob(root, lido, c) if lido else None) != (_blob(root, agora, c) if agora else None)
               for c in caminhos):
            raise Concorrencia("o arquivo foi aprovado em outro lugar ao mesmo tempo —"
                               " a tela foi atualizada, confira e aprove de novo")
        lido = agora
        time.sleep(random.uniform(0.005, 0.03) * (1 + tentativa))   # quem perdeu dá a vez
    raise Concorrencia("a chancela não parou de mudar enquanto eu gravava — tente de novo")


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
    that left and one that arrived, not an "edit" to be read word by word. Pairs never
    cross: a block that moved up is one that left and one that arrived, as in `git diff` —
    so refusing everything gives the old text back and every old block appears once.
    """
    usados: set[int] = set()
    casos: dict[int, int] = {}
    ultimo = -1
    for j, nb in enumerate(novos):
        melhor, nota = None, corte
        for i, vb in enumerate(velhos):
            # Só se casa bloco do mesmo tipo: um parágrafo que "virou" título porque os dois
            # começam com a mesma palavra é um que saiu e outro que entrou. E só adiante do
            # último casado: casar para trás punha os velhos do meio duas vezes na saída.
            if i <= ultimo or vb.tipo != nb.tipo:
                continue
            r = _parecido(vb.texto, nb.texto, nota)
            if r >= nota:
                melhor, nota = i, r
        if melhor is not None:
            usados.add(melhor)
            casos[j] = melhor
            ultimo = melhor
    saida, pos = [], 0
    for j, nb in enumerate(novos):
        alvo = casos.get(j)
        if alvo is None:
            # Um bloco que entrou não leva os velhos junto: os que saíram vêm antes do próximo
            # casado, ou no fim — levá-los aqui os repetia quando o próximo casado vinha depois.
            saida.append(("novo", None, nb))
            continue
        while pos < alvo:
            if pos not in usados:
                saida.append(("sumiu", velhos[pos], None))
            pos += 1
        saida.append(("mexido", velhos[alvo], nb))
        pos = alvo + 1
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
    tipo: str                   # to_do · comment
    data: str                   # the day a to_do was written, or "" for a comment
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
    sumiu: bool = False         # the file is not there any more — on disk, or in the branch

    @property
    def em_dia(self) -> bool:
        return self.tem_chancela and not self.mudancas

    @property
    def unidades(self) -> list[Unidade]:
        return [u for m in self.mudancas for u in m.unidades]


def situacao(root: Path, rel: str, base: str | None = None,
             rev: str | None = None) -> Situacao:
    """The file against its chancel — or against any other revision, to read it side by side.

    The verdicts always act on the chancel; `base` only changes what you are comparing with.
    `rev` reads the file from a branch's last commit instead of the disk: a branch nobody
    has checked out can still be approved, since the chancel is one for every branch.
    """
    antes = chancelado(root, rel) if base in (None, REF) else conteudo_em(root, base, rel)
    lido = conteudo_em(root, rev, rel) if rev else atual(root, rel)
    depois = lido or ""
    return Situacao(arquivo=rel, tem_chancela=antes is not None, antes=antes or "",
                    depois=depois, mudancas=mudancas(antes or "", depois),
                    sumiu=lido is None)


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


# ---- forgetting ----------------------------------------------------------------------
#
# The one rewrite of the ref's history; everything else only advances it. A file approved
# and never committed to a branch is in `.git` only because of the chancel — untracking
# keeps that text and deleting the file keeps every earlier version, and `refs/km/*` leaves
# with `git push --mirror` and with any copy of `.git`. `km forget` is how the author takes
# it out for good.

def sob(rel: str, caminhos: list[str]) -> bool:
    """`rel` is one of `caminhos`, or inside one of them."""
    return any(rel == c or rel.startswith(c + "/") for c in caminhos)


def fora_do_git(root: Path, rel: str) -> str | None:
    """Why approving this file stores text git would otherwise not have: None if git
    already has it in the index, "ignorado" if .gitignore leaves it out, "fora do git" if
    it was never added."""
    if _git(root, "--literal-pathspecs", "ls-files", "--error-unmatch", "--", rel).returncode == 0:
        return None
    if _git(root, "check-ignore", "-q", "--no-index", "--", rel).returncode == 0:
        return "ignorado"
    return "fora do git"


def fora_da_chancela(root: Path, rel: str) -> str | None:
    """The last commit outside `refs/km/*` — a branch, a tag, the stash — that has `rel`."""
    r = _git(root, "--literal-pathspecs", "log", "--exclude=refs/km/*", "--all", "-1",
             "--format=%h", "--", rel)
    return (r.stdout.strip() or None) if r.returncode == 0 else None


def na_historia(root: Path, rel: str) -> bool:
    """Has the chancel ever held `rel` (a file, or anything under a folder)?"""
    if not existe(root):
        return False
    r = _git(root, "--literal-pathspecs", "log", "-1", "--format=%h", REF, "--", rel)
    return bool(r.stdout.strip())


@dataclass
class Commit:
    sha: str
    arvore: str
    pais: list[str]
    autor: tuple[str, str, str]         # name, e-mail, "<unix time> <offset>"
    quem_grava: tuple[str, str, str]
    mensagem: bytes                     # exactly as stored
    mapa: dict[str, tuple[str, str]] = field(default_factory=dict)  # path → (mode, blob)

    @property
    def assunto(self) -> str:
        return self.mensagem.decode("utf-8", "replace").split("\n", 1)[0]

    @property
    def dia(self) -> str:
        from datetime import datetime
        return datetime.fromtimestamp(int(self.quem_grava[2].split()[0])).date().isoformat()


_PESSOA = re.compile(rb"^(.*) <(.*)> (\d+ [+-]\d{4})$")


def _pessoa(linha: bytes) -> tuple[str, str, str]:
    m = _PESSOA.match(linha)
    if not m:
        raise SystemExit(f"commit da chancela com cabeçalho que o km não lê: {linha[:80]!r}")
    return tuple(x.decode("utf-8", "surrogateescape") for x in m.groups())


def _commits(root: Path, ponta: str) -> list[Commit]:
    """Every commit of the ref, parents before children, read in one `cat-file --batch`."""
    shas = _ok(root, "rev-list", "--reverse", "--topo-order", ponta).split()
    r = subprocess.run(["git", "cat-file", "--batch"], cwd=root, capture_output=True,
                       input=("\n".join(shas) + "\n").encode())
    if r.returncode != 0:
        raise SystemExit(f"git cat-file --batch: {r.stderr.decode(errors='replace').strip()}")
    saida, pos, out = r.stdout, 0, []
    for _ in shas:
        fim = saida.index(b"\n", pos)
        sha, _tipo, tamanho = saida[pos:fim].split()
        corpo = saida[fim + 1:fim + 1 + int(tamanho)]
        pos = fim + 1 + int(tamanho) + 1
        cab, _, mensagem = corpo.partition(b"\n\n")
        campos: dict[bytes, list[bytes]] = {}
        for linha in cab.split(b"\n"):
            if linha.startswith(b" "):          # continuation of a gpgsig or mergetag
                continue
            chave, _, valor = linha.partition(b" ")
            campos.setdefault(chave, []).append(valor)
        out.append(Commit(sha=sha.decode(), arvore=campos[b"tree"][0].decode(),
                          pais=[p.decode() for p in campos.get(b"parent", [])],
                          autor=_pessoa(campos[b"author"][0]),
                          quem_grava=_pessoa(campos[b"committer"][0]), mensagem=mensagem))
    return out


def _mapa(root: Path, arvore: str) -> dict[str, tuple[str, str]]:
    r = subprocess.run(["git", "ls-tree", "-r", "-z", "--full-tree", arvore], cwd=root,
                       capture_output=True)
    if r.returncode != 0:
        raise SystemExit(f"git ls-tree {arvore}: {r.stderr.decode(errors='replace').strip()}")
    out = {}
    for item in r.stdout.decode("utf-8", "surrogateescape").split("\0"):
        if item:
            info, caminho = item.split("\t", 1)
            modo, _tipo, sha = info.split()
            out[caminho] = (modo, sha)
    return out


def _sem_linhas(mensagem: bytes, caminhos: list[str]) -> bytes:
    """The message without the lines that are just a forgotten path — how `--from` lists
    the files it approved."""
    linhas = mensagem.split(b"\n")
    fica = [l for l in linhas if not sob(l.decode("utf-8", "replace").strip(), caminhos)]
    return b"\n".join(fica) if len(fica) != len(linhas) else mensagem


@dataclass
class Esquecimento:
    """What forgetting `caminhos` does to the ref — worked out without writing anything."""

    caminhos: list[str]
    ponta: str | None                       # where the ref was read: the update is against it
    commits: list[Commit] = field(default_factory=list)
    versoes: dict[str, set[str]] = field(default_factory=dict)   # path → blobs it ever had
    tocaram: list[Commit] = field(default_factory=list)          # commits that changed a path
    vazios: set[str] = field(default_factory=set)                # of all, the ones left empty
    iguais: int = 0                         # leading commits that keep their sha
    outros: dict[str, set[str]] = field(default_factory=dict)    # blob → other paths holding it

    @property
    def blobs(self) -> set[str]:
        return {b for bs in self.versoes.values() for b in bs}

    @property
    def nada(self) -> bool:
        return not self.versoes

    @property
    def citam(self) -> list[Commit]:
        """Commits that stay and still name a forgotten path in their message."""
        return [c for c in self.commits if c.sha not in self.vazios
                and any(p.encode() in _sem_linhas(c.mensagem, self.caminhos)
                        for p in self.caminhos)]


def planejar_esquecer(root: Path, caminhos: list[str]) -> Esquecimento:
    """Which commits hold `caminhos`, which would be left empty, and what survives.

    A commit is left empty when, without the paths, its tree is its parent's — it only ever
    approved, deleted or undid those paths — and it was not empty before. It leaves; a commit
    that also touched other files stays, with the same message and dates.
    """
    plano = Esquecimento(caminhos=caminhos, ponta=_ref_em(root))
    if plano.ponta is None:
        return plano
    plano.commits = _commits(root, plano.ponta)
    memo: dict[str, dict] = {}
    por_sha = {}
    reescrever = False
    for c in plano.commits:
        if c.arvore not in memo:
            memo[c.arvore] = _mapa(root, c.arvore)
        c.mapa = memo[c.arvore]
        por_sha[c.sha] = c
        filtrado = {p: v for p, v in c.mapa.items() if not sob(p, caminhos)}
        pai = por_sha.get(c.pais[0]) if c.pais else None
        antes = pai.mapa if pai else {}
        antes_filtrado = {p: v for p, v in antes.items() if not sob(p, caminhos)}
        mexidos = {p for p in set(c.mapa) | set(antes) if c.mapa.get(p) != antes.get(p)}
        if any(sob(p, caminhos) for p in mexidos):
            plano.tocaram.append(c)
        if len(c.pais) <= 1 and filtrado == antes_filtrado and c.mapa != antes:
            plano.vazios.add(c.sha)
        for p, (_modo, blob) in c.mapa.items():
            if sob(p, caminhos):
                plano.versoes.setdefault(p, set()).add(blob)
        reescrever = reescrever or len(filtrado) != len(c.mapa) or c.sha in plano.vazios \
            or _sem_linhas(c.mensagem, caminhos) != c.mensagem
        if not reescrever:
            plano.iguais += 1
    blobs = plano.blobs
    for c in plano.commits:
        for p, (_modo, blob) in c.mapa.items():
            if blob in blobs and not sob(p, caminhos):
                plano.outros.setdefault(blob, set()).add(p)
    return plano


def esquecer(root: Path, plano: Esquecimento) -> str | None:
    """Rewrite the ref without the paths. Returns the new tip — None if nothing is left.

    Every commit keeps its message, author, committer and dates; one before the first that
    held a path keeps its sha. The ref only moves if it is still where the plan read it: an
    approval made meanwhile (the panel is open) fails this, and nothing is lost.
    """
    if plano.ponta is None or plano.nada:
        return plano.ponta
    git_dir = Path(_ok(root, "rev-parse", "--absolute-git-dir").strip())
    indice = git_dir / f"km-chancela-index-{os.getpid()}-{os.urandom(4).hex()}"
    env = {**os.environ, "GIT_INDEX_FILE": str(indice)}
    novo: dict[str, str | None] = {}
    arvores: dict[str, str] = {}
    try:
        for c in plano.commits:
            pais: list[str] = []
            for p in c.pais:
                q = novo[p]
                if q and q not in pais:
                    pais.append(q)
            if c.sha in plano.vazios:
                novo[c.sha] = pais[0] if pais else None
                continue
            tirar = [p for p in c.mapa if sob(p, plano.caminhos)]
            arvore = c.arvore
            if tirar:
                if c.arvore not in arvores:
                    _ok(root, "read-tree", c.arvore, env=env)
                    _ok(root, "update-index", "--force-remove", "--", *tirar, env=env)
                    arvores[c.arvore] = _ok(root, "write-tree", env=env).strip()
                arvore = arvores[c.arvore]
            mensagem = _sem_linhas(c.mensagem, plano.caminhos)
            if arvore == c.arvore and pais == c.pais and mensagem == c.mensagem:
                novo[c.sha] = c.sha
                continue
            pessoas = {"GIT_AUTHOR_NAME": c.autor[0], "GIT_AUTHOR_EMAIL": c.autor[1],
                       "GIT_AUTHOR_DATE": c.autor[2], "GIT_COMMITTER_NAME": c.quem_grava[0],
                       "GIT_COMMITTER_EMAIL": c.quem_grava[1],
                       "GIT_COMMITTER_DATE": c.quem_grava[2]}
            r = subprocess.run(["git", "commit-tree", arvore, *[x for p in pais for x in ("-p", p)]],
                               cwd=root, input=mensagem, capture_output=True,
                               env={**os.environ, **pessoas})
            if r.returncode != 0:
                raise SystemExit(f"git commit-tree: {r.stderr.decode(errors='replace').strip()}")
            novo[c.sha] = r.stdout.decode().strip()
    finally:
        if indice.exists():
            indice.unlink()
    ponta = novo[plano.ponta]
    r = (_git(root, "update-ref", REF, ponta, plano.ponta) if ponta
         else _git(root, "update-ref", "-d", REF, plano.ponta))
    if r.returncode != 0:
        if _ref_em(root) != plano.ponta:
            raise Concorrencia("a chancela mudou enquanto eu reescrevia — uma aprovação no"
                               " painel? Nada foi trocado; rode de novo")
        raise SystemExit(f"git update-ref {REF}: {r.stderr.strip()}")
    return ponta


def podar(root: Path) -> None:
    """Drop from `.git` what nothing reaches any more: the reflog of the ref, if it keeps
    one, and every unreachable object (`git gc --prune=now`)."""
    if _git(root, "reflog", "exists", REF).returncode == 0:
        _ok(root, "reflog", "expire", "--expire=now", "--expire-unreachable=now", REF)
    _ok(root, "gc", "--prune=now", "--quiet")


def objetos_presentes(root: Path, shas: set[str]) -> set[str]:
    """Which of these objects `.git` still has."""
    if not shas:
        return set()
    r = subprocess.run(["git", "cat-file", "--batch-check=%(objectname)"], cwd=root,
                       input="\n".join(sorted(shas)) + "\n", capture_output=True, text=True)
    return {l.strip() for l in r.stdout.splitlines() if l.strip() in shas}


def onde_mais(root: Path, shas: set[str]) -> dict[str, set[str]]:
    """Where else `.git` keeps these blobs: commits outside `refs/km/*`, and the index."""
    if not shas:
        return {}
    fora = set(_ok(root, "rev-list", "--objects", "--no-object-names", "--exclude=refs/km/*",
                   "--all").split()) & shas
    r = subprocess.run(["git", "ls-files", "-s", "-z"], cwd=root, capture_output=True)
    indice = {item.split()[1].decode() for item in r.stdout.split(b"\0") if item} & shas
    return {"commits": fora, "index": indice}


def worktrees(root: Path) -> list[str]:
    return [l[len("worktree "):] for l in _ok(root, "worktree", "list", "--porcelain").splitlines()
            if l.startswith("worktree ")]
