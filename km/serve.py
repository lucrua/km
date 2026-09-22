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


def _palavras(a: str, b: str) -> str:
    """One changed line, word by word — where the eye actually needs the detail."""
    pa, pb = PALAVRA.findall(a), PALAVRA.findall(b)
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, pa, pb, autojunk=False).get_opcodes():
        ta, tb = "".join(pa[i1:i2]), "".join(pb[j1:j2])
        if tag == "equal":
            out.append(realce_inline(tb))
        elif tag == "delete":
            out.append(f"<del>{realce_inline(ta)}</del>")
        elif tag == "insert":
            out.append(f"<ins>{realce_inline(tb)}</ins>")
        else:
            out.append(f"<del>{realce_inline(ta)}</del><ins>{realce_inline(tb)}</ins>")
    return "".join(out)


def _casar(velhas: list[str], novas: list[str], corte: float = 0.45) -> list[tuple]:
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
            saida.append(("mexido", nova, velhas[alvo]))
            posicao = alvo + 1
        else:
            saida.append(("novo", nova, None))
    while posicao < len(velhas):
        if posicao not in usadas:
            saida.append(("sumiu", velhas[posicao], None))
        posicao += 1
    return saida


def marcar(antes: str, depois: str) -> list[dict]:
    """The passage as continuous text, with what is new, gone or edited marked in place."""
    a, b = antes.splitlines(), depois.splitlines()
    saida: list[dict] = []
    if antes is None or not antes:
        pares = [("novo", l, None) for l in b]
    else:
        pares = []
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
            if tag == "equal":
                pares += [("igual", l, None) for l in b[j1:j2]]
            elif tag == "insert":
                pares += [("novo", l, None) for l in b[j1:j2]]
            elif tag == "delete":
                pares += [("sumiu", l, None) for l in a[i1:i2]]
            else:
                pares += _casar(a[i1:i2], b[j1:j2])

    em_codigo = False
    for tipo, linha, velha in pares:
        classe = _classe_da_linha(linha, em_codigo)
        if CERCA.match(linha):
            em_codigo = not em_codigo
        corpo = (_palavras(velha, linha) if tipo == "mexido"
                 else realce_linha(linha, em_codigo and not CERCA.match(linha)))
        saida.append({"tipo": tipo, "classe": classe, "html": corpo or "&nbsp;"})
    return saida


def realcar(texto: str) -> list[dict]:
    """The same, with nothing to compare: the left-hand column."""
    em_codigo = False
    saida = []
    for linha in texto.splitlines():
        classe = _classe_da_linha(linha, em_codigo)
        if CERCA.match(linha):
            em_codigo = not em_codigo
        saida.append({"tipo": "igual", "classe": classe,
                      "html": realce_linha(linha, em_codigo and not CERCA.match(linha)) or "&nbsp;"})
    return saida


def _corpo(trecho) -> str:
    """The passage without its own heading — the heading is already the card's title."""
    if trecho is None:
        return ""
    if trecho.titulo_bruto:
        return trecho.texto.split("\n", 1)[1] if "\n" in trecho.texto else ""
    return trecho.texto


def _vencida(linha: str, hoje: str) -> bool:
    m = ch.PRAZO.search(linha)
    return bool(m and m.group(1) < hoje)


def _ultima(root: Path, rel: str) -> str:
    if not ch.existe(root):
        return ""
    linhas = ch.historico(root, rel, None, limite=1).strip().splitlines()
    partes = linhas[0].split(" ") if linhas else []
    return partes[1] if len(partes) > 1 else ""


