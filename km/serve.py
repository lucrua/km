"""The review surface: the chancel, in a page you can act on.

Plain HTML served from this file, bound to localhost, no build step and no dependencies.
It reads `refs/km/chancela` and the files on disk, and every action goes through the same
functions the CLI uses — the page is a surface, not a second implementation.

One server shows every project in the registry (km/projetos.py): each request names its
project, and the root is found through the registry, never taken from the request. It is
started when you sit down to review and stopped with Ctrl-C. Nothing runs in the
background, nothing is written except what you ask for: the ref, a passage you edited
here — a mark included —, a project's `.km/config.json`, or the list of projects.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

from . import acompanhamento as ac
from . import chancela as ch
from . import cli
from . import projetos as pj

PAGINA = Path(__file__).with_name("painel.html")

ESTATICOS = {"vendor": Path(__file__).with_name("vendor"),
             "painel": Path(__file__).with_name("painel")}
TIPOS = {".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8"}


def arquivo_estatico(caminho: str, raizes: dict | None = None) -> Path | None:
    """`/static/<raiz>/<arquivo>` → a file inside km/vendor or km/painel, and nothing else."""
    from urllib.parse import unquote, urlparse

    raizes = raizes or ESTATICOS
    partes = unquote(urlparse(caminho).path).split("/")
    if len(partes) != 4 or partes[1] != "static" or partes[2] not in raizes or not partes[3]:
        return None
    try:
        base = raizes[partes[2]].resolve()
        alvo = (base / partes[3]).resolve()
        if alvo.parent != base or not alvo.is_file():
            return None
    except (OSError, ValueError):   # um byte nulo no nome, um nome longo demais
        return None
    return alvo


def _ultima(root: Path, rel: str) -> str:
    if not ch.existe(root):
        return ""
    linhas = ch.historico(root, rel, None, limite=1).strip().splitlines()
    partes = linhas[0].split(" ") if linhas else []
    return partes[1] if len(partes) > 1 else ""


def segmentos(s: ch.Situacao) -> list[dict]:
    """The document in reading order: stretches that did not change, and changes.

    A stretch that did not change is just text — one editable column, full width, no
    buttons. A change is one row, made of the blocks that changed in it, each with its
    own verdict. Headings are text like any other; they cut nothing.
    """
    pd, ba, bd, ops = ch._alinhar(s.antes, s.depois)
    por_n = {m.n: m for m in s.mudancas}
    out: list[dict] = []
    vistas: dict[str, int] = {}
    n = 0
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            if j2 > j1:
                texto = "".join(b.cru for b in bd[j1:j2]).rstrip("\n")
                out.append({"tipo": "igual", "linha": bd[j1].linha, "texto": texto,
                            "n_linhas": len(texto.splitlines())})
            continue
        n += 1
        m = por_n[n]
        t = _trecho_mudado(s, m)
        # A chave vem do texto, para o que você digitou num trecho seguir com ele quando outro
        # sai da tela; duas mudanças iguais no mesmo arquivo ganham cada uma a sua.
        k = vistas[t["chave"]] = vistas.get(t["chave"], 0) + 1
        if k > 1:
            t["chave"] += f"-{k}"
        out.append(t)
    return out


def _faixa(linhas: list[str], blocos: list) -> tuple[str, int]:
    """The raw text from the first to the last of these blocks, blank lines included."""
    if not blocos:
        return "", 0
    ini, fim = blocos[0].linha, blocos[-1].fim
    return "\n".join(linhas[ini - 1:fim - 1]), ini


def _trecho_mudado(s: ch.Situacao, m: ch.Mudanca) -> dict:
    """A change as one thing to read: everything that moved between two unchanged stretches.

    Blocks are how the engine finds and applies changes; they are not how you read them.
    Three blocks in a row that changed are one passage, with one text on each side and one
    set of verdicts. Less than the whole is a selection, not a pre-cut piece.
    """
    novos = [u.depois for u in m.unidades if u.depois]
    velhos = [u.antes for u in m.unidades if u.antes]
    agora, linha = _faixa(s.depois.splitlines(), novos)
    antes, _ = _faixa(s.antes.splitlines(), velhos)

    # Where each block sits inside the passage's text, so a selection over the passage can
    # be turned into "this part of this block" — which is what the engine applies.
    linhas = agora.split("\n") if agora else []
    inicio = [0]
    for l in linhas:
        inicio.append(inicio[-1] + len(l) + 1)
    def pos(b):
        return inicio[b.linha - linha] if agora else 0
    unidades = []
    for k, u in enumerate(m.unidades):
        if u.depois:
            a = pos(u.depois)
            unidades.append({"sha": u.sha, "tipo": u.tipo, "ini": a, "fim": a + len(u.depois.texto)})
        else:
            # O que saiu não tem texto do lado de cá: fica ancorado onde estaria, antes do
            # próximo bloco que ficou.
            prox = next((x.depois for x in m.unidades[k + 1:] if x.depois), None)
            a = pos(prox) if prox else len(agora)
            unidades.append({"sha": u.sha, "tipo": u.tipo, "ini": a, "fim": a})

    tipos = {u.tipo for u in m.unidades}
    geral = "novo" if tipos == {"novo"} else ("saiu" if tipos == {"sumiu"} else "editado")
    return {"tipo": "mudanca", "n": m.n, "titulo": m.titulo, "geral": geral,
            "linha": linha or m.linha, "antes": antes, "agora": agora,
            "chave": ch.sha_do(antes + "\x00" + agora),
            "unidades": unidades, "sumidas": m.sumidas}


# ---- what the right-hand side reads -------------------------------------------------

class FonteDesconhecida(Exception):
    """The page asked to read from a worktree or branch this repository does not have."""


def fontes(root: Path) -> list[dict]:
    """What the right-hand side can read: this folder, the repository's other worktrees, and
    the branches no worktree has checked out. The chancel is one for all of them.

    A branch checked out in a worktree is read from that worktree's disk — its uncommitted
    work is what you want to review — so it is listed as the worktree, not again as a branch.
    """
    raiz = os.path.realpath(root)
    wts, atual = [], {}
    for linha in ch._ok(root, "worktree", "list", "--porcelain").splitlines() + [""]:
        if linha.startswith("worktree "):
            atual = {"caminho": os.path.realpath(linha[len("worktree "):])}
        elif linha.startswith("branch refs/heads/"):
            atual["branch"] = linha[len("branch refs/heads/"):]
        elif not linha and atual:
            wts.append(atual)
            atual = {}
    meu = next((w for w in wts if w["caminho"] == raiz), {})
    out = [{"id": "", "tipo": "pasta", "rotulo": f"esta pasta · {meu.get('branch') or 'sem branch'}",
            "caminho": raiz}]
    for w in wts:
        if w["caminho"] != raiz and Path(w["caminho"]).is_dir():
            out.append({"id": "wt:" + w["caminho"], "tipo": "worktree", "caminho": w["caminho"],
                        "rotulo": f"{Path(w['caminho']).name} · {w.get('branch') or 'sem branch'}"})
    checados = {w.get("branch") for w in wts}
    for b in ch._ok(root, "for-each-ref", "--sort=-committerdate", "--format=%(refname:short)",
                    "refs/heads").splitlines():
        if b.strip() and b not in checados:
            out.append({"id": "br:" + b, "tipo": "branch", "rotulo": f"{b} · branch, só aprovar"})
    return out


def fonte(root: Path, lendo: object) -> tuple[Path, str | None]:
    """id → (the folder to read and write, the branch to read from). Only an id from
    `fontes`: a path or a branch name is never taken from the request as it came."""
    if not lendo:
        return root, None
    f = next((x for x in fontes(root) if x["id"] == lendo), None)
    if f is None:
        raise FonteDesconhecida(f"{lendo}: não é um worktree nem um branch solto deste repositório"
                                " — a lista foi atualizada")
    if f["tipo"] == "branch":
        return root, f["id"][len("br:"):]
    return Path(f["caminho"]), None


def _documentos(root: Path, pasta: Path, rev: str | None) -> list[str]:
    """The files under review, with this project's config, wherever the right side reads."""
    cfg = ac.carregar(root)
    return ac.documentos_em(root, rev, cfg) if rev else ac.documentos(pasta, cfg)


