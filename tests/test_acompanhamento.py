"""Run: python3 -m unittest discover -s tests -t . -v"""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from km import acompanhamento as ac


def git(root, *args):
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


class RepoTest(unittest.TestCase):
    ARQUIVOS = ["README.md", "requisitos.md", "decisoes/0001-a.md", "decisoes/README.md",
                "decisoes/antigas/0000-x.md", "design/v1.md", "decisões/a b.md"]

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        git(self.dir, "init", "-q", "-b", "main")
        git(self.dir, "config", "user.email", "t@t")
        git(self.dir, "config", "user.name", "t")
        for rel in self.ARQUIVOS:
            (self.dir / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.dir / rel).write_text(f"# {rel}\n\ntexto\n", encoding="utf-8")
        (self.dir / "node_modules" / "pkg").mkdir(parents=True)
        (self.dir / "node_modules" / "pkg" / "README.md").write_text("# lixo\n")
        (self.dir / ".gitignore").write_text("node_modules/\n.km/\n")
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-qm", "i")

    def tearDown(self):
        shutil.rmtree(self.dir)


class DecisaoTest(unittest.TestCase):
    def test_the_closest_decision_wins(self):
        cfg = {"folders": ["decisoes"], "files": ["decisoes/antigas/0000-x.md"],
               "except": ["decisoes/README.md", "decisoes/antigas"]}
        self.assertTrue(ac.decisao("decisoes/0001-a.md", cfg))
        self.assertFalse(ac.decisao("decisoes/README.md", cfg))
        self.assertTrue(ac.decisao("decisoes/antigas/0000-x.md", cfg))   # arquivo vence a pasta
        self.assertFalse(ac.decisao("decisoes/antigas/0001-y.md", cfg))
        self.assertFalse(ac.decisao("design/v1.md", cfg))

    def test_a_folder_rule_takes_files_that_do_not_exist_yet(self):
        self.assertTrue(ac.decisao("decisoes/9999-nova.md", {"folders": ["decisoes"], "files": [], "except": []}))

    def test_dot_is_the_whole_repository(self):
        self.assertTrue(ac.decisao("qualquer/coisa.md", {"folders": ["."], "files": [], "except": []}))

    def test_at_the_same_level_except_wins(self):
        cfg = {"folders": ["decisoes"], "files": ["x.md"], "except": ["decisoes", "x.md"]}
        self.assertFalse(ac.decisao("decisoes/0001-a.md", cfg))
        self.assertFalse(ac.decisao("x.md", cfg))


class NormalizarTest(unittest.TestCase):
    def test_redundant_entries_go_and_lists_are_sorted(self):
        cfg = {"folders": ["decisoes", "decisoes/antigas", "decisoes"],
               "files": ["decisoes/0001-a.md", "requisitos.md", "README.md"],
               "except": ["design/v1.md", "decisoes/README.md"]}
        self.assertEqual(ac.normalizar(cfg), {
            "folders": ["decisoes"],                    # antigas já está coberta
            "files": ["README.md", "requisitos.md"],    # 0001-a já está coberto
            "except": ["decisoes/README.md"],           # design/v1.md não tinha regra acima
        })

    def test_an_exception_between_keeps_the_entry_below(self):
        cfg = {"folders": ["decisoes", "decisoes/antigas/novas"], "files": [],
               "except": ["decisoes/antigas"]}
        self.assertEqual(ac.normalizar(cfg)["folders"], ["decisoes", "decisoes/antigas/novas"])

    def test_normalising_twice_changes_nothing(self):
        cfg = {"folders": ["b", "a"], "files": ["c.md"], "except": ["a/x.md"]}
        self.assertEqual(ac.normalizar(ac.normalizar(cfg)), ac.normalizar(cfg))


class ConfigTest(RepoTest):
    def test_no_config_tracks_nothing(self):
        self.assertEqual(ac.carregar(self.dir), ac.vazia())
        self.assertEqual(ac.documentos(self.dir), [])

    def test_the_old_format_is_rejected_naming_the_key(self):
        (self.dir / ".km").mkdir()
        (self.dir / ".km" / "config.json").write_text('{"include": ["**/*.md"]}')
        with self.assertRaises(ac.ConfigInvalida) as e:
            ac.carregar(self.dir)
        self.assertIn("include", str(e.exception))

    def test_invalid_json_and_bad_paths_say_what_is_wrong(self):
        (self.dir / ".km").mkdir()
        cfg = self.dir / ".km" / "config.json"
        cfg.write_text("{ isto não é json")
        with self.assertRaises(ac.ConfigInvalida):
            ac.carregar(self.dir)
        for ruim in ('{"files": "a.md"}', '{"files": ["../fora.md"]}', '{"folders": ["a/"]}',
                     '{"files": ["/abs.md"]}', '{"files": ["."]}'):
            cfg.write_text(ruim)
            with self.assertRaises(ac.ConfigInvalida, msg=ruim):
                ac.carregar(self.dir)

    def test_writing_is_atomic_and_normalised(self):
        ac.gravar(self.dir, {"folders": ["decisoes"], "files": ["decisoes/0001-a.md"], "except": []})
        dados = json.loads((self.dir / ".km" / "config.json").read_text())
        self.assertEqual(dados, {"folders": ["decisoes"], "files": [], "except": []})
        self.assertEqual([p.name for p in (self.dir / ".km").iterdir()], ["config.json"])


class CandidatosTest(RepoTest):
    def test_git_decides_what_exists(self):
        c = ac.candidatos(self.dir)
        self.assertIn("decisões/a b.md", c)
        self.assertNotIn("node_modules/pkg/README.md", c)

    def test_a_new_file_git_does_not_know_yet_is_a_candidate(self):
        (self.dir / "decisoes" / "0002-b.md").write_text("# nova\n")
        self.assertIn("decisoes/0002-b.md", ac.candidatos(self.dir))

    def test_documents_are_the_candidates_the_config_tracks(self):
        ac.gravar(self.dir, {"folders": ["decisoes"], "files": ["requisitos.md"],
                             "except": ["decisoes/README.md"]})
        self.assertEqual(ac.documentos(self.dir),
                         ["decisoes/0001-a.md", "decisoes/antigas/0000-x.md", "requisitos.md"])

    def test_a_listed_file_git_ignores_still_counts_if_it_is_on_disk(self):
        ac.gravar(self.dir, {"folders": [], "files": ["node_modules/pkg/README.md"], "except": []})
        self.assertEqual(ac.documentos(self.dir), ["node_modules/pkg/README.md"])
