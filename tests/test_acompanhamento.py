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


class CliqueTest(unittest.TestCase):
    def test_ticking_a_file_adds_it_or_lifts_its_exception(self):
        self.assertEqual(ac.marcar(ac.vazia(), "requisitos.md", pasta=False)["files"], ["requisitos.md"])
        cfg = {"folders": ["decisoes"], "files": [], "except": ["decisoes/README.md"]}
        self.assertEqual(ac.marcar(cfg, "decisoes/README.md", pasta=False),
                         {"folders": ["decisoes"], "files": [], "except": []})

    def test_unticking_a_file_under_a_rule_makes_an_exception(self):
        cfg = {"folders": ["decisoes"], "files": [], "except": []}
        self.assertEqual(ac.desmarcar(cfg, "decisoes/README.md", pasta=False)["except"],
                         ["decisoes/README.md"])
        self.assertEqual(ac.desmarcar({"folders": [], "files": ["a.md"], "except": []}, "a.md", False),
                         ac.vazia())

    def test_ticking_a_mixed_folder_clears_what_is_below(self):
        cfg = {"folders": [], "files": ["decisoes/0001-a.md"], "except": []}
        self.assertEqual(ac.marcar(cfg, "decisoes", pasta=True),
                         {"folders": ["decisoes"], "files": [], "except": []})
        cfg = {"folders": ["decisoes"], "files": [], "except": ["decisoes/README.md", "decisoes/antigas"]}
        self.assertEqual(ac.marcar(cfg, "decisoes", pasta=True)["except"], [])

    def test_unticking_a_folder_under_a_parent_rule_makes_it_an_exception(self):
        cfg = {"folders": ["decisoes"], "files": [], "except": []}
        self.assertEqual(ac.desmarcar(cfg, "decisoes/antigas", pasta=True)["except"], ["decisoes/antigas"])
        self.assertEqual(ac.desmarcar(cfg, "decisoes", pasta=True), ac.vazia())

    def test_a_single_file_inside_an_excluded_subfolder(self):
        cfg = {"folders": ["decisoes"], "files": [], "except": ["decisoes/antigas"]}
        novo = ac.marcar(cfg, "decisoes/antigas/0000-x.md", pasta=False)
        self.assertTrue(ac.decisao("decisoes/antigas/0000-x.md", novo))
        self.assertFalse(ac.decisao("decisoes/antigas/outra.md", novo))

    def test_the_root(self):
        self.assertEqual(ac.marcar({"folders": [], "files": ["a.md"], "except": ["b.md"]}, ".", True),
                         {"folders": ["."], "files": [], "except": []})
        self.assertEqual(ac.desmarcar({"folders": ["."], "files": [], "except": []}, ".", True), ac.vazia())


class ArvoreTest(RepoTest):
    def no(self, arv, caminho):
        pilha = [arv["raiz"]]
        while pilha:
            n = pilha.pop()
            if n["caminho"] == caminho:
                return n
            pilha += n.get("filhos", [])
        raise KeyError(caminho)

    def test_a_folder_with_an_exception_and_a_folder_picked_by_hand_are_both_mixed(self):
        ac.gravar(self.dir, {"folders": ["decisoes"], "files": ["design/v1.md"],
                             "except": ["decisoes/README.md"]})
        (self.dir / "design" / "v2.md").write_text("# v2\n")
        arv = ac.arvore(self.dir)
        dec, des = self.no(arv, "decisoes"), self.no(arv, "design")
        self.assertEqual((dec["marcado"], dec["novos"], dec["excecoes"]), ("misto", True, 1))
        self.assertEqual((des["marcado"], des["novos"]), ("misto", False))
        self.assertEqual((dec["acompanhados"], dec["total"]), (2, 3))

    def test_file_states(self):
        from km import chancela as ch
        ac.gravar(self.dir, {"folders": [], "files": ["requisitos.md", "README.md"], "except": []})
        ch.escrever(self.dir, {"requisitos.md": (self.dir / "requisitos.md").read_text(),
                               "design/v1.md": "# velho\n"}, "chancela")
        (self.dir / "requisitos.md").write_text("# requisitos.md\n\ntexto mudado\n")
        arv = ac.arvore(self.dir)
        self.assertTrue(self.no(arv, "requisitos.md")["estado"].endswith("a aprovar"))
        self.assertEqual(self.no(arv, "README.md")["estado"], "sem chancela")
        self.assertEqual(self.no(arv, "design/v1.md")["estado"], "pausado · chancela guardada")
        self.assertEqual(self.no(arv, "decisoes/0001-a.md")["estado"], "—")

    def test_a_listed_file_that_is_gone_is_shown_not_dropped(self):
        ac.gravar(self.dir, {"folders": [], "files": ["sumiu.md"], "except": []})
        self.assertEqual(self.no(ac.arvore(self.dir), "sumiu.md")["estado"], "não existe mais")
        self.assertEqual(ac.carregar(self.dir)["files"], ["sumiu.md"])

    def test_untracking_keeps_the_chancel(self):
        from km import chancela as ch
        ac.gravar(self.dir, {"folders": [], "files": ["requisitos.md"], "except": []})
        ch.escrever(self.dir, {"requisitos.md": "# antes\n"}, "chancela")
        antes = ch.chancelado(self.dir, "requisitos.md")
        ac.gravar(self.dir, ac.desmarcar(ac.carregar(self.dir), "requisitos.md", False))
        self.assertEqual(ch.chancelado(self.dir, "requisitos.md"), antes)
        self.assertEqual(self.no(ac.arvore(self.dir), "requisitos.md")["estado"],
                         "pausado · chancela guardada")

    def test_a_broken_config_is_reported_not_raised(self):
        (self.dir / ".km").mkdir(exist_ok=True)
        (self.dir / ".km" / "config.json").write_text('{"include": []}')
        arv = ac.arvore(self.dir)
        self.assertIn("include", arv["erro"])
