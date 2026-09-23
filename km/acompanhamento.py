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
    return (not caminho.startswith("/") and not caminho.endswith("/")
            and "\\" not in caminho and ".." not in caminho.split("/"))


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
            if not _caminho_valido(caminho, pasta=chave != "files"):
                raise ConfigInvalida(f".km/config.json: caminho inválido em `{chave}`: {caminho!r}"
                                     " — relativo, com /, sem .. e sem / no fim")
        cfg[chave] = list(lista)
    return cfg


def sha_config(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(normalizar(cfg), sort_keys=True).encode()).hexdigest()[:12]


def gravar(root: Path, cfg: dict) -> None:
    """Write the config normalised, atomically: a reader never sees half a file."""
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
    arquivos = sorted(set(cfg["files"]))
    excecoes = sorted(set(cfg["except"]))
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
    return sorted({p for p in r.stdout.decode("utf-8").split("\0") if p})


def documentos(root: Path, cfg: dict | None = None) -> list[str]:
    """The files the chancel covers today: tracked candidates, plus files named explicitly
    that exist on disk even if git ignores them — naming a file is a decision."""
    cfg = cfg if cfg is not None else carregar(root)
    achados = {c for c in candidatos(root) if decisao(c, cfg)}
    achados |= {f for f in cfg["files"] if (root / f).is_file() and decisao(f, cfg)}
    return sorted(achados)
