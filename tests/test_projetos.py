"""One server, many projects: the registry, the names, `km projects`, and the routes.

Run: python3 -m unittest discover -s tests -t . -v
"""

import contextlib
import io
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

from km import acompanhamento as ac
from km import chancela as ch
from km import cli
from km import projetos as pj
from km import serve


def git(root, *args):
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def novo_repo(dir: Path, arquivos: dict[str, str], init: bool = True) -> Path:
    dir.mkdir(parents=True, exist_ok=True)
    git(dir, "init", "-q", "-b", "main")
    git(dir, "config", "user.email", "t@t")
    git(dir, "config", "user.name", "t")
    for rel, texto in arquivos.items():
        (dir / rel).parent.mkdir(parents=True, exist_ok=True)
        (dir / rel).write_text(texto, encoding="utf-8")
    git(dir, "add", "-A")
    git(dir, "commit", "-qm", "inicial")
    if init:
        ac.gravar(dir, {"folders": ["."], "files": [], "except": []})
    return dir


class XdgTest(unittest.TestCase):
    """Each test has its own config home and its own folder of repositories."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.xdg = self.tmp / "xdg"
        env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.xdg)})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(shutil.rmtree, self.tmp)

    def registro(self):
        return json.loads((self.xdg / "km" / "projects.json").read_text(encoding="utf-8"))

    def km(self, *args, repo=None):
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            codigo = cli.main(["--repo", str(repo or self.tmp), *args])
        return codigo, saida.getvalue()


class RegistroTest(XdgTest):
    def test_the_registry_lives_under_xdg_config_home(self):
        self.assertEqual(pj.arquivo(), self.xdg / "km" / "projects.json")

    def test_without_xdg_it_is_under_dot_config(self):
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": ""}):
            self.assertEqual(pj.arquivo(), Path.home() / ".config" / "km" / "projects.json")

    def test_no_file_is_an_empty_registry(self):
        self.assertEqual(pj.carregar(), [])

    def test_written_absolute_sorted_deduplicated_realpath(self):
        a, b = self.tmp / "b", self.tmp / "a"
        a.mkdir(); b.mkdir()
        (self.tmp / "atalho").symlink_to(a)
        pj.gravar([str(a), str(b), str(self.tmp / "atalho"), str(a) + "/"])
        self.assertEqual(self.registro(), {"projects": [str(b), str(a)]})
        self.assertEqual(pj.carregar(), [str(b), str(a)])

    def test_writing_is_atomic_and_leaves_no_temp_file(self):
        pj.gravar([str(self.tmp)])
        self.assertEqual(sorted(p.name for p in (self.xdg / "km").iterdir()), ["projects.json"])
        with mock.patch.object(pj.os, "replace", side_effect=OSError("disco cheio")):
            with self.assertRaises(OSError):
                pj.gravar([])
        self.assertEqual(self.registro(), {"projects": [str(self.tmp)]})   # o antigo ficou
        self.assertEqual(sorted(p.name for p in (self.xdg / "km").iterdir()), ["projects.json"])

    def escreve(self, texto):
        (self.xdg / "km").mkdir(parents=True, exist_ok=True)
        (self.xdg / "km" / "projects.json").write_text(texto, encoding="utf-8")

    def test_a_broken_registry_is_a_sentence(self):
        for texto, trecho in [("{", "não é JSON válido"),
                              ("[]", "tem que ser um objeto"),
                              ('{"projects": [], "port": 1}', "port"),
                              ('{"projects": "x"}', "tem que ser uma lista"),
                              ('{"projects": ["relativo/x"]}', "absoluto"),
                              ('{"projects": [3]}', "absoluto")]:
            self.escreve(texto)
            with self.assertRaises(pj.RegistroInvalido) as e:
                pj.carregar()
            self.assertIn(trecho, str(e.exception), texto)
            self.assertIn("projects.json", str(e.exception), texto)

    def test_a_broken_registry_is_a_config_error_for_the_cli(self):
        self.assertTrue(issubclass(pj.RegistroInvalido, ac.ConfigInvalida))


class NomesTest(unittest.TestCase):
    def test_the_name_is_the_folder(self):
        self.assertEqual(pj.nomes(["/h/a", "/h/b"]), {"/h/a": "a", "/h/b": "b"})

    def test_two_with_the_same_folder_name_take_the_parent(self):
        self.assertEqual(pj.nomes(["/h/work/app", "/h/personal/app", "/h/site"]),
                         {"/h/work/app": "work/app", "/h/personal/app": "personal/app",
                          "/h/site": "site"})

    def test_until_they_differ(self):
        self.assertEqual(pj.nomes(["/x/w/app", "/y/w/app"]),
                         {"/x/w/app": "x/w/app", "/y/w/app": "y/w/app"})


class AdicionarTest(XdgTest):
    def setUp(self):
        super().setUp()
        self.repo = novo_repo(self.tmp / "repos" / "alfa", {"a.md": "# A\n"})

    def test_adds_a_repository_root(self):
        r = pj.adicionar(str(self.repo))
        self.assertEqual((r["nome"], r["caminho"], r["novo"]), ("alfa", str(self.repo), True))
        self.assertEqual(pj.carregar(), [str(self.repo)])

    def test_tilde_is_expanded(self):
        with mock.patch.dict(os.environ, {"HOME": str(self.tmp / "repos")}):
            r = pj.adicionar("~/alfa")
        self.assertEqual(r["caminho"], str(self.repo))

    def test_adding_twice_is_not_an_error(self):
        pj.adicionar(str(self.repo))
        r = pj.adicionar(str(self.repo) + "/")
        self.assertFalse(r["novo"])
        self.assertEqual(pj.carregar(), [str(self.repo)])

    def test_refusals(self):
        (self.tmp / "solto").mkdir()
        (self.tmp / "arquivo.txt").write_text("x")
        (self.repo / "sub").mkdir()
        casos = [(str(self.tmp / "nao-existe"), "não existe"),
                 (str(self.tmp / "arquivo.txt"), "não é uma pasta"),
                 (str(self.tmp / "solto"), "não é um repositório git"),
                 (str(self.repo / "sub"), "não é a raiz"),
                 ("relativo/alfa", "absoluto")]
        for caminho, trecho in casos:
            with self.assertRaises(pj.Recusado) as e:
                pj.adicionar(caminho)
            self.assertIn(trecho, str(e.exception), caminho)
        self.assertEqual(pj.carregar(), [])

    def test_without_config_it_refuses_with_a_hint(self):
        cru = novo_repo(self.tmp / "repos" / "beta", {"b.md": "# B\n"}, init=False)
        with self.assertRaises(pj.Recusado) as e:
            pj.adicionar(str(cru))
        self.assertIn("--init", str(e.exception))
        self.assertEqual(pj.carregar(), [])
        self.assertFalse((cru / ".km").exists())

    def test_with_init_it_creates_the_empty_config(self):
        cru = novo_repo(self.tmp / "repos" / "beta", {"b.md": "# B\n"}, init=False)
        r = pj.adicionar(str(cru), init=True)
        self.assertTrue(r["iniciado"])
        self.assertEqual(ac.carregar(cru), ac.vazia())
        self.assertEqual(pj.carregar(), [str(cru)])

    def test_init_never_touches_an_existing_config(self):
        antes = (self.repo / ".km" / "config.json").read_bytes()
        r = pj.adicionar(str(self.repo), init=True)
        self.assertFalse(r["iniciado"])
        self.assertEqual((self.repo / ".km" / "config.json").read_bytes(), antes)


class RemoverTest(XdgTest):
    def setUp(self):
        super().setUp()
        self.repo = novo_repo(self.tmp / "alfa", {"a.md": "# A\n\ntexto\n"})
        ch.escrever(self.repo, {"a.md": "# A\n\ntexto\n"}, "chancela: a.md\n")
        pj.adicionar(str(self.repo))

    def bytes_do_repo(self):
        ref = git(self.repo, "rev-parse", ch.REF)
        return (self.repo / ".km" / "config.json").read_bytes(), ref, (self.repo / "a.md").read_bytes()

    def test_by_name_or_path_and_the_repository_is_untouched(self):
        antes = self.bytes_do_repo()
        r = pj.remover("alfa")
        self.assertEqual(r["caminho"], str(self.repo))
        self.assertEqual(pj.carregar(), [])
        self.assertEqual(self.bytes_do_repo(), antes)
        pj.adicionar(str(self.repo))
        pj.remover(str(self.repo) + "/")
        self.assertEqual(pj.carregar(), [])
        self.assertEqual(self.bytes_do_repo(), antes)

    def test_unknown_is_refused(self):
        with self.assertRaises(pj.Recusado):
            pj.remover("gama")
        self.assertEqual(pj.carregar(), [str(self.repo)])

    def test_a_missing_folder_can_still_be_removed(self):
        pj.gravar([str(self.repo), str(self.tmp / "sumiu")])
        pj.remover("sumiu")
        self.assertEqual(pj.carregar(), [str(self.repo)])


class ListarTest(XdgTest):
    def test_each_project_with_its_state_or_its_error(self):
        a = novo_repo(self.tmp / "alfa", {"a.md": "# A\n\ntexto\n"})
        ch.escrever(a, {"a.md": "# A\n\ntexto\n"}, "c\n")
        b = novo_repo(self.tmp / "beta", {"b.md": "# B\n\ntexto\n"})
        pj.gravar([str(a), str(b), str(self.tmp / "sumiu")])
        (b / "b.md").write_text("# B\n\ntexto\n\nmais\n", encoding="utf-8")
        ch.escrever(b, {"b.md": "# B\n\ntexto\n"}, "c\n")
        por = {p["nome"]: p for p in pj.listar()}
        self.assertEqual(set(por), {"alfa", "beta", "sumiu"})
        self.assertEqual((por["alfa"]["pct"], por["alfa"]["n"], por["alfa"]["pendentes"]), ("", 1, 0))
        self.assertTrue(por["beta"]["pct"].endswith("%"))
        self.assertEqual(por["beta"]["pendentes"], 1)
        self.assertIn("não existe", por["sumiu"]["erro"])
        self.assertEqual(por["alfa"]["erro"], "")

    def test_a_repository_without_commits_is_an_error_on_its_row(self):
        a = novo_repo(self.tmp / "alfa", {"a.md": "# A\n"})
        vazio = self.tmp / "vazio"
        vazio.mkdir()
        git(vazio, "init", "-q", "-b", "main")
        ac.gravar(vazio, ac.vazia())
        pj.gravar([str(a), str(vazio)])
        por = {p["nome"]: p for p in pj.listar()}
        self.assertIn("nenhum commit", por["vazio"]["erro"])
        self.assertEqual(por["alfa"]["erro"], "")


class CliProjetosTest(XdgTest):
    def setUp(self):
        super().setUp()
        self.repo = novo_repo(self.tmp / "alfa", {"a.md": "# A\n"})

    def test_add_list_rm(self):
        codigo, saida = self.km("projects", "add", str(self.repo))
        self.assertEqual(codigo, 0)
        self.assertIn("alfa", saida)
        codigo, saida = self.km("projetos")
        self.assertIn("alfa", saida)
        self.assertIn(str(self.repo), saida)
        codigo, saida = self.km("projects", "--json")
        self.assertEqual(json.loads(saida)[0]["nome"], "alfa")
        codigo, saida = self.km("projects", "rm", "alfa")
        self.assertIn("não", saida)          # diz que o repositório não foi mexido
        self.assertEqual(pj.carregar(), [])

    def test_add_relative_to_where_you_stand(self):
        codigo, saida = self.km("projects", "add", "alfa", "--json", repo=self.tmp)
        self.assertEqual(json.loads(saida)["caminho"], str(self.repo))

    def test_a_refusal_is_a_sentence(self):
        cru = novo_repo(self.tmp / "beta", {"b.md": "# B\n"}, init=False)
        with self.assertRaises(SystemExit) as e:
            self.km("projects", "add", str(cru))
        self.assertIn("--init", str(e.exception.code))
        codigo, _ = self.km("projects", "add", str(cru), "--init")
        self.assertEqual(codigo, 0)
        self.assertTrue((cru / ".km" / "config.json").exists())

    def test_empty_list_says_how_to_add(self):
        codigo, saida = self.km("projects")
        self.assertIn("km projects add", saida)


class ServeRegistraTest(XdgTest):
    def rodar(self, repo):
        with mock.patch.object(serve, "run", return_value=0) as run:
            codigo, saida = self.km("serve", "--port", "1", repo=repo)
        return run.call_args.kwargs, saida

    def test_serving_inside_a_km_repository_registers_and_selects_it(self):
        repo = novo_repo(self.tmp / "alfa", {"a.md": "# A\n"})
        (repo / "sub").mkdir()
        args, saida = self.rodar(repo / "sub")
        self.assertEqual(pj.carregar(), [str(repo)])
        self.assertIn("registrado", saida)
        self.assertEqual(args["inicial"], repo)
        args, saida = self.rodar(repo)
        self.assertNotIn("registrado", saida)          # a segunda vez não repete

    def test_a_repository_without_config_is_not_registered(self):
        cru = novo_repo(self.tmp / "beta", {"b.md": "# B\n"}, init=False)
        args, saida = self.rodar(cru)
        self.assertEqual(pj.carregar(), [])
        self.assertIsNone(args["inicial"])
        self.assertIn("--init", saida)

    def test_outside_any_repository_it_still_serves(self):
        (self.tmp / "solto").mkdir()
        args, _ = self.rodar(self.tmp / "solto")
        self.assertIsNone(args["inicial"])


class RotasTest(XdgTest):
    """Two projects, one server: each request names its project."""

    def setUp(self):
        super().setUp()
        self.a = novo_repo(self.tmp / "alfa", {"a.md": "# A\n\ntexto de a\n"})
        self.b = novo_repo(self.tmp / "beta", {"b.md": "# B\n\ntexto de b\n", "c.md": "# C\n"})
        for r in (self.a, self.b):
            pj.adicionar(str(r))
        handler = type("H", (serve.Handler,), {"by": "teste", "inicial": self.b})
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.porta = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def get(self, caminho):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.porta}{caminho}") as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null")

    def post(self, caminho, corpo, tipo="application/json", origem="mesma"):
        cab = {"Content-Type": tipo}
        if origem == "mesma":
            cab["Origin"] = f"http://127.0.0.1:{self.porta}"
        elif origem:
            cab["Origin"] = origem
        req = urllib.request.Request(f"http://127.0.0.1:{self.porta}{caminho}",
                                     data=json.dumps(corpo).encode(), headers=cab, method="POST")
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            corpo = e.read()
            try:
                return e.code, json.loads(corpo)
            except ValueError:
                return e.code, None

    def test_each_project_answers_with_its_own_state(self):
        c, a = self.get("/api/state?projeto=alfa")
        self.assertEqual((c, a["repo"], a["projeto"], [d["file"] for d in a["docs"]]),
                         (200, "alfa", "alfa", ["a.md"]))
        c, b = self.get("/api/state?projeto=beta")
        self.assertEqual([d["file"] for d in b["docs"]], ["b.md", "c.md"])
        c, arv = self.get("/api/arquivos?projeto=beta")
        self.assertEqual(arv["raiz"]["nome"], "beta")

    def test_unknown_project_is_404_and_missing_is_400(self):
        c, j = self.get("/api/state?projeto=gama")
        self.assertEqual(c, 404)
        self.assertIn("gama", j["erro"])
        self.assertEqual(self.get("/api/state")[0], 400)
        self.assertEqual(self.get("/api/arquivos")[0], 400)
        self.assertEqual(self.post("/api/act", {"acao": "aprovar", "file": "a.md"})[0], 400)
        self.assertEqual(self.post("/api/act", {"projeto": "gama", "file": "a.md"})[0], 404)

    def test_a_path_never_names_a_project(self):
        self.assertEqual(self.get(f"/api/state?projeto={self.a}")[0], 404)

    def test_a_registered_folder_that_vanished_is_404(self):
        pj.gravar(pj.carregar() + [str(self.tmp / "sumiu")])
        c, j = self.get("/api/state?projeto=sumiu")
        self.assertEqual(c, 404)
        self.assertIn("não existe", j["erro"])

    def test_the_list_and_the_initial_project(self):
        c, j = self.get("/api/projetos")
        self.assertEqual(c, 200)
        self.assertEqual([p["nome"] for p in j["projetos"]], ["alfa", "beta"])
        self.assertEqual(j["inicial"], "beta")
        self.assertEqual(j["projetos"][1]["n"], 2)

    def test_a_project_without_commits_does_not_break_the_list(self):
        vazio = self.tmp / "vazio"
        vazio.mkdir()
        git(vazio, "init", "-q", "-b", "main")
        ac.gravar(vazio, ac.vazia())
        pj.gravar(pj.carregar() + [str(vazio)])
        c, j = self.get("/api/projetos")
        self.assertEqual(c, 200)
        por = {p["nome"]: p for p in j["projetos"]}
        self.assertEqual(set(por), {"alfa", "beta", "vazio"})
        self.assertIn("nenhum commit", por["vazio"]["erro"])
        # Sem commits ainda dá para escolher os arquivos e revisar: só não há commits a listar.
        c, j = self.get("/api/state?projeto=vazio")
        self.assertEqual(c, 200)
        self.assertNotIn("commit", [r["tipo"] for r in j["revisoes"]])
        self.assertEqual(self.get("/api/arquivos?projeto=vazio")[0], 200)

    def test_a_git_failure_is_a_sentence_not_an_empty_reply(self):
        with mock.patch.object(serve, "estado", side_effect=SystemExit("git log: falhou")):
            c, j = self.get("/api/state?projeto=alfa")
        self.assertEqual(c, 500)
        self.assertIn("git log: falhou", j["erro"])

    def test_approving_in_one_project_leaves_the_other_alone(self):
        ch.escrever(self.a, {"a.md": "# A\n\ntexto de a\n"}, "c\n")
        ref_a = git(self.a, "rev-parse", ch.REF)
        c, e = self.get("/api/state?projeto=beta&file=b.md")
        m = [s for s in e["docs"][0]["segmentos"] if s["tipo"] == "mudanca"][0]
        c, r = self.post("/api/act", {"projeto": "beta", "acao": "aprovar", "file": "b.md",
                                      "shas": [u["sha"] for u in m["unidades"]]})
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["estado"]["projeto"], "beta")
        self.assertEqual(ch.chancelado(self.b, "b.md"), "# B\n\ntexto de b\n")
        self.assertEqual(git(self.a, "rev-parse", ch.REF), ref_a)

    def test_add_and_remove_through_the_page(self):
        cru = novo_repo(self.tmp / "gama", {"g.md": "# G\n"}, init=False)
        c, r = self.post("/api/projetos", {"caminho": str(cru)})
        self.assertFalse(r["ok"])
        self.assertIn("km init", r["erro"])
        c, r = self.post("/api/projetos", {"caminho": str(cru), "init": True})
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["nome"], "gama")
        self.assertIn(str(cru), pj.carregar())
        c, r = self.post("/api/projetos/remover", {"nome": "gama"})
        self.assertTrue(r["ok"], r)
        self.assertNotIn(str(cru), pj.carregar())
        self.assertTrue((cru / ".km" / "config.json").exists())
        c, r = self.post("/api/projetos/remover", {"nome": "gama"})
        self.assertFalse(r["ok"])

    def test_the_page_cannot_add_a_relative_path(self):
        c, r = self.post("/api/projetos", {"caminho": "gama"})
        self.assertFalse(r["ok"])

    def test_another_site_cannot_add_or_remove(self):
        cru = novo_repo(self.tmp / "gama", {"g.md": "# G\n"})
        for caminho, corpo in [("/api/projetos", {"caminho": str(cru)}),
                               ("/api/projetos/remover", {"nome": "alfa"})]:
            self.assertEqual(self.post(caminho, corpo, origem="http://mal.example")[0], 403)
            self.assertEqual(self.post(caminho, corpo, tipo="text/plain")[0], 403)
        self.assertEqual(pj.carregar(), [str(self.a), str(self.b)])

    def test_a_project_added_elsewhere_is_seen_at_once(self):
        d = novo_repo(self.tmp / "delta", {"d.md": "# D\n"})
        self.km("projects", "add", str(d))
        self.assertEqual(self.get("/api/state?projeto=delta")[0], 200)


if __name__ == "__main__":
    unittest.main()
