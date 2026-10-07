"""Command line for the chancel.

The page (`km serve`) is the place to review; these commands are how the same thing is
done in a terminal, and how a script or an agent reads the state. Only `restore` writes in
a document, only `mv` moves one, and only the chancel ref is ever advanced — except by
`forget`, the one command that rewrites its history.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import unicodedata
from pathlib import Path

from . import acompanhamento as ac
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
    """Tracking is the opt-in, and it is the opt-in everywhere.

    Naming a file explicitly does not smuggle it in: otherwise the editor would decorate
    and nag about documents this repository deliberately left out.
    """
    cobertos = ac.documentos(root)
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
    cfg = root / ac.KM_DIR / ac.CONFIG
    if cfg.exists():
        print(f"{cfg} já existe")
        return 0
    ac.gravar(root, ac.vazia())
    print(f"criado {cfg} — nada é acompanhado ainda")
    print("escolha os arquivos no painel: km serve, aba Arquivos")
    return 0


def _resumo(situacoes: list[ch.Situacao]) -> str:
    em_dia = sum(1 for s in situacoes if s.em_dia)
    nunca = sum(1 for s in situacoes if not s.tem_chancela)
    pend = total = 0
    for s in situacoes:
        a, b = ch.pendencia_do_arquivo(s)
        pend, total = pend + a, total + b
    bits = [f"{em_dia} arquivo(s) em dia com a chancela"]
    if pend:
        bits.append(f"{ch.percentual(pend, total)} do conteúdo a aprovar")
    if nunca:
        bits.append(f"{nunca} sem chancela")
    return " · ".join(bits)


def cmd_pendente(args) -> int:
    """The two questions: what changed since the chancel, and what never had one."""
    root = _root(args)
    alvos = _arquivos(root, args.file)
    if args.file and not alvos:
        if args.json:
            print("[]")
            return 0
        print(f"{args.file} não é acompanhado — escolha no painel, aba Arquivos")
        return 0
    situacoes = [ch.situacao(root, rel) for rel in alvos]

    if args.json:
        # For the editor: where the pending changes are, and how much of the file they are.
        # No per-heading states and no counts — the unit is the change, the measure is %.
        saida = []
        for s in situacoes:
            pend, total = ch.pendencia_do_arquivo(s)
            saida.append({
                "file": s.arquivo, "tem_chancela": s.tem_chancela,
                "pct": ch.percentual(pend, total), "pendente": bool(s.mudancas),
                "mudancas": [{"n": m.n, "titulo": m.titulo, "linha": m.linha,
                              "fim": max(m.fim, m.linha + 1), "sumidas": m.sumidas} for m in s.mudancas],
            })
        print(json.dumps(saida, ensure_ascii=False))
        return 0
    if args.short:
        print("km: " + _resumo(situacoes))
        return 0

    total = 0
    for s in (x for x in situacoes if x.tem_chancela and x.mudancas):
        # Numbers are addresses, not a score: `--hunk 2` takes change 2, `--hunk 2.1` only
        # its first block. How much is left is the percentage, in characters.
        print(f"\n{s.arquivo}  ·  {ch.percentual(*ch.pendencia_do_arquivo(s))} a aprovar")
        for m in s.mudancas:
            # Um trecho mudado é uma coisa só para ler: blocos seguidos que mudaram não se
            # listam um a um. `--hunk 2.1` continua valendo para quem precisa endereçar menos.
            total += 1
            sinal = "!" if m.sumidas else " "
            print(f"  {m.n:>3} {sinal} {m.titulo[:40]:<40} {m.unidades[0].resumo(46)}")
            for l in m.sumidas:
                print(f"      marca removida: {l[:66]}")

    novos = [s for s in situacoes if not s.tem_chancela]
    if args.novos:
        print("\nsem chancela nenhuma:" if novos else "\ntodo arquivo acompanhado tem chancela")
        for s in novos:
            print(f"      {s.arquivo}  ·  {len(s.depois.splitlines())} linhas")

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
    if rel not in ac.documentos(root):
        raise SystemExit(f"{rel} não é acompanhado — marque-o no painel, aba Arquivos,"
                         f" antes de chancelar")
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

    commit = chancelar(root, rel, escolhidas, s, args.message, args.by)
    print(f"{rel}  ·  na chancela  ·  {commit[:8]}")
    fora = ch.fora_do_git(root, rel)
    if fora:
        print(f"⚠ {aviso_fora_do_git(rel, fora)}")
    for u in escolhidas:
        print(f"   ✓ {u.id:<5} {u.tipo:<6} {u.resumo(50)}")
        for l in u.sumidas:
            print(f"     (a marca {l[:56]} saiu junto)")
    depois = ch.situacao(root, rel)
    resto = depois.mudancas
    print(f"falta {ch.percentual(*ch.pendencia_do_arquivo(depois))} deste arquivo" if resto
          else "o arquivo está em dia com a chancela")
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
    cobertos = ac.documentos(root)
    mudancas: dict[str, str] = {}
    for rel in args.file:
        texto = ch.conteudo_em(root, rev, rel)
        if texto is None:
            print(f"   — {rel}: não existia em {rev}")
            continue
        if rel not in cobertos:
            print(f"   — {rel}: não é acompanhado")
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
        s = ch.situacao(root, rel)
        print(f"   ✓ {rel}" + (f"  ·  {ch.percentual(*ch.pendencia_do_arquivo(s))} mudou desde então" if s.mudancas
                               else "  ·  igual ao que está no disco"))
    return 0


def aviso_fora_do_git(rel: str, fora: str) -> str:
    """Said where an approval happens: the text goes into `.git` without any commit."""
    motivo = "é ignorado pelo git" if fora == "ignorado" else "não está no git"
    return (f"{rel} {motivo}: este texto fica guardado no .git (refs/km/chancela) mesmo sem"
            f" commit, e sai com qualquer cópia do .git — para apagar de lá: km forget {rel}")


def chancelar(root: Path, rel: str, escolhidas: list[ch.Unidade], s: ch.Situacao,
              motivo: str | None, by: str,
              parciais: dict[str, tuple[int, int]] | None = None) -> str:
    """Shared by the command and the page: the ref advances in one place only.

    `parciais` maps a block id to the part of its new text you selected: only the changes
    inside it enter the chancel.
    """
    parc = {k: (a, b, True) for k, (a, b) in (parciais or {}).items()}
    novo = ch.aplicar(s.antes, s.depois, {u.id for u in escolhidas}, parc)
    titulos = ", ".join(dict.fromkeys(u.titulo for u in escolhidas if u.titulo))
    inteiro = not parc and len(escolhidas) == len(s.unidades)
    cabeca = (f"chancela: {rel} · arquivo inteiro" if inteiro
              else f"chancela: {rel}" + (" · parte de um bloco" if parc else ""))
    mensagem = f"{cabeca}\n\n{titulos}\n"
    if motivo:
        mensagem += f"\n{motivo}\n"
    mensagem += f"\npor: {by}\n"
    # Aprovar que um arquivo saiu é tirá-lo da chancela: um arquivo vazio guardado no ref
    # deixaria um fantasma "em dia" para sempre.
    fora = s.sumiu and not novo.strip()
    return ch.escrever(root, {rel: None if fora else novo}, mensagem)


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
    print(f"{rel}  ·  de volta ao texto chancelado")
    for u in alvos:
        print(f"   ↩ {u.id:<5} {u.resumo(56)}")
    if args.message:
        print(f"   motivo: {args.message}  (escreva-o no commit, ou como 💬 no texto)")
    return 0


def reverter(root: Path, rel: str, alvos: list[ch.Unidade], s: ch.Situacao,
             parciais: dict[str, tuple[int, int]] | None = None) -> None:
    """Undo blocks in the file — or only the part of one block you selected."""
    parc = {k: (a, b, False) for k, (a, b) in (parciais or {}).items()}
    manter = {u.id for u in s.unidades} - {u.id for u in alvos}
    (root / rel).write_text(ch.aplicar(s.antes, s.depois, manter, parc), encoding="utf-8")


def cmd_lint(args) -> int:
    """Mechanical checks on the convention. No judgement, no model."""
    root = _root(args)
    achados = 0
    for rel in _arquivos(root, args.file):
        s = ch.situacao(root, rel)
        texto = ch.atual(root, rel)
        if texto is None:
            print(f"{rel}: tem chancela e não está mais no disco")
            if not ch.fora_da_chancela(root, rel):
                print(f"  nunca esteve num commit fora da chancela: o texto só existe nela —"
                      f" para tirá-lo do .git, km forget {rel}")
            achados += 1
            continue
        linhas = [f"  :{m.linha} {m.tipo} ainda com o texto de exemplo — {m.cru[:60]}"
                  for m in ch.marcas(texto) if m.placeholder]
        linhas += [f"  marca removida em {u.titulo[:30]} — {l[:50]}"
                   for u in s.unidades for l in u.sumidas]
        if linhas:
            print(f"\n{rel}")
            print("\n".join(linhas))
            achados += len(linhas)
    if not args.file:
        achados += _lint_config(root)
    print(f"\n{achados} apontamento(s)")
    return 1 if achados and args.strict else 0


def _lint_config(root: Path) -> int:
    """Entries of `.km/config.json` with nothing on disk.

    A folder that is gone does not show in the *Arquivos* view, so nothing on screen would
    ever take it out. Forgetting is offered when it is safe: nothing of it in the chancel,
    or text that exists only there.
    """
    linhas = []
    for chave, p in ac.inexistentes(root, ac.carregar(root)):
        if not ch.na_historia(root, p):
            dica = f"km forget {p} tira daqui (a chancela não tem nada dele)"
        elif not ch.fora_da_chancela(root, p):
            dica = f"o texto só existe na chancela — km forget {p} apaga de lá e daqui"
        elif chave == "files":
            dica = "desmarque na aba Arquivos"
        else:
            dica = "tire a linha do .km/config.json — a aba Arquivos não mostra pasta que não existe"
        linhas.append(f"  {chave}: {p} não existe no disco · {dica}")
    if linhas:
        print("\n.km/config.json")
        print("\n".join(linhas))
    return len(linhas)


def cmd_marcas(args) -> int:
    """The marks an agent is meant to find, across every Markdown file git knows about.

    Not only the tracked ones: a to-do is written for whoever passes by, and a file nobody
    reviews is exactly where one would otherwise go unseen.
    """
    root = _root(args)
    tipos = {args.tipo} if args.tipo else ({"to_do", "comment"} if args.todas else {"to_do"})
    achadas = []
    for rel in ac.candidatos(root):
        texto = ch.atual(root, rel) or ""
        for m in ch.marcas(texto):
            if m.tipo in tipos:
                achadas.append({"file": rel, "line": m.linha, "kind": m.tipo, "date": m.data,
                                "text": m.texto})
    if args.json:
        print(json.dumps(achadas, ensure_ascii=False))
        return 0
    for a in achadas:
        print(f"{a['file']}:{a['line']}  {a['kind']}  " + (f"{a['date']}  " if a["date"] else "")
              + a["text"])
    return 0


def _relativo(arg: str, raiz: str = "a raiz do repositório não se move") -> str:
    """A repository-relative path, the way the config and the ref spell it."""
    if Path(arg).is_absolute():
        raise SystemExit(f"{arg}: o caminho tem que ser relativo à raiz do repositório")
    partes = [p for p in arg.split("/") if p not in ("", ".")]
    if ".." in partes:
        raise SystemExit(f"{arg}: sem .. — o caminho é relativo à raiz do repositório")
    if not partes:
        raise SystemExit(f"{arg}: {raiz}")
    return "/".join(partes)


def cmd_mv(args) -> int:
    """Move a file or a folder, and its chancel and its place in the config with it.

    A plain `git mv` leaves the chancel under the old path: the moved file reads as never
    reviewed and the old one as deleted. Here the content is not touched, so a pure move
    leaves nothing to approve.
    """
    root = _root(args)
    de, para = _relativo(args.origem), _relativo(args.destino)
    if de == para:
        raise SystemExit(f"{de}: mover um caminho para ele mesmo não faz nada")
    if para.startswith(de + "/"):
        raise SystemExit(f"{para} fica dentro de {de} — uma pasta não se move para dentro de si")
    if (root / para).exists() or (root / para).is_symlink():
        raise SystemExit(f"{para} já existe — o km mv não escreve por cima")
    no_git = subprocess.run(["git", "ls-files", "--error-unmatch", "--", de], cwd=root,
                            capture_output=True, text=True)
    if no_git.returncode != 0:
        raise SystemExit(f"{de} não está no git — o km mv usa `git mv`, para o histórico seguir"
                         f" o arquivo; faça `git add {de}` antes")
    na_ref = ch.arquivos(root)
    ocupados = [r for r in na_ref if r == para or r.startswith(para + "/")]
    if ocupados:
        raise SystemExit(f"{para} ainda tem chancela guardada ({ocupados[0]}, apagado do disco)"
                         f" — aprove a remoção no painel antes de mover algo para lá")
    pasta = (root / de).is_dir()

    cfg = ac.carregar(root)
    acompanhados = [d for d in ac.documentos(root, cfg) if d == de or d.startswith(de + "/")]
    novo_cfg = ac.mover(cfg, de, para, pasta, acompanhados)
    antigo_cfg = ac.normalizar(cfg)
    pares = {r: ac.renomear(r, de, para) for r in na_ref if r == de or r.startswith(de + "/")}
    entram = [ac.renomear(c, de, para) for c in ac.candidatos(root)
              if (c == de or c.startswith(de + "/")) and c not in acompanhados
              and ac.decisao(ac.renomear(c, de, para), novo_cfg)]

    print(f"{de} → {para}" + ("  (pasta)" if pasta else ""))
    print(f"  git mv {de} {para}")
    if novo_cfg != antigo_cfg:
        print("  .km/config.json")
        for chave in ac.CHAVES:
            sai = [x for x in antigo_cfg[chave] if x not in novo_cfg[chave]]
            entra = [x for x in novo_cfg[chave] if x not in antigo_cfg[chave]]
            if sai or entra:
                print(f"    {chave:<8} " + "  ".join([f"- {x}" for x in sai] + [f"+ {x}" for x in entra]))
    elif not acompanhados:
        print("  não acompanhado — .km/config.json não muda")
    if pares:
        print(f"  chancela: {len(pares)} arquivo(s) levados para o caminho novo")
        for velho, novo in pares.items():
            print(f"    {velho} → {novo}")
    else:
        print("  sem chancela — nada a levar no ref")
    for rel in entram:
        print(f"  {rel} passa a ser acompanhado, pela regra da pasta — sem chancela")

    if args.dry_run:
        print("simulação: nada foi escrito")
        return 0

    faltam = []
    pai = (root / para).parent
    while not pai.exists():
        faltam.append(pai)
        pai = pai.parent
    for d in reversed(faltam):
        d.mkdir()
    r = subprocess.run(["git", "mv", "--", de, para], cwd=root, capture_output=True, text=True)
    if r.returncode != 0:
        for d in faltam:
            d.rmdir()
        raise SystemExit(f"git mv {de} {para}: {r.stderr.strip()}")
    if novo_cfg != antigo_cfg:
        ac.gravar(root, novo_cfg)
    if pares:
        ch.mover(root, pares, f"km mv {de} → {para}")
    print("movido — o conteúdo não mudou, então não há nada novo a aprovar")
    return 0


def cmd_forget(args) -> int:
    """Take files out of the chancel for good: from every commit of the ref, and the config.

    The one command that rewrites the ref's history instead of advancing it. Untracking keeps
    the chancel and deleting a file keeps every version it had, so text that was never
    committed to a branch stays in `.git` — and leaves with `git push --mirror` or any copy
    of it. The author's act, like `km chancela`; as with `km boot`, nothing is written
    without `--apply`.
    """
    root = _root(args)
    caminhos = list(dict.fromkeys(
        _relativo(a, "esquecer a raiz apagaria a chancela inteira — diga as pastas ou arquivos")
        for a in args.caminhos))
    plano = ch.planejar_esquecer(root, caminhos)
    cfg = ac.carregar(root)
    antigo_cfg = ac.normalizar(cfg)
    novo_cfg = ac.esquecer(cfg, caminhos, lambda c: (root / c).exists())
    muda_cfg = novo_cfg != antigo_cfg

    print("km forget " + " ".join(caminhos))
    if plano.nada and not muda_cfg:
        print("  nada a esquecer: não está na chancela nem em .km/config.json")
        return 0

    total = len(plano.commits)
    if plano.nada:
        print(f"\n{ch.REF}: nada destes caminhos" + (f" em {total} commits" if total else ""))
    else:
        print(f"\n{ch.REF} — {total} commits")
        largura = max(len(p) for p in plano.versoes)
        for p in sorted(plano.versoes):
            n = len(plano.versoes[p])
            print(f"  {p:<{largura}}  ·  {n} {'versão' if n == 1 else 'versões'}")
        for c in caminhos:
            if not any(ch.sob(p, [c]) for p in plano.versoes):
                print(f"  {c}  ·  nunca esteve na chancela")
        print(f"  {len(plano.tocaram)} commit(s) mexeram nesses caminhos:")
        for c in plano.tocaram:
            destino = "sai: fica vazio" if c.sha in plano.vazios else "fica, sem esses caminhos"
            print(f"    {c.sha[:8]}  {c.dia}  {c.assunto[:56]:<56}  {destino}")
        vazios = len(plano.vazios)
        novos = total - plano.iguais - vazios
        partes = [f"{vazios} {'sai vazio' if vazios == 1 else 'saem vazios'}"]
        if novos:
            partes.append(f"{novos} {'ganha' if novos == 1 else 'ganham'} outro sha, com a mesma"
                          f" mensagem e as mesmas datas")
        if plano.iguais:
            partes.append(f"{plano.iguais} de antes {'fica' if plano.iguais == 1 else 'ficam'}"
                          f" como {'está' if plano.iguais == 1 else 'estão'}")
        print(f"  depois: {total - vazios} commits · " + " · ".join(partes))
        for c in plano.citam:
            print(f"  ⚠ {c.sha[:8]} fica e cita o caminho na mensagem: {c.assunto[:60]}")

    if muda_cfg:
        print("\n.km/config.json")
        for chave in ac.CHAVES:
            sai = [x for x in antigo_cfg[chave] if x not in novo_cfg[chave]]
            entra = [x for x in novo_cfg[chave] if x not in antigo_cfg[chave]]
            if sai or entra:
                print(f"    {chave:<8} " + "  ".join([f"- {x}" for x in sai] + [f"+ {x}" for x in entra]))
        for c in caminhos:
            if c in novo_cfg["except"] and c not in antigo_cfg["except"]:
                print(f"  {c} continua no disco, sob uma pasta acompanhada: vira exceção, para a"
                      f" próxima aprovação não guardá-lo de novo")
    for c in caminhos:
        if (root / c).exists():
            print(f"  {c} continua no disco — o km forget não apaga arquivos")

    # O que o km forget não alcança: o mesmo texto em outro caminho da chancela, em commits
    # de branch, tag ou stash, e no index. Dito antes, para ninguém achar que sumiu.
    fica = []
    for blob, outros in sorted(plano.outros.items()):
        o = sorted(outros)[0]
        fica.append(f"  uma versão é igual a {o}, que fica na chancela — esquecer junto: km forget {o}")
    for c in sorted(plano.versoes):
        sha = ch.fora_da_chancela(root, c)
        if sha:
            fica.append(f"  {c} está em commits fora da chancela ({sha}) — o km forget não mexe"
                        f" em branches; um branch que ainda o tenha o mostra sem chancela")
    lugares = ch.onde_mais(root, plano.blobs)
    if lugares.get("index"):
        fica.append(f"  {len(lugares['index'])} versão(ões) no index (git add) — git rm --cached"
                    f" tira de lá")
    if fica:
        print("\ncontinua no .git mesmo assim:")
        print("\n".join(fica))

    if not args.apply:
        print("\nsimulação: nada foi escrito")
        print(f"para valer:  km forget {' '.join(caminhos)} --apply"
              + ("" if args.prune else "   (--prune apaga também as versões velhas do .git)"))
        return 0

    antes = plano.ponta
    try:
        ponta = ch.esquecer(root, plano)
    except ch.Concorrencia as e:
        raise SystemExit(f"km: {e}")
    if muda_cfg:
        ac.gravar(root, novo_cfg)
    print()
    if not plano.nada:
        print(f"chancela reescrita: {total} → {total - len(plano.vazios)} commits  ·  "
              f"{antes[:8]} → {ponta[:8] if ponta else 'apagada: não sobrou nada'}")
    if muda_cfg:
        print(".km/config.json reescrito")
    for w in ch.worktrees(root):
        if Path(w).resolve() == root.resolve():
            continue
        try:
            dele = ac.carregar(Path(w))
        except ac.ConfigInvalida:
            continue
        if any(ch.sob(x, caminhos) for k in ("folders", "files") for x in dele[k]):
            print(f"  o worktree {w} tem a config dele, que ainda lista esses caminhos:"
                  f" km --repo {w} forget {' '.join(caminhos)} --apply")

    if not plano.nada:
        n_wt = len(ch.worktrees(root))
        mesmo = (f"os {n_wt} worktrees deste repositório dividem o mesmo .git: a chancela"
                 f" reescrita e o gc valem para todos" if n_wt > 1
                 else "os worktrees de um repositório dividem o mesmo .git — este não tem outros")
        if args.prune:
            ch.podar(root)
            restam = ch.objetos_presentes(root, plano.blobs)
            if restam:
                print(f"gc feito: {len(plano.blobs) - len(restam)} de {len(plano.blobs)} versões"
                      f" saíram do .git; {len(restam)} continuam, pelos motivos acima"
                      f" (git log --all --find-object=<sha> diz onde):")
                for b in sorted(restam):
                    print(f"    {b}")
            else:
                print(f"gc feito: as {len(plano.blobs)} versões saíram do .git"
                      f" (git cat-file -e falha em todas)")
            print(f"  {mesmo}")
        else:
            print("o texto velho continua nos objetos do .git até o gc — para apagar agora:")
            if subprocess.run(["git", "reflog", "exists", ch.REF], cwd=root).returncode == 0:
                print(f"    git reflog expire --expire=now --expire-unreachable=now {ch.REF}")
            print("    git gc --prune=now")
            print(f"  (ou rode com --prune) · {mesmo}")
        print("cópias feitas antes — um clone, um zip, um backup, um push --mirror — continuam"
              " com o texto: o km não alcança")
        print("km serve: não precisa reiniciar, lê a chancela a cada pedido — recarregue a página;"
              " o ↶ Desfazer aprovação de antes desta limpeza não vale mais")
    return 0


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
    """One panel for every registered project, from wherever you are.

    Started inside a repository that uses km, it registers it — serving it means you want to
    see it — and opens on it.
    """
    from . import projetos as pj
    from . import serve

    inicial = None
    raiz = pj.raiz_git(Path(args.repo).expanduser().resolve())
    if raiz is not None and (raiz / ac.KM_DIR / ac.CONFIG).exists():
        r = pj.adicionar(str(raiz))
        if r["novo"]:
            print(f"registrado: {r['nome']}  ·  {r['caminho']}", flush=True)
        inicial = raiz
    elif raiz is not None:
        print(f"{raiz.name} não usa o km (falta .km/config.json) — não entra no painel.\n"
              f"para entrar: km projects add {raiz} --init")
    return serve.run(port=args.port, by=args.by, inicial=inicial)


def _situacao_projeto(p: dict) -> str:
    if p["erro"]:
        return "—"
    return f"{p['pct']} a aprovar" if p["pct"] else "em dia"


def cmd_projects(args) -> int:
    """The projects `km serve` shows. Only the list changes; no repository is touched."""
    from . import projetos as pj

    acao = getattr(args, "acao", None)
    if acao in ("add", "adicionar"):
        caminho = os.path.join(args.repo, os.path.expanduser(args.caminho))
        try:
            r = pj.adicionar(caminho, init=args.init)
        except pj.Recusado as e:
            raise SystemExit(f"km: {e}")
        if args.json:
            print(json.dumps(r, ensure_ascii=False))
            return 0
        if r["iniciado"]:
            print(f"criado {r['caminho']}/.km/config.json — nada é acompanhado ainda")
        print(("registrado: " if r["novo"] else "já estava registrado: ")
              + f"{r['nome']}  ·  {r['caminho']}")
        return 0
    if acao in ("rm", "remover"):
        try:
            r = pj.remover(args.alvo)
        except pj.Recusado as e:
            raise SystemExit(f"km: {e}")
        print(f"fora da lista: {r['nome']}  ·  {r['caminho']}")
        print("o repositório, o .km/config.json e a chancela não foram mexidos")
        return 0

    lista = pj.listar()
    if args.json:
        print(json.dumps(lista, ensure_ascii=False))
        return 0
    if not lista:
        print(f"nenhum projeto registrado ({pj.arquivo()})")
        print("adicionar: km projects add <caminho>   ·   ou km serve dentro do repositório")
        return 0
    largura = max(len(p["nome"]) for p in lista)
    for p in lista:
        linha = f"{p['nome']:<{largura}}  {_situacao_projeto(p):<15} {p['caminho']}"
        if p["erro"]:
            linha += f"  ({p['erro']})"
        print(linha)
    return 0


def cmd_boot(args) -> int:
    """The panel starts with the machine: a generated systemd user unit, like the esteira's."""
    from . import boot
    return boot.executar(args.apply, args.port)


