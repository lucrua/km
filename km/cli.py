"""Command line for the chancel.

The page (`km serve`) is the place to review; these commands are how the same thing is
done in a terminal, and how a script or an agent reads the state. Only `restore` writes in
a document, and only the chancel ref is ever advanced.
"""

from __future__ import annotations

import argparse
import json
import os
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


def _hunks_por_ref(rel: str, ref: str, hs: list[ch.Hunk]) -> list[ch.Hunk]:
    """`--hunk` takes the number printed by `km pendente`, or part of a heading.

    A heading takes every pending change under it, not the first one: endorsing a passage
    is endorsing the passage, and picking one of its changes is what the number is for.
    """
    if ref.isdigit():
        achados = [h for h in hs if h.n == int(ref)]
        if not achados:
            raise SystemExit(f"{rel}: não há trecho {ref} — rode `km pendente {rel}`")
        return achados
    alvo = _sem_acento(ref)
    achados = ([h for h in hs if alvo in _sem_acento(h.titulo)]
               or [h for h in hs if alvo in _sem_acento(h.caminho)])
    if not achados:
        raise SystemExit(f"{rel}: nenhuma mudança pendente em um título com {ref!r}")
    return achados


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
    mexidos = sum(len(s.hunks) for s in situacoes if s.tem_chancela)
    nunca = sum(1 for s in situacoes if not s.tem_chancela)
    vencidas = sum(len(s.vencidas) for s in situacoes)
    bits = [f"{em_dia} arquivo(s) em dia com a chancela"]
    if mexidos:
        bits.append(f"{mexidos} trechos mexidos")
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
    for s in (x for x in situacoes if x.tem_chancela and x.hunks):
        # The number is the hunk's own, inside its file: `km chancela <arquivo> --hunk 2`.
        # A list numbered across files would need a sidecar to be resolved again, and a
        # sidecar is what this design removed.
        print(f"\n{s.arquivo}")
        for h in s.hunks:
            total += 1
            sinal = "🚫" if h.bloqueio else ("⚠️" if h.sumidas else "  ")
            print(f"  {h.n:>3} {sinal} -{len(h.antes):<3} +{len(h.depois):<3}"
                  f" {h.titulo[:40]:<40} {h.resumo(38)}")
            for l in h.sumidas:
                print(f"       ressalva removida: {l[:70]}")
            if h.bloqueio:
                print(f"       trecho bloqueado: {h.bloqueio[:70]}")

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

    print(f"\n{total} trechos mexidos · " + _resumo(situacoes))
    if novos and not args.novos:
        print("a lista dos sem chancela: km pendente --novos")
    if total:
        print("chancelar: km chancela <arquivo> --hunk <n|título>   ·   tudo: --all")
    return 0


def cmd_chancela(args) -> int:
    """Write the accepted passages into the ref. The act is per passage; the ref holds files."""
    root = _root(args)
    rel = args.file
    if ch.atual(root, rel) is None:
        raise SystemExit(f"{rel} não existe no disco")
    if rel not in ch.documentos(root):
        raise SystemExit(f"{rel} está fora do `include` do .km/config.json — "
                         f"inclua-o lá antes de chancelar")
    s = ch.situacao(root, rel)
    if not s.hunks:
        print(f"{rel}: nada pendente — a chancela já é o arquivo de hoje")
        return 0

    if args.all:
        escolhidos = list(s.hunks)
    elif args.hunk:
        escolhidos = [h for r in args.hunk for h in _hunks_por_ref(rel, r, s.hunks)]
    else:
        raise SystemExit("diga o que entra: --hunk <n|título> (um ou mais) ou --all")

    barrados = [h for h in escolhidos if h.bloqueio and not args.force]
    escolhidos = [h for h in escolhidos if h not in barrados]
    if not escolhidos:
        for h in barrados:
            print(f"🚫 {h.titulo}: {h.bloqueio}")
        raise SystemExit("nada entrou: resolva o 🚫 (ou --force, que o deixa no texto)")

    commit = chancelar(root, rel, escolhidos, s, args.message, args.by)
    print(f"{rel}  ·  {len(escolhidos)} trecho(s) na chancela  ·  {commit[:8]}")
    por_titulo: dict[str, list[ch.Hunk]] = {}
    for h in escolhidos:
        por_titulo.setdefault(h.titulo, []).append(h)
    for titulo, dela in por_titulo.items():
        quantos = f"  ({len(dela)} mudanças)" if len(dela) > 1 else ""
        print(f"   ✓ {titulo}{quantos}")
        for l in (x for h in dela for x in h.sumidas):
            print(f"     (a ressalva {l[:56]} saiu junto)")
    for h in barrados:
        print(f"   🚫 {h.titulo} — ficou de fora: {h.bloqueio[:60]}")
    resto = ch.situacao(root, rel).hunks
    print(f"faltam {len(resto)} trecho(s) neste arquivo")
    if resto:
        # The numbers come from the diff, and the diff just moved. Acting on a number from
        # the previous listing would chancel a passage you did not look at.
        print("os números mudaram — rode `km pendente` de novo"
              " (ou passe vários --hunk de uma vez)")
    return 0


def chancelar(root: Path, rel: str, escolhidos: list[ch.Hunk], s: ch.Situacao,
              motivo: str | None, by: str) -> str:
    """Shared by the command and the page: the ref advances in one place only."""
    novo = ch.aplicar(s.antes, s.depois, {h.n for h in escolhidos}, s.hunks)
    titulos = ", ".join(dict.fromkeys(h.titulo for h in escolhidos))
    inteiro = len(escolhidos) == len(s.hunks)
    cabeca = (f"chancela: {rel} · arquivo inteiro" if inteiro
              else f"chancela: {rel} · {len(escolhidos)} trecho(s)")
    mensagem = f"{cabeca}\n\n{titulos}\n"
    if motivo:
        mensagem += f"\n{motivo}\n"
    mensagem += f"\npor: {by}\n"
    return ch.escrever(root, {rel: novo}, mensagem)


def cmd_restore(args) -> int:
    """Put back the chancelled text of a passage — refusing a change and leaving it in
    place would keep in the document exactly what you just rejected."""
    root = _root(args)
    rel = args.file
    s = ch.situacao(root, rel)
    if not s.tem_chancela:
        raise SystemExit(f"{rel} nunca teve chancela — não há texto para devolver")
    if not s.hunks:
        print(f"{rel}: nada mudou desde a chancela")
        return 0
    alvos = (list(s.hunks) if args.all
             else [h for r in args.hunk for h in _hunks_por_ref(rel, r, s.hunks)])
    if not alvos:
        raise SystemExit("diga o que volta: --hunk <n|título> ou --all")
    reverter(root, rel, alvos, s)
    print(f"{rel}  ·  {len(alvos)} trecho(s) de volta ao texto chancelado")
    for titulo in dict.fromkeys(h.titulo for h in alvos):
        print(f"   ↩ {titulo}")
    if args.message:
        print(f"   motivo: {args.message}  (escreva-o no commit, ou como ⚠️ no texto)")
    return 0


def reverter(root: Path, rel: str, alvos: list[ch.Hunk], s: ch.Situacao) -> None:
    manter = {h.n for h in s.hunks} - {h.n for h in alvos}
    (root / rel).write_text(ch.aplicar(s.antes, s.depois, manter, s.hunks), encoding="utf-8")


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
        linhas += [f"  ⚠️ ressalva removida em {h.titulo[:30]} — {l[:50]}"
                   for h in s.hunks for l in h.sumidas]
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
    s.add_argument("file")
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