def estado(root: Path, by: str = "", base: str | None = None,
           arquivo: str | None = None, lendo: str | None = None) -> dict:
    """The state for the page.

    The heavy part — every line of the document, highlighted and marked — is built only
    for the document being read. The rail on the left is counts. `lendo` picks what the
    right-hand side reads: this folder, another worktree, or a branch.
    """
    docs = []
    soma_pend = soma_total = 0
    lista = fontes(root)
    aviso = ""
    try:
        pasta, rev = fonte(root, lendo)
    except FonteDesconhecida as e:
        # O worktree foi removido, o branch apagado: volta para esta pasta, e diz.
        pasta, rev, lendo, aviso = root, None, "", str(e)
    extra = {"fontes": lista, "lendo": lendo or "", "so_aprovar": bool(rev), "pasta": str(pasta),
             **({"aviso": aviso} if aviso else {})}
    try:
        acompanhados = _documentos(root, pasta, rev)
    except ac.ConfigInvalida as e:
        # Uma config quebrada vira um aviso na tela, não uma página que não carrega.
        return {"repo": root.name, "root": str(root), "docs": [], "by": by,
                "base": base or ch.REF, "revisoes": ch.revisoes(root), "pct": "",
                "erro": str(e), **extra}
    for rel in acompanhados:
        s = ch.situacao(pasta, rel, base=base, rev=rev)
        if not s.depois.strip():
            continue
        cheio = rel == arquivo
        pend, total = ch.pendencia_do_arquivo(s)
        soma_pend, soma_total = soma_pend + pend, soma_total + total
        d = {"file": rel, "rastreado": s.tem_chancela, "cheio": cheio,
             "pendente": bool(s.mudancas), "pct": ch.percentual(pend, total)}
        if cheio:
            d["em"] = _ultima(root, rel)
            # Aprovar um arquivo que o git não tem guarda o texto no .git mesmo assim.
            fora = None if rev else ch.fora_do_git(pasta, rel)
            if fora:
                d["fora_do_git"] = cli.aviso_fora_do_git(rel, fora)
            d["segmentos"] = segmentos(s)
        docs.append(d)
    docs.sort(key=lambda d: (not d["rastreado"], d["file"]))
    return {"repo": root.name, "root": str(root), "docs": docs, "by": by,
            "base": base or ch.REF, "revisoes": ch.revisoes(root),
            "pct": ch.percentual(soma_pend, soma_total) if soma_pend else "", **extra}


