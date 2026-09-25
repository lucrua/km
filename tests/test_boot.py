"""`km boot`: the systemd user unit that starts the panel with the machine.

Run: python3 -m unittest discover -s tests -t . -v
"""

import contextlib
import io
import os
import unittest
from pathlib import Path
from unittest import mock

from km import boot
from km import cli


class UnidadeTest(unittest.TestCase):
    def texto(self, codigo="/mnt/c/Users/x/AppData/Local/Programs/Microsoft VS Code/bin"):
        return boot.unidade(sha="abc1234", km="/home/u/knowledge-manager/bin/km",
                            caminho=boot.caminho("/home/u/knowledge-manager/bin", codigo),
                            home="/home/u", porta=8431)

    def test_the_unit_says_it_is_generated_and_from_which_commit(self):
        t = self.texto()
        self.assertTrue(t.startswith("# GENERATED — escrito por `km boot --apply` a partir de abc1234."))
        self.assertIn("Não edite aqui", t)

    def test_the_unit_serves_every_project_on_the_port_from_home(self):
        t = self.texto()
        self.assertIn("ExecStart=/home/u/knowledge-manager/bin/km serve --port 8431\n", t)
        self.assertIn("WorkingDirectory=/home/u\n", t)
        self.assertIn("Environment=HOME=/home/u\n", t)
        self.assertIn("Restart=on-failure\n", t)
        self.assertIn("WantedBy=default.target\n", t)

    def test_the_path_is_quoted_whole_so_a_windows_dir_with_spaces_survives(self):
        # systemd splits an unquoted Environment= on spaces: `Microsoft VS Code` would cut the
        # PATH and `abrir no VS Code` would find no `code`.
        t = self.texto()
        linha = next(l for l in t.splitlines() if l.startswith("Environment=\"PATH="))
        self.assertTrue(linha.endswith("Microsoft VS Code/bin\""), linha)

    def test_the_path_has_km_and_the_system_and_code_only_when_found(self):
        self.assertEqual(boot.caminho("/k/bin", None), "/k/bin:/usr/local/bin:/usr/bin:/bin")
        self.assertEqual(boot.caminho("/k/bin", "/c/bin"), "/k/bin:/usr/local/bin:/usr/bin:/bin:/c/bin")


class CodeTest(unittest.TestCase):
    def test_code_comes_from_the_path_first(self):
        with mock.patch.object(boot.shutil, "which", lambda n: "/x/bin/code"):
            self.assertEqual(boot.achar_code(raiz="/nao/existe"), "/x/bin")

    def test_without_code_on_the_path_the_windows_install_is_found(self):
        # A service that starts with Ubuntu never has VS Code's terminal PATH.
        import tempfile
        raiz = Path(tempfile.mkdtemp())
        bin_ = raiz / "fulano" / "AppData" / "Local" / "Programs" / "Microsoft VS Code" / "bin"
        bin_.mkdir(parents=True)
        (bin_ / "code").write_text("")
        with mock.patch.object(boot.shutil, "which", lambda n: None):
            self.assertEqual(boot.achar_code(raiz=str(raiz)), str(bin_))

    def test_no_code_anywhere_is_none(self):
        with mock.patch.object(boot.shutil, "which", lambda n: None):
            self.assertIsNone(boot.achar_code(raiz="/nao/existe"))


class ComandoTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(os.environ["XDG_CONFIG_HOME"]) / "systemd" / "user"
        (self.dir / "km.service").unlink(missing_ok=True)
        self.chamadas = []

    def rodar(self, *argv):
        def systemctl(*args):
            self.chamadas.append(args)
            return ""
        out = io.StringIO()
        with mock.patch.object(boot, "systemctl", systemctl), \
             mock.patch.object(boot, "responde", lambda porta: True), \
             contextlib.redirect_stdout(out):
            codigo = cli.main(["boot", *argv])
        return codigo, out.getvalue()

    def test_without_apply_it_writes_nothing_and_starts_nothing(self):
        codigo, out = self.rodar()
        self.assertEqual(codigo, 0)
        self.assertFalse((self.dir / "km.service").exists())
        self.assertEqual([c for c in self.chamadas if c and c[0] in ("enable", "restart", "daemon-reload")], [])
        self.assertIn("--apply", out)

    def test_apply_writes_the_unit_reloads_enables_and_restarts(self):
        codigo, out = self.rodar("--apply")
        self.assertEqual(codigo, 0, out)
        self.assertIn("ExecStart=", (self.dir / "km.service").read_text(encoding="utf-8"))
        feitas = [c[0] for c in self.chamadas]
        for passo in ("daemon-reload", "enable", "restart"):
            self.assertIn(passo, feitas)
        self.assertLess(feitas.index("daemon-reload"), feitas.index("restart"))

    def test_a_port_that_never_answers_fails_loudly(self):
        out = io.StringIO()
        with mock.patch.object(boot, "systemctl", lambda *a: ""), \
             mock.patch.object(boot, "responde", lambda porta: False), \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            codigo = cli.main(["boot", "--apply"])
        self.assertNotEqual(codigo, 0)
        self.assertIn("journalctl --user -u km", out.getvalue())


if __name__ == "__main__":
    unittest.main()
