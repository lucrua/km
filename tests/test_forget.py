"""`km forget`: a file leaves the chancel for good — every commit of the ref, the config, and
with `--prune` the objects in `.git`. Also what keeps it from leaking again: `km lint`, the
warning on approving a file git does not have, and the pre-push hook.

Run: python3 -m unittest discover -s tests -t . -v
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from km import acompanhamento as ac
from km import chancela as ch
from km import cli
from km import serve

A = "# A\n\nO texto de a.\n"
B = "# B\n\nO texto de b.\n"
R1 = "# Rascunho\n\nSEGREDO um, para o cliente.\n"
R2 = R1 + "\nSEGREDO dois.\n"


def git(root, *args, entrada=None, ok=True):
    r = subprocess.run(["git", *args], cwd=root, input=entrada, capture_output=True, text=True)
    if ok:
        assert r.returncode == 0, r.stderr
    return r if not ok else r.stdout


class ForgetTest(unittest.TestCase):
    """The case from the issue: a draft in a tracked folder, never committed, approved a
    few times between approvals of committed files, then deleted from disk."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        git(self.dir, "init", "-q", "-b", "main")
        git(self.dir, "config", "user.email", "t@t")
        git(self.dir, "config", "user.name", "t")
        (self.dir / "docs").mkdir()
        (self.dir / "docs" / "a.md").write_text(A, encoding="utf-8")
        (self.dir / "docs" / "b.md").write_text(B, encoding="utf-8")
        (self.dir / ".gitignore").write_text(".km/\n")
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-qm", "inicial")
        ac.gravar(self.dir, {"folders": ["docs", "rascunho"], "files": [], "except": []})

    def tearDown(self):
        shutil.rmtree(self.dir)

    def km(self, *args):
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            codigo = cli.main(["--repo", str(self.dir), *args])
        return codigo, saida.getvalue()

    def escrever(self, rel, texto):
        p = self.dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(texto, encoding="utf-8")

    def config(self):
        return json.loads((self.dir / ".km" / "config.json").read_text(encoding="utf-8"))

    def ref(self):
        return git(self.dir, "rev-parse", "--verify", "--quiet", ch.REF, ok=False).stdout.strip()

    def no_dia(self, n):
        """Each approval on a day of its own, in another time zone: a rewrite that wrote
        "now" instead of the original dates would show."""
        quando = f"{1700000000 + n * 86400} +0530"
        return mock.patch.dict(os.environ, {"GIT_AUTHOR_DATE": quando,
                                            "GIT_COMMITTER_DATE": quando})

    def o_caso(self):
        """Approvals of a.md, of the draft twice, of b.md, then the draft deleted and the
        deletion approved — as in the issue, where only the tip was clean."""
        with self.no_dia(1):
            self.km("chancela", "docs/a.md", "--all")
        self.escrever("rascunho/r.md", R1)
        with self.no_dia(2):
            self.km("chancela", "rascunho/r.md", "--all")
        self.escrever("docs/a.md", A + "\nMais um parágrafo.\n")
        with self.no_dia(3):
            self.km("chancela", "docs/a.md", "--all")
        self.escrever("rascunho/r.md", R2)
        with self.no_dia(4):
            self.km("chancela", "rascunho/r.md", "--all")
        with self.no_dia(5):
            self.km("chancela", "docs/b.md", "--all")
        self.blobs = {git(self.dir, "rev-parse", f"{ch.REF}~1:rascunho/r.md").strip(),
                      git(self.dir, "rev-parse", f"{ch.REF}~3:rascunho/r.md").strip()}
        shutil.rmtree(self.dir / "rascunho")
        cli.chancelar(self.dir, "rascunho/r.md", ch.situacao(self.dir, "rascunho/r.md").unidades,
                      ch.situacao(self.dir, "rascunho/r.md"), None, "t")
        self.assertIsNone(ch.chancelado(self.dir, "rascunho/r.md"))   # only the tip is clean
        self.assertIn("SEGREDO", git(self.dir, "log", "-p", ch.REF))

    def respostas(self):
        """What every other file answers: the acceptance says these must not change. The
        sha `km quando` prints is the one thing a rewrite changes — date and message stay."""
        sem_sha = lambda s: [l.split(" ", 1)[1] for l in s.splitlines()]
        return {rel: (self.km("pendente", "--json", rel)[1], sem_sha(self.km("quando", rel)[1]),
                      self.km("baseline", rel)[1])
                for rel in ("docs/a.md", "docs/b.md")}

    # ---- the acceptance --------------------------------------------------------------

    def test_apply_and_prune_remove_every_line_and_every_blob(self):
        self.o_caso()
        antes = self.respostas()
        codigo, saida = self.km("forget", "rascunho", "--apply", "--prune")
        self.assertEqual(codigo, 0)
        self.assertNotIn("SEGREDO", git(self.dir, "log", "-p", ch.REF))
        self.assertNotIn("rascunho", git(self.dir, "log", "--format=%B", ch.REF))
        for blob in self.blobs:
            self.assertNotEqual(git(self.dir, "cat-file", "-e", blob, ok=False).returncode, 0)
        self.assertEqual(self.respostas(), antes)
        self.assertEqual(self.config(), {"folders": ["docs"], "files": [], "except": []})
        self.assertIn("as 2 versões saíram do .git", saida)
        self.assertIn("km serve: não precisa reiniciar", saida)
        self.assertIn("worktrees", saida)

    def test_commits_left_empty_leave_and_the_rest_keep_message_author_and_dates(self):
        self.o_caso()
        formato = "%s%x00%an%x00%ae%x00%ad%x00%cn%x00%ce%x00%cd%x00%B%x1e"
        velhos = git(self.dir, "log", f"--format={formato}", "--date=raw", ch.REF).split("\x1e")
        velhos = [v.lstrip("\n") for v in velhos]
        primeiro = git(self.dir, "rev-list", "--reverse", ch.REF).split()[0]
        self.km("forget", "rascunho", "--apply")
        novos = git(self.dir, "log", f"--format={formato}", "--date=raw", ch.REF).split("\x1e")
        novos = [v.lstrip("\n") for v in novos]
        # 6 commits: a, r, a, r, b, deletion of r → the three about r leave (plus the
        # empty string after the last separator)
        self.assertEqual(len(velhos), 7)
        self.assertEqual(novos, [v for v in velhos if "rascunho" not in v.split("\x00")[0]])
        # the one before the draft keeps its sha
        self.assertEqual(git(self.dir, "rev-list", "--reverse", ch.REF).split()[0], primeiro)

    def test_dry_run_writes_nothing_and_lists_the_commits(self):
        self.o_caso()
        ref, cfg = self.ref(), self.config()
        objetos = git(self.dir, "count-objects", "-v")
        codigo, saida = self.km("forget", "rascunho")
        self.assertEqual(codigo, 0)
        self.assertEqual((self.ref(), self.config()), (ref, cfg))
        self.assertEqual(git(self.dir, "count-objects", "-v"), objetos)
        self.assertIn("rascunho/r.md  ·  2 versões", saida)
        self.assertIn("3 commit(s) mexeram nesses caminhos", saida)
        self.assertEqual(saida.count("sai: fica vazio"), 3)
        self.assertIn("depois: 3 commits · 3 saem vazios", saida)
        self.assertIn("folders  - rascunho", saida)
        self.assertIn("simulação: nada foi escrito", saida)

    def test_without_prune_it_prints_the_commands(self):
        self.o_caso()
        _, saida = self.km("forget", "rascunho", "--apply")
        self.assertIn("git gc --prune=now", saida)
        self.assertNotIn("SEGREDO", git(self.dir, "log", "-p", ch.REF))

    def test_an_undo_from_before_is_refused_not_misapplied(self):
        self.o_caso()
        velha = git(self.dir, "rev-parse", ch.REF + "~1").strip()      # approval of b.md
        self.km("forget", "rascunho", "--apply")
        with self.assertRaises(ch.NaoDesfaz):
            ch.desfazer(self.dir, "docs/b.md", velha, "desfazer")

    # ---- what stays, and what changes alongside --------------------------------------

    def test_a_commit_that_also_touched_another_file_stays_without_the_path(self):
        self.km("chancela", "docs/a.md", "--all")
        self.escrever("rascunho/r.md", R1)
        ch.escrever(self.dir, {"rascunho/r.md": R1, "docs/b.md": B},
                    "chancela: 2 arquivo(s), conteúdo de main\n\ndocs/b.md\nrascunho/r.md\n")
        self.km("forget", "rascunho", "--apply")
        self.assertEqual(git(self.dir, "rev-list", "--count", ch.REF).strip(), "2")
        self.assertEqual(ch.arquivos(self.dir), ["docs/a.md", "docs/b.md"])
        # the line that named the path goes; the rest of the message stays
        self.assertEqual(git(self.dir, "log", "-1", "--format=%B", ch.REF),
                         "chancela: 2 arquivo(s), conteúdo de main\n\ndocs/b.md\n\n")

    def test_forgetting_everything_deletes_the_ref(self):
        self.escrever("rascunho/r.md", R1)
        self.km("chancela", "rascunho/r.md", "--all")
        _, saida = self.km("forget", "rascunho/r.md", "--apply", "--prune")
        self.assertFalse(ch.existe(self.dir))
        self.assertIn("não sobrou nada", saida)

    def test_a_file_still_on_disk_becomes_an_exception_and_is_not_deleted(self):
        self.escrever("rascunho/r.md", R1)
        self.km("chancela", "rascunho/r.md", "--all")
        ac.gravar(self.dir, {"folders": ["."], "files": [], "except": []})
        _, saida = self.km("forget", "rascunho/r.md", "--apply")
        self.assertEqual((self.dir / "rascunho" / "r.md").read_text(encoding="utf-8"), R1)
        self.assertEqual(self.config()["except"], ["rascunho/r.md"])
        self.assertNotIn("rascunho/r.md", ac.documentos(self.dir))
        self.assertIn("vira exceção", saida)
        self.assertIn("continua no disco", saida)

    def test_an_exception_is_kept_it_is_what_leaves_the_path_out(self):
        ac.gravar(self.dir, {"folders": ["docs"], "files": [], "except": ["docs/privado"]})
        self.escrever("docs/privado/p.md", R1)
        ch.escrever(self.dir, {"docs/privado/p.md": R1}, "antes da exceção")
        self.km("forget", "docs/privado", "--apply")
        self.assertEqual(self.config()["except"], ["docs/privado"])
        self.assertFalse(ch.existe(self.dir))

    def test_the_same_text_under_another_path_is_named_and_survives(self):
        self.escrever("rascunho/r.md", R1)
        self.escrever("docs/copia.md", R1)
        self.km("chancela", "rascunho/r.md", "--all")
        self.km("chancela", "docs/copia.md", "--all")
        _, saida = self.km("forget", "rascunho")
        self.assertIn("igual a docs/copia.md", saida)
        self.assertIn("km forget docs/copia.md", saida)
        _, saida = self.km("forget", "rascunho", "--apply", "--prune")
        self.assertIn("1 continuam", saida)

    def test_a_file_committed_in_a_branch_is_said_to_stay_in_git(self):
        self.km("chancela", "docs/a.md", "--all")
        _, saida = self.km("forget", "docs/a.md")
        self.assertIn("está em commits fora da chancela", saida)

    def test_a_stale_config_entry_alone_is_cleaned(self):
        self.km("chancela", "docs/a.md", "--all")
        ref = self.ref()
        _, saida = self.km("forget", "rascunho", "--apply")
        self.assertEqual(self.ref(), ref)
        self.assertEqual(self.config()["folders"], ["docs"])
        self.assertIn("nada destes caminhos", saida)

    def test_nothing_to_forget(self):
        ac.gravar(self.dir, {"folders": ["docs"], "files": [], "except": []})
        self.km("chancela", "docs/a.md", "--all")
        ref, cfg = self.ref(), self.config()
        codigo, saida = self.km("forget", "outra/coisa.md", "--apply", "--prune")
        self.assertEqual(codigo, 0)
        self.assertIn("nada a esquecer", saida)
        self.assertEqual((self.ref(), self.config()), (ref, cfg))

    def test_refusals(self):
        for caminho, motivo in ((".", "raiz"), ("../x", ".."), ("/tmp/x", "relativo")):
            with self.assertRaises(SystemExit, msg=caminho) as e:
                self.km("forget", caminho, "--apply")
            self.assertIn(motivo, str(e.exception.code))

    def test_an_approval_meanwhile_makes_it_fail_and_nothing_is_lost(self):
        self.o_caso()
        plano = ch.planejar_esquecer(self.dir, ["rascunho"])
        self.escrever("docs/b.md", B + "\nNovo.\n")
        self.km("chancela", "docs/b.md", "--all")            # the panel, approving meanwhile
        depois = self.ref()
        with self.assertRaises(ch.Concorrencia):
            ch.esquecer(self.dir, plano)
        self.assertEqual(self.ref(), depois)
        self.assertEqual(ch.chancelado(self.dir, "docs/b.md"), B + "\nNovo.\n")

    def test_another_worktree_shares_the_chancel_and_is_told_about_its_config(self):
        self.o_caso()
        outro = self.dir.parent / (self.dir.name + "-wt")
        git(self.dir, "worktree", "add", "-q", str(outro), "-b", "outro")
        try:
            ac.gravar(outro, {"folders": ["docs", "rascunho"], "files": [], "except": []})
            _, saida = self.km("forget", "rascunho", "--apply")
            self.assertIn(f"o worktree {outro}", saida)
            self.assertIn("os 2 worktrees", saida)
            self.assertNotIn("SEGREDO", git(outro, "log", "-p", ch.REF))
        finally:
            shutil.rmtree(outro)
            git(self.dir, "worktree", "prune")

    def test_the_alias(self):
        self.o_caso()
        self.km("esquecer", "rascunho", "--apply")
        self.assertNotIn("SEGREDO", git(self.dir, "log", "-p", ch.REF))

    # ---- km lint ---------------------------------------------------------------------

    def test_lint_flags_the_stale_entry_and_suggests_forget_for_text_only_in_the_chancel(self):
        self.escrever("rascunho/r.md", R1)
        self.km("chancela", "rascunho/r.md", "--all")
        shutil.rmtree(self.dir / "rascunho")
        codigo, saida = self.km("lint", "--strict")
        self.assertEqual(codigo, 1)
        self.assertIn("rascunho/r.md: tem chancela e não está mais no disco", saida)
        self.assertIn("km forget rascunho/r.md", saida)
        self.assertIn("folders: rascunho não existe no disco", saida)
        self.assertIn("km forget rascunho apaga", saida)

    def test_lint_does_not_suggest_forget_for_a_file_a_branch_has(self):
        ac.gravar(self.dir, {"folders": ["docs"], "files": [], "except": []})
        self.km("chancela", "docs/a.md", "--all")
        git(self.dir, "rm", "-q", "docs/a.md")
        _, saida = self.km("lint")
        self.assertIn("docs/a.md: tem chancela e não está mais no disco", saida)
        self.assertNotIn("km forget", saida)

    def test_lint_a_stale_entry_with_nothing_in_the_chancel(self):
        _, saida = self.km("lint")
        self.assertIn("folders: rascunho não existe no disco · km forget rascunho tira daqui", saida)

    def test_lint_on_one_file_skips_the_config(self):
        _, saida = self.km("lint", "docs/a.md")
        self.assertNotIn(".km/config.json", saida)

    # ---- approving what git does not have --------------------------------------------

    def test_chancela_warns_when_the_file_is_not_in_git(self):
        self.escrever("rascunho/r.md", R1)
        _, saida = self.km("chancela", "rascunho/r.md", "--all")
        self.assertIn("⚠ rascunho/r.md não está no git", saida)
        self.assertIn("fica guardado no .git", saida)
        _, saida = self.km("chancela", "docs/a.md", "--all")
        self.assertNotIn("⚠", saida)

    def test_chancela_warns_when_the_file_is_ignored(self):
        (self.dir / ".gitignore").write_text(".km/\nprivado.md\n")
        self.escrever("privado.md", R1)
        ac.gravar(self.dir, {"folders": [], "files": ["privado.md"], "except": []})
        _, saida = self.km("chancela", "privado.md", "--all")
        self.assertIn("⚠ privado.md é ignorado pelo git", saida)

    def test_the_panel_warns_too(self):
        self.escrever("rascunho/r.md", R1)
        e = serve.estado(self.dir, arquivo="rascunho/r.md")
        d = next(d for d in e["docs"] if d["file"] == "rascunho/r.md")
        self.assertIn("não está no git", d["fora_do_git"])
        d = next(d for d in serve.estado(self.dir, arquivo="docs/a.md")["docs"]
                 if d["file"] == "docs/a.md")
        self.assertNotIn("fora_do_git", d)
        s = ch.situacao(self.dir, "rascunho/r.md")
        r = serve.agir(self.dir, {"acao": "aprovar", "file": "rascunho/r.md",
                                  "shas": [u.sha for u in s.unidades]}, "t")
        self.assertTrue(r["ok"], r)
        self.assertIn("⚠ fora do git", r["msg"])


