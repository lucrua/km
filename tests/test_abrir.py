"""Abrir no VS Code: o painel pede, o servidor roda `code <arquivo>` — e só para um documento
que ele conhece, dentro do repositório.

Run: python3 -m unittest discover -s tests -t . -v"""

import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from km import serve


def git(root, *args):
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


CODE = "/mnt/c/VS Code/bin/code"


class AbrirTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp()).resolve()
        self.fora = Path(tempfile.mkdtemp()).resolve()
        git(self.dir, "init", "-q", "-b", "main")
        (self.dir / "docs").mkdir()
        (self.dir / "docs" / "regras.md").write_text("# regras\n\ntexto\n", encoding="utf-8")
        (self.dir / "leia.txt").write_text("não é markdown\n", encoding="utf-8")
        (self.fora / "segredo.md").write_text("# fora\n", encoding="utf-8")
        (self.dir / "atalho.md").symlink_to(self.fora / "segredo.md")
        self.chamadas = []

    def tearDown(self):
        shutil.rmtree(self.dir)
        shutil.rmtree(self.fora)

    def abrir(self, pedido, code=CODE):
        with mock.patch.object(serve.shutil, "which", lambda nome: code if nome == "code" else None), \
             mock.patch.object(serve, "_lancar", self.chamadas.append):
            return serve.abrir_no_code(self.dir, pedido)

    def test_documento_abre_com_o_code(self):
        r = self.abrir({"file": "docs/regras.md"})
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.chamadas, [[CODE, str(self.dir / "docs" / "regras.md")]])

    def test_com_linha_abre_na_linha(self):
        r = self.abrir({"file": "docs/regras.md", "line": 3})
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.chamadas, [[CODE, "-g", f"{self.dir / 'docs' / 'regras.md'}:3"]])

    def test_linha_invalida_abre_so_o_arquivo(self):
        self.abrir({"file": "docs/regras.md", "line": "3; rm -rf /"})
        self.assertEqual(self.chamadas, [[CODE, str(self.dir / "docs" / "regras.md")]])

    def test_caminhos_recusados(self):
        for rel in ["../x.md", "docs/../../x.md", str(self.fora / "segredo.md"), "/etc/passwd",
                    "atalho.md", "leia.txt", "nao-existe.md", "", None, 3]:
            with self.subTest(rel=rel):
                r = self.abrir({"file": rel})
                self.assertFalse(r["ok"], r)
                self.assertTrue(r["erro"])
        self.assertEqual(self.chamadas, [])

    def test_sem_code_no_path(self):
        r = self.abrir({"file": "docs/regras.md"}, code=None)
        self.assertFalse(r["ok"])
        self.assertIn("o comando code não está no PATH do km serve", r["erro"])
        self.assertEqual(self.chamadas, [])

    def test_lancar_nao_espera_e_nao_usa_shell(self):
        with mock.patch.object(serve.subprocess, "Popen") as popen:
            serve._lancar([CODE, "/a b.md"])
        args, kw = popen.call_args
        self.assertEqual(args[0], [CODE, "/a b.md"])
        self.assertFalse(kw.get("shell", False))
        self.assertEqual(kw.get("stdout"), subprocess.DEVNULL)
        self.assertEqual(kw.get("stderr"), subprocess.DEVNULL)
        self.assertTrue(kw.get("start_new_session"))


class RotaAbrirTest(AbrirTest):
    """A rota passa pelas mesmas proteções das outras POST."""

    def setUp(self):
        super().setUp()
        handler = type("H", (serve.Handler,), {"root": self.dir, "by": "teste"})
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.porta = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        super().tearDown()

    def post(self, corpo, tipo="application/json", origem="mesma"):
        cab = {"Content-Type": tipo}
        if origem == "mesma":
            cab["Origin"] = f"http://127.0.0.1:{self.porta}"
        elif origem:
            cab["Origin"] = origem
        req = urllib.request.Request(f"http://127.0.0.1:{self.porta}/api/abrir",
                                     data=json.dumps(corpo).encode(), headers=cab, method="POST")
        with mock.patch.object(serve.shutil, "which", lambda nome: CODE), \
             mock.patch.object(serve, "_lancar", self.chamadas.append):
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, None

    def test_rota_abre(self):
        codigo, r = self.post({"file": "docs/regras.md", "line": 2})
        self.assertEqual(codigo, 200)
        self.assertTrue(r["ok"], r)
        self.assertEqual(len(self.chamadas), 1)

    def test_rota_recusa_outro_tipo(self):
        codigo, _ = self.post({"file": "docs/regras.md"}, tipo="text/plain")
        self.assertEqual(codigo, 403)
        self.assertEqual(self.chamadas, [])

    def test_rota_recusa_outra_origem(self):
        codigo, _ = self.post({"file": "docs/regras.md"}, origem="http://mal.example")
        self.assertEqual(codigo, 403)
        self.assertEqual(self.chamadas, [])

    def test_rota_recusa_travessia(self):
        codigo, r = self.post({"file": "../x.md"})
        self.assertEqual(codigo, 200)
        self.assertFalse(r["ok"])
        self.assertEqual(self.chamadas, [])


if __name__ == "__main__":
    unittest.main()