def estado(root: Path, by: str = "", base: str | None = None,
           arquivo: str | None = None) -> dict:
    """The state for the page.

    The heavy part — every line of every passage, highlighted and marked — is built only
    for the document being read. Building it for the whole repository was 4.7 MB and 1.3 s
    per request, and the page asks again every eight seconds.
    """
    hoje = date.today().isoformat()
    docs = []
    for rel in ch.documentos(root):
        s = ch.situacao(root, rel, hoje, base=base)
        if not s.depois.strip():
            continue
        cheio = rel == arquivo
        # O texto que a tela mostra e a caixa edita é o do arquivo, cru. A versão
        # canonizada (tabela re-alinhada vira a mesma tabela) serve só para decidir o que
        # mudou de verdade — mostrar ou salvar o texto canonizado reescreveria o arquivo
        # do autor por conta própria.
        base_cru = ""
        antes: dict = {}
        agora: dict = {}
        if cheio:
            base_cru = (ch.chancelado(root, rel) if base in (None, ch.REF)
                        else ch.conteudo_em(root, base, rel)) or ""
            antes = {x.caminho: x for x in ch.trechos(base_cru)}
            agora = {x.caminho: x for x in ch.trechos(ch.atual(root, rel) or "")}

        trechos = []
        for e in ch.estados(s):
            t = {
                "heading": e["heading"], "path": e["path"], "line": e["line"],
                "lines": e["lines"], "estado": e["state"], "bloqueado": e["blocked"],
                "ressalvas": [{"mark": c["mark"], "text": c["text"].lstrip("> ").strip(),
                               "vencida": c["mark"] == "❓" and _vencida(c["text"], hoje)}
                              for c in e["caveats"]],
            }
            if cheio:
                atual_txt = agora[e["path"]].texto if e["path"] in agora else ""
                base_txt = antes[e["path"]].texto if e["path"] in antes else ""
                t.update({
                    "texto": atual_txt,
                    # The sha of what the page is showing: saving sends it back, and the
                    # server refuses if the passage moved meanwhile.
                    "sha": ch.sha_do(atual_txt),
                    "sumidas": ch.sumidas(base_txt.splitlines(), atual_txt.splitlines()),
                    "base": realcar(base_txt) if base_txt else [],
                    # De pé é de pé: se a única diferença for cosmética — uma tabela
                    # re-alinhada —, o texto aparece limpo, sem marcas que não pedem nada.
                    "marcado": (realcar(atual_txt) if e["state"] == "com chancela"
                                else marcar(base_txt, atual_txt)),
                })
            else:
                t["sumidas"] = e["dropped"]
            trechos.append(t)

        # Passages that exist in the chancel and no longer in the file: the deletion is a
        # change like any other, and nothing else on screen would show it.
        if cheio:
            for caminho, velho in antes.items():
                if caminho in agora:
                    continue
                trechos.append({
                    "heading": velho.titulo, "path": caminho, "line": velho.linha,
                    "lines": velho.linhas, "estado": "apagado", "bloqueado": "",
                    "ressalvas": [], "sumidas": [], "texto": "", "sha": "",
                    "base": realcar(velho.texto), "marcado": [],
                })
        docs.append({"file": rel, "trechos": trechos, "rastreado": s.tem_chancela,
                     "cheio": cheio, "em": _ultima(root, rel) if cheio else "",
                     "linhas": len(s.depois.splitlines())})
    docs.sort(key=lambda d: (not d["rastreado"], d["file"]))
    return {"repo": root.name, "root": str(root), "docs": docs, "hoje": hoje, "by": by,
            "base": base or ch.REF, "revisoes": ch.revisoes(root)}


# ---- the actions ---------------------------------------------------------------------

def _alvos(root: Path, rel: str, caminho: str) -> tuple[ch.Situacao, list, list[str]]:
    s = ch.situacao(root, rel)
    est = next((e for e in ch.estados(s) if e["path"] == caminho), None)
    if est is None:
        raise KeyError(caminho)
    alvos = [h for h in s.hunks if h.n in est["hunks"]]
    titulos = list(dict.fromkeys(h.titulo for h in alvos))
    return s, alvos, titulos