class PrePushTest(unittest.TestCase):
    """`git push --mirror` sends every ref; the hook refuses refs/km/* and lets the rest by."""

    def setUp(self):
        self.base = Path(tempfile.mkdtemp())
        self.dir = self.base / "repo"
        self.remoto = self.base / "remoto.git"
        self.dir.mkdir()
        git(self.dir, "init", "-q", "-b", "main")
        git(self.dir, "config", "user.email", "t@t")
        git(self.dir, "config", "user.name", "t")
        (self.dir / "a.md").write_text(A, encoding="utf-8")
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-qm", "inicial")
        git(self.base, "init", "-q", "--bare", str(self.remoto))
        git(self.dir, "remote", "add", "cliente", str(self.remoto))
        ch.escrever(self.dir, {"rascunho.md": R1}, "chancela")
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            self.codigo = cli.main(["--repo", str(self.dir), "install-hooks"])
        self.saida = saida.getvalue()

    def tearDown(self):
        shutil.rmtree(self.base)

    def no_remoto(self):
        return git(self.remoto, "for-each-ref", "--format=%(refname)")

    def test_installs_both_hooks(self):
        self.assertEqual(self.codigo, 0)
        self.assertIn("post-commit", self.saida)
        self.assertIn("pre-push", self.saida)

    def test_mirror_is_refused_and_a_branch_goes_through(self):
        r = git(self.dir, "push", "--mirror", "cliente", ok=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("km: push recusado", r.stderr)
        self.assertIn("refs/km/chancela", r.stderr)
        self.assertEqual(self.no_remoto(), "")
        git(self.dir, "push", "-q", "cliente", "main")
        self.assertEqual(self.no_remoto().split(), ["refs/heads/main"])

    def test_naming_the_ref_is_refused_too(self):
        for spec in ("refs/km/chancela", "refs/km/chancela:refs/heads/x",
                     "main:refs/km/chancela"):
            r = git(self.dir, "push", "cliente", spec, ok=False)
            self.assertNotEqual(r.returncode, 0, spec)
        self.assertEqual(self.no_remoto(), "")

    def test_deleting_it_from_the_remote_is_allowed(self):
        git(self.dir, "push", "-q", "--no-verify", "cliente", ch.REF)
        git(self.dir, "push", "-q", "cliente", ":" + ch.REF)
        self.assertEqual(self.no_remoto(), "")

    def test_a_hook_that_is_not_ours_is_left_alone(self):
        alheio = self.dir / ".git" / "hooks" / "pre-push"
        alheio.write_text("#!/bin/sh\nexit 0\n")
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            codigo = cli.main(["--repo", str(self.dir), "install-hooks"])
        self.assertEqual(codigo, 1)
        self.assertIn("não é nosso", saida.getvalue())
        self.assertEqual(alheio.read_text(), "#!/bin/sh\nexit 0\n")


if __name__ == "__main__":
    unittest.main()
