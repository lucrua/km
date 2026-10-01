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

> 💬 a ordem veio de um print, não do export.

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
        (self.dir / ".gitignore").write_text(".km/\n")      # como nos repositórios de verdade
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-qm", "inicial")
        from km import acompanhamento as ac
        ac.gravar(self.dir, {"folders": ["."], "files": [], "except": []})

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

    def test_an_approval_of_another_file_in_the_middle_is_kept(self):
        # Duas abas, dois worktrees: outra aprovação chega entre ler a chancela e gravá-la.
        ch.escrever(self.dir, {"regras.md": DOC}, "primeira")
        chegou = []

        def no_meio(env):
            if not chegou:
                chegou.append(ch.escrever(self.dir, {"outro.md": "# Outro\n"}, "no meio"))
            sha = git(self.dir, "hash-object", "-w", "--stdin", entrada="novo\n").strip()
            git_env = subprocess.run(["git", "update-index", "--add", "--cacheinfo",
                                      f"100644,{sha},regras.md"], cwd=self.dir, env=env)
            assert git_env.returncode == 0
        ch._avancar(self.dir, no_meio, "a minha", ["regras.md"])
        self.assertEqual(ch.chancelado(self.dir, "outro.md"), "# Outro\n")
        self.assertEqual(ch.chancelado(self.dir, "regras.md"), "novo\n")

    def test_an_approval_of_the_same_file_in_the_middle_is_not_overwritten(self):
        ch.escrever(self.dir, {"regras.md": DOC}, "primeira")

        def no_meio(env):
            ch.escrever(self.dir, {"regras.md": "a da outra aba\n"}, "no meio")
        with self.assertRaises(ch.Concorrencia):
            ch._avancar(self.dir, no_meio, "a minha", ["regras.md"])
        self.assertEqual(ch.chancelado(self.dir, "regras.md"), "a da outra aba\n")

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


class BlocoTest(unittest.TestCase):
    """The unit you approve is a Markdown block — never half a paragraph."""

    def test_paragraphs_items_tables_headings_quotes_and_code_are_blocks(self):
        texto = ("# T\n\num parágrafo\nem duas linhas\n\n- item um\n- item dois\n\n"
                 "| a | b |\n|---|---|\n| 1 | 2 |\n\n> citação\n> continua\n\n"
                 "```\ncódigo\n\ncom linha vazia\n```\n")
        _, bs = ch.blocos(texto)
        self.assertEqual([b.tipo for b in bs],
                         ["titulo", "paragrafo", "item", "item", "tabela", "citacao", "codigo"])
        self.assertEqual(bs[1].texto, "um parágrafo\nem duas linhas")

    def test_a_heading_glued_to_its_paragraph_is_still_two_blocks(self):
        _, bs = ch.blocos("## Prazo\nO prazo conta.\n")
        self.assertEqual([b.tipo for b in bs], ["titulo", "paragrafo"])


class MudancaTest(unittest.TestCase):
    def test_an_edit_inside_a_paragraph_is_the_whole_paragraph(self):
        ms = ch.mudancas(DOC, DOC.replace("horas úteis", "horas corridas"))
        self.assertEqual(len(ms), 1)
        [u] = ms[0].unidades
        self.assertEqual((u.tipo, u.depois.texto), ("mexido", "O prazo conta em horas corridas."))
        self.assertEqual(ms[0].titulo, "Prazo")

    def test_neighbouring_blocks_that_changed_are_one_change(self):
        depois = DOC.replace("Onze", "Doze").replace("> 💬 a ordem veio de um print, não do export.",
                                                     "> 💬 outra dúvida, bem diferente da primeira.")
        ms = ch.mudancas(DOC, depois)
        self.assertEqual(len(ms), 1)
        self.assertEqual(len(ms[0].unidades), 2)

    def test_changes_apart_are_separate_rows(self):
        depois = DOC.replace("Onze", "Doze").replace("horas úteis", "horas corridas")
        self.assertEqual(len(ch.mudancas(DOC, depois)), 2)

    def test_realigning_a_table_is_not_a_change(self):
        antes = "# T\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
        depois = "# T\n\n| a   | b   |\n| --- | --- |\n| 1   | 2   |\n"
        self.assertEqual(ch.mudancas(antes, depois), [])

    def test_accepting_everything_is_the_file_byte_for_byte(self):
        depois = DOC.replace("Onze", "Doze") + "\n## Nova\n\nx\n"
        ms = ch.mudancas(DOC, depois)
        self.assertEqual(ch.aplicar(DOC, depois, {str(m.n) for m in ms}), depois)

    def test_accepting_nothing_is_the_chancel(self):
        depois = DOC.replace("Onze", "Doze") + "\n## Nova\n\nx\n"
        self.assertEqual(ch.mudancas(ch.aplicar(DOC, depois, set()), DOC), [])

    def test_reordered_blocks_are_never_written_twice(self):
        # Um bloco que subiu casava com um velho que já tinha passado, e os velhos entre
        # os dois saíam de novo como "sumiu": cada aprovação duplicava parte da chancela.
        antes = "# T\n\nAlfa alfa alfa alfa.\n\nBeta beta beta beta.\n\nGama gama gama gama.\n"
        depois = "# T\n\nGama gama gama gama mudado.\n\nAlfa alfa alfa alfa mudado.\n"
        self.assertEqual(ch.aplicar(antes, depois, set()), antes)
        ms = ch.mudancas(antes, depois)
        self.assertEqual(ch.aplicar(antes, depois, {str(m.n) for m in ms}), depois)
        for m in ms:
            velhos = [u.antes.texto for u in m.unidades if u.antes]
            self.assertEqual(len(velhos), len(set(velhos)), "um bloco velho aparece duas vezes")

    def test_a_new_block_before_an_edited_one_does_not_repeat_the_old_ones(self):
        # Um bloco novo sem par levava todos os velhos restantes como "sumiu"; o próximo
        # casado voltava a posição e os mesmos velhos saíam de novo.
        antes = ("# T\n\nAlfa alfa alfa alfa.\n\nBeta beta beta beta.\n\nGama gama gama gama.\n\n"
                 "Delta delta delta delta.\n")
        depois = "# T\n\nAlfa alfa alfa alfa mudado.\n\nNada a ver com nada.\n\nGama gama gama gama mudado.\n"
        self.assertEqual(ch.aplicar(antes, depois, set()), antes)
        ms = ch.mudancas(antes, depois)
        self.assertEqual(ch.aplicar(antes, depois, {str(m.n) for m in ms}), depois)
        velhos = [u.antes.texto for m in ms for u in m.unidades if u.antes]
        self.assertEqual(len(velhos), len(set(velhos)), "um bloco velho aparece duas vezes")

    def test_accepting_one_block_of_a_change_leaves_the_rest_pending(self):
        depois = DOC.replace("Onze", "Doze").replace(
            "> 💬 a ordem veio de um print, não do export.",
            "> 💬 outra dúvida, bem diferente da primeira.")
        [m] = ch.mudancas(DOC, depois)
        primeiro = m.unidades[0]
        novo = ch.aplicar(DOC, depois, {primeiro.id})
        self.assertIn("Doze colunas", novo)
        self.assertIn("a ordem veio de um print", novo)
        [resto] = ch.mudancas(novo, depois)
        self.assertEqual(len(resto.unidades), 1)

    def test_a_block_is_identified_by_content_not_position(self):
        depois = DOC.replace("horas úteis", "horas corridas")
        sha = ch.mudancas(DOC, depois)[0].unidades[0].sha
        empurrado = "Linha nova no topo.\n\n" + depois
        self.assertTrue(ch.unidades_por_sha(ch.mudancas(DOC, empurrado), {sha}))