PRE_PUSH = """#!/bin/sh
# knowledge-manager: refuses a push that would send refs/km/*. Written by `km install-hooks`.
# The chancel (refs/km/chancela) keeps the full text of every file ever approved, files
# never committed to any branch included — and `git push --mirror` sends every ref.
recusa=""
while read -r local_ref local_sha remote_ref remote_sha; do
  alvo=""
  case "$local_ref" in refs/km/*) alvo="$local_ref" ;; esac
  # Apagar um refs/km/* do remoto (sha local só de zeros) é limpar, não vazar: passa.
  case "$local_sha" in *[!0]*) case "$remote_ref" in refs/km/*) alvo="$remote_ref" ;; esac ;; esac
  [ -n "$alvo" ] && recusa="$recusa $alvo"
done
[ -z "$recusa" ] && exit 0
cat >&2 <<EOF
km: push recusado — levaria ao remoto:$recusa
A chancela guarda o texto inteiro de cada arquivo aprovado, inclusive o que nunca foi
commitado em branch nenhum. Nada foi enviado.
  um branch:             git push <remoto> <branch>
  branches e tags:       git push <remoto> --all && git push <remoto> --tags
  enviar mesmo assim:    git push --no-verify   (sabendo o que vai junto)
EOF
exit 1
"""


