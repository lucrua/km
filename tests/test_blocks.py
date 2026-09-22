"""Run: python3 -m unittest discover -s tests -t . -v"""

import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from km import blocks as blk

DOC = """# Regras

Uma frase de abertura.

## Calendário

- O expediente é 8 às 17, com almoço.

## Tolerância

- Chamado perdoado sai do numerador.

### Limite

- O limite é parâmetro do contrato.
"""


class SplitTest(unittest.TestCase):
    def setUp(self):
        self.bs = blk.split(DOC, "regras.md")

    def test_boundary_is_the_next_heading_of_same_or_higher_level(self):
        self.assertEqual([b.heading for b in self.bs],
                         ["Regras", "Calendário", "Tolerância", "Limite"])
        self.assertEqual(self.bs[3].path, "Regras › Tolerância › Limite")

    def test_a_nested_block_is_not_part_of_its_parent(self):
        tol = next(b for b in self.bs if b.heading == "Tolerância")
        self.assertNotIn("parâmetro do contrato", tol.body)

    def test_key_is_file_and_heading_path(self):
        self.assertEqual(self.bs[1].key, "regras.md#Regras › Calendário")

    def test_cosmetic_edits_keep_the_hash(self):
        a = blk.split(DOC, "x.md")[1].hash
        b = blk.split(DOC.replace("8 às 17", "**8 às 17**"), "x.md")[1].hash
        self.assertEqual(a, b)

    def test_changing_a_number_changes_the_hash(self):
        a = blk.split(DOC, "x.md")[1].hash
        b = blk.split(DOC.replace("8 às 17", "8 às 18"), "x.md")[1].hash
        self.assertNotEqual(a, b)


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.bs = blk.split(DOC, "regras.md")
        self.ledger = blk.Ledger(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_unvouched_is_not_a_state_you_set(self):
        self.assertEqual(self.ledger.status_of(self.bs[0]), "não revisado")

    def test_vouching_survives_a_reload(self):
        self.ledger.vouch(self.bs[1], "aprovado", by="human:test")
        self.ledger.save()
        self.assertEqual(blk.Ledger(self.tmp).status_of(self.bs[1]), "aprovado")

    def test_an_edit_says_what_it_undid(self):
        self.ledger.vouch(self.bs[1], "aprovado", by="human:test")
        mexido = blk.split(DOC.replace("8 às 17", "8 às 18"), "regras.md")[1]
        self.assertEqual(self.ledger.status_of(mexido), "mexido depois de aprovado")

    def test_waiting_on_something_expires_when_its_date_passes(self):
        self.ledger.vouch(self.bs[1], "a-validar", by="human:test")
        amanha = (date.today() + timedelta(days=1)).isoformat()
        depois = (date.today() + timedelta(days=blk.ACCEPT_EXPIRES_DAYS + 1)).isoformat()
        self.assertEqual(self.ledger.status_of(self.bs[1], today=amanha), "a-validar")
        self.assertEqual(self.ledger.status_of(self.bs[1], today=depois), "vencido")

    def test_the_old_states_are_read_as_the_two_that_remain(self):
        self.ledger.vouch(self.bs[1], "aceite", by="human:test")
        self.assertEqual(self.ledger.status_of(self.bs[1]), "a-validar")

    def test_a_vouched_block_that_left_the_file_is_an_orphan(self):
        self.ledger.vouch(self.bs[2], "aprovado", by="human:test")
        sem = [b for b in self.bs if b.heading != "Tolerância"]
        self.assertEqual([o["path"] for o in self.ledger.orphans(sem)],
                         ["Regras › Tolerância"])

    def test_branches_and_commits_are_not_part_of_identity(self):
        """The same text vouched once is vouched wherever it lives."""
        self.ledger.vouch(self.bs[1], "aprovado", by="human:test", source="abc1234")
        outro = blk.split(DOC, "regras.md")[1]
        self.assertEqual(self.ledger.status_of(outro), "aprovado")

    def test_an_unknown_state_is_refused(self):
        with self.assertRaises(ValueError):
            self.ledger.vouch(self.bs[0], "pendente", by="human:test")


if __name__ == "__main__":
    unittest.main()


class TableNormalisationTest(unittest.TestCase):
    """Re-aligning a table is decoration; it must not cost a chancel."""

    APERTADA = "## Colunas\n\n| Para quê | Atributos |\n|---|---|\n| Cliente | `CustomerID` |\n"
    ALINHADA = ("## Colunas\n\n| Para quê  | Atributos       |\n"
                "| --------- | --------------- |\n| Cliente   | `CustomerID`    |\n")

    def test_realigning_keeps_the_hash(self):
        self.assertEqual(blk.split(self.APERTADA, "x.md")[0].hash,
                         blk.split(self.ALINHADA, "x.md")[0].hash)

    def test_changing_a_cell_still_changes_the_hash(self):
        outra = self.ALINHADA.replace("`CustomerID`", "`CustomerUserID`")
        self.assertNotEqual(blk.split(self.ALINHADA, "x.md")[0].hash,
                            blk.split(outra, "x.md")[0].hash)

    def test_adding_a_column_changes_the_hash(self):
        outra = self.APERTADA.replace("| Cliente | `CustomerID` |",
                                      "| Cliente | `CustomerID` | novo |")
        self.assertNotEqual(blk.split(self.APERTADA, "x.md")[0].hash,
                            blk.split(outra, "x.md")[0].hash)


class VouchedBodyTest(unittest.TestCase):
    """The left-hand column needs the text, and git cannot always recover it."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "regras.md").write_text(DOC, encoding="utf-8")
        self.ledger = blk.Ledger(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_the_vouched_text_survives_an_edit_to_the_file(self):
        antes = blk.of_file(self.tmp, "regras.md")[1]
        self.ledger.vouch(antes, "aprovado", by="human:test")
        self.ledger.save()
        (self.tmp / "regras.md").write_text(DOC.replace("8 às 17", "8 às 19"), encoding="utf-8")
        depois = blk.of_file(self.tmp, "regras.md")[1]
        self.assertEqual(self.ledger.status_of(depois), "mexido depois de aprovado")
        self.assertIn("8 às 17", blk.Ledger(self.tmp).vouched_body(depois))

    def test_the_baseline_carries_only_what_you_vouched(self):
        bs = blk.of_file(self.tmp, "regras.md")
        self.ledger.vouch(bs[1], "aprovado", by="human:test")
        self.ledger.save()
        (self.tmp / "regras.md").write_text(
            DOC.replace("8 às 17", "8 às 19").replace("numerador", "denominador"),
            encoding="utf-8")
        base = blk.Ledger(self.tmp).vouched_file(self.tmp, "regras.md")
        self.assertIn("8 às 17", base)          # o bloco chancelado, como você aprovou
        self.assertNotIn("denominador", base)   # nunca chancelado: fica de fora, e o
        self.assertNotIn("numerador", base)     # diff o mostra como acréscimo


class NotesTest(unittest.TestCase):
    """A thread is a conversation: notes accumulate, they do not overwrite."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.bs = blk.split(DOC, "regras.md")
        self.ledger = blk.Ledger(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_notes_accumulate_across_vouches(self):
        self.ledger.vouch(self.bs[1], "a-validar", by="human:test", note="falta a fonte")
        self.ledger.vouch(self.bs[1], "a-validar", by="human:test", note="perguntei ao gestor")
        rec = self.ledger.records[self.bs[1].key]
        self.assertEqual([n["text"] for n in rec["notes"]],
                         ["falta a fonte", "perguntei ao gestor"])
        self.assertEqual(rec["state"], "a-validar")

    def test_a_note_alone_does_not_change_the_state(self):
        self.ledger.vouch(self.bs[1], "aprovado", by="human:test")
        self.ledger.note(self.bs[1], "conferir na próxima reunião", by="human:test")
        self.assertEqual(self.ledger.records[self.bs[1].key]["state"], "aprovado")
        self.assertEqual(self.ledger.status_of(self.bs[1]), "aprovado")

    def test_a_note_on_an_unvouched_block_opens_it_as_to_validate(self):
        self.ledger.note(self.bs[2], "isto tem prova?", by="human:test")
        self.assertEqual(self.ledger.status_of(self.bs[2]), "a-validar")


class BaselineOnlyVouchedTest(unittest.TestCase):
    """The left-hand column is what you vouched — never a copy of what is there now."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "regras.md").write_text(DOC, encoding="utf-8")
        self.ledger = blk.Ledger(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_a_file_never_vouched_has_an_empty_baseline(self):
        self.assertEqual(self.ledger.vouched_file(self.tmp, "regras.md"), "")

    def test_only_the_vouched_block_appears(self):
        bs = blk.of_file(self.tmp, "regras.md")
        self.ledger.vouch(bs[1], "aprovado", by="human:test")
        base = self.ledger.vouched_file(self.tmp, "regras.md")
        self.assertIn("Calendário", base)
        self.assertNotIn("Tolerância", base)

    def test_orphans_are_scoped_to_the_files_you_asked_about(self):
        bs = blk.of_file(self.tmp, "regras.md")
        self.ledger.vouch(bs[1], "aprovado", by="human:test")
        outro = blk.Block("outro.md", "X", "X", 1, 2, "corpo")
        self.ledger.vouch(outro, "aprovado", by="human:test")
        self.assertEqual(self.ledger.orphans(bs, files={"regras.md"}), [])
        self.assertEqual(len(self.ledger.orphans(bs)), 1)


class RestoreTest(unittest.TestCase):
    """Refusing a change and leaving it in place keeps in the document what you rejected."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "regras.md").write_text(DOC, encoding="utf-8")
        self.ledger = blk.Ledger(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_restoring_puts_the_vouched_text_back_in_the_file(self):
        alvo = blk.of_file(self.tmp, "regras.md")[1]
        self.ledger.vouch(alvo, "aprovado", by="human:test")
        (self.tmp / "regras.md").write_text(DOC.replace("8 às 17", "8 às 19"), encoding="utf-8")
        mexido = blk.of_file(self.tmp, "regras.md")[1]
        self.assertEqual(self.ledger.status_of(mexido), "mexido depois de aprovado")

        self.assertTrue(self.ledger.restore(self.tmp, mexido, "o expediente não mudou",
                                            by="human:test"))
        depois = blk.of_file(self.tmp, "regras.md")[1]
        self.assertIn("8 às 17", depois.body)
        self.assertEqual(self.ledger.status_of(depois), "aprovado")
        self.assertEqual(self.ledger.records[depois.key]["notes"][-1]["text"],
                         "o expediente não mudou")

    def test_the_rest_of_the_file_is_untouched(self):
        alvo = blk.of_file(self.tmp, "regras.md")[1]
        self.ledger.vouch(alvo, "aprovado", by="human:test")
        (self.tmp / "regras.md").write_text(
            DOC.replace("8 às 17", "8 às 19").replace("numerador", "denominador"),
            encoding="utf-8")
        self.ledger.restore(self.tmp, blk.of_file(self.tmp, "regras.md")[1], "não", by="t")
        texto = (self.tmp / "regras.md").read_text(encoding="utf-8")
        self.assertIn("8 às 17", texto)        # o bloco voltou
        self.assertIn("denominador", texto)    # o vizinho nao foi tocado

    def test_a_block_never_vouched_has_nothing_to_go_back_to(self):
        alvo = blk.of_file(self.tmp, "regras.md")[2]
        self.assertFalse(self.ledger.restore(self.tmp, alvo, "x", by="t"))
