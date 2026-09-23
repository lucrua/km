"""Which documents the chancel covers: three lists and the closest decision.

`.km/config.json` holds `folders`, `files` and `except`. A folder is a rule — it takes the
Markdown files under it, including the ones created later; a file is taken on its own; an
exception leaves a file or folder out of a rule above it. For any path the closest decision
wins, walking from the file up to the root. The design is in docs/tracked-files.md.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

KM_DIR = ".km"
CONFIG = "config.json"
CHAVES = ("folders", "files", "except")


class ConfigInvalida(Exception):
    """The config says something `km` cannot read. The message is shown as it is."""


def vazia() -> dict:
    return {k: [] for k in CHAVES}


def _caminho_valido(caminho: object, pasta: bool) -> bool:
    if not isinstance(caminho, str) or not caminho:
        return False
    if caminho == ".":
        return pasta
    # Uma barra invertida é um caractere como outro no nome de um arquivo (em Linux, `a\\b.md`
    # existe); o separador é sempre "/".
    return (not caminho.startswith("/") and not caminho.endswith("/")
            and ".." not in caminho.split("/"))


def carregar(root: Path) -> dict:
    """The config, validated. No file means nothing is tracked."""
    path = root / KM_DIR / CONFIG
    if not path.exists():
        return vazia()
    try:
        dados = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigInvalida(f".km/config.json não é JSON válido (linha {e.lineno}): {e.msg}")
    if not isinstance(dados, dict):
        raise ConfigInvalida(".km/config.json tem que ser um objeto com folders, files e except")
    sobra = sorted(set(dados) - set(CHAVES))
    if sobra:
        raise ConfigInvalida(f".km/config.json tem chave(s) que o km não lê: {', '.join(sobra)}"
                             " — o formato é folders, files, except")
    cfg = vazia()
    for chave in CHAVES:
        lista = dados.get(chave, [])
        if not isinstance(lista, list):
            raise ConfigInvalida(f".km/config.json: `{chave}` tem que ser uma lista")
        for caminho in lista:
            if not _caminho_valido(caminho, pasta=chave == "folders"):
                raise ConfigInvalida(f".km/config.json: caminho inválido em `{chave}`: {caminho!r}"
                                     " — relativo, com /, sem .. e sem / no fim")
        cfg[chave] = list(lista)
    return cfg


def sha_config(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(normalizar(cfg), sort_keys=True).encode()).hexdigest()[:12]


def validar(cfg: dict) -> None:
    """Refuse a config `carregar` would refuse — so nothing written can lock `km` out."""
    for chave in CHAVES:
        for caminho in cfg.get(chave, []):
            if not _caminho_valido(caminho, pasta=chave == "folders"):
                raise ConfigInvalida(f"caminho inválido em `{chave}`: {caminho!r}")


def gravar(root: Path, cfg: dict) -> None:
    """Write the config normalised, atomically: a reader never sees half a file."""
    validar(cfg)
    d = root / KM_DIR
    d.mkdir(parents=True, exist_ok=True)
    texto = json.dumps(normalizar(cfg), indent=2, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(texto)
        os.replace(tmp, d / CONFIG)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _pais(caminho: str) -> list[str]:
    """The folders above a path, deepest first, without "."."""
    partes = caminho.split("/")[:-1] if caminho != "." else []
    return ["/".join(partes[:i]) for i in range(len(partes), 0, -1)]


def herdado(caminho: str, cfg: dict) -> bool:
    """The decision a path gets from the folders above it, ignoring any entry for itself."""
    for pasta in _pais(caminho):
        if pasta in cfg["except"]:
            return False
        if pasta in cfg["folders"]:
            return True
    return caminho != "." and "." in cfg["folders"]


def decisao(rel: str, cfg: dict) -> bool:
    """Is this file tracked? The closest decision wins; at the same level, except wins."""
    if rel in cfg["except"]:
        return False
    if rel in cfg["files"]:
        return True
    return herdado(rel, cfg)


def normalizar(cfg: dict) -> dict:
    """The same decisions, with nothing redundant, sorted — so the file stays readable."""
    pastas = sorted(set(cfg["folders"]))
    excecoes = sorted(set(cfg["except"]))
    # No mesmo nível a exceção vence: um arquivo listado nos dois não é acompanhado, e
    # continuar em `files` depois que a exceção sai por redundante o faria voltar.
    arquivos = sorted(set(cfg["files"]) - set(excecoes))
    bruto = {"folders": pastas, "files": arquivos, "except": excecoes}
    pastas = [p for p in pastas if p not in excecoes and (p == "." or not herdado(p, bruto))]
    limpo = {"folders": pastas, "files": [], "except": excecoes}
    excecoes = [e for e in excecoes if herdado(e, limpo)]
    limpo = {"folders": pastas, "files": [], "except": excecoes}
    arquivos = [a for a in arquivos if a not in excecoes and not herdado(a, limpo)]
    return {"folders": pastas, "files": arquivos, "except": excecoes}


def candidatos(root: Path) -> list[str]:
    """The Markdown files git knows about or would add — `.gitignore` respected."""
    r = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard",
                        "--", "*.md"], cwd=root, capture_output=True)
    if r.returncode != 0:
        return []
    return sorted({p for p in r.stdout.decode("utf-8").split("\0")
                   if p and (root / p).is_file()})


def documentos(root: Path, cfg: dict | None = None) -> list[str]:
    """The files the chancel covers today: tracked candidates, plus files named explicitly
    that exist on disk even if git ignores them — naming a file is a decision."""
    from . import chancela as ch

    cfg = cfg if cfg is not None else carregar(root)
    achados = {c for c in candidatos(root) if decisao(c, cfg)}
    achados |= {f for f in cfg["files"] if (root / f).is_file() and decisao(f, cfg)}
    # Um arquivo acompanhado que saiu do disco ainda tem chancela: a remoção é uma mudança
    # como outra e tem que poder ser aprovada — senão um agente apaga e ninguém vê.
    achados |= {f for f in ch.arquivos(root) if decisao(f, cfg)}
    return sorted(achados)


def _abaixo(caminho: str, outro: str) -> bool:
    return caminho == "." or outro.startswith(caminho + "/")


def _limpar_abaixo(cfg: dict, caminho: str) -> dict:
    return {k: [p for p in cfg[k] if not _abaixo(caminho, p)] for k in CHAVES}


def marcar(cfg: dict, caminho: str, pasta: bool) -> dict:
    """Tick a file or folder, as a tri-state tree does."""
    novo = {k: list(v) for k, v in cfg.items()}
    novo["except"] = [e for e in novo["except"] if e != caminho]
    if pasta:
        novo = _limpar_abaixo(novo, caminho)
        novo["folders"].append(caminho)
    elif not decisao(caminho, novo):
        novo["files"].append(caminho)
    return normalizar(novo)


def desmarcar(cfg: dict, caminho: str, pasta: bool) -> dict:
    """Untick a file or folder. Under a rule it becomes an exception; the chancel is kept."""
    novo = {k: list(v) for k, v in cfg.items()}
    novo["files"] = [f for f in novo["files"] if f != caminho]
    novo["folders"] = [f for f in novo["folders"] if f != caminho]
    if pasta:
        novo = _limpar_abaixo(novo, caminho)
        if caminho != "." and herdado(caminho, novo):
            novo["except"].append(caminho)
    elif decisao(caminho, novo):
        novo["except"].append(caminho)
    return normalizar(novo)


def rotulo(root: Path, antes: dict, depois: dict, caminho: str, pasta: bool, marcou: bool) -> str:
    """One line saying what the click did, in terms of files."""
    from . import chancela as ch

    ja, agora = set(documentos(root, antes)), set(documentos(root, depois))
    entraram, sairam = len(agora - ja), len(ja - agora)
    nome = "o repositório inteiro" if caminho == "." else caminho + ("/" if pasta else "")
    if pasta and marcou:
        return f"{nome} passou a ser acompanhada (+ novos) · {entraram} arquivo(s) entraram"
    if pasta:
        return f"{nome} saiu do acompanhamento · {sairam} arquivo(s) saíram · as chancelas ficam guardadas"
    if marcou:
        return f"{nome} passou a ser acompanhado"
    guardada = " · a chancela fica guardada" if caminho in ch.arquivos(root) else ""
    return f"{nome} saiu do acompanhamento{guardada}"


def arvore(root: Path) -> dict:
    """The repository as a tree of Markdown files, with what each tick means."""
    from . import chancela as ch

    try:
        cfg = carregar(root)
        erro = ""
    except ConfigInvalida as e:
        cfg, erro = vazia(), str(e)
    cands = set(candidatos(root))
    na_chancela = set(ch.arquivos(root))
    todos = sorted(cands | na_chancela | set(cfg["files"]))

    raiz = {"nome": root.name, "caminho": ".", "tipo": "pasta", "filhos": []}
    pastas = {".": raiz}

    def pasta_de(caminho: str) -> dict:
        if caminho in pastas:
            return pastas[caminho]
        pai = pasta_de(caminho.rsplit("/", 1)[0] if "/" in caminho else ".")
        n = {"nome": caminho.rsplit("/", 1)[-1], "caminho": caminho, "tipo": "pasta", "filhos": []}
        pai["filhos"].append(n)
        pastas[caminho] = n
        return n

    for rel in todos:
        existe = rel in cands or (root / rel).is_file()
        decidido = decisao(rel, cfg)
        acomp = existe and decidido
        if not existe:
            estado = "não existe mais"
        elif acomp:
            s = ch.situacao(root, rel)
            estado = ("sem chancela" if not s.tem_chancela
                      else f"{ch.percentual(*ch.pendencia_do_arquivo(s))} a aprovar" if s.mudancas
                      else "em dia")
        elif rel in na_chancela:
            estado = "pausado · chancela guardada"
        else:
            estado = "—"
        pai = pasta_de(rel.rsplit("/", 1)[0] if "/" in rel else ".")
        pai["filhos"].append({"nome": rel.rsplit("/", 1)[-1], "caminho": rel, "tipo": "arquivo",
                              "marcado": "sim" if decidido else "nao", "estado": estado,
                              "existe": existe, "excecao": rel in cfg["except"]})

    def completar(n: dict) -> tuple[int, int]:
        acomp = total = 0
        for f in n["filhos"]:
            if f["tipo"] == "pasta":
                a, t = completar(f)
            else:
                a, t = (1 if f["existe"] and f["marcado"] == "sim" else 0), (1 if f["existe"] else 0)
            acomp, total = acomp + a, total + t
        n["filhos"].sort(key=lambda f: (f["tipo"] == "arquivo", f["nome"].lower()))
        n["acompanhados"], n["total"] = acomp, total
        n["marcado"] = "nao" if acomp == 0 else ("sim" if acomp == total else "misto")
        # `+ novos`: would a Markdown file created here tomorrow be tracked?
        n["novos"] = decisao(("" if n["caminho"] == "." else n["caminho"] + "/") + "\0novo.md", cfg)
        n["regra_propria"] = n["caminho"] in cfg["folders"]
        n["excecoes"] = sum(1 for e in cfg["except"] if _abaixo(n["caminho"], e))
        return acomp, total

    completar(raiz)
    return {"raiz": raiz, "sha": sha_config(cfg), "config": cfg, "erro": erro}