# ---- the actions ---------------------------------------------------------------------

def _unidades(root: Path, rel: str, shas: list[str],
              rev: str | None = None) -> tuple[ch.Situacao, list[ch.Unidade]]:
    """The blocks the page asked for, found by content. If any is missing the file moved
    under the page, and acting on the rest would be acting on something you did not see.
    Blocks with the same text share a sha, so one sha can find several blocks."""
    s = ch.situacao(root, rel, rev=rev)
    achadas = ch.unidades_por_sha(s.mudancas, set(shas))
    if {u.sha for u in achadas} != set(shas):
        raise LookupError("o arquivo mudou enquanto você olhava — a tela foi atualizada")
    return s, achadas


def agir(root: Path, pedido: dict, by: str) -> dict:
    """One place for every verdict, so the page and the CLI cannot drift apart."""
    acao = pedido.get("acao")
    rel = pedido.get("file", "")
    # Tudo abaixo age em `root`: a pasta de onde o lado direito lê — esta, ou outro worktree,
    # que divide a mesma chancela. Um branch sem worktree não tem disco: só se aprova.
    projeto_raiz = root
    try:
        root, rev = fonte(projeto_raiz, pedido.get("lendo"))
    except FonteDesconhecida as e:
        return {"ok": False, "erro": str(e)}
    if rel not in _documentos(projeto_raiz, root, rev):
        return {"ok": False, "erro": f"{rel} não é acompanhado — escolha na aba Arquivos"}
    if rev and acao not in ("aprovar", "desfazer"):
        return {"ok": False, "erro": f"{rev} é um branch sem worktree: aqui só se aprova —"
                " para editar ou reverter, abra um worktree dele"}

    if acao == "salvar":
        try:
            ch.substituir_texto(root, rel, pedido.get("original", ""),
                                pedido.get("texto", ""), int(pedido.get("linha") or 1))
        except ch.Conflito as e:
            return {"ok": False, "erro": "o texto mudou no arquivo desde que você abriu",
                    "conflito": {"atual": e.atual}}
        return {"ok": True, "msg": "salvo no arquivo"}

    if acao == "desfazer":
        # Uma aprovação volta atrás: a chancela deste arquivo fica como estava antes dela.
        commit = pedido.get("commit")
        if not isinstance(commit, str) or not commit:
            return {"ok": False, "erro": "falta qual aprovação desfazer"}
        try:
            ch.desfazer(root, rel, commit, f"chancela: {rel} · desfeita a aprovação "
                        f"{commit[:8]}\n\npor: {by}\n")
        except ch.NaoDesfaz as e:
            return {"ok": False, "erro": str(e)}
        depois = ch.situacao(root, rel, rev=rev)
        falta = (f"falta {ch.percentual(*ch.pendencia_do_arquivo(depois))} deste arquivo"
                 if depois.tem_chancela else "o arquivo voltou a não ter chancela")
        return {"ok": True, "msg": f"aprovação {commit[:8]} desfeita · {falta}"}

    # Uma seleção vem como {sha, ini, fim}: só as mudanças dentro daquele pedaço do texto
    # novo daquele bloco. É o "aceitar metade do hunk" de uma revisão de código.
    selecao = pedido.get("parciais") or []
    try:
        s, alvos = _unidades(root, rel, (pedido.get("shas") or []) + [x["sha"] for x in selecao], rev)
    except LookupError as e:
        return {"ok": False, "erro": str(e)}
    if not alvos:
        return {"ok": False, "erro": "nada escolhido"}
    por_sha = {u.sha: u for u in alvos}
    parciais = {por_sha[x["sha"]].id: (int(x["ini"]), int(x["fim"])) for x in selecao}
    inteiras = [u for u in alvos if u.id not in parciais]

    if acao == "reverter":
        cli.reverter(root, rel, inteiras, s, parciais)
        return {"ok": True, "msg": "de volta ao texto chancelado"
                + (" — só a parte selecionada" if parciais else "")}

    if acao == "aprovar":
        commit = cli.chancelar(root, rel, inteiras, s, pedido.get("motivo"), by, parciais)
        saiu = sum(len(u.sumidas) for u in inteiras)
        depois = ch.situacao(root, rel, rev=rev)
        msg = (f"na chancela ({commit[:8]})" + (" — só a parte selecionada" if parciais else "")
               + (f" · falta {ch.percentual(*ch.pendencia_do_arquivo(depois))} deste arquivo"
                  if depois.mudancas else " · arquivo em dia"))
        if saiu:
            msg += f" · {saiu} marca(s) removida(s) aprovada(s) junto"
        fora = None if rev else ch.fora_do_git(root, rel)
        if fora:
            msg += " · ⚠ " + ("ignorado pelo git" if fora == "ignorado" else "fora do git")
            msg += ": o texto fica guardado no .git mesmo sem commit"
        return {"ok": True, "msg": msg, "desfazer": commit}

    return {"ok": False, "erro": f"ação desconhecida: {acao}"}


