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


class RotaTest(RepoTest):
    def setUp(self):
        super().setUp()
        from km import serve
        self.serve = serve

    def clicar(self, caminho, pasta, marcar, sha=None):
        sha = sha or ac.arvore(self.dir)["sha"]
        return self.serve.arquivos_clicar(self.dir, {"caminho": caminho, "pasta": pasta,
                                                     "marcar": marcar, "sha": sha})

    def test_a_click_writes_and_returns_the_step(self):
        r = self.clicar("decisoes", True, True)
        self.assertTrue(r["ok"], r)
        self.assertEqual(ac.carregar(self.dir)["folders"], ["decisoes"])
        self.assertIn("passou a ser acompanhada", r["msg"])
        self.assertEqual(r["passo"]["antes"], ac.vazia())

    def test_a_stale_click_is_refused(self):
        sha_velho = ac.arvore(self.dir)["sha"]
        ac.gravar(self.dir, {"folders": [], "files": ["README.md"], "except": []})   # um agente
        r = self.clicar("decisoes", True, True, sha=sha_velho)
        self.assertFalse(r["ok"])
        self.assertEqual(ac.carregar(self.dir)["files"], ["README.md"])

    def test_undo_and_redo(self):
        passo = self.clicar("decisoes", True, True)["passo"]
        r = self.serve.arquivos_trocar(self.dir, {"config": passo["antes"], "esperado": passo["depois"]})
        self.assertTrue(r["ok"], r)
        self.assertEqual(ac.carregar(self.dir), ac.vazia())
        r = self.serve.arquivos_trocar(self.dir, {"config": passo["depois"], "esperado": passo["antes"]})
        self.assertEqual(ac.carregar(self.dir)["folders"], ["decisoes"])

    def test_undo_refuses_when_the_file_changed_from_outside(self):
        passo = self.clicar("decisoes", True, True)["passo"]
        ac.gravar(self.dir, {"folders": ["decisoes"], "files": ["README.md"], "except": []})
        r = self.serve.arquivos_trocar(self.dir, {"config": passo["antes"], "esperado": passo["depois"]})
        self.assertFalse(r["ok"])
        self.assertIn("mudou por fora", r["erro"])
        self.assertEqual(ac.carregar(self.dir)["files"], ["README.md"])


class CliConfigTest(RepoTest):
    def test_a_broken_config_is_one_line_not_a_traceback(self):
        from km import cli
        (self.dir / ".km").mkdir(exist_ok=True)
        (self.dir / ".km" / "config.json").write_text('{"include": ["**/*.md"]}')
        with self.assertRaises(SystemExit) as e:
            cli.main(["--repo", str(self.dir), "pendente"])
        self.assertIn("include", str(e.exception.code))

    def test_the_review_state_reports_a_broken_config(self):
        from km import serve
        (self.dir / ".km").mkdir(exist_ok=True)
        (self.dir / ".km" / "config.json").write_text("{ não é json")
        e = serve.estado(self.dir)
        self.assertEqual(e["docs"], [])
        self.assertIn("JSON", e["erro"])