def agir(root: Path, pedido: dict, by: str) -> dict:
    """One place for every verdict, so the page and the CLI cannot drift apart."""
    acao = pedido.get("acao")
    rel = pedido.get("file", "")
    caminho = pedido.get("path", "")
    texto = (pedido.get("texto") or "").strip()

    if acao == "salvar":
        try:
            ch.substituir_trecho(root, rel, caminho, pedido.get("texto", ""),
                                 pedido.get("sha", ""))
        except ch.Conflito as e:
            return {"ok": False, "erro": "o texto mudou desde que você abriu",
                    "conflito": {"atual": e.atual}}
        return {"ok": True, "msg": "salvo no arquivo"}

    if acao == "marca":
        if not ch.inserir_marca(root, rel, caminho, pedido.get("marca", "⚠️"), texto,
                                pedido.get("prazo")):
            return {"ok": False, "erro": "não consegui escrever a marca"}
        return {"ok": True, "msg": "escrito no texto"}

    try:
        s, alvos, titulos = _alvos(root, rel, caminho)
    except KeyError:
        return {"ok": False, "erro": "esse trecho não está mais no arquivo"}

    if acao == "reverter":
        if not alvos:
            return {"ok": False, "erro": "nada mudou aqui desde a chancela"}
        cli.reverter(root, rel, alvos, s)
        return {"ok": True, "msg": "de volta ao texto chancelado: " + ", ".join(titulos)}

    if acao in ("aprovar", "validar"):
        if acao == "validar":
            if not ch.inserir_marca(root, rel, caminho, "❓", texto, pedido.get("prazo")):
                return {"ok": False, "erro": "não consegui escrever o prazo no texto"}
            s, alvos, titulos = _alvos(root, rel, caminho)   # o arquivo acabou de mudar
        if not alvos:
            return {"ok": False, "erro": "nada pendente neste trecho"}
        barrados = [h for h in alvos if h.bloqueio]
        if barrados and not pedido.get("force"):
            return {"ok": False, "erro": "🚫 " + barrados[0].bloqueio.lstrip("> ")}
        commit = cli.chancelar(root, rel, alvos, s, pedido.get("motivo"), by)
        extra = [l for h in alvos for l in h.sumidas]
        msg = f"na chancela ({commit[:8]}): " + ", ".join(titulos)
        if extra:
            msg += f" · {len(extra)} ressalva(s) saíram junto"
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
:root{--bg:#0F1419;--card:#141B22;--ink:#DCE3EA;--mut:#8695A2;--rule:#232D36;--acc:#6EA8D8;
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
.doc{flex:1;min-width:0;display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr) 168px;
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
.ln{display:block;padding:0 2px;border-radius:2px}
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
textarea{width:100%;min-height:200px;font:12.9px/1.62 ui-monospace,Menlo,monospace;padding:8px;
border-radius:6px;border:1px solid var(--acc);background:var(--bg);color:var(--ink);resize:vertical}
.form{display:flex;flex-direction:column;gap:5px}
.form input{font:inherit;font-size:12.5px;padding:4px 8px;border-radius:6px;
border:1px solid var(--rule);background:var(--bg);color:var(--ink)}
.vazio{padding:24px;color:var(--mut)}
@media(max-width:1200px){.doc{grid-template-columns:minmax(0,1fr) 150px}
.col.base{display:none}.col.agora.inteiro{grid-column:auto}.lado{width:170px;flex-basis:170px}}
</style></head><body>
<div class="topo"><b id="repo">km</b><span class="n" id="resumo"></span>
<div class="dir">
  <span class="q">comparar com</span><select id="base" onchange="trocarBase()"></select>
  <button onclick="setVer('tudo')" id="v-tudo" aria-pressed="true">texto inteiro</button>
  <button onclick="setVer('mudou')" id="v-mudou">só o que mudou</button>
</div></div>
<div class="recado" id="recado" hidden></div>
<div class="corpo"><nav class="lado" id="lado"></nav><main class="doc" id="doc"></main></div>
<script>
const $ = (id) => document.getElementById(id);
const esc = s => (s==null?'':String(s)).replace(/[&<>]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[m]));
const neg = s => esc(s).replace(/\\*\\*(.+?)\\*\\*/g, '<b>$1</b>');
const CH = {'com chancela':'e-aprovado','mexido':'e-mexido','sem chancela':'e-pendente',
            'apagado':'e-negado'};
const emDias = n => new Date(Date.now()+n*864e5).toISOString().slice(0,10);
const pedeVoce = t => t.estado !== 'com chancela' || !!t.bloqueado
  || (t.sumidas||[]).length > 0 || (t.ressalvas||[]).some(r => r.vencida);

let D = null, doc = 0, foco = 0, ver = 'tudo', base = null;
let form = null, editor = null, recado = '', meuTexto = '';