# ---- which files -------------------------------------------------------------------

def arquivos_clicar(root: Path, pedido: dict) -> dict:
    """One click in the tree: written at once, reported in one line, undoable."""
    try:
        antes = ac.carregar(root)
    except ac.ConfigInvalida as e:
        return {"ok": False, "erro": str(e), "arvore": ac.arvore(root)}
    if pedido.get("sha") != ac.sha_config(antes):
        return {"ok": False, "erro": "a configuração mudou por fora — a tela foi atualizada",
                "arvore": ac.arvore(root)}
    caminho, pasta, marcou = pedido["caminho"], bool(pedido.get("pasta")), bool(pedido.get("marcar"))
    depois = (ac.marcar if marcou else ac.desmarcar)(antes, caminho, pasta)
    try:
        ac.gravar(root, depois)
    except ac.ConfigInvalida as e:
        return {"ok": False, "erro": str(e), "arvore": ac.arvore(root)}
    msg = ac.rotulo(root, antes, depois, caminho, pasta, marcou)
    return {"ok": True, "msg": msg,
            "passo": {"rotulo": msg.split(" · ")[0], "antes": antes, "depois": ac.normalizar(depois)},
            "arvore": ac.arvore(root)}


def arquivos_trocar(root: Path, pedido: dict) -> dict:
    """Undo or redo a step: write `config` only if the file is still `esperado`."""
    try:
        atual = ac.carregar(root)
    except ac.ConfigInvalida as e:
        return {"ok": False, "erro": str(e), "arvore": ac.arvore(root)}
    if ac.normalizar(atual) != ac.normalizar(pedido["esperado"]):
        return {"ok": False, "erro": "a configuração mudou por fora — a tela foi atualizada",
                "arvore": ac.arvore(root)}
    try:
        ac.gravar(root, pedido["config"])
    except ac.ConfigInvalida as e:
        return {"ok": False, "erro": str(e), "arvore": ac.arvore(root)}
    return {"ok": True, "arvore": ac.arvore(root)}


