"""The projects one `km serve` shows: a list of repository roots, kept per user.

`$XDG_CONFIG_HOME/km/projects.json` (by default `~/.config/km/projects.json`) holds
`{"projects": ["/abs/path", ...]}` and nothing else. Each project keeps its own
`.km/config.json` and `refs/km/chancela`; the registry only says where they are. A project
is named by its folder, and two folders with the same name take their parent
(`work/app`, `personal/app`). The server resolves a name to a path through this list and
nothing else. The design is in docs/projects.md.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from . import acompanhamento as ac

CHAVE = "projects"


class RegistroInvalido(ac.ConfigInvalida):
    """The registry says something `km` cannot read. The message is shown as it is."""


class Recusado(Exception):
    """A project that cannot be added or removed, and why — one sentence."""


def arquivo() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or ""
    # A especificação do XDG manda ignorar um caminho relativo.
    raiz = Path(base) if base and Path(base).is_absolute() else Path.home() / ".config"
    return raiz / "km" / "projects.json"


def carregar() -> list[str]:
    """The registered roots, validated. No file means no project."""
    path = arquivo()
    if not path.exists():
        return []
    try:
        dados = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise RegistroInvalido(f"{path} não é JSON válido (linha {e.lineno}): {e.msg}")
    if not isinstance(dados, dict):
        raise RegistroInvalido(f"{path} tem que ser um objeto com a chave projects")
    sobra = sorted(set(dados) - {CHAVE})
    if sobra:
        raise RegistroInvalido(f"{path} tem chave(s) que o km não lê: {', '.join(sobra)}"
                               " — o formato é {\"projects\": [\"/caminho/absoluto\", ...]}")
    lista = dados.get(CHAVE, [])
    if not isinstance(lista, list):
        raise RegistroInvalido(f"{path}: `projects` tem que ser uma lista")
    for c in lista:
        if not isinstance(c, str) or not os.path.isabs(c):
            raise RegistroInvalido(f"{path}: caminho inválido em `projects`: {c!r}"
                                   " — tem que ser absoluto")
    return sorted(dict.fromkeys(os.path.normpath(c) for c in lista))


def gravar(caminhos: list[str]) -> list[str]:
    """Write the list normalised — real paths, no repeats, sorted — atomically."""
    lista = sorted({os.path.realpath(c) for c in caminhos})
    path = arquivo()
    path.parent.mkdir(parents=True, exist_ok=True)
    texto = json.dumps({CHAVE: lista}, indent=2, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".projects-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(texto)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return lista


def nomes(caminhos: list[str]) -> dict[str, str]:
    """path → name: the folder, and as many parents as it takes to tell two apart."""
    prof = {c: 1 for c in caminhos}

    def nome(c: str) -> str:
        return "/".join(Path(c).parts[-prof[c]:])

    while True:
        grupos: dict[str, list[str]] = {}
        for c in caminhos:
            grupos.setdefault(nome(c), []).append(c)
        mudou = False
        for g in grupos.values():
            if len(g) < 2:
                continue
            for c in g:
                if prof[c] < len(Path(c).parts) - 1:
                    prof[c] += 1
                    mudou = True
        if not mudou:
            return {c: nome(c) for c in caminhos}


def resolver(nome: str) -> Path | None:
    """The root registered under this name — and only a registered one."""
    for c, n in nomes(carregar()).items():
        if n == nome:
            return Path(c)
    return None


def nome_de(raiz: Path | str) -> str | None:
    return nomes(carregar()).get(os.path.realpath(raiz))


def raiz_git(pasta: Path) -> Path | None:
    """The top of the work tree `pasta` is in, or None."""
    try:
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=pasta,
                           capture_output=True, text=True)
    except OSError:
        return None
    if r.returncode != 0 or not r.stdout.strip():
        return None
    return Path(os.path.realpath(r.stdout.strip()))


def sem_commit(raiz: Path) -> bool:
    """A repository just made with `git init`: no HEAD yet, so nothing to compare against."""
    r = subprocess.run(["git", "rev-parse", "--verify", "--quiet", "HEAD"], cwd=raiz,
                       capture_output=True, text=True)
    return r.returncode != 0


SEM_COMMIT = "ainda não tem nenhum commit — faça o primeiro"


def adicionar(caminho: str, init: bool = False) -> dict:
    """Register a repository root. Adding one already there is not an error.

    The path must be absolute (or start with ~) and be the root of a git work tree — a
    subfolder would be a second project over the same ref. Without `.km/config.json` it is
    refused unless `init`, which writes the empty config `km init` writes.
    """
    bruto = os.path.expanduser(caminho.strip()) if isinstance(caminho, str) else ""
    if not bruto or not os.path.isabs(bruto):
        raise Recusado(f"{caminho!r}: o caminho tem que ser absoluto (ou começar com ~)")
    pasta = Path(os.path.realpath(bruto))
    if not pasta.exists():
        raise Recusado(f"{bruto} não existe")
    if not pasta.is_dir():
        raise Recusado(f"{bruto} não é uma pasta")
    topo = raiz_git(pasta)
    if topo is None:
        raise Recusado(f"{bruto} não é um repositório git — a chancela é um ref, o km só"
                       " acompanha repositórios")
    if topo != pasta:
        raise Recusado(f"{bruto} não é a raiz do repositório — adicione {topo}")
    iniciado = False
    if not (pasta / ac.KM_DIR / ac.CONFIG).exists():
        if not init:
            raise Recusado(f"{pasta.name} ainda não usa o km (falta .km/config.json) — rode"
                           f" km init dentro dele, ou adicione com --init")
        ac.gravar(pasta, ac.vazia())
        iniciado = True
    antes = carregar()
    novo = str(pasta) not in antes
    if novo:
        gravar(antes + [str(pasta)])
    return {"nome": nome_de(pasta), "caminho": str(pasta), "novo": novo, "iniciado": iniciado}


def remover(alvo: str) -> dict:
    """Take a project off the list, by name or by path. The repository is not touched."""
    lista = carregar()
    por_nome = {n: c for c, n in nomes(lista).items()}
    caminho = por_nome.get(alvo)
    if caminho is None and isinstance(alvo, str) and alvo.strip():
        bruto = os.path.expanduser(alvo.strip())
        if os.path.isabs(bruto):
            for c in (os.path.normpath(bruto), os.path.realpath(bruto)):
                if c in lista:
                    caminho = c
                    break
    if caminho is None:
        raise Recusado(f"{alvo!r} não está na lista de projetos — veja km projects")
    nome = nomes(lista)[caminho]
    gravar([c for c in lista if c != caminho])
    return {"nome": nome, "caminho": caminho}


def resumo(raiz: Path) -> dict:
    """What the list says about one project: how much is left, or what is wrong with it."""
    from . import serve

    if not raiz.is_dir():
        return {"pct": "", "n": 0, "pendentes": 0, "erro": "a pasta não existe mais"}
    if raiz_git(raiz) != Path(os.path.realpath(raiz)):
        return {"pct": "", "n": 0, "pendentes": 0, "erro": "não é mais a raiz de um repositório git"}
    if not (raiz / ac.KM_DIR / ac.CONFIG).exists():
        return {"pct": "", "n": 0, "pendentes": 0, "erro": "sem .km/config.json"}
    if sem_commit(raiz):
        return {"pct": "", "n": 0, "pendentes": 0, "erro": SEM_COMMIT}
    try:
        e = serve.estado(raiz)
    except SystemExit as x:                 # um git que falhou: o erro fica na linha dele
        return {"pct": "", "n": 0, "pendentes": 0, "erro": str(x)}
    return {"pct": e["pct"], "n": len(e["docs"]),
            "pendentes": sum(1 for d in e["docs"] if d["pendente"]), "erro": e.get("erro", "")}


def listar() -> list[dict]:
    """Every project with its name, path and state, sorted by name."""
    saida = []
    for c, n in nomes(carregar()).items():
        saida.append({"nome": n, "caminho": c, **resumo(Path(c))})
    return sorted(saida, key=lambda p: p["nome"].lower())