async function carregar(arquivo){
  // Só o documento aberto vem com o texto inteiro marcado; o resto é a régua lateral.
  const q = new URLSearchParams();
  if (base) q.set('base', base);
  const alvoArq = arquivo || (D && D.docs[doc] ? D.docs[doc].file : '');
  if (alvoArq) q.set('file', alvoArq);
  const nova = await (await fetch('/api/state?' + q)).json();
  base = nova.base;
  const i = nova.docs.findIndex(d => d.file === alvoArq);
  D = nova;
  doc = i >= 0 ? i : 0;
  if (!D.docs[doc] || !D.docs[doc].cheio) return carregar(D.docs[doc] ? D.docs[doc].file : '');
  desenhar();
}

async function agir(corpo){
  const r = await fetch('/api/act', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({...corpo, base: base === 'refs/km/chancela' ? '' : base})});
  const j = await r.json();
  if (j.estado) { D = j.estado; }
  recado = j.ok ? '✓ ' + (j.msg || 'feito') : '✕ ' + (j.erro || 'não deu');
  if (j.conflito) { editor = {i: editor ? editor.i : foco, conflito: j.conflito.atual}; }
  else { form = null; if (j.ok) editor = null; }
  desenhar();
  if (j.ok) setTimeout(() => { if (!form && !editor) carregar(); }, 50);
}

const trechos = () => (D && D.docs[doc] ? D.docs[doc].trechos : []);
const trecho = (i) => trechos()[i];
const alvo = (i) => ({file: D.docs[doc].file, path: trecho(i).path});
const visiveis = () => trechos().map((t,i)=>[t,i]).filter(([t])=> ver === 'tudo' || pedeVoce(t));

function contar(d){
  const c = {pe:0, mex:0, pend:0, neg:0};
  for (const t of d.trechos){
    if (t.bloqueado || t.estado === 'apagado') c.neg++;
    else if (t.estado === 'mexido') c.mex++;
    else if (t.estado === 'sem chancela') c.pend++;
    else c.pe++;
  }
  return c;
}

function lado(){
  let divisor = false;
  $('lado').innerHTML = D.docs.map((d,i)=>{
    let antes = '';
    if (!d.rastreado && !divisor) { divisor = true;
      antes = '<div class="rot" style="padding:11px 8px 5px">sem chancela ainda</div>'; }
    const c = contar(d), t = d.trechos.length || 1;
    const seg = [[c.pe,'var(--ok)'],[c.mex,'var(--ace)'],[c.neg,'var(--neg)'],[c.pend,'var(--rule)']]
      .map(([n,cor])=>n?`<i style="width:${100*n/t}%;background:${cor}"></i>`:'').join('');
    return antes + `<button aria-current="${i===doc}" onclick="abrir(${i})">
      <div class="f">${esc(d.file)}</div>
      <div class="q">${c.pe}/${d.trechos.length} de pé${c.mex?' · '+c.mex+' mexidos':''}</div>
      <div class="barra">${seg}</div></button>`;}).join('');
}

function linhas(ls){
  if (!ls || !ls.length) return '<div class="vaziocol">— nada aqui —</div>';
  return '<div class="txt">' + ls.map(l =>
    `<span class="ln ${l.tipo === 'igual' ? '' : l.tipo} ${l.classe}">${l.html}</span>`).join('') + '</div>';
}

function avisos(t){
  let out = '';
  for (const s of (t.sumidas||[])) {
    out += `<div class="nota"><b>ressalva removida</b> — ${neg(s.replace(/^\\s*>\\s*/,''))}
      <div class="q">estava na chancela. Aprovar aqui aprova a remoção.</div></div>`;
  }
  if (t.bloqueado) out += `<div class="nota"><b>🚫 bloqueado</b> — ${neg(t.bloqueado.replace(/^\\s*>\\s*/,''))}</div>`;
  for (const r of (t.ressalvas||[])) {
    if (r.vencida) out += `<div class="nota aviso"><b>❓ prazo vencido</b> — ${neg(r.text)}</div>`;
  }
  return out;
}