# ---- open in VS Code ---------------------------------------------------------------

def _lancar(argv: list[str]) -> None:
    """Start VS Code and walk away: no shell, no pipes, its own session. A thread reaps the
    wrapper when it exits, so clicks do not pile up zombies in a server that stays up."""
    p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    threading.Thread(target=p.wait, daemon=True).start()


def abrir_no_code(root: Path, pedido: dict) -> dict:
    """`code <file>` (or `code -g <file>:<line>`) for a document the panel knows.

    Under WSL, `code` is the wrapper that opens Windows VS Code in WSL mode. Only a Markdown
    file git knows about — or one the chancel follows — that really lives inside the
    repository: a path with `..`, an absolute path or a symlink that leads out is refused.
    """
    rel = pedido.get("file")
    if not isinstance(rel, str) or not rel:
        return {"ok": False, "erro": "nenhum arquivo pedido"}
    projeto_raiz = root
    try:
        root, rev = fonte(projeto_raiz, pedido.get("lendo"))
    except FonteDesconhecida as e:
        return {"ok": False, "erro": str(e)}
    if rev:
        return {"ok": False, "erro": f"{rev} é um branch sem worktree: não há arquivo para abrir"}
    partes = Path(rel).parts
    if Path(rel).is_absolute() or "\\" in rel or ".." in partes:
        return {"ok": False, "erro": f"{rel}: só um caminho relativo, dentro do repositório"}
    try:
        conhecidos = set(ac.documentos(root, ac.carregar(projeto_raiz)))
    except ac.ConfigInvalida:
        conhecidos = set()
    conhecidos |= set(ac.candidatos(root))
    base = root.resolve()
    alvo = (base / rel).resolve()
    if rel not in conhecidos or not alvo.is_file():
        return {"ok": False, "erro": f"{rel} não é um documento deste repositório"}
    if not alvo.is_relative_to(base):
        return {"ok": False, "erro": f"{rel} aponta para fora do repositório"}
    code = shutil.which("code")
    if not code:
        return {"ok": False, "erro": "o comando code não está no PATH do km serve"}
    linha = pedido.get("line")
    if isinstance(linha, int) and not isinstance(linha, bool) and linha > 0:
        argv = [code, "-g", f"{alvo}:{linha}"]
    else:
        argv = [code, str(alvo)]
    try:
        _lancar(argv)
    except OSError as e:
        return {"ok": False, "erro": f"não consegui rodar o code: {e}"}
    return {"ok": True, "msg": f"aberto no VS Code: {rel}" + (f":{linha}" if len(argv) == 3 else "")}


# ---- the server ----------------------------------------------------------------------

