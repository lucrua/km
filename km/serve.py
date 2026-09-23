"""The review surface: the chancel, in a page you can act on.

Plain HTML served from this file, bound to localhost, no build step and no dependencies.
It reads `refs/km/chancela` and the files on disk, and every action goes through the same
functions the CLI uses — the page is a surface, not a second implementation.

It is started when you sit down to review and stopped with Ctrl-C. Nothing runs in the
background, nothing is written except what you ask for: the ref, a reservation in the text,
or a passage you edited here.
"""

from __future__ import annotations

import difflib
import html
import json
import re
import webbrowser
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import chancela as ch
from . import cli

PALAVRA = re.compile(r"\d{4}-\d{2}-\d{2}|\s+|\w+|[^\w\s]")


def diff_inline(antes: str, agora: str) -> tuple[str, float, int]:
    """One stream, in reading order — the Word-like view.

    Prose is read in sequence, and side by side makes the eye jump. But interleaved marks
    turn a heavily rewritten paragraph into soup, so the caller gets the share of words that
    moved and can fall back to two columns when the change is wholesale.
    """
    a, b = PALAVRA.findall(antes), PALAVRA.findall(agora)
    # The share is measured against the longer side: a paragraph that shrinks by half
    # would otherwise report more than 100% of its words moved.
    saida, mexidas, total = [], 0, max(len(a), len(b), 1)
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        ta, tb = html.escape("".join(a[i1:i2])), html.escape("".join(b[j1:j2]))
        if tag == "equal":
            saida.append(tb)
        elif tag == "delete":
            saida.append(f"<del>{ta}</del>"); mexidas += i2 - i1
        elif tag == "insert":
            saida.append(f"<ins>{tb}</ins>"); mexidas += j2 - j1
        else:
            saida.append(f"<del>{ta}</del><ins>{tb}</ins>"); mexidas += max(i2 - i1, j2 - j1)
    return "".join(saida), round(mexidas / total, 3), mexidas


def diff_palavras(antes: str, agora: str) -> tuple[str, str]:
    """Word-level, because prose changes a word and a line diff paints the paragraph."""
    a, b = PALAVRA.findall(antes), PALAVRA.findall(agora)
    esq, dir_ = [], []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        ta, tb = html.escape("".join(a[i1:i2])), html.escape("".join(b[j1:j2]))
        if tag == "equal":
            esq.append(ta); dir_.append(tb)
        elif tag == "delete":
            esq.append(f"<del>{ta}</del>")
        elif tag == "insert":
            dir_.append(f"<ins>{tb}</ins>")
        else:
            esq.append(f"<del>{ta}</del>"); dir_.append(f"<ins>{tb}</ins>")
    return "".join(esq), "".join(dir_)



# ---- markdown, realçado e marcado ----------------------------------------------------
#
# O diff é feito por linha e, dentro da linha mexida, por palavra — é o que pandiff faz
# com prosa: você lê o texto corrido e vê no lugar o que entrou, o que saiu e o que mudou.
# O realce é do **fonte** markdown, não do markdown renderizado: a coluna do meio é
# editável, e editar texto renderizado é WYSIWYG, que reescreve o arquivo inteiro na hora
# de salvar.

CERCA = re.compile(r"^\s*(```|~~~)")
TITULO = re.compile(r"^(#{1,6})\s+(.*)$")
CITACAO = re.compile(r"^(\s*>\s?)(.*)$")
ITEM = re.compile(r"^(\s*)([-*+]|\d{1,3}[.)])\s+(.*)$")
TABELA = re.compile(r"^\s*\|.*\|\s*$")
INLINE = re.compile(r"(`[^`]+`|\*\*[^*]+\*\*|__[^_]+__|\*[^*\s][^*]*\*|_[^_\s][^_]*_"
                    r"|\[[^\]]+\]\([^)]+\)|~~[^~]+~~)")


def realce_inline(texto: str) -> str:
    """Emphasis, code, links — enough for the eye to find its way in the source."""
    out = []
    for parte in INLINE.split(texto):
        if not parte:
            continue
        e = html.escape(parte)
        if parte.startswith("`"):
            out.append(f'<span class="m-cod">{e}</span>')
        elif parte.startswith(("**", "__")):
            out.append(f'<span class="m-forte">{e}</span>')
        elif parte.startswith("~~"):
            out.append(f'<span class="m-riscado">{e}</span>')
        elif parte.startswith("["):
            alvo = e.split("](", 1)
            out.append(f'<span class="m-link">{alvo[0]}]</span>'
                       f'<span class="m-url">({alvo[1]}</span>' if len(alvo) == 2 else e)
        elif parte.startswith(("*", "_")):
            out.append(f'<span class="m-enfase">{e}</span>')
        else:
            out.append(e)
    return "".join(out)


def _classe_da_linha(linha: str, em_codigo: bool) -> str:
    if em_codigo or CERCA.match(linha):
        return "l-cod"
    m = TITULO.match(linha)
    if m:
        return f"l-t{len(m.group(1))}"
    if CITACAO.match(linha):
        marca = next((c for c in linha if c in MARCAS_TXT), "")
        return "l-cit" + (" l-marca" if marca else "")
    if TABELA.match(linha):
        return "l-tab"
    if ITEM.match(linha):
        return "l-item"
    return ""


MARCAS_TXT = "⚠❓🚫"


def realce_linha(linha: str, em_codigo: bool) -> str:
    if em_codigo or CERCA.match(linha):
        return html.escape(linha)
    m = TITULO.match(linha)
    if m:
        return (f'<span class="m-cerquilha">{m.group(1)}</span> '
                + realce_inline(m.group(2)))
    m = CITACAO.match(linha)
    if m:
        return f'<span class="m-cerquilha">{html.escape(m.group(1))}</span>' + realce_inline(m.group(2))
    m = ITEM.match(linha)
    if m:
        return (html.escape(m.group(1)) + f'<span class="m-cerquilha">{m.group(2)}</span> '
                + realce_inline(m.group(3)))
    return realce_inline(linha)


