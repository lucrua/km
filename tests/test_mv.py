"""`km mv`: moving a reviewed document moves its chancel and its place in the config.

Run: python3 -m unittest discover -s tests -t . -v
"""

import contextlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from km import acompanhamento as ac
from km import chancela as ch
from km import cli

A = "# A\n\nO texto de a.\n\n> 💬 um comentário que viaja junto.\n"
B = "# B\n\nO texto de b.\n"
C = "# C\n\nO texto de c.\n"


def git(root, *args):
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


class MvTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        git(self.dir, "init", "-q", "-b", "main")
        git(self.dir, "config", "user.email", "t@t")
        git(self.dir, "config", "user.name", "t")
        (self.dir / "docs" / "sub").mkdir(parents=True)
        (self.dir / "docs" / "a.md").write_text(A, encoding="utf-8")
        (self.dir / "docs" / "b.md").write_text(B, encoding="utf-8")
        (self.dir / "docs" / "sub" / "c.md").write_text(C, encoding="utf-8")
        (self.dir / "solto.md").write_text("# Solto\n", encoding="utf-8")
        (self.dir / ".gitignore").write_text(".km/\n")
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-qm", "inicial")

    def tearDown(self):
        shutil.rmtree(self.dir)

    def km(self, *args):
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            codigo = cli.main(["--repo", str(self.dir), *args])
        return codigo, saida.getvalue()

    def config(self):
        return json.loads((self.dir / ".km" / "config.json").read_text(encoding="utf-8"))

    def estado(self):
        """Everything a move could touch: the ref, the config, the index and the disk."""
        ref = subprocess.run(["git", "rev-parse", "--verify", "--quiet", ch.REF], cwd=self.dir,
                             capture_output=True, text=True).stdout
        cfg = self.dir / ".km" / "config.json"
        disco = sorted(str(p.relative_to(self.dir)) for p in self.dir.rglob("*")
                       if ".git" not in p.parts)
        return (ref, cfg.read_bytes() if cfg.exists() else None,
                git(self.dir, "status", "--porcelain"), disco)

    def pendentes(self, rel):
        return ch.situacao(self.dir, rel).mudancas

    # ---- a file ------------------------------------------------------------------------

    def test_a_file_move_keeps_its_chancel(self):
        ac.gravar(self.dir, {"folders": [], "files": ["docs/a.md"], "except": []})
        self.km("chancela", "docs/a.md", "--all")
        antes = git(self.dir, "rev-list", "--count", ch.REF)
        self.km("mv", "docs/a.md", "guides/a.md")
        self.assertTrue((self.dir / "guides" / "a.md").exists())
        self.assertFalse((self.dir / "docs" / "a.md").exists())
        self.assertIn("guides/a.md", git(self.dir, "ls-files"))
        self.assertEqual(self.config()["files"], ["guides/a.md"])
        self.assertEqual(ch.chancelado(self.dir, "guides/a.md"), A)
        self.assertIsNone(ch.chancelado(self.dir, "docs/a.md"))
        self.assertEqual(self.pendentes("guides/a.md"), [])
        self.assertEqual(ac.documentos(self.dir), ["guides/a.md"])
        self.assertIn("1 arquivo(s) em dia", self.km("pendente", "--short")[1])
        # one commit on the ref, saying what moved
        self.assertEqual(int(git(self.dir, "rev-list", "--count", ch.REF)), int(antes) + 1)
        self.assertEqual(git(self.dir, "log", "-1", "--format=%s", ch.REF).strip(),
                         "km mv docs/a.md → guides/a.md")

    def test_the_chancel_moves_byte_for_byte(self):
        ac.gravar(self.dir, {"folders": [], "files": ["docs/a.md"], "except": []})
        ch.escrever(self.dir, {"docs/a.md": "linha\r\ncom CRLF\r\n"}, "chancela")
        blob = git(self.dir, "rev-parse", f"{ch.REF}:docs/a.md")
        self.km("mv", "docs/a.md", "guides/a.md")
        self.assertEqual(git(self.dir, "rev-parse", f"{ch.REF}:guides/a.md"), blob)

    def test_an_edit_after_the_move_is_all_that_shows(self):
        ac.gravar(self.dir, {"folders": [], "files": ["docs/a.md"], "except": []})
        self.km("chancela", "docs/a.md", "--all")
        self.km("mv", "docs/a.md", "guides/a.md")
        (self.dir / "guides" / "a.md").write_text(A.replace("texto de a", "texto novo"),
                                                  encoding="utf-8")
        ms = self.pendentes("guides/a.md")
        self.assertEqual(len(ms), 1)
        self.assertEqual(ms[0].unidades[0].antes.texto, "O texto de a.")
        self.assertEqual(ms[0].unidades[0].depois.texto, "O texto novo.")

    def test_uncommitted_edits_move_with_the_file_and_stay_pending(self):
        ac.gravar(self.dir, {"folders": [], "files": ["docs/a.md"], "except": []})
        self.km("chancela", "docs/a.md", "--all")
        editado = A.replace("texto de a", "texto por commitar")
        (self.dir / "docs" / "a.md").write_text(editado, encoding="utf-8")
        self.km("mv", "docs/a.md", "guides/a.md")
        self.assertEqual((self.dir / "guides" / "a.md").read_text(encoding="utf-8"), editado)
        self.assertEqual(ch.chancelado(self.dir, "guides/a.md"), A)
        ms = self.pendentes("guides/a.md")
        self.assertEqual(len(ms), 1)
        self.assertEqual(ms[0].unidades[0].depois.texto, "O texto por commitar.")

    def test_a_file_moved_out_of_a_tracked_folder_stays_tracked(self):
        ac.gravar(self.dir, {"folders": ["docs"], "files": [], "except": []})
        self.km("chancela", "docs/a.md", "--all")
        _, saida = self.km("mv", "docs/a.md", "a.md")
        self.assertEqual(self.config(), {"folders": ["docs"], "files": ["a.md"], "except": []})
        self.assertIn("a.md", ac.documentos(self.dir))
        self.assertEqual(self.pendentes("a.md"), [])

    def test_the_alias(self):
        ac.gravar(self.dir, {"folders": [], "files": ["docs/a.md"], "except": []})
        self.km("mover", "docs/a.md", "a.md")
        self.assertEqual(self.config()["files"], ["a.md"])

    # ---- a folder ----------------------------------------------------------------------

    def test_a_folder_move_rekeys_everything_under_it_and_rewrites_the_config(self):
        ac.gravar(self.dir, {"folders": ["docs"], "files": [], "except": ["docs/b.md"]})
        self.km("chancela", "docs/a.md", "--all")
        self.km("chancela", "docs/sub/c.md", "--all")
        ch.escrever(self.dir, {"docs/b.md": B}, "b, antes da exceção")   # a paused file
        self.km("mv", "docs", "guides2")
        self.assertEqual(self.config(),
                         {"folders": ["guides2"], "files": [], "except": ["guides2/b.md"]})
        self.assertEqual(ch.arquivos(self.dir),
                         ["guides2/a.md", "guides2/b.md", "guides2/sub/c.md"])
        self.assertEqual(ac.documentos(self.dir), ["guides2/a.md", "guides2/sub/c.md"])
        for rel in ac.documentos(self.dir):
            self.assertEqual(self.pendentes(rel), [], rel)
        self.assertEqual(git(self.dir, "log", "-1", "--format=%s", ch.REF).strip(),
                         "km mv docs → guides2")

    def test_a_folder_tracked_through_its_parent_keeps_its_rule(self):
        ac.gravar(self.dir, {"folders": ["docs"], "files": [], "except": []})
        self.km("chancela", "docs/sub/c.md", "--all")
        self.km("mv", "docs/sub", "outra/sub")
        self.assertEqual(self.config()["folders"], ["docs", "outra/sub"])
        self.assertIn("outra/sub/c.md", ac.documentos(self.dir))

    def test_a_trailing_slash_is_the_same_folder(self):
        ac.gravar(self.dir, {"folders": ["docs"], "files": [], "except": []})
        self.km("mv", "docs/", "guides/")
        self.assertEqual(self.config()["folders"], ["guides"])

    def test_a_folder_with_no_markdown_tracked_just_moves(self):
        _, saida = self.km("mv", "docs", "guides")
        self.assertTrue((self.dir / "guides" / "sub" / "c.md").exists())
        self.assertFalse((self.dir / ".km" / "config.json").exists())
        self.assertFalse(ch.existe(self.dir))
        self.assertIn("sem chancela", saida)

    # ---- nothing to carry --------------------------------------------------------------

    def test_a_file_with_no_chancel_and_not_tracked_still_moves(self):
        ac.gravar(self.dir, ac.vazia())
        cfg = (self.dir / ".km" / "config.json").read_bytes()
        _, saida = self.km("mv", "solto.md", "guias/solto.md")
        self.assertTrue((self.dir / "guias" / "solto.md").exists())
        self.assertEqual((self.dir / ".km" / "config.json").read_bytes(), cfg)
        self.assertFalse(ch.existe(self.dir))
        self.assertIn("sem chancela", saida)
        self.assertIn("não acompanhado", saida)

    # ---- dry run -----------------------------------------------------------------------

    def test_dry_run_writes_nothing(self):
        ac.gravar(self.dir, {"folders": ["docs"], "files": [], "except": ["docs/b.md"]})
        self.km("chancela", "docs/a.md", "--all")
        antes = self.estado()
        _, saida = self.km("mv", "docs", "guides", "--dry-run")
        self.assertEqual(self.estado(), antes)
        self.assertIn("docs/a.md → guides/a.md", saida)
        self.assertIn("guides/b.md", saida)            # the exception, rewritten
        _, saida = self.km("mv", "docs/a.md", "x/a.md", "--dry-run")
        self.assertEqual(self.estado(), antes)

    # ---- refusals ----------------------------------------------------------------------

    def test_refusals_change_nothing(self):
        ac.gravar(self.dir, {"folders": ["docs"], "files": [], "except": []})
        self.km("chancela", "docs/a.md", "--all")
        (self.dir / "novo.md").write_text("# Novo, fora do git\n", encoding="utf-8")
        antes = self.estado()
        casos = {
            ("../fora.md", "a.md"): "..",
            ("docs/a.md", "../fora.md"): "..",
            ("/tmp/a.md", "a.md"): "relativo",
            ("docs/a.md", str(self.dir / "a.md")): "relativo",
            ("docs/a.md", "docs/a.md"): "ele mesmo",
            ("docs", "docs/dentro"): "dentro de si",
            ("docs/a.md", "docs/b.md"): "já existe",
            ("docs", "solto.md"): "já existe",
            ("nada.md", "x.md"): "não está no git",
            ("novo.md", "x.md"): "não está no git",
            (".", "x"): "raiz",
        }
        for (de, para), motivo in casos.items():
            with self.assertRaises(SystemExit, msg=(de, para)) as e:
                self.km("mv", de, para)
            self.assertIn(motivo, str(e.exception.code), (de, para))
            self.assertEqual(self.estado(), antes, (de, para))

    def test_a_destination_that_still_has_a_chancel_is_refused(self):
        """A deleted file awaiting approval keeps its chancel; moving over it would drop it."""
        ac.gravar(self.dir, {"folders": ["docs"], "files": [], "except": []})
        self.km("chancela", "docs/a.md", "--all")
        self.km("chancela", "docs/b.md", "--all")
        git(self.dir, "rm", "-q", "docs/b.md")
        antes = self.estado()
        with self.assertRaises(SystemExit) as e:
            self.km("mv", "docs/a.md", "docs/b.md")
        self.assertIn("chancela", str(e.exception.code))
        self.assertEqual(self.estado(), antes)


if __name__ == "__main__":
    unittest.main()