function acoes(t, i){
  if (editor && editor.i === i) {
    return `<button class="pri" onclick="salvar(${i})">Salvar</button>
      <button onclick="fechar()">cancelar</button>
      <div class="q">salva só este trecho</div>`;
  }
  if (form && form.i === i) {
    const rot = {validar:['o que falta confirmar','prazo'], reverter:['por que não serve',''],
                 '⚠️':['a dúvida, como vai para o texto',''], '🚫':['o que está errado','']}[form.tipo];
    return `<div class="form">
      <input id="f-texto" placeholder="${esc(rot[0])}" autofocus
        onkeydown="if(event.key==='Enter')enviar(${i});if(event.key==='Escape')fechar()">
      ${rot[1]==='prazo'?`<input id="f-prazo" value="${emDias(14)}">`:''}
      <button class="pri" onclick="enviar(${i})">${form.tipo==='reverter'?'Reverter':'Escrever'}</button>
      <button onclick="fechar()">cancelar</button></div>`;
  }
  if (t.estado === 'apagado') {
    return `<span class="chip e-negado">apagado</span>
      <div class="q">saiu do arquivo depois da chancela</div>
      <button onclick="agir({...alvo(${i}), acao:'aprovar', motivo:'trecho removido'})">Aprovar a remoção</button>`;
  }
  const trava = t.bloqueado ? 'disabled title="resolva o 🚫 primeiro"' : '';
  const marcas = `<div class="marcas">
      <button onclick="abrirForm(${i},'⚠️')" title="ressalva: sem certeza">⚠️</button>
      <button onclick="abrirForm(${i},'🚫')" title="discordo — bloqueia a chancela">🚫</button>
      <button onclick="abrirForm(${i},'validar')" title="a validar, com prazo">❓</button>
      <button onclick="editar(${i})" title="editar este trecho">✎</button></div>`;
  // Um trecho que esta de pe nao precisa de tres botoes ocupando a altura do texto: ele
  // precisa de uma marca dizendo que esta de pe, e das marcas se voce quiser escrever algo.
  if (t.estado === 'com chancela' && !t.bloqueado && !(t.sumidas||[]).length) {
    return `<span class="chip e-aprovado">de pé</span>${marcas}
      <div class="q">linha ${t.line} · ${t.lines}l</div>`;
  }
  return `<span class="chip ${CH[t.estado]||'e-pendente'}">${esc(t.estado)}</span>
    <button class="pri" ${trava} onclick="agir({...alvo(${i}), acao:'aprovar'})">Aprovar</button>
    <button onclick="abrirForm(${i},'validar')">A validar…</button>
    <button onclick="abrirForm(${i},'reverter')">Reverter…</button>
    ${marcas}<div class="q">linha ${t.line} · ${t.lines}l</div>`;
}

function desenhar(){
  if (!D) return;
  $('repo').textContent = D.repo;
  const c = D.docs.reduce((a,d)=>{const x=contar(d);
    return {pe:a.pe+x.pe, mex:a.mex+x.mex, pend:a.pend+x.pend};},{pe:0,mex:0,pend:0});
  $('resumo').textContent = `${D.docs.length} arquivos · ${c.pe} de pé · ${c.mex} mexidos · ${c.pend} sem chancela`;
  const r = $('recado'); r.hidden = !recado; r.textContent = recado;
  r.className = 'recado' + (recado.startsWith('✕') ? ' ruim' : '');
  $('base').innerHTML = D.revisoes.map(v =>
    `<option value="${esc(v.rev)}" ${v.rev===D.base?'selected':''}>${esc(v.label)}</option>`).join('');
  $('v-tudo').setAttribute('aria-pressed', ver==='tudo');
  $('v-mudou').setAttribute('aria-pressed', ver==='mudou');
  lado();

  const d = D.docs[doc];
  const vis = visiveis();
  const cabecalho = `<div class="cabgrade rot">${D.base === 'refs/km/chancela' ? 'a chancela' : esc(D.base)}</div>
    <div class="cabgrade rot">${esc(d.file)} — agora${D.base === 'refs/km/chancela' ? '' : ' (os botões continuam escrevendo na chancela)'}</div>
    <div class="cabgrade rot">o que fazer</div>`;
  $('doc').innerHTML = cabecalho + (vis.length ? vis.map(([t,i]) => {
    // Trecho de pé tem as duas colunas iguais. Em vez de repetir o texto, ele ocupa a
    // largura inteira: o que se lê a maior parte do tempo é o documento, não o diff.
    const igual = t.estado === 'com chancela' && !t.bloqueado && !(t.sumidas||[]).length
      && !(editor && editor.i === i);
    const meio = `<div class="col agora ${igual?'inteiro':''}">${avisos(t)}${editor && editor.i === i
        ? caixa(t, i) : linhas(t.marcado)}</div>`;
    return `<div class="tr ${foco===i?'foco':''}" id="t${i}" onclick="focar(${i})">
      ${igual ? '' : `<div class="col base">${linhas(t.base)}</div>`}
      ${meio}
      <div class="col acoes">${acoes(t, i)}</div>
    </div>`; }).join('') : '<div class="vazio">Nada mudou neste arquivo.</div>');
  const campo = $('f-texto') || $('e-texto');
  if (campo) campo.focus();
}