def _palavras(a: str, b: str, lado: str = "dir") -> str:
    """One changed line, word by word — each side showing only its own words.

    The left keeps what left, the right what arrived: the same line read twice, once as it
    was and once as it is, instead of both interleaved in one column.
    """
    pa, pb = PALAVRA.findall(a), PALAVRA.findall(b)
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, pa, pb, autojunk=False).get_opcodes():
        ta, tb = "".join(pa[i1:i2]), "".join(pb[j1:j2])
        if tag == "equal":
            out.append(realce_inline(ta if lado == "esq" else tb))
        elif tag == "delete":
            if lado == "esq":
                out.append(f"<del>{realce_inline(ta)}</del>")
        elif tag == "insert":
            if lado == "dir":
                out.append(f"<ins>{realce_inline(tb)}</ins>")
        else:
            out.append(f"<del>{realce_inline(ta)}</del>" if lado == "esq"
                       else f"<ins>{realce_inline(tb)}</ins>")
    return "".join(out)


def _casar(velhas: list[str], novas: list[str], corte: float = 0.45) -> list[tuple]:
    # devolve tuplas (tipo, linha de antes, linha de agora) — None do lado que não existe
    """Which old line became which new one, inside one changed block.

    Pairing by position turns a rewritten paragraph into soup — two lines with nothing to
    do with each other shown word by word. Pairing by similarity, in order, gives the
    "edited" line where there is one and an honest gone/new where there is not.
    """
    saida: list[tuple] = []
    disponiveis = list(enumerate(velhas))
    usadas: set[int] = set()
    casos: dict[int, int] = {}
    for j, nova in enumerate(novas):
        melhor, nota = None, corte
        for i, velha in disponiveis:
            if i in usadas:
                continue
            r = difflib.SequenceMatcher(None, velha, nova).ratio()
            if r >= nota:
                melhor, nota = i, r
        if melhor is not None:
            usadas.add(melhor)
            casos[j] = melhor
    # A linha que saiu aparece onde ela estava, e não empilhada no começo do bloco: quem
    # lê está lendo o texto, não um relatório de diferenças.
    posicao = 0
    for j, nova in enumerate(novas):
        alvo = casos.get(j)
        limite = alvo if alvo is not None else len(velhas)
        while posicao < limite:
            if posicao not in usadas:
                saida.append(("sumiu", velhas[posicao], None))
            posicao += 1
        if alvo is not None:
            saida.append(("mexido", velhas[alvo], nova))
            posicao = alvo + 1
        else:
            saida.append(("novo", None, nova))
    while posicao < len(velhas):
        if posicao not in usadas:
            saida.append(("sumiu", velhas[posicao], None))
        posicao += 1
    return saida


def marcar(antes: str, depois: str) -> list[dict]:
    """The passage as two aligned columns of text.

    What was removed is cut on the left, where it was — not copied to the right to be
    struck there. The right-hand column is then exactly the file's text, which is what
    makes it editable in place: nothing on it is a ghost of something that no longer
    exists.

    Each row carries `esq` and `dir`; either can be None, and the page draws an empty line
    in its place so the two columns stay side by side.
    """
    a, b = antes.splitlines(), depois.splitlines()
    if not antes:
        pares = [("novo", None, l) for l in b]
    else:
        pares = []
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
            if tag == "equal":
                pares += [("igual", x, y) for x, y in zip(a[i1:i2], b[j1:j2])]
            elif tag == "insert":
                pares += [("novo", None, l) for l in b[j1:j2]]
            elif tag == "delete":
                pares += [("sumiu", l, None) for l in a[i1:i2]]
            else:
                pares += _casar(a[i1:i2], b[j1:j2])

    esq_codigo = dir_codigo = False
    saida = []
    for tipo, velha, nova in pares:
        linha = {"tipo": tipo, "esq": None, "dir": None}
        if velha is not None:
            classe = _classe_da_linha(velha, esq_codigo)
            if CERCA.match(velha):
                esq_codigo = not esq_codigo
            corpo = (_palavras(velha, nova, lado="esq") if tipo == "mexido"
                     else realce_linha(velha, esq_codigo and not CERCA.match(velha)))
            linha["esq"] = {"classe": classe, "html": corpo}
        if nova is not None:
            classe = _classe_da_linha(nova, dir_codigo)
            if CERCA.match(nova):
                dir_codigo = not dir_codigo
            corpo = (_palavras(velha, nova, lado="dir") if tipo == "mexido"
                     else realce_linha(nova, dir_codigo and not CERCA.match(nova)))
            linha["dir"] = {"classe": classe, "html": corpo}
        saida.append(linha)
    return saida


def realcar(texto: str) -> list[dict]:
    """The same shape, with nothing to compare: one column of plain, highlighted text."""
    em_codigo = False
    saida = []
    for linha in texto.splitlines():
        classe = _classe_da_linha(linha, em_codigo)
        if CERCA.match(linha):
            em_codigo = not em_codigo
        corpo = realce_linha(linha, em_codigo and not CERCA.match(linha))
        saida.append({"tipo": "igual", "esq": None, "dir": {"classe": classe, "html": corpo}})
    return saida


def so_esquerda(texto: str) -> list[dict]:
    """A passage that left the file: it only has a left-hand column now."""
    return [{"tipo": "sumiu", "dir": None, "esq": l["dir"]} for l in realcar(texto)]