class RevisaoFinalTest(RepoTest):
    """Findings of the whole-branch review, each pinned before its fix."""

    def test_normalising_never_changes_a_decision_when_a_file_is_also_an_exception(self):
        cfg = {"folders": [], "files": ["f.md"], "except": ["f.md"]}
        self.assertFalse(ac.decisao("f.md", cfg))
        self.assertFalse(ac.decisao("f.md", ac.normalizar(cfg)))

    def test_dot_cannot_be_an_exception(self):
        (self.dir / ".km").mkdir(exist_ok=True)
        (self.dir / ".km" / "config.json").write_text('{"folders": ["."], "except": ["."]}')
        with self.assertRaises(ac.ConfigInvalida):
            ac.carregar(self.dir)

    def test_a_path_the_config_cannot_hold_is_refused_by_the_server(self):
        from km import serve
        sha = ac.arvore(self.dir)["sha"]
        r = serve.arquivos_clicar(self.dir, {"caminho": "../x.md", "pasta": False, "marcar": True, "sha": sha})
        self.assertFalse(r["ok"])
        self.assertEqual(ac.carregar(self.dir), ac.vazia())
        r = serve.arquivos_trocar(self.dir, {"config": {"folders": [], "files": ["../x.md"], "except": []},
                                             "esperado": ac.vazia()})
        self.assertFalse(r["ok"])
        self.assertEqual(ac.carregar(self.dir), ac.vazia())

    def test_a_backslash_in_a_file_name_is_just_a_character(self):
        from km import serve
        (self.dir / "a\\b.md").write_text("# barra\n")
        sha = ac.arvore(self.dir)["sha"]
        r = serve.arquivos_clicar(self.dir, {"caminho": "a\\b.md", "pasta": False, "marcar": True, "sha": sha})
        self.assertTrue(r["ok"], r)
        self.assertIn("a\\b.md", ac.documentos(self.dir))

    def test_a_file_deleted_from_disk_is_not_a_candidate(self):
        (self.dir / "design" / "v1.md").unlink()                   # rm, sem git rm
        self.assertNotIn("design/v1.md", ac.candidatos(self.dir))

    def test_a_tracked_file_deleted_and_committed_is_still_reviewed(self):
        from km import chancela as ch, serve
        ac.gravar(self.dir, {"folders": ["design"], "files": [], "except": []})
        ch.escrever(self.dir, {"design/v1.md": (self.dir / "design" / "v1.md").read_text()}, "chancela")
        git(self.dir, "rm", "-q", "design/v1.md")
        git(self.dir, "commit", "-qm", "um agente apagou")
        self.assertIn("design/v1.md", ac.documentos(self.dir))
        s = ch.situacao(self.dir, "design/v1.md")
        self.assertTrue(s.unidades and all(u.tipo == "sumiu" for u in s.unidades))
        r = serve.agir(self.dir, {"acao": "aprovar", "file": "design/v1.md",
                                  "shas": [u.sha for u in s.unidades]}, by="t")
        self.assertTrue(r["ok"], r)
        self.assertIsNone(ch.chancelado(self.dir, "design/v1.md"))  # a remoção aprovada sai do ref
        self.assertNotIn("design/v1.md", ac.documentos(self.dir))

    def test_a_change_that_removes_the_same_paragraph_twice_can_be_approved(self):
        from km import chancela as ch, serve
        ac.gravar(self.dir, {"folders": ["design"], "files": [], "except": []})
        repetido = "# v1\n\nrepetido\n\nno meio\n\nrepetido\n"
        ch.escrever(self.dir, {"design/v1.md": repetido}, "chancela")
        (self.dir / "design" / "v1.md").write_text("# v1\n\nno meio\n", encoding="utf-8")
        s = ch.situacao(self.dir, "design/v1.md")
        shas = [u.sha for u in s.unidades]
        self.assertGreater(len(shas), len(set(shas)))              # dois blocos, um só sha
        r = serve.agir(self.dir, {"acao": "aprovar", "file": "design/v1.md", "shas": shas}, by="t")
        self.assertTrue(r["ok"], r)
        self.assertFalse(ch.situacao(self.dir, "design/v1.md").mudancas)

    def test_two_identical_changes_have_different_keys(self):
        from km import chancela as ch, serve
        ac.gravar(self.dir, {"folders": ["design"], "files": [], "except": []})
        ch.escrever(self.dir, {"design/v1.md": "# v1\n\num\n\ndois\n\ntrês\n"}, "chancela")
        (self.dir / "design" / "v1.md").write_text("# v1\n\num\n\nnova\n\ndois\n\nnova\n\ntrês\n",
                                                   encoding="utf-8")
        ms = [x for x in serve.segmentos(ch.situacao(self.dir, "design/v1.md")) if x["tipo"] == "mudanca"]
        self.assertEqual([(m["antes"], m["agora"]) for m in ms], [("", "nova"), ("", "nova")])
        self.assertEqual(len({m["chave"] for m in ms}), 2)

    def test_a_listed_file_that_is_gone_can_be_unticked(self):
        ac.gravar(self.dir, {"folders": [], "files": ["sumiu.md"], "except": []})
        arv = ac.arvore(self.dir)
        no = next(f for f in arv["raiz"]["filhos"] if f["caminho"] == "sumiu.md")
        self.assertEqual((no["marcado"], no["estado"]), ("sim", "não existe mais"))
        self.assertEqual(arv["raiz"]["acompanhados"], 0)            # o que não existe não conta
        self.assertEqual(ac.desmarcar(ac.carregar(self.dir), "sumiu.md", False), ac.vazia())

    def test_the_tree_never_puts_a_path_inside_a_js_string(self):
        pagina = (Path(__file__).parent.parent / "km" / "painel.html").read_text(encoding="utf-8")
        self.assertNotIn("('${esc(n.caminho)}')", pagina)
        self.assertNotIn("${esc(JSON.stringify", pagina)