def cmd_install_hooks(args) -> int:
    """So nothing has to be memorised: the repository tells you where it stands, and does
    not hand the chancel to a remote."""
    root = _root(args)
    r = subprocess.run(["git", "rev-parse", "--git-path", "hooks"], cwd=root,
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("não é um repositório git")
    hooks = root / r.stdout.strip()          # respeita core.hooksPath e worktrees
    hooks.mkdir(parents=True, exist_ok=True)
    km = Path(__file__).resolve().parent.parent / "bin" / "km"
    pos_commit = f"""#!/bin/sh
# knowledge-manager: report only. Never blocks a commit, always exits 0.
"{km}" pendente --short 2>/dev/null || true
exit 0
"""
    codigo = 0
    for nome, corpo, diz in (
            ("post-commit", pos_commit, "diz onde você está depois de cada commit"),
            ("pre-push", PRE_PUSH, "recusa um push que levaria refs/km/* (git push --mirror)")):
        target = hooks / nome
        if target.exists() and "knowledge-manager" not in target.read_text(encoding="utf-8"):
            print(f"{target} já existe e não é nosso — não mexi")
            codigo = 1
            continue
        target.write_text(corpo, encoding="utf-8")
        target.chmod(0o755)
        onde = target.relative_to(root) if target.is_relative_to(root) else target
        print(f"instalado {onde} — {diz}")
    return codigo


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="km",
                                description="O que dos seus documentos você realmente revisou.")
    p.add_argument("--repo", default=os.getcwd(), help="raiz do repositório (padrão: aqui)")
    sub = p.add_subparsers(dest="cmd", required=True)
    quem = "human:" + os.environ.get("USER", "unknown")

    sub.add_parser("init", help="criar .km/config.json, com o opt-in por arquivo"
                   ).set_defaults(func=cmd_init)

    s = sub.add_parser("serve", aliases=["painel"],
                       help="a tela da revisão de todos os projetos, num servidor local sob demanda")
    s.add_argument("--port", type=int, default=8431)
    s.add_argument("--by", default=quem)
    s.set_defaults(func=cmd_serve)

    s = sub.add_parser("projects", aliases=["projetos"],
                       help="os projetos que o km serve mostra: listar, adicionar, tirar da lista")
    s.add_argument("--json", action="store_true",
                   help="lista de {nome, caminho, pct, n, pendentes, erro}")
    s.set_defaults(func=cmd_projects)
    acoes = s.add_subparsers(dest="acao")
    a = acoes.add_parser("add", aliases=["adicionar"],
                         help="registrar a raiz de um repositório git que usa o km")
    a.add_argument("caminho")
    a.add_argument("--init", action="store_true",
                   help="criar .km/config.json vazio se ainda não houver (como km init)")
    a.add_argument("--json", action="store_true", help="{nome, caminho, novo, iniciado}")
    a = acoes.add_parser("rm", aliases=["remover"],
                         help="tirar da lista; o repositório, a config e a chancela ficam")
    a.add_argument("alvo", help="o nome, como km projects mostra, ou o caminho")

    s = sub.add_parser("pendente", aliases=["pending"],
                       help="o que mudou desde a chancela, e o que nunca teve uma")
    s.add_argument("file", nargs="?")
    s.add_argument("--novos", action="store_true", help="listar os arquivos acompanhados que nunca tiveram chancela")
    s.add_argument("--short", action="store_true", help="uma linha, para o hook")
    s.add_argument("--json", action="store_true", help="para o editor e para a tela")
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
    s.add_argument("--by", default=quem)
    s.set_defaults(func=cmd_chancela)

    s = sub.add_parser("restore", help="devolver ao texto que você chancelou")
    s.add_argument("file")
    s.add_argument("--hunk", action="append", default=[])
    s.add_argument("--all", action="store_true")
    s.add_argument("-m", "--message", help="por que a mudança não serve")
    s.set_defaults(func=cmd_restore)

    s = sub.add_parser("mv", aliases=["mover"],
                       help="mover um arquivo ou pasta com git mv, levando a chancela e a"
                            " configuração junto")
    s.add_argument("origem", help="arquivo ou pasta, relativo à raiz do repositório")
    s.add_argument("destino", help="o caminho novo; não pode existir")
    s.add_argument("--dry-run", action="store_true", help="mostrar o que aconteceria, sem escrever")
    s.set_defaults(func=cmd_mv)

    s = sub.add_parser("forget", aliases=["esquecer"],
                       help="tirar arquivos ou pastas da chancela de vez — de todo o histórico"
                            " do ref e da configuração (sem --apply, só mostra)")
    s.add_argument("caminhos", nargs="+", metavar="caminho",
                   help="arquivo ou pasta, relativo à raiz do repositório")
    s.add_argument("--apply", action="store_true", help="reescrever o ref e a configuração")
    s.add_argument("--prune", action="store_true",
                   help="depois, apagar do .git as versões velhas (reflog do ref e git gc --prune=now)")
    s.set_defaults(func=cmd_forget)

    s = sub.add_parser("lint", help="a convenção das marcas: texto de exemplo, marca sumida")
    s.add_argument("file", nargs="?")
    s.add_argument("--strict", action="store_true", help="sai com erro se houver apontamento")
    s.set_defaults(func=cmd_lint)

    s = sub.add_parser("marcas", aliases=["marks"],
                       help="as marcas 📌 to_do de todo Markdown do git,"
                            " acompanhado ou não — para um agente achar o que fazer")
    s.add_argument("--tipo", "--kind", dest="tipo", choices=["to_do", "comment"])
    s.add_argument("--todas", "--all", dest="todas", action="store_true",
                   help="incluir 💬 comment")
    s.add_argument("--json", action="store_true",
                   help="lista de {file, line, kind, date, text}")
    s.set_defaults(func=cmd_marcas)

    s = sub.add_parser("quando", aliases=["when"],
                       help="quando este trecho teve chancela pela última vez")
    s.add_argument("file")
    s.add_argument("--trecho", help="parte do título")
    s.add_argument("--limit", type=int, default=5)
    s.set_defaults(func=cmd_quando)

    s = sub.add_parser("baseline", help="o documento como você o chancelou (coluna da esquerda)")
    s.add_argument("file")
    s.set_defaults(func=cmd_baseline)

    s = sub.add_parser("boot", help="o painel sobe com a máquina: a unidade systemd de usuário "
                       "(sem --apply, só mostra)")
    s.add_argument("--apply", action="store_true", help="escrever a unidade, ligar e (re)iniciar")
    s.add_argument("--port", type=int, default=8431)
    s.set_defaults(func=cmd_boot)

    sub.add_parser("install-hooks", help="uma linha depois de cada commit, dizendo onde você está,"
                   " e um pre-push que recusa enviar refs/km/*").set_defaults(func=cmd_install_hooks)

    args = p.parse_args(argv)
    try:
        return args.func(args)
    except ac.ConfigInvalida as e:
        # A config é escrita à mão também: o que está errado nela é uma frase, não um traceback.
        raise SystemExit(f"km: {e}")
