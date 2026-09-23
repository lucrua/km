"""The review surface: the chancel, in a page you can act on.

Plain HTML served from this file, bound to localhost, no build step and no dependencies.
It reads `refs/km/chancela` and the files on disk, and every action goes through the same
functions the CLI uses — the page is a surface, not a second implementation.

It is started when you sit down to review and stopped with Ctrl-C. Nothing runs in the
background, nothing is written except what you ask for: the ref, a reservation in the text,
or a passage you edited here.
"""

from __future__ import annotations

import json
import webbrowser
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import acompanhamento as ac
from . import chancela as ch
from . import cli

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
            "unidades": unidades, "bloqueio": m.bloqueio, "sumidas": m.sumidas}


def estado(root: Path, by: str = "", base: str | None = None,
           arquivo: str | None = None) -> dict:
    """The state for the page.

    The heavy part — every line of the document, highlighted and marked — is built only
    for the document being read. The rail on the left is counts.
    """
    hoje = date.today().isoformat()
    docs = []
    soma_pend = soma_total = 0
    try:
        acompanhados = ac.documentos(root)
    except ac.ConfigInvalida as e:
        # Uma config quebrada vira um aviso na tela, não uma página que não carrega.
        return {"repo": root.name, "root": str(root), "docs": [], "hoje": hoje, "by": by,
                "base": base or ch.REF, "revisoes": ch.revisoes(root), "pct": "",
                "erro": str(e)}
    for rel in acompanhados:
        s = ch.situacao(root, rel, hoje, base=base)
        if not s.depois.strip():
            continue
        cheio = rel == arquivo
        pend, total = ch.pendencia_do_arquivo(s)
        soma_pend, soma_total = soma_pend + pend, soma_total + total
        d = {"file": rel, "rastreado": s.tem_chancela, "cheio": cheio,
             "pendente": bool(s.mudancas), "pct": ch.percentual(pend, total),
             "bloqueado": any(u.bloqueio for u in s.unidades),
             "vencidas": len(s.vencidas)}
        if cheio:
            d["em"] = _ultima(root, rel)
            d["segmentos"] = segmentos(s)
            d["vencidas_txt"] = [{"linha": l, "prazo": p, "texto": x} for l, p, x in s.vencidas]
        docs.append(d)
    docs.sort(key=lambda d: (not d["rastreado"], d["file"]))
    return {"repo": root.name, "root": str(root), "docs": docs, "hoje": hoje, "by": by,
            "base": base or ch.REF, "revisoes": ch.revisoes(root),
            "pct": ch.percentual(soma_pend, soma_total) if soma_pend else ""}


# ---- the actions ---------------------------------------------------------------------

def _unidades(root: Path, rel: str, shas: list[str]) -> tuple[ch.Situacao, list[ch.Unidade]]:
    """The blocks the page asked for, found by content. If any is missing the file moved
    under the page, and acting on the rest would be acting on something you did not see.
    Blocks with the same text share a sha, so one sha can find several blocks."""
    s = ch.situacao(root, rel)
    achadas = ch.unidades_por_sha(s.mudancas, set(shas))
    if {u.sha for u in achadas} != set(shas):
        raise LookupError("o arquivo mudou enquanto você olhava — a tela foi atualizada")
    return s, achadas


