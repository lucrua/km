#!/usr/bin/env python3
"""One shot: carry an old block ledger (.km/blocks.jsonl) into refs/km/chancela.

The ledger stored the vouched text of each block. That text is exactly what the chancel
holds, so the migration is a projection: for every passage of the file today, keep the
vouched body if there was one and drop the passage if there was not. A passage you never
endorsed then shows up in the review as an addition, which is what it is.

Usage: python3 tools/migrar_ledger.py <repo> [--apply]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from km import chancela as ch  # noqa: E402


def projetar(root: Path, rel: str, registros: dict[str, dict]) -> tuple[str, int, int]:
    atual = ch.atual(root, rel) or ""
    linhas = atual.splitlines()
    saida, com, sem = [], 0, 0
    for t in ch.trechos(atual):
        rec = registros.get(f"{rel}#{t.caminho}")
        if not rec:
            sem += 1
            continue
        com += 1
        cabeca = linhas[t.linha - 1] if t.titulo_bruto else ""
        corpo = rec.get("body", "")
        saida.append((cabeca + "\n" + corpo).strip("\n") if cabeca else corpo)
    texto = "\n\n".join(s for s in saida if s.strip())
    return (texto + "\n" if texto else ""), com, sem


def main(argv: list[str]) -> int:
    root = Path(argv[0]).expanduser().resolve()
    aplicar = "--apply" in argv
    ledger = root / ".km" / "blocks.jsonl"
    if not ledger.exists():
        print(f"{ledger} não existe — nada a migrar")
        return 1
    registros = {}
    for linha in ledger.read_text(encoding="utf-8").splitlines():
        if linha.strip():
            rec = json.loads(linha)
            registros[rec["key"]] = rec

    mudancas = {}
    for rel in sorted({r["file"] for r in registros.values()}):
        if ch.atual(root, rel) is None:
            print(f"{rel}: não está mais no disco — ignorado")
            continue
        texto, com, sem = projetar(root, rel, registros)
        mudancas[rel] = texto
        print(f"{rel}: {com} trechos com chancela, {sem} sem")

    if not aplicar:
        print("\nnada escrito — rode de novo com --apply")
        return 0
    commit = ch.escrever(root, mudancas, "chancela: migrada do ledger de blocos\n\n"
                                         "O texto endossado por bloco, projetado como a "
                                         "cópia revisada de cada arquivo.\n")
    print(f"\nrefs/km/chancela  ·  {commit[:8]}  ·  {len(mudancas)} arquivo(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