class OrigemTest(unittest.TestCase):
    """The panel writes documents and the chancel: only the panel itself may ask it to."""

    def setUp(self):
        import threading
        from http.server import ThreadingHTTPServer
        from km import serve
        self.dir = Path(tempfile.mkdtemp())
        git(self.dir, "init", "-q", "-b", "main")
        serve.Handler.root, serve.Handler.by = self.dir, "t"
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
        self.porta = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        shutil.rmtree(self.dir)

    def post(self, **cabecalhos):
        import urllib.request, urllib.error
        req = urllib.request.Request(f"http://127.0.0.1:{self.porta}/api/arquivos",
                                     data=json.dumps({"caminho": "a.md", "pasta": False, "marcar": True,
                                                      "sha": ac.sha_config(ac.vazia())}).encode(),
                                     headers=cabecalhos, method="POST")
        try:
            return urllib.request.urlopen(req).status
        except urllib.error.HTTPError as e:
            return e.code

    def test_another_site_cannot_write(self):
        self.assertEqual(self.post(**{"Content-Type": "application/json",
                                      "Origin": "http://mal.example"}), 403)
        self.assertEqual(self.post(**{"Content-Type": "text/plain"}), 403)
        self.assertFalse((self.dir / ".km" / "config.json").exists())

    def test_the_panel_through_a_forwarded_port_can(self):
        self.assertEqual(self.post(**{"Content-Type": "application/json", "Host": "localhost:9999",
                                      "Origin": "http://localhost:9999"}), 200)

    def test_a_rebound_name_cannot(self):
        self.assertEqual(self.post(**{"Content-Type": "application/json", "Host": "mal.example:8431",
                                      "Origin": "http://mal.example:8431"}), 403)

    def test_the_panel_itself_can(self):
        self.assertEqual(self.post(**{"Content-Type": "application/json",
                                      "Origin": f"http://127.0.0.1:{self.porta}"}), 200)


class EstaticoTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "painel").mkdir()
        (self.dir / "painel" / "a.js").write_text("export const a = 1;\n")
        (self.dir / "segredo.py").write_text("x = 1\n")
        self.raizes = {"painel": self.dir / "painel"}

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_a_module_is_served(self):
        from km import serve
        self.assertEqual(serve.arquivo_estatico("/static/painel/a.js", self.raizes),
                         self.dir / "painel" / "a.js")

    def test_nothing_outside_the_two_folders(self):
        from km import serve
        for ruim in ("/static/painel/../segredo.py", "/static/outra/a.js", "/static/painel/nao.js",
                     "/static/painel/", "/static/painel/%2e%2e/segredo.py"):
            self.assertIsNone(serve.arquivo_estatico(ruim, self.raizes), ruim)

    def test_a_null_byte_is_not_found_not_a_crash(self):
        from km import serve
        self.assertIsNone(serve.arquivo_estatico("/static/painel/a%00.js", self.raizes))