def _vencida(linha: str, hoje: str) -> bool:
    m = ch.PRAZO.search(linha)
    return bool(m and m.group(1) < hoje)


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
    n = 0
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            if j2 > j1:
                texto = "".join(b.cru for b in bd[j1:j2]).rstrip("\n")
                out.append({"tipo": "igual", "linha": bd[j1].linha, "texto": texto,
                            "linhas": realcar(texto),
                            "n_linhas": len(texto.splitlines())})
            continue
        n += 1
        m = por_n[n]
        out.append(_trecho_mudado(s, m))
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
            "linha": linha or m.linha, "texto": agora,
            "chave": ch.sha_do(antes + "\x00" + agora),
            "linhas": marcar(antes, agora) if agora else so_esquerda(antes),
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
    for rel in ch.documentos(root):
        s = ch.situacao(root, rel, hoje, base=base)
        if not s.depois.strip():
            continue
        cheio = rel == arquivo
        pend, total = cli._pct(s)
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
    under the page, and acting on the rest would be acting on something you did not see."""
    s = ch.situacao(root, rel)
    achadas = ch.unidades_por_sha(s.mudancas, set(shas))
    if len(achadas) != len(set(shas)):
        raise LookupError("o arquivo mudou enquanto você olhava — a tela foi atualizada")
    return s, achadas


def agir(root: Path, pedido: dict, by: str) -> dict:
    """One place for every verdict, so the page and the CLI cannot drift apart."""
    acao = pedido.get("acao")
    rel = pedido.get("file", "")
    if rel not in ch.documentos(root):
        return {"ok": False, "erro": f"{rel} está fora do include do .km/config.json"}

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
               + (f" · falta {ch.percentual(*cli._pct(depois))} deste arquivo"
                  if depois.mudancas else " · arquivo em dia"))
        if saiu:
            msg += f" · {saiu} ressalva(s) removida(s) aprovada(s) junto"
        return {"ok": True, "msg": msg}

    return {"ok": False, "erro": f"ação desconhecida: {acao}"}


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
        if self.path.startswith("/api/state"):
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            self._json(estado(self.root, self.by, base=q.get("base", [None])[0],
                              arquivo=q.get("file", [None])[0]))
        elif self.path in ("/", "/index.html"):
            self._envia(PAGE.encode("utf-8"), "text/html; charset=utf-8")
        else:
            self._envia(b"nao encontrado", "text/plain; charset=utf-8", 404)

    def do_POST(self) -> None:  # noqa: N802
        if not self.path.startswith("/api/act"):
            self._envia(b"nao encontrado", "text/plain; charset=utf-8", 404)
            return
        tamanho = int(self.headers.get("Content-Length", 0))
        pedido = json.loads(self.rfile.read(tamanho) or b"{}")
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


PAGE = """<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>km · chancela</title><style>
/* Escuro por decisao, nao por preferencia do sistema: e onde o autor trabalha. */
:root{color-scheme:dark;--bg:#0F1419;--card:#141B22;--ink:#DCE3EA;--mut:#8695A2;--rule:#232D36;--acc:#6EA8D8;
--ok:#7BC49A;--ok-bg:#16301F;--ace:#E0B463;--ace-bg:#2E2513;--neg:#E09A9A;--neg-bg:#331F1F;
--val:#6EA8D8;--val-bg:#152433;--pend:#8695A2;--pend-bg:#1C242B}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:14.5px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
.topo{display:flex;gap:12px;align-items:center;flex-wrap:wrap;padding:9px 16px;
border-bottom:1px solid var(--rule);position:sticky;top:0;background:var(--bg);z-index:5}
.topo b{font-size:15px}
.q,.topo .n{color:var(--mut);font-size:12px;font-family:ui-monospace,Menlo,monospace}
select,.topo button{font:inherit;font-size:12.5px;padding:3px 9px;border-radius:6px;
border:1px solid var(--rule);background:var(--bg);color:var(--ink);cursor:pointer}
.topo .dir{margin-left:auto;display:flex;gap:8px;align-items:center}
.recado{padding:7px 16px;font-size:13px;background:var(--ok-bg);color:var(--ok);
border-bottom:1px solid var(--rule)}
.recado.ruim{background:var(--neg-bg);color:var(--neg)}
.corpo{display:flex;align-items:flex-start}
.lado{width:210px;flex:0 0 210px;border-right:1px solid var(--rule);padding:9px 7px;
position:sticky;top:45px;max-height:calc(100vh - 45px);overflow:auto}
.lado button{display:block;width:100%;text-align:left;background:none;border:0;color:inherit;
font:inherit;padding:6px 8px;border-radius:6px;cursor:pointer}
.lado button:hover{background:var(--card)}
.lado button[aria-current=true]{background:var(--card);box-shadow:inset 2px 0 0 var(--acc)}
.lado .f{font-family:ui-monospace,Menlo,monospace;font-size:11.5px;word-break:break-all}
.barra{display:flex;height:4px;border-radius:3px;overflow:hidden;margin-top:4px;background:var(--rule)}
.barra i{display:block;height:100%}
.rot{font-family:system-ui,sans-serif;font-size:10px;text-transform:uppercase;
letter-spacing:.08em;color:var(--mut)}

/* A grade: uma linha por trecho, tres colunas alinhadas. O texto corre de cima a baixo;
   o que separa um trecho do outro e uma regua fina, nao um cartao. */
.doc{flex:1;min-width:0;display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr) 196px;
align-items:stretch}
.cabgrade{position:sticky;top:45px;background:var(--bg);border-bottom:1px solid var(--rule);
padding:6px 14px;z-index:4}
.tr{display:contents}
.col{padding:10px 14px 14px;border-bottom:1px solid var(--rule);min-width:0}
.col.base{border-right:1px solid var(--rule);background:color-mix(in srgb,var(--bg) 55%,#000)}
.col.agora{border-right:1px solid var(--rule)}
.col.agora.inteiro{grid-column:1 / 3}
.col.acoes{display:flex;flex-direction:column;gap:4px;align-items:stretch;padding:10px 10px 12px}
.tr.foco .col{background:color-mix(in srgb,var(--card) 70%,transparent)}
.tr.foco .col.agora{box-shadow:inset 2px 0 0 var(--acc)}
.txt{font:12.9px/1.62 ui-monospace,SFMono-Regular,Menlo,monospace;white-space:pre-wrap;
word-break:break-word;overflow-wrap:anywhere}
.ln{display:block;padding:0 2px;border-radius:2px;min-height:1.62em}
.ln.novo{background:var(--ok-bg)}
.ln.sumiu{background:var(--neg-bg);color:var(--neg);text-decoration:line-through;
text-decoration-color:color-mix(in srgb,var(--neg) 60%,transparent)}
.ln.mexido{background:color-mix(in srgb,var(--ace-bg) 55%,transparent)}
del{background:var(--neg-bg);color:var(--neg);text-decoration:line-through;
padding:0 2px;border-radius:2px}
ins{background:var(--ok-bg);color:var(--ok);text-decoration:none;padding:0 2px;border-radius:2px}
/* o realce do fonte markdown */
.l-t1,.l-t2,.l-t3,.l-t4,.l-t5,.l-t6{color:#EDF2F7;font-weight:600}
.l-t1{font-size:16.5px}.l-t2{font-size:15px}.l-t3{font-size:13.8px}
.l-cit{color:#B9C6D2}.l-marca{color:var(--ace)}
.l-cod{color:#9FD3B8}.l-tab{color:#B9C6D2}
/* Tabela não quebra linha: quebrada, uma linha de separadores vira vinte linhas de traços.
   Ela rola na horizontal, dentro da própria coluna. */
.ln.l-tab{white-space:pre;width:max-content;min-width:100%}
.col.base,.col.agora{overflow-x:auto}
.m-cerquilha{color:#54626E}.m-forte{color:#EDF2F7}.m-enfase{color:#CBD5DE;font-style:italic}
.m-cod{color:#9FD3B8}.m-link{color:var(--acc)}.m-url{color:#54626E}
.m-riscado{color:var(--mut)}
.vaziocol{color:#3C4752;font-size:11.5px;font-family:ui-monospace,Menlo,monospace}
.chip{font:10.5px/1.7 ui-monospace,Menlo,monospace;padding:0 8px;border-radius:999px;
white-space:nowrap;align-self:flex-start}
.e-aprovado{color:var(--ok);background:var(--ok-bg)}.e-mexido{color:var(--ace);background:var(--ace-bg)}
.e-pendente{color:var(--pend);background:var(--pend-bg)}.e-negado{color:var(--neg);background:var(--neg-bg)}
.acoes button{font:inherit;font-size:12.5px;padding:4px 10px;border-radius:6px;cursor:pointer;
border:1px solid var(--rule);background:var(--bg);color:var(--ink);text-align:left}
.acoes button:hover{border-color:var(--acc)}
.acoes button.pri{background:var(--ok-bg);border-color:var(--ok-bg);color:var(--ok)}
.acoes button[disabled]{opacity:.35;cursor:not-allowed}
.acoes .marcas{display:flex;gap:4px}
.acoes .marcas button{flex:1;text-align:center;padding:3px 0;font-size:12px}
.nota{font-size:12px;border-left:3px solid var(--neg);background:var(--neg-bg);
padding:6px 9px;margin-bottom:8px;border-radius:0 4px 4px 0}
.nota.aviso{border-color:var(--ace);background:var(--ace-bg)}
/* A coluna 2 é sempre a interface de edição: mesmo texto, mesma medida, sem troca de
   modo. O que muda quando você escreve é só a moldura. */
.txt.edit{outline:0;border-radius:4px;padding:0 4px;margin:0 -4px;
caret-color:var(--acc);min-height:1.6em}
.txt.edit:focus{box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--acc) 45%,transparent)}
.ln.g{color:transparent;background:repeating-linear-gradient(135deg,
color-mix(in srgb,var(--rule) 55%,transparent) 0 6px,transparent 6px 12px);opacity:.45}
.col.agora.sumida{background:color-mix(in srgb,var(--neg-bg) 25%,transparent)}
.form{display:flex;flex-direction:column;gap:5px}
.form input{font:inherit;font-size:12.5px;padding:4px 8px;border-radius:6px;
border:1px solid var(--rule);background:var(--bg);color:var(--ink)}
.vazio{padding:24px;color:var(--mut)}
@media(max-width:1200px){.doc{grid-template-columns:minmax(0,1fr) 150px}
.col.base{display:none}.col.agora.inteiro{grid-column:auto}.lado{width:170px;flex-basis:170px}}

/* uma mudança: cabeçalho de largura inteira, depois um bloco por linha */
.cab-m{grid-column:1 / 4;display:flex;flex-wrap:wrap;gap:6px 12px;align-items:center;
padding:10px 14px 8px;border-top:1px solid var(--ace);background:color-mix(in srgb,var(--ace-bg) 45%,transparent)}
.cab-m.foco{box-shadow:inset 3px 0 0 var(--acc)}
.cab-m .titulo-m{font-weight:600;color:#EDF2F7}
.cab-m .botoes-m{margin-left:auto;display:flex;gap:6px;align-items:center}
.cab-m .botoes-m button{font:inherit;font-size:12.5px;padding:3px 10px;border-radius:6px;cursor:pointer;
border:1px solid var(--rule);background:var(--bg);color:var(--ink)}
.cab-m .botoes-m button.pri{background:var(--ok-bg);border-color:var(--ok-bg);color:var(--ok)}
.cab-m .botoes-m button[disabled]{opacity:.35;cursor:not-allowed}
.cab-m .nota{flex-basis:100%;margin:2px 0 0}
.cab-m .form{flex-direction:row;flex-wrap:wrap;align-items:center}
.col.base.novo,.col.agora.sumiu{background:color-mix(in srgb,var(--bg) 70%,#000)}
.inicio-m{border-top:2px solid color-mix(in srgb,var(--ace) 55%,transparent)}
.foco-m{box-shadow:inset 0 2px 0 var(--acc)}
.acoes .par2{display:flex;gap:4px}.acoes .par2 button{flex:1;padding:4px 6px;font-size:12px}
.acoes .tudo{display:flex;flex-direction:column;gap:4px;padding-bottom:8px;margin-bottom:6px;
border-bottom:1px dashed var(--rule)}
#selecao{position:fixed;z-index:20;display:flex;gap:6px;padding:5px;border-radius:8px;
background:var(--card);border:1px solid var(--acc);box-shadow:0 6px 24px #0008}
#selecao[hidden]{display:none}
#selecao button{font:inherit;font-size:12.5px;padding:4px 11px;border-radius:6px;cursor:pointer;
border:1px solid var(--rule);background:var(--bg);color:var(--ink)}
#selecao button.pri{background:var(--ok-bg);border-color:var(--ok-bg);color:var(--ok)}
.dobra{grid-column:1 / 4;padding:4px 14px;color:var(--mut);font-size:11.5px;cursor:pointer;
font-family:ui-monospace,Menlo,monospace;border-bottom:1px solid var(--rule)}
.dobra:hover{color:var(--ink)}
.aviso-doc{grid-column:1 / 4;padding:12px 14px;color:var(--ok);font-size:13px;border-bottom:1px solid var(--rule)}
.bolinha{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:6px;vertical-align:1px}
.txt.mini{font-size:11.5px;max-height:160px;overflow:auto;margin-top:4px;opacity:.85}
.topo .dir button{padding:3px 8px}
</style></head><body>
<div class="topo"><b id="repo">km</b><span class="n" id="resumo"></span>
<div class="dir">
  <span class="q">no cursor:</span>
  <button onmousedown="event.preventDefault()" onclick="noCursor('⚠️')" title="ressalva: sem certeza">⚠️</button>
  <button onmousedown="event.preventDefault()" onclick="noCursor('❓')" title="a confirmar, com prazo">❓</button>
  <button onmousedown="event.preventDefault()" onclick="noCursor('🚫')" title="discordo — bloqueia a chancela">🚫</button>
  <span style="width:10px"></span>
  <span class="q">comparar com</span><select id="base" onchange="trocarBase()"></select>
  <button onclick="setVer('tudo')" id="v-tudo">texto inteiro</button>
  <button onclick="setVer('mudou')" id="v-mudou">só as mudanças</button>
</div></div>
<div class="recado" id="recado" hidden></div>
<div id="selecao" hidden>
  <button class="pri" onmousedown="event.preventDefault()" onclick="naSelecao('aprovar')">Aprovar seleção</button>
  <button onmousedown="event.preventDefault()" onclick="naSelecao('reverter')">Reverter seleção</button>
</div>
<div class="corpo"><nav class="lado" id="lado"></nav><main class="doc" id="doc"></main></div>
<script>
const $ = (id) => document.getElementById(id);
const esc = s => (s==null?'':String(s)).replace(/[&<>"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]));
const neg = s => esc(s).replace(/\\*\\*(.+?)\\*\\*/g, '<b>$1</b>');
const emDias = n => new Date(Date.now()+n*864e5).toISOString().slice(0,10);
const MODELO = {'⚠️': '> ⚠️ **sem certeza** — ', '🚫': '> 🚫 **discordo** — ',
                '❓': () => '> ❓ **a confirmar até ' + emDias(14) + '** — '};
const TIPO = {novo: 'novo', sumiu: 'saiu', mexido: 'editado'};

let D = null, doc = 0, ver = 'tudo', base = null, foco = null;
let form = null, recado = '', conflito = null;
// O texto que você escreveu e ainda não salvou, por pedaço da tela. Enquanto houver algo
// aqui a tela não se recarrega sozinha: recarregar apagaria o que você digitou.
let sujos = {}, originais = {};
const temSujo = () => Object.keys(sujos).length > 0;
const naChancela = () => !D || D.base === 'refs/km/chancela';
// O texto do arquivo termina em quebra de linha e o da tela não; comparar sem isso evita
// marcar como editado um pedaço em que você só clicou.
const mesmo = (a, b) => (a||'').replace(/\\s+$/, '') === (b||'').replace(/\\s+$/, '');

let carregando = false;
async function carregar(arquivo){
  if (carregando && !arquivo) return;   // um pedido de cada vez: não empilhar recargas
  carregando = true;
  try { return await _carregar(arquivo); } finally { carregando = false; }
}
async function _carregar(arquivo){
  // Só o documento aberto vem com o texto; o resto é a régua lateral.
  const q = new URLSearchParams();
  if (base) q.set('base', base);
  const alvo = arquivo || (D && D.docs[doc] ? D.docs[doc].file : '');
  if (alvo) q.set('file', alvo);
  const nova = await (await fetch('/api/state?' + q)).json();
  base = nova.base;
  const i = nova.docs.findIndex(d => d.file === alvo);
  D = nova; doc = i >= 0 ? i : 0;
  if (D.docs[doc] && !D.docs[doc].cheio) return _carregar(D.docs[doc].file);
  desenhar();
}

async function agir(corpo){
  const r = await fetch('/api/act', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({...corpo, file: D.docs[doc].file,
                          base: naChancela() ? '' : base})});
  const j = await r.json();
  if (j.estado) D = j.estado;
  recado = j.ok ? '✓ ' + (j.msg || 'feito') : '✕ ' + (j.erro || 'não deu');
  if (j.conflito) conflito = {chave: corpo.chave, atual: j.conflito.atual};
  else { conflito = null; form = null; if (j.ok && corpo.chave) delete sujos[corpo.chave]; }
  desenhar();
  if (j.ok && !temSujo()) setTimeout(() => carregar(), 50);
}

const segs = () => (D && D.docs[doc] && D.docs[doc].segmentos) || [];
const mudancas = () => segs().filter(s => s.tipo === 'mudanca');
const achar = (n) => mudancas().find(m => m.n === n);

// ---- a régua da esquerda ----------------------------------------------------------
function lado(){
  let divisor = false;
  $('lado').innerHTML = D.docs.map((d,i)=>{
    let antes = '';
    if (!d.rastreado && !divisor) { divisor = true;
      antes = '<div class="rot" style="padding:11px 8px 5px">sem chancela ainda</div>'; }
    const estado = !d.rastreado ? 'sem chancela' : (d.pendente ? `${d.pct} a aprovar` : 'em dia');
    const cor = !d.rastreado ? 'var(--rule)' : (d.bloqueado ? 'var(--neg)' : (d.pendente ? 'var(--ace)' : 'var(--ok)'));
    return antes + `<button aria-current="${i===doc}" onclick="abrir(${i})">
      <div class="f">${esc(d.file)}</div>
      <div class="q"><i class="bolinha" style="background:${cor}"></i>${estado}${d.vencidas?' · ❓ vencida':''}</div></button>`;
  }).join('');
}

// ---- as linhas, dos dois lados ----------------------------------------------------
// Uma linha de cada lado, sempre no mesmo número: onde um lado não tem nada entra uma linha
// fantasma, que não é texto — ela é pulada na hora de ler o que você escreveu.
const fantasma = () => '<span class="ln g" data-g contenteditable="false"></span>';
function coluna(ls, lado){
  return (ls||[]).map(l => {
    const c = l[lado];
    if (!c) return fantasma();
    return `<span class="ln ${l.tipo === 'igual' ? '' : l.tipo} ${c.classe}">${c.html}</span>`;
  }).join('');
}
function textoDaColuna(el){
  const partes = [];
  for (const n of el.childNodes){
    if (n.nodeType === 1 && n.hasAttribute('data-g')) continue;
    partes.push(n.nodeType === 1 ? n.innerText : n.textContent);
  }
  return partes.join('\\n').replace(/ /g, '');
}
function editavel(chave, linha, texto, html){
  originais[chave] = texto;
  const corpo = sujos[chave] !== undefined
    ? esc(sujos[chave]).split('\\n').map(l => `<span class="ln">${l}</span>`).join('')
    : html;
  return `<div class="txt edit" contenteditable="plaintext-only" spellcheck="false"
    data-chave="${esc(chave)}" data-linha="${linha}"
    oninput="mexeu(this)" onfocus="foco=this.dataset.chave">${corpo}</div>`;
}

// ---- o que fazer, por bloco e por mudança -----------------------------------------
function salvarCel(chave){
  if (sujos[chave] === undefined) return '';
  let out = `<span class="chip e-mexido">editado aqui</span>
    <button class="pri" onclick="salvar('${chave}')">Salvar no arquivo</button>
    <button onclick="descartar('${chave}')">Descartar</button>
    <div class="q">Ctrl+S salva · Esc descarta</div>`;
  if (conflito && conflito.chave === chave) {
    out += `<div class="nota"><b>esse texto mudou no arquivo</b>
      <div class="q">outro agente ou o editor chegaram primeiro. Nada foi sobrescrito.
      No arquivo agora:</div><div class="txt mini">${esc(conflito.atual)}</div></div>
      <button onclick="copiar('${chave}')">Copiar o meu texto</button>`;
  }
  return out;
}

function formulario(chave, shas){
  const rot = {validar:['o que falta confirmar','prazo'], reverter:['por que não serve (opcional)','']}[form.tipo];
  return `<div class="form">
    <input id="f-texto" placeholder="${esc(rot[0])}"
      onkeydown="if(event.key==='Enter')enviar();if(event.key==='Escape')fechar()">
    ${rot[1]==='prazo'?`<input id="f-prazo" value="${emDias(14)}">`:''}
    <button class="pri" onclick="enviar()">${form.tipo==='reverter'?'Reverter':'Escrever e chancelar'}</button>
    <button onclick="fechar()">cancelar</button>
    <div class="q">${form.tipo==='validar'?'o ❓ e o prazo entram no texto, logo depois do bloco'
      :'o texto volta ao que você chancelou'}</div></div>`;
}

function acoesDaMudanca(m){
  const chave = 'c:' + m.chave;
  if (sujos[chave] !== undefined) return salvarCel(chave);
  const shas = m.unidades.map(u => u.sha);
  if (form && form.chave === chave) return formulario(chave, shas);
  const rotulo = {novo: 'novo', saiu: 'saiu', editado: 'editado'}[m.geral];
  if (!naChancela()) return `<span class="chip e-pendente">${rotulo}</span>`;
  const js = esc(JSON.stringify(shas));
  const marcas = m.texto ? `<div class="marcas">
      <button onclick="marcaNaMudanca('${chave}','⚠️')" title="ressalva: sem certeza">⚠️</button>
      <button onclick="marcaNaMudanca('${chave}','🚫')" title="discordo — bloqueia a chancela">🚫</button></div>` : '';
  return `<span class="chip ${m.geral==='saiu'?'e-negado':(m.geral==='novo'?'e-aprovado':'e-mexido')}">${rotulo}</span>
    <button class="pri" ${m.bloqueio?'disabled title="resolva o 🚫 primeiro"':''} onclick="aprovar(${js})">${m.geral==='saiu'?'Aprovar a remoção':'Aprovar'}</button>
    <div class="par2">
      <button onclick="abrirForm('${chave}','validar',${js})">A validar…</button>
      <button onclick="abrirForm('${chave}','reverter',${js})">${m.geral==='saiu'?'Trazer de volta':'Reverter'}</button></div>
    ${marcas}
    <div class="q">para aprovar só uma parte, selecione o texto</div>`;
}

function avisosDaMudanca(m){
  let out = '';
  for (const s of (m.sumidas||[])) out += `<div class="nota"><b>ressalva removida</b> — ${neg(s.replace(/^\\s*>\\s*/,''))}
    <div class="q">estava na chancela; aprovar aqui aprova a remoção</div></div>`;
  if (m.bloqueio) out += `<div class="nota"><b>🚫 bloqueado</b> — ${neg(m.bloqueio.replace(/^\\s*>\\s*/,''))}</div>`;
  return out;
}

// ---- o documento ----------------------------------------------------------------
function desenhar(){
  if (!D) return;
  $('repo').textContent = D.repo;
  const em = D.docs.filter(d => d.rastreado && !d.pendente).length;
  const sem = D.docs.filter(d => !d.rastreado).length;
  $('resumo').textContent = `${D.docs.length} arquivos · ${em} em dia · `
    + (D.pct ? `${D.pct} do conteúdo a aprovar` : 'nada a aprovar') + (sem ? ` · ${sem} sem chancela` : '');
  const r = $('recado'); r.hidden = !recado; r.textContent = recado;
  r.className = 'recado' + (recado.startsWith('✕') ? ' ruim' : '');
  $('base').innerHTML = D.revisoes.map(v =>
    `<option value="${esc(v.rev)}" ${v.rev===D.base?'selected':''}>${esc(v.label)}</option>`).join('');
  $('v-tudo').setAttribute('aria-pressed', ver==='tudo');
  $('v-mudou').setAttribute('aria-pressed', ver==='mudou');
  lado();

  const d = D.docs[doc];
  originais = {};
  let html = `<div class="cabgrade rot">${naChancela() ? 'a chancela' : esc(D.base)}</div>
    <div class="cabgrade rot">${esc(d.file)} — agora</div>
    <div class="cabgrade rot">${naChancela() ? 'o que fazer' : 'só leitura — os botões agem na chancela'}</div>`;
  if (!segs().some(s => s.tipo === 'mudanca'))
    html += `<div class="aviso-doc">${d.rastreado ? '✓ Em dia com a chancela' + (d.em ? ' de ' + esc(d.em) : '') + '. Nada a decidir neste arquivo.' : ''}</div>`;
  for (const s of segs()){
    if (s.tipo === 'igual') {
      const chave = 'g:' + s.linha;
      if (ver === 'mudou' && sujos[chave] === undefined) {
        html += `<div class="dobra" onclick="setVer('tudo')">⋯ ${s.n_linhas} linhas sem mudança</div>`;
        continue;
      }
      html += `<div class="col agora inteiro">${editavel(chave, s.linha, s.texto, coluna(s.linhas, 'dir'))}</div>
        <div class="col acoes">${salvarCel(chave)}</div>`;
      continue;
    }
    const chave = 'c:' + s.chave;
    const inicio = ` inicio-m${foco === 'm:' + s.n ? ' foco-m' : ''}`;
    html += `<div class="col base ${s.geral}${inicio}" id="m${s.n}"><div class="txt">${coluna(s.linhas, 'esq')}</div></div>
      <div class="col agora ${s.geral}${inicio}">${avisosDaMudanca(s)}${s.texto
        ? editavel(chave, s.linha, s.texto, coluna(s.linhas, 'dir'))
        : '<div class="vaziocol">— saiu do arquivo —</div>'}</div>
      <div class="col acoes${inicio}">${acoesDaMudanca(s)}</div>`;
  }
  $('doc').innerHTML = html;
  const campo = $('f-texto');
  if (campo) campo.focus();
}

// ---- gestos -----------------------------------------------------------------------
function abrir(i){
  if (temSujo() && !confirm('Há texto editado e não salvo. Sair mesmo assim?')) return;
  sujos = {}; conflito = null; form = null; foco = null; scrollTo(0,0);
  carregar(D.docs[i].file);
}
function fechar(){ form = null; desenhar(); }
function abrirForm(chave, tipo, shas){ form = {chave, tipo, shas}; desenhar(); }
function aprovar(shas){ agir({acao:'aprovar', shas}); }
function enviar(){
  const texto = ($('f-texto')||{}).value || '';
  const prazo = ($('f-prazo')||{}).value || '';
  if (form.tipo === 'validar') return agir({acao:'validar', shas: form.shas, texto, prazo});
  return agir({acao:'reverter', shas: form.shas, motivo: texto});
}
function celula(chave){ return document.querySelector(`.txt.edit[data-chave="${CSS.escape(chave)}"]`); }
function mexeu(el){
  const chave = el.dataset.chave;
  const texto = textoDaColuna(el);
  if (mesmo(texto, originais[chave])) delete sujos[chave]; else sujos[chave] = texto;
  // Só a coluna das ações muda; o texto que você está digitando fica onde está.
  const cel = el.closest('.col').nextElementSibling;
  if (cel && cel.classList.contains('acoes')) {
    if (chave.startsWith('c:')) {
      const m = mudancas().find(x => 'c:' + x.chave === chave);
      cel.innerHTML = m ? acoesDaMudanca(m) : salvarCel(chave);
    } else cel.innerHTML = salvarCel(chave);
  }
}
function salvar(chave){
  if (sujos[chave] === undefined) return;
  const el = celula(chave);
  agir({acao:'salvar', chave, original: originais[chave], texto: sujos[chave],
        linha: el ? Number(el.dataset.linha) : 1});
}
function descartar(chave){ delete sujos[chave]; if (conflito && conflito.chave === chave) conflito = null; desenhar(); }
function copiar(chave){ navigator.clipboard?.writeText(sujos[chave] || ''); recado = '✓ seu texto está na área de transferência'; desenhar(); }

// A marca entra onde está o cursor, no formato combinado, e vira texto seu: você completa
// e salva como qualquer outra edição.
function inserir(el, marca){
  el.focus();
  const modelo = typeof MODELO[marca] === 'function' ? MODELO[marca]() : MODELO[marca];
  // A marca é um bloco próprio: vai para o fim da linha onde está o cursor, com linha em
  // branco antes e depois. Colada no meio da linha, ela viraria parte do parágrafo — e
  // sem a linha em branco depois, o parágrafo seguinte viraria parte da citação.
  const s = getSelection();
  s.modify('move', 'forward', 'lineboundary');
  document.execCommand('insertText', false, '\\n\\n' + modelo + '\\n');
  s.modify('move', 'backward', 'character');
}
function noCursor(marca){
  const s = getSelection();
  const el = s && s.anchorNode && (s.anchorNode.nodeType === 1 ? s.anchorNode : s.anchorNode.parentElement)?.closest('.txt.edit');
  if (!el) { recado = '✕ clique no texto, onde a marca deve entrar, e depois no botão'; return desenhar(); }
  inserir(el, marca);
}
function marcaNaMudanca(chave, marca){
  const el = celula(chave); if (!el) return;
  el.focus();
  const r = document.createRange(); r.selectNodeContents(el); r.collapse(false);
  const s = getSelection(); s.removeAllRanges(); s.addRange(r);
  inserir(el, marca);
}
// ---- aprovar parte de um bloco ----------------------------------------------------
// Como aceitar metade de um hunk numa revisão de código: selecione, na coluna do texto
// de hoje, o pedaço cuja mudança você aceita. O resto do bloco continua pendente.
function deslocamento(el, no, off){
  // posição no texto do bloco (o mesmo texto que o servidor tem), pulando as fantasmas
  if (no === el) {
    let total = 0, primeiro = true;
    for (const f of [...el.childNodes].slice(0, off)) {
      if (f.nodeType === 1 && f.hasAttribute('data-g')) continue;
      if (!primeiro) total += 1; primeiro = false;
      total += (f.nodeType === 1 ? f.innerText : f.textContent).length;
    }
    return total;
  }
  let total = 0, primeiro = true;
  for (const f of el.childNodes) {
    if (f.nodeType === 1 && f.hasAttribute('data-g')) continue;
    if (!primeiro) total += 1; primeiro = false;
    if (f === no || f.contains(no)) {
      const r = document.createRange(); r.selectNodeContents(f); r.setEnd(no, off);
      return total + r.toString().length;
    }
    total += (f.nodeType === 1 ? f.innerText : f.textContent).length;
  }
  return total;
}
function selecaoAtual(){
  const s = getSelection();
  if (!s || s.isCollapsed || !s.rangeCount || !naChancela()) return null;
  const r = s.getRangeAt(0);
  const host = n => (n.nodeType === 1 ? n : n.parentElement)?.closest('.txt.edit[data-chave^="c:"]');
  const el = host(r.startContainer);
  if (!el || el !== host(r.endContainer)) return null;       // um trecho de cada vez
  const chave = el.dataset.chave;
  if (sujos[chave] !== undefined) return {erro: 'salve ou descarte a edição deste trecho antes de aprovar parte dele'};
  const m = mudancas().find(x => 'c:' + x.chave === chave);
  if (!m) return null;
  const a = deslocamento(el, r.startContainer, r.startOffset);
  const b = deslocamento(el, r.endContainer, r.endOffset);
  // O motor aplica por bloco; a tela converte a seleção no trecho em "esta parte deste bloco".
  const shas = [], parciais = [];
  for (const u of m.unidades) {
    if (u.ini === u.fim) { if (a <= u.ini && u.ini <= b) shas.push(u.sha); continue; }
    if (b <= u.ini || a >= u.fim) continue;
    if (a <= u.ini && b >= u.fim) shas.push(u.sha);
    else parciais.push({sha: u.sha, ini: Math.max(a, u.ini) - u.ini, fim: Math.min(b, u.fim) - u.ini});
  }
  if (!shas.length && !parciais.length) return null;
  return {shas, parciais, rect: r.getBoundingClientRect()};
}
document.addEventListener('selectionchange', () => {
  const barra = $('selecao'), sel = selecaoAtual();
  if (!sel || sel.erro) { barra.hidden = true; return; }
  barra.hidden = false;
  barra.style.top = Math.max(50, sel.rect.top - 40) + 'px';
  barra.style.left = Math.min(innerWidth - 300, Math.max(10, sel.rect.left)) + 'px';
});
function naSelecao(acao){
  const sel = selecaoAtual();
  if (!sel) return;
  if (sel.erro) { recado = '✕ ' + sel.erro; return desenhar(); }
  $('selecao').hidden = true;
  agir({acao, shas: sel.shas, parciais: sel.parciais});
}

function setVer(v){ ver = v; desenhar(); }
function trocarBase(){ base = $('base').value; carregar(); }

document.addEventListener('keydown', (e)=>{
  const el = e.target;
  if ((e.ctrlKey || e.metaKey) && e.key === 's') {
    e.preventDefault();
    if (el.isContentEditable) salvar(el.dataset.chave);
    return;
  }
  if (el.isContentEditable) {
    if (e.key === 'Escape') { el.blur(); descartar(el.dataset.chave); }
    return;   // dentro do texto, letra é letra
  }
  if (el.tagName === 'INPUT' || el.tagName === 'SELECT') { if (e.key === 'Escape') fechar(); return; }
  const ms = mudancas();
  if (!ms.length) return;
  const atual = foco && foco.startsWith('m:') ? Number(foco.slice(2)) : 0;
  const pos = ms.findIndex(m => m.n === atual);
  const ir = (m) => { foco = 'm:' + m.n; desenhar(); $('m' + m.n)?.scrollIntoView({block:'center'}); };
  if (e.key === 'j') ir(ms[Math.min(pos + 1, ms.length - 1)]);
  else if (e.key === 'k') ir(ms[Math.max(pos - 1, 0)]);
  else if (e.key === 'a' && pos >= 0 && naChancela()) aprovar(ms[pos].unidades.map(u => u.sha));
});

// O arquivo muda por fora: um agente escreve, o editor salva. A tela se atualiza sozinha
// quando você não está no meio de escrever nada.
setInterval(()=>{ if (!form && !temSujo()) carregar(); }, 8000);
carregar();
</script></body></html>"""