def agir(root: Path, pedido: dict, by: str) -> dict:
    """One place for every verdict, so the page and the CLI cannot drift apart."""
    acao = pedido.get("acao")
    rel = pedido.get("file", "")
    if rel not in ac.documentos(root):
        return {"ok": False, "erro": f"{rel} não é acompanhado — escolha na aba Arquivos"}

    if acao == "salvar":
        try:
            ch.substituir_texto(root, rel, pedido.get("original", ""),
                                pedido.get("texto", ""), int(pedido.get("linha") or 1))
        except ch.Conflito as e:
            return {"ok": False, "erro": "o texto mudou no arquivo desde que você abriu",
                    "conflito": {"atual": e.atual}}
        return {"ok": True, "msg": "salvo no arquivo"}

    # Uma seleção vem como {sha, ini, fim}: só as mudanças dentro daquele pedaço do texto
    # novo daquele bloco. É o "aceitar metade do hunk" de uma revisão de código.
    selecao = pedido.get("parciais") or []
    try:
        s, alvos = _unidades(root, rel, (pedido.get("shas") or []) + [x["sha"] for x in selecao])
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

    if acao == "validar":
        # O ❓ entra logo depois do último bloco escolhido, como bloco próprio, e entra na
        # chancela junto: a meia-chancela é uma linha que qualquer leitor vê.
        linha = max((u.depois.fim - 1 for u in alvos if u.depois),
                    default=min(u.antes.linha for u in alvos) - 1)
        marca = ch.linha_de_marca("❓", pedido.get("texto") or "", pedido.get("prazo"))
        shas = {u.sha for u in alvos}
        if not ch.inserir_apos(root, rel, linha, marca):
            return {"ok": False, "erro": "não consegui escrever o prazo no texto"}
        s = ch.situacao(root, rel)
        alvos = [u for u in s.unidades
                 if u.sha in shas or (u.depois and u.depois.texto == marca)]
        inteiras, parciais = alvos, {}
        acao = "aprovar"

    if acao == "aprovar":
        barradas = [u for u in alvos if u.bloqueio]
        if barradas and not pedido.get("force"):
            return {"ok": False, "erro": "🚫 " + barradas[0].bloqueio.lstrip("> ")}
        commit = cli.chancelar(root, rel, inteiras, s, pedido.get("motivo"), by, parciais)
        saiu = sum(len(u.sumidas) for u in inteiras)
        depois = ch.situacao(root, rel)
        msg = (f"na chancela ({commit[:8]})" + (" — só a parte selecionada" if parciais else "")
               + (f" · falta {ch.percentual(*ch.pendencia_do_arquivo(depois))} deste arquivo"
                  if depois.mudancas else " · arquivo em dia"))
        if saiu:
            msg += f" · {saiu} ressalva(s) removida(s) aprovada(s) junto"
        return {"ok": True, "msg": msg}

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


# ---- the server ----------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    root: Path
    by: str

    def _envia(self, corpo: bytes, tipo: str, codigo: int = 200) -> None:
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def _json(self, dados: dict, codigo: int = 200) -> None:
        self._envia(json.dumps(dados, ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8", codigo)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/static/"):
            alvo = arquivo_estatico(self.path)
            if alvo is None or alvo.suffix not in TIPOS:
                self._envia(b"nao encontrado", "text/plain; charset=utf-8", 404)
            else:
                self._envia(alvo.read_bytes(), TIPOS[alvo.suffix])
            return
        if self.path.startswith("/api/arquivos"):
            self._json(ac.arvore(self.root))
        elif self.path.startswith("/api/state"):
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            self._json(estado(self.root, self.by, base=q.get("base", [None])[0],
                              arquivo=q.get("file", [None])[0]))
        elif self.path in ("/", "/index.html"):
            self._envia(PAGINA.read_bytes(), "text/html; charset=utf-8")
        else:
            self._envia(b"nao encontrado", "text/plain; charset=utf-8", 404)

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

    def do_POST(self) -> None:  # noqa: N802
        if self._de_outro_site():
            self._envia(b"origem recusada", "text/plain; charset=utf-8", 403)
            return
        tamanho = int(self.headers.get("Content-Length", 0))
        pedido = json.loads(self.rfile.read(tamanho) or b"{}")
        if self.path.startswith("/api/arquivos/desfazer"):
            self._json(arquivos_trocar(self.root, pedido))
            return
        if self.path.startswith("/api/arquivos"):
            self._json(arquivos_clicar(self.root, pedido))
            return
        if not self.path.startswith("/api/act"):
            self._envia(b"nao encontrado", "text/plain; charset=utf-8", 404)
            return
        try:
            resposta = agir(self.root, pedido, self.by)
        except Exception as e:                      # o servidor é local; o erro vai à tela
            resposta = {"ok": False, "erro": f"{type(e).__name__}: {e}"}
        resposta["estado"] = estado(self.root, self.by,
                                    base=pedido.get("base") or None,
                                    arquivo=pedido.get("file"))
        self._json(resposta)

    def log_message(self, *args) -> None:           # sem ruído no terminal
        return


def run(root: Path, port: int = 8431, by: str = "", abrir: bool = False) -> int:
    Handler.root = root
    Handler.by = by
    try:
        servidor = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as e:
        if e.errno != 98:
            raise
        raise SystemExit(
            f"a porta {port} já está ocupada — provavelmente por um painel que ficou aberto.\n"
            f"abra http://127.0.0.1:{port} para ver de qual repositório ele é,\n"
            f"ou suba este em outra: km serve --port {port + 1}")
    url = f"http://127.0.0.1:{port}"
    print(f"km · {root.name}  ·  {url}  ·  Ctrl-C encerra")
    if abrir:
        webbrowser.open(url)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nencerrado")
    finally:
        servidor.server_close()
    return 0