class ParcialTest(unittest.TestCase):
    """Approving part of a block, like staging half a hunk."""

    A = "O prazo conta em horas úteis, pelo calendário do contrato."
    B = "O prazo conta em dias corridos, pelo calendário vigente do contrato assinado."

    def test_only_the_selected_change_is_taken(self):
        i = self.B.index("dias")
        self.assertEqual(ch.mesclar(self.A, self.B, i, i + len("dias corridos")),
                         "O prazo conta em dias corridos, pelo calendário do contrato.")

    def test_a_selection_inside_a_word_takes_the_word(self):
        i = self.B.index("vigente")
        self.assertIn("calendário vigente do contrato.", ch.mesclar(self.A, self.B, i + 2, i + 3))

    def test_reverting_a_selection_undoes_only_it(self):
        i = self.B.index("assinado")
        self.assertEqual(ch.mesclar(self.A, self.B, i, len(self.B), aceitar=False),
                         "O prazo conta em dias corridos, pelo calendário vigente do contrato.")

    def test_selecting_everything_is_the_new_text_and_nothing_the_old(self):
        self.assertEqual(ch.mesclar(self.A, self.B, 0, len(self.B)), self.B)
        self.assertEqual(ch.mesclar(self.A, self.B, 0, len(self.B), aceitar=False), self.A)


class PendenciaTest(unittest.TestCase):
    def test_a_long_one_line_paragraph_edited_is_an_edit(self):
        """A 4,000-character changelog on one line, with one entry added: an edit of a few
        dozen characters — not the whole paragraph gone and another one arrived."""
        base = "**Changelog** — " + " · ".join(f"2026-09-{d:02d}: entrada número {d} do registro" for d in range(1, 90))
        antes = f"# T\n\n{base}\n"
        depois = f"# T\n\n**Changelog** — 2026-09-22: uma entrada nova · {base[len('**Changelog** — '):]}\n"
        [m] = ch.mudancas(antes, depois)
        self.assertEqual([u.tipo for u in m.unidades], ["mexido"])
        pend, total = ch.pendencia(antes, depois)
        self.assertLess(pend, total * 0.05)


    def test_counted_in_characters_that_changed_not_in_blocks(self):
        pequena = ch.pendencia(DOC, DOC.replace("Onze", "Doze"))
        grande = ch.pendencia(DOC, DOC + "\n## Nova\n\n" + "texto novo " * 40 + "\n")
        self.assertLess(pequena[0], grande[0])
        self.assertEqual(ch.pendencia(DOC, DOC), (0, ch._conta(DOC)))

    def test_something_pending_never_reads_as_zero(self):
        self.assertEqual(ch.percentual(1, 100000), "<1%")
        self.assertEqual(ch.percentual(0, 100), "0%")


