"""`km boot`: the panel starts with the machine, as a systemd user unit.

The same shape as the esteira's `esteira boot`: the unit file is GENERATED, never edited by
hand; without `--apply` nothing is written; the PATH is built from what km really calls, not
copied from the shell.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

UNIDADE = "km.service"


def diretorio() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "systemd" / "user"


def caminho(km_bin: str, codigo: str | None) -> str:
    # Copiar o $PATH do WSL não serve: ele traz os caminhos do Windows, e o systemd corta
    # `Environment=` sem aspas no primeiro espaço. Entra o que o km chama — ele mesmo, o
    # python e o git do sistema — e, se existir, o diretório do `code`, para o *abrir no
    # VS Code*. É o único do Windows, e tem espaço no nome: por isso a linha vai entre aspas.
    partes = [km_bin, "/usr/local/bin", "/usr/bin", "/bin"]
    if codigo:
        partes.append(codigo)
    return ":".join(partes)


def achar_code(raiz: str = "/mnt/c/Users") -> str | None:
    """The directory of VS Code's `code`: the PATH first, then the Windows install.

    Um serviço que sobe com o Ubuntu não tem o PATH do terminal do VS Code, que é de onde o
    `code` costuma vir: sem este segundo lugar, o *abrir no VS Code* nunca funcionaria nele."""
    achado = shutil.which("code")
    if achado:
        return os.path.dirname(achado)
    for c in sorted(Path(raiz).glob("*/AppData/Local/Programs/Microsoft VS Code/bin/code")):
        return str(c.parent)
    return None


def unidade(sha: str, km: str, caminho: str, home: str, porta: int) -> str:
    return "\n".join([
        f"# GENERATED — escrito por `km boot --apply` a partir de {sha}.",
        "# Não edite aqui; edite km/boot.py e rode de novo.",
        "# O PATH abaixo foi resolvido no momento da escrita: se o VS Code mudar de",
        "# lugar, rode `km boot --apply` outra vez.",
        "[Unit]",
        "Description=km — o painel da chancela, todos os projetos",
        "[Service]",
        "Type=simple",
        f"Environment=\"PATH={caminho}\"",
        f"Environment=HOME={home}",
        f"WorkingDirectory={home}",
        f"ExecStart={km} serve --port {porta}",
        "Restart=on-failure",
        "[Install]",
        "WantedBy=default.target",
        "",
    ])


def systemctl(*args: str) -> str:
    r = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True)
    return (r.stdout or r.stderr).strip()


def responde(porta: int) -> bool:
    for _ in range(20):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{porta}/api/projetos", timeout=1) as r:
                if r.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(0.25)
    return False


def _linger() -> str:
    r = subprocess.run(["loginctl", "show-user", os.environ.get("USER", ""), "-p", "Linger", "--value"],
                       capture_output=True, text=True)
    return r.stdout.strip() or "?"


def executar(aplicar: bool, porta: int) -> int:
    raiz = Path(__file__).resolve().parent.parent
    km = str(raiz / "bin" / "km")
    sha = subprocess.run(["git", "-C", str(raiz), "rev-parse", "--short", "HEAD"],
                         capture_output=True, text=True).stdout.strip() or "unknown"
    code = achar_code()
    texto = unidade(sha, km, caminho(str(raiz / "bin"), code),
                    str(Path.home()), porta)
    alvo = diretorio() / UNIDADE

    print(f"linger    {_linger()}  (precisa ser yes para sobreviver ao fechar da janela)")
    print(f"unidade   {alvo}  ·  {systemctl('show', UNIDADE, '-p', 'UnitFileState', '--value') or 'ausente'}")
    print(f"km        {km}")
    print(f"code      {code or 'não encontrado — o abrir no VS Code vai avisar'}")
    print(f"porta     {porta}")
    print()
    if not aplicar:
        print(texto)
        print("(dry run — passe --apply para escrever e ligar)")
        return 0

    alvo.parent.mkdir(parents=True, exist_ok=True)
    tmp = alvo.with_suffix(".tmp")
    tmp.write_text(texto, encoding="utf-8")
    tmp.replace(alvo)
    systemctl("daemon-reload")
    systemctl("enable", UNIDADE)
    # restart e não start: depois de um merge no km, o Python em memória é o velho.
    systemctl("restart", UNIDADE)
    if not responde(porta):
        print(f"✕ o km não respondeu em http://127.0.0.1:{porta} — veja: journalctl --user -u km -n 30",
              file=sys.stderr)
        return 1
    print(f"✓ {alvo.name} ligado · http://127.0.0.1:{porta}")
    return 0