class SemProjeto(Exception):
    """The request names no project, or one the registry does not have."""

    def __init__(self, codigo: int, erro: str):
        super().__init__(erro)
        self.codigo, self.erro = codigo, erro


def projeto(nome: object) -> tuple[str, Path]:
    """name → root, through the registry only: a path is never taken from the request."""
    if not isinstance(nome, str) or not nome:
        raise SemProjeto(400, "falta o projeto — ?projeto=<nome> (GET) ou \"projeto\" (POST)")
    raiz = pj.resolver(nome)
    if raiz is None:
        raise SemProjeto(404, f"projeto desconhecido: {nome} — veja a aba Projetos")
    if not raiz.is_dir():
        raise SemProjeto(404, f"{nome}: {raiz} não existe mais — tire-o da lista na aba Projetos")
    return nome, raiz


def projetos_adicionar(pedido: dict) -> dict:
    try:
        r = pj.adicionar(pedido.get("caminho") or "", init=bool(pedido.get("init")))
    except (pj.Recusado, ac.ConfigInvalida) as e:
        return {"ok": False, "erro": str(e)}
    msg = (f"{r['nome']} entrou na lista" if r["novo"] else f"{r['nome']} já estava na lista")
    if r["iniciado"]:
        msg += " · .km/config.json criado, nada acompanhado ainda"
    return {"ok": True, "msg": msg, **r}


def projetos_remover(pedido: dict) -> dict:
    try:
        r = pj.remover(pedido.get("nome") or "")
    except (pj.Recusado, ac.ConfigInvalida) as e:
        return {"ok": False, "erro": str(e)}
    return {"ok": True, "msg": f"{r['nome']} saiu da lista · o repositório não foi mexido", **r}