class MarcaTest(unittest.TestCase):
    """The three marks, in the exact form an agent can grep for."""

    def test_reads_the_three_marks(self):
        texto = ("> ❓ **to_validate by 2026-10-01** — com quem assina\n"
                 "> 💬 para quem ler depois\n"
                 "> 📌 **to_do · 2026-09-24** — trocar a tabela\n")
        ms = ch.marcas(texto)
        self.assertEqual([(m.linha, m.tipo, m.data, m.texto) for m in ms], [
            (1, "to_validate", "2026-10-01", "com quem assina"),
            (2, "comment", "", "para quem ler depois"),
            (3, "to_do", "2026-09-24", "trocar a tabela")])

    def test_what_is_not_the_exact_form_is_not_a_mark(self):
        for linha in ["> ❓ **to_validate** — sem data",
                      "> ❓ **to_validate by 2026-10-01** - hífen, não travessão",
                      "> 📌 **to_do 2026-09-24** — sem o ponto",
                      "> 📌 **to_do · 2026-09-24** — ",
                      "> 💬 ",
                      ">💬 sem espaço",
                      "💬 fora da citação",
                      "❓ **to_validate by 2026-10-01** — fora da citação",
                      "> ⚠️ **sem certeza** — a marca antiga",
                      "> 🚫 **discordo** — a marca antiga",
                      "> ❓ **a confirmar até 2026-10-01** — a marca antiga"]:
            self.assertEqual(ch.marcas(linha), [], linha)

    def test_a_removed_mark_is_flagged_on_its_own(self):
        depois = DOC.replace("> 💬 a ordem veio de um print, não do export.\n\n", "")
        m = ch.mudancas(DOC, depois)[0]
        self.assertEqual(len(m.sumidas), 1)
        self.assertIn("💬", m.sumidas[0])

    def test_each_kind_that_vanishes_is_flagged(self):
        for linha in ["> ❓ **to_validate by 2026-10-01** — x",
                      "> 💬 x",
                      "> 📌 **to_do · 2026-09-24** — x"]:
            antes = DOC + "\n" + linha + "\n"
            ms = ch.mudancas(antes, DOC)
            self.assertEqual([s for m in ms for s in m.sumidas], [linha], linha)

    def test_rewriting_a_mark_is_not_removing_it(self):
        antes = ["> ❓ **to_validate by 2026-09-15** — com quem assina"]
        depois = ["> ❓ **to_validate by 2026-10-10** — com quem assina, e quando"]
        self.assertEqual(ch.sumidas(antes, depois), [])
        self.assertEqual(ch.sumidas(antes, []), [antes[0]])

    def test_a_mark_turned_into_another_kind_is_flagged(self):
        antes = ["> 📌 **to_do · 2026-09-24** — trocar a tabela"]
        depois = ["> 💬 trocar a tabela"]
        self.assertEqual(ch.sumidas(antes, depois), [antes[0]])

    def test_an_ordinary_edit_flags_nothing(self):
        m = ch.mudancas(DOC, DOC.replace("horas úteis", "horas corridas"))[0]
        self.assertEqual(m.sumidas, [])

    def test_a_deadline_past_today_is_overdue(self):
        texto = ("> ❓ **to_validate by 2026-09-23** — ontem\n"
                 "> ❓ **to_validate by 2026-09-24** — hoje\n"
                 "> 📌 **to_do · 2020-01-01** — to_do não vence\n")
        self.assertEqual([(l, d) for l, d, _ in ch.vencidas(texto, hoje="2026-09-24")],
                         [(1, "2026-09-23")])

    def test_the_placeholder_is_found(self):
        texto = ("> 💬 add your comment here\n"
                 "> 📌 **to_do · 2026-09-24** — trocar a tabela\n")
        self.assertEqual([m.linha for m in ch.marcas(texto) if m.placeholder], [1])

    def test_no_mark_blocks_anything(self):
        self.assertFalse(hasattr(ch, "bloqueio_de"))
        self.assertFalse(hasattr(ch.Mudanca, "bloqueio"))


