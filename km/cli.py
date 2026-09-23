"""Command line for the chancel.

The page (`km serve`) is the place to review; these commands are how the same thing is
done in a terminal, and how a script or an agent reads the state. Only `restore` writes in
a document, and only the chancel ref is ever advanced.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import unicodedata
from datetime import date
from pathlib import Path

from . import chancela as ch


def _root(args) -> Path:
    """The repository root, from wherever you are standing.

    The chancel is a git ref, so there is no such thing as using `km` outside a repository
    — and without this check a run from `~` walks the whole home directory looking for
    Markdown. Climbing to the top also means any subdirectory works.
    """
    pedido = Path(args.repo).expanduser().resolve()
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=pedido,
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(
            f"{pedido} não está num repositório git — a chancela é um ref, então o km só\n"
            f"funciona dentro de um. Entre no repositório e rode de novo, por exemplo:\n"
            f"  cd ~/demo-sla-project && km serve")
    return Path(r.stdout.strip())


def _sem_acento(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t.lower())
                   if unicodedata.category(c) != "Mn")


def _arquivos(root: Path, arg: str | None) -> list[str]:
    """The opt-in is the `include` list, and it is the opt-in everywhere.

    Naming a file explicitly does not smuggle it in: otherwise the editor would decorate
    and nag about documents this repository deliberately left out.
    """
    cobertos = ch.documentos(root)
    if not arg:
        return cobertos
    return [arg] if arg in cobertos else []


def _escolher(rel: str, refs: list[str], s: ch.Situacao) -> list[ch.Unidade]:
    """`--hunk` takes a change ("2"), one block of it ("2.1"), or part of a heading.

    A heading takes every change in that section, not the first one: endorsing a section
    is endorsing the section, and picking one block is what "2.1" is for.
    """
    escolhidas: list[ch.Unidade] = []
    for ref in refs:
        if re.fullmatch(r"\d+", ref):
            m = next((m for m in s.mudancas if m.n == int(ref)), None)
            if m is None:
                raise SystemExit(f"{rel}: não há mudança {ref} — rode `km pendente {rel}`")
            achadas = m.unidades
        elif re.fullmatch(r"\d+\.\d+", ref):
            achadas = [u for u in s.unidades if u.id == ref]
            if not achadas:
                raise SystemExit(f"{rel}: não há bloco {ref} — rode `km pendente {rel}`")
        else:
            alvo = _sem_acento(ref)
            achadas = [u for m in s.mudancas for u in m.unidades
                       if alvo in _sem_acento(u.titulo) or alvo in _sem_acento(m.titulo)
                       or alvo in _sem_acento(m.caminho)]
            if not achadas:
                raise SystemExit(f"{rel}: nenhuma mudança pendente em um título com {ref!r}")
        escolhidas += [u for u in achadas if u not in escolhidas]
    return escolhidas


def cmd_init(args) -> int:
    root = _root(args)
    d = root / ch.KM_DIR
    d.mkdir(parents=True, exist_ok=True)
    cfg = d / ch.CONFIG
    if cfg.exists():
        print(f"{cfg} já existe")
        return 0
    cfg.write_text(json.dumps(ch.DEFAULT_CONFIG, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"criado {cfg}")
    print("o `include` é o opt-in: só o que estiver nele é revisado")
    print("nada mais foi tocado — `km pendente` para ver onde você está")
    return 0


def _resumo(situacoes: list[ch.Situacao]) -> str:
    em_dia = sum(1 for s in situacoes if s.em_dia)
    mexidos = sum(len(s.mudancas) for s in situacoes if s.tem_chancela)
    nunca = sum(1 for s in situacoes if not s.tem_chancela)
    vencidas = sum(len(s.vencidas) for s in situacoes)
    bits = [f"{em_dia} arquivo(s) em dia com a chancela"]
    if mexidos:
        bits.append(f"{mexidos} mudança(s) pendente(s)")
    if nunca:
        bits.append(f"{nunca} sem chancela")
    if vencidas:
        bits.append(f"❓ {vencidas} com prazo vencido")
    return " · ".join(bits)


def cmd_pendente(args) -> int:
    """The two questions: what changed since the chancel, and what never had one."""
    root = _root(args)
    hoje = date.today().isoformat()
    alvos = _arquivos(root, args.file)
    if args.file and not alvos:
        if args.json:
            print("[]")
            return 0
        print(f"{args.file} está fora do `include` do .km/config.json — o km não olha para ele")
        return 0
    situacoes = [ch.situacao(root, rel, hoje) for rel in alvos]

    if args.json:
        print(json.dumps([e for s in situacoes for e in ch.estados(s)], ensure_ascii=False))
        return 0
    if args.short:
        print("km: " + _resumo(situacoes))
        return 0

    total = 0
    for s in (x for x in situacoes if x.tem_chancela and x.mudancas):
        # Numbers are the file's own: `km chancela <arquivo> --hunk 2` takes change 2,
        # `--hunk 2.1` only its first block. A numbering across files would need a sidecar
        # to be resolved again, and a sidecar is what this design removed.
        print(f"\n{s.arquivo}")
        for m in s.mudancas:
            total += 1
            menos, mais = m.contagem()
            sinal = "🚫" if m.bloqueio else ("⚠️" if m.sumidas else "  ")
            print(f"  {m.n:>3} {sinal} -{menos:<2} +{mais:<2} {m.titulo[:52]}")
            for u in m.unidades:
                print(f"       {u.id:<5} {u.tipo:<6} {u.resumo(56)}")
                for l in u.sumidas:
                    print(f"             ressalva removida: {l[:60]}")
            if m.bloqueio:
                print(f"       trecho bloqueado: {m.bloqueio[:66]}")

    novos = [s for s in situacoes if not s.tem_chancela]
    if args.novos:
        print("\nsem chancela nenhuma:" if novos else "\ntodo arquivo incluído tem chancela")
        for s in novos:
            print(f"      {s.arquivo}  ·  {len(s.depois.splitlines())} linhas")

    vencidas = [(s.arquivo, l, prazo, txt) for s in situacoes for l, prazo, txt in s.vencidas]
    if vencidas:
        print(f"\n❓ com prazo vencido ({len(vencidas)}):")
        for arquivo, l, prazo, txt in vencidas[:args.limit]:
            print(f"      {arquivo}:{l}  desde {prazo}  {txt[:60]}")

    print("\n" + _resumo(situacoes))
    if novos and not args.novos:
        print("a lista dos sem chancela: km pendente --novos")
    if total:
        print("chancelar: km chancela <arquivo> --hunk <n|n.m|título>   ·   tudo: --all")
    return 0


def cmd_chancela(args) -> int:
    """Write the accepted passages into the ref. The act is per passage; the ref holds files."""
    root = _root(args)
    if args.origem:
        return _chancelar_de(root, args)
    if len(args.file) > 1:
        raise SystemExit("um arquivo por vez, a não ser com --from <commit>")
    rel = args.file[0]
    if ch.atual(root, rel) is None:
        raise SystemExit(f"{rel} não existe no disco")
    if rel not in ch.documentos(root):
        raise SystemExit(f"{rel} está fora do `include` do .km/config.json — "
                         f"inclua-o lá antes de chancelar")
    s = ch.situacao(root, rel)
    if not s.mudancas:
        print(f"{rel}: nada pendente — a chancela já é o arquivo de hoje")
        return 0

    if args.all:
        escolhidas = list(s.unidades)
    elif args.hunk:
        escolhidas = _escolher(rel, args.hunk, s)
    else:
        raise SystemExit("diga o que entra: --hunk <n|n.m|título> (um ou mais) ou --all")

    barradas = [u for u in escolhidas if u.bloqueio and not args.force]
    escolhidas = [u for u in escolhidas if u not in barradas]
    if not escolhidas:
        for u in barradas:
            print(f"🚫 {u.titulo}: {u.bloqueio}")
        raise SystemExit("nada entrou: resolva o 🚫 (ou --force, que o deixa no texto)")

    commit = chancelar(root, rel, escolhidas, s, args.message, args.by)
    print(f"{rel}  ·  {len(escolhidas)} bloco(s) na chancela  ·  {commit[:8]}")
    for u in escolhidas:
        print(f"   ✓ {u.id:<5} {u.tipo:<6} {u.resumo(50)}")
        for l in u.sumidas:
            print(f"     (a ressalva {l[:56]} saiu junto)")
    for u in barradas:
        print(f"   🚫 {u.id} {u.titulo} — ficou de fora: {u.bloqueio[:60]}")
    resto = ch.situacao(root, rel).mudancas
    print(f"faltam {len(resto)} mudança(s) neste arquivo")
    if resto:
        # The numbers come from the diff, and the diff just moved. Acting on a number from
        # the previous listing would chancel a block you did not look at.
        print("os números mudaram — rode `km pendente` de novo"
              " (ou passe vários --hunk de uma vez)")
    return 0


def _chancelar_de(root: Path, args) -> int:
    """Endorse what a commit already held.

    The review happened before the tool existed — in a reading, in a meeting, in the commit
    itself. This states that, at once, and from then on the diff carries the conversation.
    """
    rev = args.origem
    cobertos = ch.documentos(root)
    mudancas: dict[str, str] = {}
    for rel in args.file:
        texto = ch.conteudo_em(root, rev, rel)
        if texto is None:
            print(f"   — {rel}: não existia em {rev}")
            continue
        if rel not in cobertos:
            print(f"   — {rel}: fora do `include` do .km/config.json")
            continue
        mudancas[rel] = texto
    if not mudancas:
        raise SystemExit("nada a chancelar")

    curto = ch.historico(root, rev, None, limite=1).strip() or rev
    mensagem = (f"chancela: {len(mudancas)} arquivo(s), conteúdo de {rev}\n\n"
                + "\n".join(sorted(mudancas)) + "\n"
                + (f"\n{args.message}\n" if args.message else "")
                + f"\npor: {args.by}\n")
    commit = ch.escrever(root, mudancas, mensagem)
    print(f"{len(mudancas)} arquivo(s) chancelados no conteúdo de {rev}  ·  {commit[:8]}")
    for rel in sorted(mudancas):
        pendentes = len(ch.situacao(root, rel).mudancas)
        print(f"   ✓ {rel}" + (f"  ·  {pendentes} mudança(s) desde então" if pendentes
                               else "  ·  igual ao que está no disco"))
    return 0


def chancelar(root: Path, rel: str, escolhidas: list[ch.Unidade], s: ch.Situacao,
              motivo: str | None, by: str) -> str:
    """Shared by the command and the page: the ref advances in one place only."""
    novo = ch.aplicar(s.antes, s.depois, {u.id for u in escolhidas})
    titulos = ", ".join(dict.fromkeys(u.titulo for u in escolhidas if u.titulo))
    inteiro = len(escolhidas) == len(s.unidades)
    cabeca = (f"chancela: {rel} · arquivo inteiro" if inteiro
              else f"chancela: {rel} · {len(escolhidas)} bloco(s)")
    mensagem = f"{cabeca}\n\n{titulos}\n"
    if motivo:
        mensagem += f"\n{motivo}\n"
    mensagem += f"\npor: {by}\n"
    return ch.escrever(root, {rel: novo}, mensagem)


def cmd_restore(args) -> int:
    """Put back the chancelled text of a block — refusing a change and leaving it in place
    would keep in the document exactly what you just rejected."""
    root = _root(args)
    rel = args.file
    s = ch.situacao(root, rel)
    if not s.tem_chancela:
        raise SystemExit(f"{rel} nunca teve chancela — não há texto para devolver")
    if not s.mudancas:
        print(f"{rel}: nada mudou desde a chancela")
        return 0
    alvos = list(s.unidades) if args.all else _escolher(rel, args.hunk, s)
    if not alvos:
        raise SystemExit("diga o que volta: --hunk <n|n.m|título> ou --all")
    reverter(root, rel, alvos, s)
    print(f"{rel}  ·  {len(alvos)} bloco(s) de volta ao texto chancelado")
    for u in alvos:
        print(f"   ↩ {u.id:<5} {u.resumo(56)}")
    if args.message:
        print(f"   motivo: {args.message}  (escreva-o no commit, ou como ⚠️ no texto)")
    return 0


def reverter(root: Path, rel: str, alvos: list[ch.Unidade], s: ch.Situacao) -> None:
    manter = {u.id for u in s.unidades} - {u.id for u in alvos}
    (root / rel).write_text(ch.aplicar(s.antes, s.depois, manter), encoding="utf-8")


def cmd_lint(args) -> int:
    """Mechanical checks on the convention. No judgement, no model."""
    root = _root(args)
    hoje = date.today().isoformat()
    achados = 0
    for rel in _arquivos(root, args.file):
        s = ch.situacao(root, rel, hoje)
        texto = ch.atual(root, rel)
        if texto is None:
            print(f"{rel}: tem chancela e não está mais no disco")
            achados += 1
            continue
        linhas = [f"  ❓ :{n} venceu em {prazo} — {txt[:60]}" for n, prazo, txt in s.vencidas]
        linhas += [f"  🚫 bloqueia a chancela do trecho — {txt[:60]}"
                   for _, marca, txt in ch.ressalvas(texto) if marca == "🚫"]
        linhas += [f"  ⚠️ ressalva removida em {u.titulo[:30]} — {l[:50]}"
                   for u in s.unidades for l in u.sumidas]
        if linhas:
            print(f"\n{rel}")
            print("\n".join(linhas))
            achados += len(linhas)
    print(f"\n{achados} apontamento(s)")
    return 1 if achados and args.strict else 0


def cmd_baseline(args) -> int:
    """The left-hand column: the document as you last endorsed it."""
    texto = ch.chancelado(_root(args), args.file)
    if texto is None:
        print(f"<!-- km: {args.file} nunca teve chancela -->")
        return 0
    print(texto, end="")
    return 0


def cmd_quando(args) -> int:
    """When did this passage last have a chancel — the question blocks were storing for."""
    root = _root(args)
    alvo = None
    if args.trecho:
        base = ch.chancelado(root, args.file) or ch.atual(root, args.file) or ""
        ref = _sem_acento(args.trecho)
        achados = [t for t in ch.trechos(base) if ref in _sem_acento(t.titulo)]
        if not achados:
            raise SystemExit(f"nenhum trecho com {args.trecho!r} em {args.file}")
        alvo = achados[0]
        print(f"{args.file} › {alvo.titulo}")
    saida = ch.historico(root, args.file, alvo, limite=args.limit).strip()
    print(saida or "nunca teve chancela")
    return 0


def cmd_serve(args) -> int:
    from . import serve

    return serve.run(_root(args), port=args.port, by=args.by)


def cmd_install_hooks(args) -> int:
    """So nothing has to be memorised: the repository tells you where it stands."""
    root = _root(args)
    hooks = root / ".git" / "hooks"
    if not hooks.parent.exists():
        raise SystemExit("não é um repositório git")
    hooks.mkdir(parents=True, exist_ok=True)
    km = Path(__file__).resolve().parent.parent / "bin" / "km"
    body = f"""#!/bin/sh
