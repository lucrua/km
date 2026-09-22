"""Run: python3 -m unittest discover -s tests -t . -v

The chancel is a git ref, so most of this runs against a real repository in a temp
directory — including the promise that writing the ref leaves the branch, the index and
the working tree exactly as they were.
"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from km import chancela as ch

DOC = """# Regras

Texto de abertura.

## A lista fechada de colunas

Onze colunas, nesta ordem.

> ⚠️ **sem certeza** — a ordem veio de um print, não do export.

## Prazo

O prazo conta em horas úteis.
"""


def git(root, *args, entrada=None):
    r = subprocess.run(["git", *args], cwd=root, input=entrada,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


class RepoTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        git(self.dir, "init", "-q", "-b", "main")
        git(self.dir, "config", "user.email", "t@t")
        git(self.dir, "config", "user.name", "t")
        (self.dir / "regras.md").write_text(DOC, encoding="utf-8")
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-qm", "inicial")

    def tearDown(self):
        shutil.rmtree(self.dir)

    def escrever(self, texto):
        (self.dir / "regras.md").write_text(texto, encoding="utf-8")


class RefTest(RepoTest):
    def test_write_read_round_trip(self):
        self.assertFalse(ch.existe(self.dir))
        ch.escrever(self.dir, {"regras.md": DOC}, "primeira chancela")
        self.assertTrue(ch.existe(self.dir))
        self.assertEqual(ch.chancelado(self.dir, "regras.md"), DOC)
        self.assertEqual(ch.arquivos(self.dir), ["regras.md"])

    def test_leaves_branch_index_and_worktree_alone(self):
        antes = (git(self.dir, "rev-parse", "HEAD"),
                 git(self.dir, "symbolic-ref", "HEAD"),
                 git(self.dir, "status", "--porcelain"))
        ch.escrever(self.dir, {"regras.md": DOC + "\nmais\n"}, "chancela")
        depois = (git(self.dir, "rev-parse", "HEAD"),
                  git(self.dir, "symbolic-ref", "HEAD"),
                  git(self.dir, "status", "--porcelain"))
        self.assertEqual(antes, depois)
        self.assertEqual(git(self.dir, "status", "--porcelain"), "")
        # and the temporary index it used is gone
        self.assertFalse((self.dir / ".git" / "km-chancela-index").exists())

    def test_history_answers_when_a_passage_was_chancelled(self):
        ch.escrever(self.dir, {"regras.md": DOC}, "chancela: tudo")
        novo = DOC.replace("Onze colunas", "Doze colunas")
        ch.escrever(self.dir, {"regras.md": novo}, "chancela: a lista de colunas")
        t = [x for x in ch.trechos(novo) if x.titulo.startswith("A lista")][0]
        saida = ch.historico(self.dir, "regras.md", t)
        self.assertIn("a lista de colunas", saida)


class TrechoTest(unittest.TestCase):
    def test_splits_on_headings_and_keeps_the_preamble(self):
        ts = ch.trechos("intro\n\n# A\n\nx\n\n## B\n\ny\n")
        self.assertEqual([t.titulo for t in ts], ["(início do arquivo)", "A", "B"])
        self.assertEqual(ts[2].caminho, "A › B")

    def test_a_passage_ends_at_the_next_heading_whatever_its_level(self):
        ts = ch.trechos("# A\n\nx\n\n## B\n\ny\n\n# C\n\nz\n")
        a = [t for t in ts if t.titulo == "A"][0]
        self.assertEqual(a.linhas, 4)          # up to `## B`, which is its own passage
        self.assertEqual([t.caminho for t in ts], ["A", "A › B", "C"])
        c = [t for t in ts if t.titulo == "C"][0]
        self.assertEqual(c.linha, 9)


class HunkTest(unittest.TestCase):
    def test_nearby_changes_become_one_hunk(self):
        antes = "a\nb\nc\nd\ne\n"
        depois = "a\nB\nc\nD\ne\n"
        self.assertEqual(len(ch.hunks(antes, depois)), 1)

    def test_far_apart_changes_stay_apart(self):
        antes = "a\nb\nc\nd\ne\nf\ng\nh\n"
        depois = "A\nb\nc\nd\ne\nf\ng\nH\n"
        self.assertEqual(len(ch.hunks(antes, depois)), 2)

    def test_a_hunk_knows_its_passage(self):
        antes = DOC
        depois = DOC.replace("horas úteis", "horas corridas")
        h = ch.hunks(antes, depois)[0]
        self.assertEqual(h.titulo, "Prazo")

    def test_accepting_one_hunk_leaves_the_other_as_it_was(self):
        antes = "# A\n\num\n\n# B\n\ndois\n"
        depois = "# A\n\nUM\n\n# B\n\nDOIS\n"
        hs = ch.hunks(antes, depois)
        self.assertEqual(len(hs), 2)
        saida = ch.aplicar(antes, depois, {hs[0].n}, hs)
        self.assertIn("UM", saida)
        self.assertIn("dois", saida)
        self.assertNotIn("DOIS", saida)

    def test_accepting_everything_is_the_file_itself(self):
        antes, depois = DOC, DOC.replace("Onze", "Doze") + "\n## Nova\n\nx\n"
        hs = ch.hunks(antes, depois)
        self.assertEqual(ch.aplicar(antes, depois, {h.n for h in hs}, hs), depois)

    def test_accepting_nothing_is_the_chancel_itself(self):
        antes, depois = DOC, DOC.replace("Onze", "Doze")
        self.assertEqual(ch.aplicar(antes, depois, set()), antes)


class RessalvaTest(unittest.TestCase):
    def test_reads_the_three_marks(self):
        texto = ("> ⚠️ **sem certeza** — x\n"
                 "> ❓ **a confirmar até 2020-01-01** — y\n"
                 "> 🚫 **discordo** — z\n")
        self.assertEqual([m for _, m, _ in ch.ressalvas(texto)], ["⚠", "❓", "🚫"])

    def test_a_removed_caveat_is_flagged_on_its_own(self):
        antes = DOC
        depois = DOC.replace("> ⚠️ **sem certeza** — a ordem veio de um print, não do export.\n\n", "")
        h = ch.hunks(antes, depois)[0]
        self.assertTrue(h.sumidas)
        self.assertIn("sem certeza", h.sumidas[0])

    def test_rewriting_a_caveat_is_not_removing_it(self):
        antes = ["> ❓ **a confirmar até 2026-09-15** — com quem assina"]
        depois = ["> ❓ **a confirmar até 2026-10-10** — com quem assina"]
        self.assertEqual(ch.sumidas(antes, depois), [])
        self.assertEqual(ch.sumidas(antes, []), [antes[0]])

    def test_an_ordinary_edit_flags_nothing(self):
        h = ch.hunks(DOC, DOC.replace("horas úteis", "horas corridas"))[0]
        self.assertEqual(h.sumidas, [])

    def test_a_refusal_blocks_its_passage_only(self):
        depois = DOC.replace("O prazo conta em horas úteis.",
                             "O prazo conta em dias.\n\n> 🚫 **discordo** — não é o que vale.")
        hs = ch.hunks(DOC, depois)
        self.assertTrue(hs[0].bloqueio)
        outro = ch.hunks(DOC, DOC.replace("Onze", "Doze"))[0]
        self.assertFalse(outro.bloqueio)

    def test_a_question_past_its_date_is_reported(self):
        texto = "> ❓ **a confirmar até 2020-01-01** — y\n> ❓ **a confirmar até 2999-01-01** — z\n"
        self.assertEqual(len(ch.vencidas(texto, hoje="2026-09-22")), 1)


class EstadoTest(RepoTest):
    def test_passages_report_standing_moved_and_never_chancelled(self):
        ch.escrever(self.dir, {"regras.md": DOC}, "chancela")
        self.escrever(DOC.replace("horas úteis", "horas corridas") + "\n## Nova\n\nx\n")
        s = ch.situacao(self.dir, "regras.md")
        por_titulo = {e["heading"]: e["state"] for e in ch.estados(s)}
        self.assertEqual(por_titulo["A lista fechada de colunas"], "com chancela")
        self.assertEqual(por_titulo["Prazo"], "mexido")
        self.assertEqual(por_titulo["Nova"], "sem chancela")

    def test_a_file_with_no_chancel_at_all(self):
        s = ch.situacao(self.dir, "regras.md")
        self.assertFalse(s.tem_chancela)
        self.assertTrue(all(e["state"] == "sem chancela" for e in ch.estados(s)))

    def test_realigning_a_table_is_not_a_change(self):
        tabela = "# T\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
        ch.escrever(self.dir, {"regras.md": tabela}, "chancela")
        self.escrever("# T\n\n| a   | b   |\n| --- | --- |\n| 1   | 2   |\n")
        self.assertEqual(ch.situacao(self.dir, "regras.md").hunks, [])




class CliTest(RepoTest):
    """The commands, end to end, on a real repository."""

    def km(self, *args):
        import contextlib
        import io

        from km import cli
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            codigo = cli.main(["--repo", str(self.dir), *args])
        return codigo, saida.getvalue()

    def test_chancela_all_then_nothing_is_pending(self):
        self.km("chancela", "regras.md", "--all", "-m", "li inteiro")
        _, saida = self.km("pendente")
        self.assertIn("1 arquivo(s) em dia", self.km("pendente", "--short")[1])
        self.assertIn("0 trechos mexidos", saida)

    def test_one_passage_at_a_time(self):
        self.km("chancela", "regras.md", "--all")
        self.escrever(DOC.replace("Onze", "Doze").replace("horas úteis", "horas corridas"))
        self.km("chancela", "regras.md", "--hunk", "lista")
        chancela = ch.chancelado(self.dir, "regras.md")
        self.assertIn("Doze colunas", chancela)          # o que você olhou entrou
        self.assertIn("horas úteis", chancela)           # o que você não olhou, não

    def test_a_refusal_blocks_the_passage_and_says_so(self):
        self.km("chancela", "regras.md", "--all")
        self.escrever(DOC.replace("O prazo conta em horas úteis.",
                                  "O prazo conta em dias.\n\n> 🚫 **discordo** — não é isso."))
        with self.assertRaises(SystemExit):
            self.km("chancela", "regras.md", "--hunk", "Prazo")
        self.assertIn("horas úteis", ch.chancelado(self.dir, "regras.md"))
        codigo, saida = self.km("lint")
        self.assertIn("bloqueia a chancela", saida)

    def test_restore_puts_the_chancelled_text_back_on_disk(self):
        self.km("chancela", "regras.md", "--all")
        self.escrever(DOC.replace("horas úteis", "dias corridos"))
        self.km("restore", "regras.md", "--hunk", "Prazo", "-m", "já decidido")
        self.assertIn("horas úteis", (self.dir / "regras.md").read_text(encoding="utf-8"))
        self.assertEqual(self.km("pendente", "regras.md")[1].count("Prazo"), 0)

    def test_restore_refuses_when_there_is_nothing_to_go_back_to(self):
        with self.assertRaises(SystemExit):
            self.km("restore", "regras.md", "--all")

    def test_baseline_is_the_chancelled_copy(self):
        self.km("chancela", "regras.md", "--all")
        self.escrever(DOC.replace("Onze", "Doze"))
        self.assertIn("Onze colunas", self.km("baseline", "regras.md")[1])

    def test_a_removed_caveat_is_reported_apart_from_the_edit(self):
        self.km("chancela", "regras.md", "--all")
        self.escrever(DOC.replace("> ⚠️ **sem certeza** — a ordem veio de um print, não do export.\n\n", ""))
        _, saida = self.km("pendente", "regras.md")
        self.assertIn("ressalva removida", saida)

class PainelTest(RepoTest):
    """The page acts through the same functions as the CLI — these are those functions."""

    def setUp(self):
        super().setUp()
        from km import serve
        self.serve = serve

    def caminho(self, titulo):
        atual = ch.atual(self.dir, "regras.md")
        return next(t.caminho for t in ch.trechos(atual) if t.titulo == titulo)

    def agir(self, **pedido):
        pedido.setdefault("file", "regras.md")
        return self.serve.agir(self.dir, pedido, by="teste")

    def trecho(self, d, titulo):
        return next(t for t in d["trechos"] if t["heading"].startswith(titulo))

    def test_state_carries_the_marked_text_and_the_caveats(self):
        self.serve.agir(self.dir, {"acao": "aprovar", "file": "regras.md",
                                   "path": self.caminho("Regras")}, by="t")
        self.escrever(DOC.replace("horas úteis", "horas corridas"))
        d = self.serve.estado(self.dir, arquivo="regras.md")["docs"][0]
        prazo = self.trecho(d, "Prazo")
        self.assertEqual(prazo["estado"], "mexido")
        # a linha mexida vem marcada palavra a palavra, no meio do texto corrido
        mexidas = [l for l in prazo["marcado"] if l["tipo"] == "mexido"]
        self.assertTrue(mexidas)
        self.assertIn("<del>", mexidas[0]["html"])
        self.assertTrue(any(l["tipo"] == "igual" and "Prazo" in l["html"]
                            for l in prazo["marcado"]))
        self.assertEqual(self.trecho(d, "A lista")["ressalvas"][0]["mark"], "⚠")

    def test_the_ruler_is_light_and_the_open_document_is_not(self):
        """A régua lateral não carrega o texto: era 4,7 MB por requisição, de 8 em 8s."""
        self.agir(acao="aprovar", path=self.caminho("Regras"))
        leve = self.serve.estado(self.dir)["docs"][0]
        self.assertFalse(leve["cheio"])
        self.assertNotIn("marcado", leve["trechos"][0])
        cheio = self.serve.estado(self.dir, arquivo="regras.md")["docs"][0]
        self.assertTrue(cheio["cheio"])
        self.assertIn("marcado", cheio["trechos"][0])

    def test_a_deleted_passage_still_shows_up(self):
        self.serve.agir(self.dir, {"acao": "aprovar", "file": "regras.md",
                                   "path": self.caminho("Regras")}, by="t")
        self.escrever(DOC.split("## Prazo")[0])          # a seção Prazo sai do arquivo
        d = self.serve.estado(self.dir, arquivo="regras.md")["docs"][0]
        sumido = self.trecho(d, "Prazo")
        self.assertEqual(sumido["estado"], "apagado")
        self.assertTrue(sumido["base"])                  # o texto de antes continua à vista
        self.assertEqual(sumido["marcado"], [])

    def test_comparing_against_another_revision(self):
        import subprocess
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.dir,
                             capture_output=True, text=True).stdout.strip()
        self.escrever(DOC.replace("horas úteis", "horas corridas"))
        d = self.serve.estado(self.dir, base=sha, arquivo="regras.md")["docs"][0]
        self.assertTrue(any(l["tipo"] == "mexido" for l in self.trecho(d, "Prazo")["marcado"]))

    def test_aprovar_advances_the_ref(self):
        r = self.agir(acao="aprovar", path=self.caminho("Regras"))
        self.assertTrue(r["ok"], r)
        self.assertEqual(ch.chancelado(self.dir, "regras.md"), DOC)

    def test_validar_writes_the_deadline_in_the_text_and_chancels(self):
        self.agir(acao="aprovar", path=self.caminho("Regras"))
        self.escrever(DOC.replace("horas úteis", "horas corridas"))
        r = self.agir(acao="validar", path=self.caminho("Prazo"),
                      texto="confirmar com quem assina", prazo="2026-10-15")
        self.assertTrue(r["ok"], r)
        texto = (self.dir / "regras.md").read_text(encoding="utf-8")
        self.assertIn("> ❓ **a confirmar até 2026-10-15** — confirmar com quem assina", texto)
        self.assertIn("a confirmar até 2026-10-15", ch.chancelado(self.dir, "regras.md"))

    def test_reverter_puts_the_text_back(self):
        self.agir(acao="aprovar", path=self.caminho("Regras"))
        self.escrever(DOC.replace("horas úteis", "dias corridos"))
        r = self.agir(acao="reverter", path=self.caminho("Prazo"), motivo="já decidido")
        self.assertTrue(r["ok"], r)
        self.assertIn("horas úteis", (self.dir / "regras.md").read_text(encoding="utf-8"))

    def test_a_refusal_keeps_the_passage_out(self):
        self.agir(acao="aprovar", path=self.caminho("Regras"))
        self.escrever(DOC.replace("O prazo conta em horas úteis.",
                                  "O prazo conta em dias.\n\n> 🚫 **discordo** — não é isso."))
        r = self.agir(acao="aprovar", path=self.caminho("Prazo"))
        self.assertFalse(r["ok"])
        self.assertIn("🚫", r["erro"])
        self.assertIn("horas úteis", ch.chancelado(self.dir, "regras.md"))

    def test_marca_writes_the_agreed_form(self):
        r = self.agir(acao="marca", path=self.caminho("Prazo"), marca="⚠️",
                      texto="veio de um print")
        self.assertTrue(r["ok"], r)
        self.assertIn("> ⚠️ **sem certeza** — veio de um print",
                      (self.dir / "regras.md").read_text(encoding="utf-8"))

    def test_editing_a_passage_saves_only_that_passage(self):
        d = self.serve.estado(self.dir, arquivo="regras.md")["docs"][0]
        prazo = self.trecho(d, "Prazo")
        r = self.agir(acao="salvar", path=prazo["path"], sha=prazo["sha"],
                      texto="## Prazo\n\nO prazo conta em horas úteis, sempre.")
        self.assertTrue(r["ok"], r)
        texto = (self.dir / "regras.md").read_text(encoding="utf-8")
        self.assertIn("horas úteis, sempre", texto)
        self.assertIn("Onze colunas", texto)             # o resto do arquivo ficou

    def test_saving_over_someone_else_is_refused_and_shows_both(self):
        d = self.serve.estado(self.dir, arquivo="regras.md")["docs"][0]
        prazo = self.trecho(d, "Prazo")
        self.escrever(DOC.replace("horas úteis", "horas corridas"))   # outro agente escreveu
        r = self.agir(acao="salvar", path=prazo["path"], sha=prazo["sha"],
                      texto="## Prazo\n\nminha versão")
        self.assertFalse(r["ok"])
        self.assertIn("horas corridas", r["conflito"]["atual"])
        self.assertNotIn("minha versão", (self.dir / "regras.md").read_text(encoding="utf-8"))

    def test_the_editable_column_is_the_file_itself(self):
        """Uma tabela re-alinhada não conta como mudança, mas o que a tela mostra e salva
        é o texto do arquivo — normalizar na tela reescreveria o arquivo do autor."""
        tabela = DOC + "\n## Tabela\n\n| coluna | origem |\n| ------ | ------ |\n| Delta  | Tasks  |\n"
        self.escrever(tabela)
        self.agir(acao="aprovar", path=self.caminho("Regras"))
        d = self.serve.estado(self.dir, arquivo="regras.md")["docs"][0]
        tr = self.trecho(d, "Tabela")
        self.assertIn("| coluna | origem |", tr["texto"])
        self.assertEqual(tr["sha"], ch.sha_do(tr["texto"]))
        r = self.agir(acao="salvar", path=tr["path"], sha=tr["sha"], texto=tr["texto"])
        self.assertTrue(r["ok"], r)          # salvar o que a tela mostrou não é conflito
        self.assertIn("| coluna | origem |", (self.dir / "regras.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