class EstadoTest(RepoTest):
    def test_the_file_reports_its_changes_where_they_are(self):
        ch.escrever(self.dir, {"regras.md": DOC}, "chancela")
        self.escrever(DOC.replace("horas úteis", "horas corridas") + "\n## Nova\n\nx\n")
        s = ch.situacao(self.dir, "regras.md")
        self.assertEqual([m.titulo for m in s.mudancas], ["Prazo"])
        self.assertEqual([u.tipo for u in s.unidades], ["mexido", "novo", "novo"])

    def test_a_file_with_no_chancel_is_all_new(self):
        s = ch.situacao(self.dir, "regras.md")
        self.assertFalse(s.tem_chancela)
        self.assertTrue(all(u.tipo == "novo" for u in s.unidades))

    def test_realigning_a_table_is_not_a_change(self):
        tabela = "# T\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
        ch.escrever(self.dir, {"regras.md": tabela}, "chancela")
        self.escrever("# T\n\n| a   | b   |\n| --- | --- |\n| 1   | 2   |\n")
        self.assertEqual(ch.situacao(self.dir, "regras.md").mudancas, [])




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
        self.assertIn("1 arquivo(s) em dia", self.km("pendente", "--short")[1])
        self.assertNotIn("trechos mexidos", self.km("pendente")[1])

    def test_one_passage_at_a_time(self):
        self.km("chancela", "regras.md", "--all")
        self.escrever(DOC.replace("Onze", "Doze").replace("horas úteis", "horas corridas"))
        self.km("chancela", "regras.md", "--hunk", "lista")
        chancela = ch.chancelado(self.dir, "regras.md")
        self.assertIn("Doze colunas", chancela)          # o que você olhou entrou
        self.assertIn("horas úteis", chancela)           # o que você não olhou, não

    def test_a_mark_never_blocks_the_chancel(self):
        self.km("chancela", "regras.md", "--all")
        self.escrever(DOC.replace("O prazo conta em horas úteis.",
                                  "O prazo conta em dias.\n\n> ❓ **to_validate by 2026-10-01** — é isso?"))
        self.km("chancela", "regras.md", "--hunk", "Prazo")
        self.assertIn("to_validate by 2026-10-01", ch.chancelado(self.dir, "regras.md"))

    def test_there_is_no_force(self):
        with self.assertRaises(SystemExit):
            self.km("chancela", "regras.md", "--all", "--force")

    def test_lint_reports_overdue_and_placeholder_and_nothing_else(self):
        self.escrever(DOC + "\n> ❓ **to_validate by 2020-01-01** — venceu\n"
                      "\n> ❓ **to_validate by 2999-01-01** — longe\n"
                      "\n> 📌 **to_do · 2020-01-01** — add your comment here\n"
                      "\n> 💬 um comentário de verdade\n")
        self.km("chancela", "regras.md", "--all")
        codigo, saida = self.km("lint")
        self.assertIn(":15", saida)                       # o ❓ vencido, com a linha
        self.assertIn("2020-01-01", saida)
        self.assertNotIn("longe", saida)
        self.assertIn("add your comment here", saida)
        self.assertIn("2 apontamento(s)", saida)
        self.assertEqual(self.km("lint", "--strict")[0], 1)

    def test_marcas_lists_what_an_agent_should_find(self):
        (self.dir / "outro.md").write_text(
            "# Outro\n\n> 📌 **to_do · 2026-09-24** — trocar a tabela\n\n"
            "> 💬 para quem ler\n", encoding="utf-8")
        self.escrever(DOC + "\n> ❓ **to_validate by 2020-01-01** — venceu\n")
        _, saida = self.km("marcas")
        linhas = [l for l in saida.splitlines() if l.strip()]
        self.assertEqual(linhas, [
            "outro.md:3  to_do  2026-09-24  trocar a tabela",
            "regras.md:15  to_validate  2020-01-01  venceu  (vencido)"])
        self.assertIn("para quem ler", self.km("marcas", "--todas")[1])
        self.assertIn("para quem ler", self.km("marcas", "--all")[1])
        self.assertNotIn("regras.md", self.km("marcas", "--tipo", "to_do")[1])

    def test_marcas_json(self):
        import json
        self.escrever(DOC + "\n> ❓ **to_validate by 2020-01-01** — venceu\n")
        _, saida = self.km("marcas", "--json", "--todas")
        dados = json.loads(saida)
        self.assertEqual(dados, [
            {"file": "regras.md", "line": 9, "kind": "comment", "date": "",
             "text": "a ordem veio de um print, não do export.", "overdue": False},
            {"file": "regras.md", "line": 15, "kind": "to_validate", "date": "2020-01-01",
             "text": "venceu", "overdue": True}])

    def test_marcas_reads_files_the_chancel_does_not_track(self):
        from km import acompanhamento as ac
        ac.gravar(self.dir, ac.vazia())
        self.escrever(DOC + "\n> 📌 **to_do · 2026-09-24** — mesmo sem acompanhar\n")
        self.assertIn("mesmo sem acompanhar", self.km("marcas")[1])

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

    def test_a_removed_mark_is_reported_apart_from_the_edit(self):
        self.km("chancela", "regras.md", "--all")
        self.escrever(DOC.replace("> 💬 a ordem veio de um print, não do export.\n\n", ""))
        _, saida = self.km("pendente", "regras.md")
        self.assertIn("marca removida", saida)

