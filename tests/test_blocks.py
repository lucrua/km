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

    def test_accepted_expires_into_an_assumption(self):
        self.ledger.vouch(self.bs[1], "aceite", by="human:test")
        amanha = (date.today() + timedelta(days=1)).isoformat()
        depois = (date.today() + timedelta(days=blk.ACCEPT_EXPIRES_DAYS + 1)).isoformat()
        self.assertEqual(self.ledger.status_of(self.bs[1], today=amanha), "aceite")
        self.assertEqual(self.ledger.status_of(self.bs[1], today=depois), "suposição")

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