# knowledge-manager: report only. Never blocks a commit, always exits 0.
"{km}" pendente --short 2>/dev/null || true
exit 0
"""
    target = hooks / "post-commit"
    if target.exists() and "knowledge-manager" not in target.read_text(encoding="utf-8"):
        print(f"{target} já existe e não é nosso — não mexi")
        return 1
    target.write_text(body, encoding="utf-8")
    target.chmod(0o755)
    print(f"instalado {target.relative_to(root)} — diz onde você está depois de cada commit")
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="km",
                                description="O que dos seus documentos você realmente revisou.")
    p.add_argument("--repo", default=os.getcwd(), help="raiz do repositório (padrão: aqui)")
    sub = p.add_subparsers(dest="cmd", required=True)
    quem = "human:" + os.environ.get("USER", "unknown")

    sub.add_parser("init", help="criar .km/config.json, com o opt-in por arquivo"
                   ).set_defaults(func=cmd_init)

    s = sub.add_parser("serve", aliases=["painel"],
                       help="a tela da revisão, num servidor local sob demanda")
    s.add_argument("--port", type=int, default=8431)
    s.add_argument("--by", default=quem)
    s.set_defaults(func=cmd_serve)

    s = sub.add_parser("pendente", aliases=["pending"],
                       help="o que mudou desde a chancela, e o que nunca teve uma")
    s.add_argument("file", nargs="?")
    s.add_argument("--novos", action="store_true", help="listar os arquivos sem chancela")
    s.add_argument("--short", action="store_true", help="uma linha, para o hook")
    s.add_argument("--json", action="store_true", help="para o editor e para a tela")
    s.add_argument("--limit", type=int, default=12)
    s.set_defaults(func=cmd_pendente)

    s = sub.add_parser("chancela", aliases=["chancel"],
                       help="escrever os trechos aceitos na chancela (refs/km/chancela)")
    s.add_argument("file", nargs="+")
    s.add_argument("--from", dest="origem", metavar="REV",
                   help="chancelar o conteúdo que o arquivo tinha naquele commit ou branch")
    s.add_argument("--hunk", action="append", default=[],
                   help="número do `km pendente`, ou parte do título; repetível")
    s.add_argument("--all", action="store_true", help="o arquivo inteiro como está hoje")
    s.add_argument("-m", "--message", help="por que você endossa (vai na mensagem do commit)")
    s.add_argument("--force", action="store_true", help="chancelar mesmo com 🚫 no trecho")
    s.add_argument("--by", default=quem)
    s.set_defaults(func=cmd_chancela)

    s = sub.add_parser("restore", help="devolver ao texto que você chancelou")
    s.add_argument("file")
    s.add_argument("--hunk", action="append", default=[])
    s.add_argument("--all", action="store_true")
    s.add_argument("-m", "--message", help="por que a mudança não serve")
    s.set_defaults(func=cmd_restore)

    s = sub.add_parser("lint", help="a convenção das ressalvas: 🚫 pendente, ❓ vencida, ⚠️ sumida")
    s.add_argument("file", nargs="?")
    s.add_argument("--strict", action="store_true", help="sai com erro se houver apontamento")
    s.set_defaults(func=cmd_lint)

    s = sub.add_parser("quando", aliases=["when"],
                       help="quando este trecho teve chancela pela última vez")
    s.add_argument("file")
    s.add_argument("--trecho", help="parte do título")
    s.add_argument("--limit", type=int, default=5)
    s.set_defaults(func=cmd_quando)

    s = sub.add_parser("baseline", help="o documento como você o chancelou (coluna da esquerda)")
    s.add_argument("file")
    s.set_defaults(func=cmd_baseline)

    sub.add_parser("install-hooks", help="uma linha depois de cada commit, dizendo onde você está"
                   ).set_defaults(func=cmd_install_hooks)

    args = p.parse_args(argv)
    return args.func(args)