class PainelTest(RepoTest):
    """The page acts through the same functions as the CLI — these are those functions."""

    def setUp(self):
        super().setUp()
        from km import serve
        self.serve = serve
        ch.escrever(self.dir, {"regras.md": DOC}, "chancela")

    def agir(self, **pedido):
        pedido.setdefault("file", "regras.md")
        return self.serve.agir(self.dir, pedido, by="teste")

    def doc(self, **kw):
        return self.serve.estado(self.dir, arquivo="regras.md", **kw)["docs"][0]

    def mudancas(self, **kw):
        return [s for s in self.doc(**kw)["segmentos"] if s["tipo"] == "mudanca"]

    def texto(self):
        return (self.dir / "regras.md").read_text(encoding="utf-8")

    def test_a_file_in_step_is_one_run_of_text_with_nothing_to_decide(self):
        segs = self.doc()["segmentos"]
        self.assertEqual([s["tipo"] for s in segs], ["igual"])
        self.assertEqual(segs[0]["texto"], DOC.rstrip("\n"))

    def test_changes_are_rows_and_headings_cut_nothing(self):
        self.escrever(DOC.replace("Onze", "Doze").replace("horas úteis", "horas corridas"))
        segs = self.doc()["segmentos"]
        self.assertEqual([s["tipo"] for s in segs],
                         ["igual", "mudanca", "igual", "mudanca", "igual"][:len(segs)])
        self.assertEqual(len([s for s in segs if s["tipo"] == "mudanca"]), 2)

    def test_a_change_carries_both_texts_and_no_html(self):
        self.escrever(DOC.replace("horas úteis", "horas corridas"))
        [m] = self.mudancas()
        self.assertEqual(m["antes"], "O prazo conta em horas úteis.")
        self.assertEqual(m["agora"], "O prazo conta em horas corridas.")
        self.assertNotIn("linhas", m)
        segs = self.doc()["segmentos"]
        self.assertTrue(all("<" not in (s.get("texto") or "") or "<" in DOC for s in segs))

    def test_consecutive_changed_blocks_are_one_passage(self):
        """A heading, a table and a paragraph that all changed, one after the other, are
        one thing to read — one text on each side, one set of verdicts."""
        self.escrever(DOC.replace("## A lista fechada de colunas\n\nOnze colunas, nesta ordem.",
                                  "## A lista aberta de colunas\n\nDoze colunas, em outra ordem."))
        [m] = self.mudancas()
        self.assertEqual(m["agora"], "## A lista aberta de colunas\n\nDoze colunas, em outra ordem.")
        self.assertEqual(len(m["unidades"]), 2)                     # o motor ainda sabe dos blocos
        self.assertEqual(m["unidades"][1]["ini"], m["agora"].index("Doze"))

    def test_a_selection_over_the_passage_reaches_the_right_block(self):
        self.escrever(DOC.replace("## A lista fechada de colunas\n\nOnze colunas, nesta ordem.",
                                  "## A lista aberta de colunas\n\nDoze colunas, em outra ordem."))
        [m] = self.mudancas()
        par = m["unidades"][1]                                       # o parágrafo
        i = m["agora"].index("Doze")
        r = self.agir(acao="aprovar", parciais=[{"sha": par["sha"], "ini": i - par["ini"],
                                                 "fim": i + 4 - par["ini"]}])
        self.assertTrue(r["ok"], r)
        chancela = ch.chancelado(self.dir, "regras.md")
        self.assertIn("Doze colunas, nesta ordem.", chancela)        # só a palavra selecionada
        self.assertIn("## A lista fechada de colunas", chancela)     # o título ficou pendente

    def test_approving_one_block_leaves_its_neighbour_pending(self):
        self.escrever(DOC.replace("Onze", "Doze").replace(
            "> 💬 a ordem veio de um print, não do export.",
            "> 💬 outra dúvida, bem diferente da primeira."))
        [m] = self.mudancas()
        r = self.agir(acao="aprovar", shas=[m["unidades"][0]["sha"]])
        self.assertTrue(r["ok"], r)
        self.assertIn("Doze colunas", ch.chancelado(self.dir, "regras.md"))
        self.assertIn("a ordem veio de um print", ch.chancelado(self.dir, "regras.md"))
        [resto] = self.mudancas()
        self.assertEqual(len(resto["unidades"]), 1)

    def test_a_stale_page_cannot_approve_something_else(self):
        self.escrever(DOC.replace("horas úteis", "horas corridas"))
        sha = self.mudancas()[0]["unidades"][0]["sha"]
        self.escrever(DOC.replace("horas úteis", "dias corridos"))    # mudou de novo
        r = self.agir(acao="aprovar", shas=[sha])
        self.assertFalse(r["ok"])
        self.assertIn("horas úteis", ch.chancelado(self.dir, "regras.md"))

    def test_there_is_no_validar_action(self):
        self.escrever(DOC.replace("horas úteis", "horas corridas"))
        sha = self.mudancas()[0]["unidades"][0]["sha"]
        r = self.agir(acao="validar", shas=[sha], texto="x", prazo="2026-10-15")
        self.assertFalse(r["ok"])
        self.assertIn("desconhecida", r["erro"])
        self.assertNotIn("to_validate", self.texto())
        self.assertIn("horas úteis", ch.chancelado(self.dir, "regras.md"))

    def test_reverter_puts_the_block_back(self):
        self.escrever(DOC.replace("horas úteis", "dias corridos"))
        sha = self.mudancas()[0]["unidades"][0]["sha"]
        r = self.agir(acao="reverter", shas=[sha])
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.texto(), DOC)

    def test_approving_takes_the_passage_and_its_mark_and_nothing_blocks_it(self):
        for linha in ["> ❓ **to_validate by 2020-01-01** — é isso?",
                      "> 📌 **to_do · 2026-09-24** — refazer",
                      "> 💬 add your comment here"]:
            ch.escrever(self.dir, {"regras.md": DOC}, "chancela")
            self.escrever(DOC.replace("O prazo conta em horas úteis.",
                                      "O prazo conta em dias.\n\n" + linha))
            [m] = self.mudancas()
            self.assertNotIn("bloqueio", m)
            r = self.agir(acao="aprovar", shas=[u["sha"] for u in m["unidades"]])
            self.assertTrue(r["ok"], r)
            self.assertEqual(ch.chancelado(self.dir, "regras.md"), self.texto())
            self.assertNotIn("bloqueado", self.doc())

    def test_a_vanished_mark_reaches_the_page(self):
        self.escrever(DOC.replace("> 💬 a ordem veio de um print, não do export.\n\n", ""))
        [m] = self.mudancas()
        self.assertEqual(m["sumidas"], ["> 💬 a ordem veio de um print, não do export."])

    def test_saving_finds_the_text_even_if_the_file_moved(self):
        self.escrever(DOC.replace("horas úteis", "horas corridas"))
        u = self.mudancas()[0]
        self.escrever("Linha nova no topo.\n\n" + self.texto())       # um agente empurrou tudo
        r = self.agir(acao="salvar", original=u["agora"], linha=u["linha"],
                      texto="O prazo conta em horas úteis, sempre.")
        self.assertTrue(r["ok"], r)
        self.assertIn("Linha nova no topo.", self.texto())
        self.assertIn("horas úteis, sempre.", self.texto())

    def test_saving_over_someone_else_is_refused_and_shows_theirs(self):
        self.escrever(DOC.replace("horas úteis", "horas corridas"))
        u = self.mudancas()[0]
        self.escrever(DOC.replace("horas úteis", "dias corridos"))    # outro agente reescreveu
        r = self.agir(acao="salvar", original=u["agora"], linha=u["linha"], texto="minha versão")
        self.assertFalse(r["ok"])
        self.assertIn("dias corridos", r["conflito"]["atual"])
        self.assertNotIn("minha versão", self.texto())

    def test_the_editable_text_is_the_file_itself(self):
        """A re-aligned table does not count as a change, but what the page shows and saves
        is the file's text — showing the canonical form would reformat the author's file."""
        tabela = DOC + "\n## Tabela\n\n| coluna | origem |\n| ------ | ------ |\n| Delta  | Tasks  |\n"
        self.escrever(tabela)
        ch.escrever(self.dir, {"regras.md": tabela}, "chancela")
        [s] = self.doc()["segmentos"]
        self.assertIn("| coluna | origem |", s["texto"])

    def test_the_ruler_is_light_and_the_open_document_is_not(self):
        leve = self.serve.estado(self.dir)["docs"][0]
        self.assertNotIn("segmentos", leve)
        self.assertIn("segmentos", self.doc())

    def test_comparing_against_another_revision(self):
        import subprocess
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.dir,
                             capture_output=True, text=True).stdout.strip()
        self.escrever(DOC.replace("horas úteis", "horas corridas"))
        self.assertEqual(len(self.mudancas(base=sha)), 1)

    def test_approving_a_selection_takes_only_that_part(self):
        self.escrever(DOC.replace("horas úteis", "dias corridos, sempre"))
        m = self.mudancas()[0]
        u = m["unidades"][0]
        i = m["agora"].index("dias corridos") - u["ini"]
        r = self.agir(acao="aprovar", parciais=[{"sha": u["sha"], "ini": i, "fim": i + 13}])
        self.assertTrue(r["ok"], r)
        self.assertIn("O prazo conta em dias corridos.", ch.chancelado(self.dir, "regras.md"))
        [resto] = self.mudancas()
        self.assertIn("sempre", resto["agora"])

    def test_reverting_a_selection_undoes_only_that_part_in_the_file(self):
        self.escrever(DOC.replace("horas úteis", "dias corridos, sempre"))
        m = self.mudancas()[0]
        u = m["unidades"][0]
        i = m["agora"].index(", sempre") - u["ini"]
        r = self.agir(acao="reverter", parciais=[{"sha": u["sha"], "ini": i, "fim": i + 8}])
        self.assertTrue(r["ok"], r)
        self.assertIn("O prazo conta em dias corridos.", self.texto())

    def test_an_approval_can_be_undone_and_the_passage_is_pending_again(self):
        self.escrever(DOC.replace("horas úteis", "dias corridos"))
        [m] = self.mudancas()
        r = self.agir(acao="aprovar", shas=[u["sha"] for u in m["unidades"]])
        self.assertTrue(r["ok"], r)
        self.assertIn("dias corridos", ch.chancelado(self.dir, "regras.md"))
        r = self.agir(acao="desfazer", commit=r["desfazer"])
        self.assertTrue(r["ok"], r)
        self.assertEqual(ch.chancelado(self.dir, "regras.md"), DOC)
        self.assertIn("dias corridos", self.texto())        # o arquivo não é mexido
        self.assertEqual(len(self.mudancas()), 1)

    def test_the_whole_file_in_one_approval_is_one_commit_and_one_undo(self):
        """Aprovar o arquivo inteiro: os blocos de todas as mudanças da tela, de uma vez."""
        hoje = DOC.replace("Onze", "Doze").replace("horas úteis", "dias corridos").replace(
            "> 💬 a ordem veio de um print, não do export.\n\n", "")
        self.escrever(hoje)
        ms = self.mudancas()
        self.assertGreaterEqual(len(ms), 2)
        antes = git(self.dir, "rev-list", "--count", ch.REF)
        r = self.agir(acao="aprovar", shas=[u["sha"] for m in ms for u in m["unidades"]])
        self.assertTrue(r["ok"], r)
        self.assertIn("arquivo em dia", r["msg"])
        self.assertIn("1 marca(s) removida(s)", r["msg"])
        self.assertEqual(ch.chancelado(self.dir, "regras.md"), hoje)     # byte a byte
        self.assertEqual(int(git(self.dir, "rev-list", "--count", ch.REF)), int(antes) + 1)
        self.assertIn("arquivo inteiro", git(self.dir, "log", "-1", "--format=%s", ch.REF))
        r = self.agir(acao="desfazer", commit=r["desfazer"])
        self.assertTrue(r["ok"], r)
        self.assertEqual(ch.chancelado(self.dir, "regras.md"), DOC)
        self.assertEqual(len(self.mudancas()), len(ms))

    def test_the_whole_file_approves_what_the_page_saw_not_what_came_after(self):
        self.escrever(DOC.replace("Onze", "Doze").replace("horas úteis", "dias corridos"))
        shas = [u["sha"] for m in self.mudancas() for u in m["unidades"]]
        depois = self.texto().replace("Texto de abertura.", "Texto de abertura, de um agente.")
        self.escrever(depois)                                   # um agente, enquanto você lia
        r = self.agir(acao="aprovar", shas=shas)
        self.assertTrue(r["ok"], r)
        self.assertIn("falta", r["msg"])
        chancela = ch.chancelado(self.dir, "regras.md")
        self.assertIn("Doze colunas", chancela)
        self.assertIn("dias corridos", chancela)
        self.assertIn("Texto de abertura.", chancela)
        self.assertNotIn("arquivo inteiro", git(self.dir, "log", "-1", "--format=%s", ch.REF))
        [resto] = self.mudancas()
        self.assertEqual(resto["agora"], "Texto de abertura, de um agente.")

    def test_undoing_the_first_approval_of_a_file_makes_it_new_again(self):
        (self.dir / "novo.md").write_text("# Novo\n\nTexto.\n", encoding="utf-8")
        s = ch.situacao(self.dir, "novo.md")
        r = self.agir(acao="aprovar", file="novo.md", shas=[u.sha for u in s.unidades])
        self.assertTrue(r["ok"], r)
        self.assertIsNotNone(ch.chancelado(self.dir, "novo.md"))
        r = self.agir(acao="desfazer", file="novo.md", commit=r["desfazer"])
        self.assertTrue(r["ok"], r)
        self.assertIsNone(ch.chancelado(self.dir, "novo.md"))
        self.assertEqual(ch.chancelado(self.dir, "regras.md"), DOC)

    def test_undo_is_refused_once_the_file_was_approved_again(self):
        self.escrever(DOC.replace("horas úteis", "dias corridos").replace("Onze", "Doze"))
        primeiro, _ = self.mudancas()
        r1 = self.agir(acao="aprovar", shas=[u["sha"] for u in primeiro["unidades"]])
        [segundo] = self.mudancas()
        r2 = self.agir(acao="aprovar", shas=[u["sha"] for u in segundo["unidades"]])
        r = self.agir(acao="desfazer", commit=r1["desfazer"])
        self.assertFalse(r["ok"])
        self.assertIn("dias corridos", ch.chancelado(self.dir, "regras.md"))
        # De trás para frente, cada um volta.
        self.assertTrue(self.agir(acao="desfazer", commit=r2["desfazer"])["ok"])
        self.assertTrue(self.agir(acao="desfazer", commit=r1["desfazer"])["ok"])
        self.assertEqual(ch.chancelado(self.dir, "regras.md"), DOC)

    def test_undo_ignores_approvals_of_other_files_made_after(self):
        self.escrever(DOC.replace("horas úteis", "dias corridos"))
        [m] = self.mudancas()
        r = self.agir(acao="aprovar", shas=[u["sha"] for u in m["unidades"]])
        (self.dir / "outro.md").write_text("# Outro\n", encoding="utf-8")
        s = ch.situacao(self.dir, "outro.md")
        self.agir(acao="aprovar", file="outro.md", shas=[u.sha for u in s.unidades])
        self.assertTrue(self.agir(acao="desfazer", commit=r["desfazer"])["ok"])
        self.assertEqual(ch.chancelado(self.dir, "regras.md"), DOC)
        self.assertEqual(ch.chancelado(self.dir, "outro.md"), "# Outro\n")

    def test_undo_refuses_a_commit_that_is_not_an_approval_of_this_file(self):
        r = self.agir(acao="desfazer", commit="HEAD")
        self.assertFalse(r["ok"])
        self.assertEqual(ch.chancelado(self.dir, "regras.md"), DOC)

    def test_the_rail_speaks_in_percent_not_counts(self):
        self.escrever(DOC.replace("horas úteis", "horas corridas"))
        d = self.serve.estado(self.dir)["docs"][0]
        self.assertTrue(d["pct"].endswith("%"))
        self.assertNotIn("blocos", d)
        self.assertNotIn("mudancas", d)