class Handler(BaseHTTPRequestHandler):
    by: str
    inicial: Path | None = None      # o repositório de onde o km serve foi chamado

    def _envia(self, corpo: bytes, tipo: str, codigo: int = 200) -> None:
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def _json(self, dados: dict, codigo: int = 200) -> None:
        self._envia(json.dumps(dados, ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8", codigo)

    def _estado(self, nome: str, raiz: Path, **kw) -> dict:
        e = estado(raiz, self.by, **kw)
        e["projeto"] = nome
        return e

    def do_GET(self) -> None:  # noqa: N802
        from urllib.parse import parse_qs, urlparse

        if self.path.startswith("/static/"):
            alvo = arquivo_estatico(self.path)
            if alvo is None or alvo.suffix not in TIPOS:
                self._envia(b"nao encontrado", "text/plain; charset=utf-8", 404)
            else:
                self._envia(alvo.read_bytes(), TIPOS[alvo.suffix])
            return
        url = urlparse(self.path)
        q = parse_qs(url.query)
        try:
            if url.path in ("/", "/index.html"):
                self._envia(PAGINA.read_bytes(), "text/html; charset=utf-8")
            elif url.path == "/api/projetos":
                inicial = pj.nome_de(self.inicial) if self.inicial else None
                self._json({"projetos": pj.listar(), "inicial": inicial})
            elif url.path == "/api/arquivos":
                _, raiz = projeto(q.get("projeto", [None])[0])
                self._json(ac.arvore(raiz))
            elif url.path == "/api/state":
                nome, raiz = projeto(q.get("projeto", [None])[0])
                self._json(self._estado(nome, raiz, base=q.get("base", [None])[0],
                                        arquivo=q.get("file", [None])[0],
                                        lendo=q.get("lendo", [None])[0]))
            else:
                self._envia(b"nao encontrado", "text/plain; charset=utf-8", 404)
        except SemProjeto as e:
            self._json({"ok": False, "erro": e.erro}, e.codigo)
        except ac.ConfigInvalida as e:          # o registro quebrado: uma frase, não um 500 mudo
            self._json({"ok": False, "erro": str(e)}, 500)
        except SystemExit as e:                 # um git que falhou: a frase dele, não uma resposta vazia
            self._json({"ok": False, "erro": str(e)}, 500)

    def _de_outro_site(self) -> bool:
        """This server writes documents and the chancel. A page from anywhere else must not
        be able to ask it to: a cross-site POST carries its own Origin, and insisting on
        application/json forces the browser's preflight, which this server never grants."""
        if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
            return True
        origem = self.headers.get("Origin")
        if not origem:
            return False                      # não veio de um navegador em outro site
        from urllib.parse import urlparse
        # Mesma origem é o Host que o próprio navegador usou — o VS Code no WSL pode
        # encaminhar a porta para outra no Windows, então a porta do servidor não serve de
        # régua. E o Host tem que ser local, contra DNS rebinding.
        host = self.headers.get("Host", "")
        local = urlparse("//" + host).hostname in ("127.0.0.1", "localhost")
        return not (local and urlparse(origem).netloc == host)

    ROTAS_DO_PROJETO = ("/api/abrir", "/api/arquivos/desfazer", "/api/arquivos", "/api/act")

    def do_POST(self) -> None:  # noqa: N802
        from urllib.parse import urlparse

        if self._de_outro_site():
            self._envia(b"origem recusada", "text/plain; charset=utf-8", 403)
            return
        caminho = urlparse(self.path).path
        tamanho = int(self.headers.get("Content-Length", 0))
        try:
            pedido = json.loads(self.rfile.read(tamanho) or b"{}")
        except ValueError:
            pedido = None
        if not isinstance(pedido, dict):
            self._json({"ok": False, "erro": "o pedido tem que ser um objeto JSON"}, 400)
            return
        if caminho == "/api/projetos":
            self._json(projetos_adicionar(pedido))
            return
        if caminho == "/api/projetos/remover":
            self._json(projetos_remover(pedido))
            return
        if caminho not in self.ROTAS_DO_PROJETO:
            self._envia(b"nao encontrado", "text/plain; charset=utf-8", 404)
            return
        try:
            nome, raiz = projeto(pedido.get("projeto"))
        except SemProjeto as e:
            self._json({"ok": False, "erro": e.erro}, e.codigo)
            return
        except ac.ConfigInvalida as e:
            self._json({"ok": False, "erro": str(e)}, 500)
            return
        if caminho == "/api/abrir":
            self._json(abrir_no_code(raiz, pedido))
            return
        if caminho == "/api/arquivos/desfazer":
            self._json(arquivos_trocar(raiz, pedido))
            return
        if caminho == "/api/arquivos":
            self._json(arquivos_clicar(raiz, pedido))
            return
        try:
            resposta = agir(raiz, pedido, self.by)
        except ch.Concorrencia as e:                # outra aba aprovou o mesmo arquivo antes
            resposta = {"ok": False, "erro": str(e)}
        except Exception as e:                      # o servidor é local; o erro vai à tela
            resposta = {"ok": False, "erro": f"{type(e).__name__}: {e}"}
        resposta["estado"] = self._estado(nome, raiz, base=pedido.get("base") or None,
                                          arquivo=pedido.get("file"), lendo=pedido.get("lendo"))
        self._json(resposta)

    def log_message(self, *args) -> None:           # sem ruído no terminal
        return


def run(port: int = 8431, by: str = "", inicial: Path | None = None, abrir: bool = False) -> int:
    """One server for every registered project. The registry is read on each request, so a
    project added by `km projects add` in another terminal shows up without a restart."""
    Handler.by = by
    Handler.inicial = inicial
    url = f"http://127.0.0.1:{port}"
    nome = pj.nome_de(inicial) if inicial else None
    endereco = url + (f"/?projeto={quote(nome)}" if nome else "/")
    try:
        servidor = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as e:
        if e.errno != 98:
            raise
        raise SystemExit(
            f"a porta {port} já está ocupada — provavelmente pelo painel, que mostra todos os\n"
            f"projetos registrados: abra {endereco}\n"
            f"ou suba outro nesta: km serve --port {port + 1}")
    n = len(pj.carregar())
    print(f"km · {n} projeto(s)  ·  {endereco}  ·  Ctrl-C encerra", flush=True)
    if abrir:
        webbrowser.open(endereco)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nencerrado")
    finally:
        servidor.server_close()
    return 0