function caixa(t, i){
  if (editor.conflito !== undefined) {
    return `<div class="nota"><b>o arquivo mudou enquanto você editava</b>
      <div class="q">outro agente ou o editor chegaram primeiro. Nada foi sobrescrito.</div></div>
      <div class="rot">no arquivo agora</div>
      <div class="txt" style="opacity:.8">${esc(editor.conflito)}</div>
      <div class="rot" style="margin-top:8px">o seu texto</div>
      <textarea id="e-texto">${esc(meuTexto)}</textarea>
      <div class="q">“Salvar” grava o seu por cima</div>`;
  }
  return `<textarea id="e-texto" onkeydown="if(event.key==='Escape')fechar()">${esc(t.texto)}</textarea>`;
}

function abrir(i){ foco = 0; form = null; editor = null; scrollTo(0,0); carregar(D.docs[i].file); }
function focar(i){ if (foco === i) return; foco = i; desenhar(); }
function fechar(){ form = null; editor = null; desenhar(); }
function abrirForm(i, tipo){ editor = null; form = {i, tipo}; foco = i; desenhar(); }
function editar(i){ form = null; editor = {i}; foco = i; meuTexto = trecho(i).texto; desenhar(); }
function enviar(i){
  const texto = ($('f-texto')||{}).value || '';
  const prazo = ($('f-prazo')||{}).value || '';
  if (form.tipo === 'validar') return agir({...alvo(i), acao:'validar', texto, prazo});
  if (form.tipo === 'reverter') return agir({...alvo(i), acao:'reverter', motivo: texto});
  return agir({...alvo(i), acao:'marca', marca: form.tipo, texto});
}
function salvar(i){
  const t = ($('e-texto')||{}).value || '';
  meuTexto = t;
  agir({...alvo(i), acao:'salvar', texto: t,
        sha: (editor && editor.conflito !== undefined) ? '' : trecho(i).sha});
}
function setVer(v){ ver = v; foco = 0; desenhar(); }
function trocarBase(){ base = $('base').value; carregar(); }

document.addEventListener('keydown', (e)=>{
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') {
    if (e.key === 'Escape') fechar();
    return;
  }
  const vis = visiveis().map(([,i])=>i);
  const pos = vis.indexOf(foco);
  if (e.key === 'j' && pos < vis.length-1) { focar(vis[pos+1]); $('t'+foco)?.scrollIntoView({block:'center'}); }
  else if (e.key === 'k' && pos > 0) { focar(vis[pos-1]); $('t'+foco)?.scrollIntoView({block:'center'}); }
  else if (e.key === 'a') agir({...alvo(foco), acao:'aprovar'});
  else if (e.key === 'v') abrirForm(foco,'validar');
  else if (e.key === 'r') abrirForm(foco,'reverter');
  else if (e.key === 'e') editar(foco);
  else if (e.key === 'Escape') fechar();
});

// O arquivo muda por fora: um agente escreve, o editor salva. A tela se atualiza sozinha
// quando voce nao esta no meio de escrever nada.
setInterval(()=>{ if (!form && !editor) carregar(); }, 8000);
carregar();
</script></body></html>"""