class LendoTest(RepoTest):
    """The right-hand side can be another worktree or a branch, against the one chancel."""

    def setUp(self):
        super().setUp()
        from km import serve
        self.serve = serve
        ch.escrever(self.dir, {"regras.md": DOC}, "chancela")
        # Um worktree com o arquivo mexido, sem .km/config.json — como os de verdade.
        self.wt = Path(tempfile.mkdtemp()) / "wt"
        git(self.dir, "worktree", "add", "-q", "-b", "wt", str(self.wt))
        (self.wt / "regras.md").write_text(DOC.replace("horas úteis", "horas do worktree"),
                                           encoding="utf-8")
        # Um branch sem worktree, com um arquivo que só existe nele.
        git(self.dir, "checkout", "-q", "-b", "solto")
        self.escrever(DOC.replace("Onze", "Doze"))
        (self.dir / "so-no-branch.md").write_text("# Só aqui\n", encoding="utf-8")
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-qm", "solto")
        git(self.dir, "checkout", "-q", "main")

    def tearDown(self):
        shutil.rmtree(self.wt.parent)
        super().tearDown()

    def fontes(self):
        return {f["id"]: f for f in self.serve.fontes(self.dir)}

    def test_lists_this_folder_the_other_worktrees_and_the_loose_branches(self):
        f = self.fontes()
        self.assertEqual(f[""]["tipo"], "pasta")
        wt = [x for x in f.values() if x["tipo"] == "worktree"]
        self.assertEqual([x["rotulo"].split(" · ")[0] for x in wt], ["wt"])
        self.assertIn("br:solto", f)
        self.assertNotIn("br:main", f)          # checado aqui mesmo
        self.assertNotIn("br:wt", f)            # checado no worktree: vale o disco dele

    def test_an_unknown_source_is_refused(self):
        for lendo in ["wt:/etc", "br:nao-existe", "br:main", "../x"]:
            r = self.serve.agir(self.dir, {"acao": "aprovar", "file": "regras.md",
                                           "shas": [], "lendo": lendo}, by="t")
            self.assertFalse(r["ok"], lendo)

    def test_a_worktree_is_read_from_its_disk_with_this_projects_config(self):
        wt = next(i for i, x in self.fontes().items() if x["tipo"] == "worktree")
        e = self.serve.estado(self.dir, arquivo="regras.md", lendo=wt)
        [d] = e["docs"]
        [m] = [s for s in d["segmentos"] if s["tipo"] == "mudanca"]
        self.assertIn("horas do worktree", m["agora"])
        self.assertFalse(e["so_aprovar"])
        self.assertEqual(e["pasta"], str(self.wt))

    def test_approving_in_a_worktree_writes_the_one_chancel(self):
        wt = next(i for i, x in self.fontes().items() if x["tipo"] == "worktree")
        e = self.serve.estado(self.dir, arquivo="regras.md", lendo=wt)
        [m] = [s for s in e["docs"][0]["segmentos"] if s["tipo"] == "mudanca"]
        r = self.serve.agir(self.dir, {"acao": "aprovar", "file": "regras.md", "lendo": wt,
                                       "shas": [u["sha"] for u in m["unidades"]]}, by="t")
        self.assertTrue(r["ok"], r)
        self.assertIn("horas do worktree", ch.chancelado(self.dir, "regras.md"))
        # Aqui, onde o arquivo ainda diz horas úteis, isso vira pendência.
        self.assertTrue(ch.situacao(self.dir, "regras.md").mudancas)

    def test_reverting_in_a_worktree_writes_the_worktree_file(self):
        wt = next(i for i, x in self.fontes().items() if x["tipo"] == "worktree")
        e = self.serve.estado(self.dir, arquivo="regras.md", lendo=wt)
        [m] = [s for s in e["docs"][0]["segmentos"] if s["tipo"] == "mudanca"]
        r = self.serve.agir(self.dir, {"acao": "reverter", "file": "regras.md", "lendo": wt,
                                       "shas": [u["sha"] for u in m["unidades"]]}, by="t")
        self.assertTrue(r["ok"], r)
        self.assertEqual((self.wt / "regras.md").read_text(encoding="utf-8"), DOC)
        self.assertEqual((self.dir / "regras.md").read_text(encoding="utf-8"), DOC)

    def test_a_branch_is_read_from_its_last_commit_files_included(self):
        e = self.serve.estado(self.dir, arquivo="regras.md", lendo="br:solto")
        self.assertTrue(e["so_aprovar"])
        self.assertIn("so-no-branch.md", [d["file"] for d in e["docs"]])
        d = next(d for d in e["docs"] if d["file"] == "regras.md")
        [m] = [s for s in d["segmentos"] if s["tipo"] == "mudanca"]
        self.assertIn("Doze", m["agora"])

    def test_a_branch_can_be_approved_and_undone_but_nothing_is_written_to_disk(self):
        e = self.serve.estado(self.dir, arquivo="regras.md", lendo="br:solto")
        d = next(d for d in e["docs"] if d["file"] == "regras.md")
        [m] = [s for s in d["segmentos"] if s["tipo"] == "mudanca"]
        shas = [u["sha"] for u in m["unidades"]]
        for acao in ("reverter", "salvar"):
            r = self.serve.agir(self.dir, {"acao": acao, "file": "regras.md", "lendo": "br:solto",
                                           "shas": shas, "original": "x", "texto": "y"}, by="t")
            self.assertFalse(r["ok"], acao)
        r = self.serve.agir(self.dir, {"acao": "aprovar", "file": "regras.md", "lendo": "br:solto",
                                       "shas": shas}, by="t")
        self.assertTrue(r["ok"], r)
        self.assertIn("Doze colunas", ch.chancelado(self.dir, "regras.md"))
        self.assertEqual((self.dir / "regras.md").read_text(encoding="utf-8"), DOC)
        r = self.serve.agir(self.dir, {"acao": "desfazer", "file": "regras.md", "lendo": "br:solto",
                                       "commit": r["desfazer"]}, by="t")
        self.assertTrue(r["ok"], r)
        self.assertEqual(ch.chancelado(self.dir, "regras.md"), DOC)

    def test_a_file_only_on_the_branch_can_be_approved_whole(self):
        s = ch.situacao(self.dir, "so-no-branch.md", rev="solto")
        r = self.serve.agir(self.dir, {"acao": "aprovar", "file": "so-no-branch.md",
                                       "lendo": "br:solto", "shas": [u.sha for u in s.unidades]}, by="t")
        self.assertTrue(r["ok"], r)
        self.assertEqual(ch.chancelado(self.dir, "so-no-branch.md"), "# Só aqui\n")


if __name__ == "__main__":
    unittest.main()
