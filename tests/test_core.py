"""Run: python3 -m unittest discover -s tests -t . -v"""

import shutil
import tempfile
import unittest
from pathlib import Path

from km import core

FIXTURE = Path(__file__).parent / "fixtures"


class ParseTest(unittest.TestCase):
    def setUp(self):
        self.claims = core.scan(FIXTURE, core.DEFAULT_CONFIG)
        self.by_preview = {c.preview(): c for c in self.claims}

    def test_finds_list_items_and_paragraphs(self):
        previews = list(self.by_preview)
        self.assertTrue(any("measured per contract" in p for p in previews))
        self.assertTrue(any("paragraph that states something" in p for p in previews))

    def test_ignores_context(self):
        texts = [c.text for c in self.claims]
        for noise in ("print(", "| column", "type: Rules"):
            self.assertFalse(any(noise in t for t in texts), noise)
        self.assertFalse(any(t.startswith(("#", ">", "|")) for t in texts))
        self.assertFalse(any("quoted line" in t for t in texts))
        self.assertNotIn("Availability", [t.strip() for t in texts])

    def test_heading_path_is_kept(self):
        claim = next(c for c in self.claims if "measured per contract" in c.text)
        self.assertIn("Availability", claim.heading)

    def test_id_claims_are_keyed_by_id(self):
        claim = next(c for c in self.claims if c.claim_id)
        self.assertEqual(claim.key, "DSP-9")
        self.assertEqual(claim.kind, "id")


class NormaliseTest(unittest.TestCase):
    def test_cosmetic_edits_keep_the_hash(self):
        a = "- **Availability** is measured per `contract`."
        b = "- Availability is measured per contract"
        self.assertEqual(core.text_hash(a), core.text_hash(b))

    def test_link_target_is_noise_but_text_is_not(self):
        self.assertEqual(core.text_hash("see [the rule](a.md)"),
                         core.text_hash("see [the rule](b.md)"))
        self.assertNotEqual(core.text_hash("see [the rule](a.md)"),
                            core.text_hash("see [another rule](a.md)"))

    def test_numbers_are_never_normalised(self):
        self.assertNotEqual(core.text_hash("at least 98% of cases"),
                            core.text_hash("at least 89% of cases"))


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        shutil.copytree(FIXTURE, self.tmp / "docs")
        self.root = self.tmp

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def claims(self):
        return core.scan(self.root, core.DEFAULT_CONFIG)

    def test_approval_survives_reload_and_sets_status(self):
        claims = self.claims()
        target = next(c for c in claims if "measured per contract" in c.text)
        store = core.Store(self.root)
        self.assertEqual(core.status_of(target, store), "proposed")
        store.approve(target, by="human:test")
        store.save()

        store2 = core.Store(self.root)
        self.assertEqual(core.status_of(target, store2), "approved")

    def test_editing_the_text_drops_the_approval(self):
        claims = self.claims()
        target = next(c for c in claims if "measured per contract" in c.text)
        store = core.Store(self.root)
        store.approve(target, by="human:test")
        store.save()

        path = self.root / "docs" / "rules.md"
        path.write_text(path.read_text().replace("per contract", "per client"), encoding="utf-8")
        claims = self.claims()
        store = core.Store(self.root)
        edited = next(c for c in claims if "measured per client" in c.text)
        self.assertEqual(core.status_of(edited, store), "proposed")
        self.assertEqual(len(core.gone(claims, store)), 1)

    def test_id_claim_reports_changed_not_gone(self):
        claims = self.claims()
        target = next(c for c in claims if c.claim_id == "DSP-9")
        store = core.Store(self.root)
        store.approve(target, by="human:test")
        store.save()

        path = self.root / "docs" / "rules.md"
        path.write_text(path.read_text().replace("counts as open", "counts as closed"), encoding="utf-8")
        claims = self.claims()
        changed = next(c for c in claims if c.claim_id == "DSP-9")
        self.assertEqual(core.status_of(changed, core.Store(self.root)), "changed")
        self.assertEqual(core.gone(claims, core.Store(self.root)), [])

    def test_to_validate_and_expiry(self):
        claims = self.claims()
        target = next(c for c in claims if "measured per contract" in c.text)
        store = core.Store(self.root)
        store.approve(target, by="human:test", validate="ask the owner", due="2026-10-15")
        self.assertEqual(core.status_of(target, store, today="2026-09-16"), "to-validate")
        self.assertEqual(core.status_of(target, store, today="2026-10-16"), "expired")

    def test_carry_keeps_the_original_date(self):
        claims = self.claims()
        target = next(c for c in claims if "measured per contract" in c.text)
        store = core.Store(self.root)
        store.approve(target, by="human:test", origin="stated", approved_at="2026-09-01")
        store.save()

        path = self.root / "docs" / "rules.md"
        path.write_text(path.read_text().replace("measured per contract",
                                                 "measured per contract, never per client"),
                        encoding="utf-8")
        claims = self.claims()
        reworded = next(c for c in claims if "never per client" in c.text)
        store = core.Store(self.root)
        rec = store.approve(reworded, by="human:test", carried_from=target.key)
        self.assertEqual(rec["approved_at"], "2026-09-01")
        self.assertEqual(rec["origin"], "stated")
        self.assertNotIn(target.key, store.records)

    def test_nothing_outside_km_is_written(self):
        before = {p: p.stat().st_mtime_ns for p in (self.root / "docs").rglob("*")}
        claims = self.claims()
        store = core.Store(self.root)
        store.approve(claims[0], by="human:test")
        store.save()
        after = {p: p.stat().st_mtime_ns for p in (self.root / "docs").rglob("*")}
        self.assertEqual(before, after)


class QuestionTest(unittest.TestCase):
    def test_checkbox_item_is_an_open_question(self):
        claims = core.scan(FIXTURE, core.DEFAULT_CONFIG)
        question = next(c for c in claims if "Confirm the monthly target" in c.text)
        self.assertTrue(question.is_question)
        self.assertFalse(any(c.is_question for c in claims if "per contract" in c.text))


class QueueOrderTest(unittest.TestCase):
    def claim(self, file: str, line: int) -> core.Claim:
        return core.Claim(key=f"{file}:{line}", kind="hash", claim_id=None, text="x",
                          text_hash="0", file=file, line=line, heading="")

    def test_risk_first_then_round_robin_between_documents(self):
        rows = [(2, "proposed", self.claim("a.md", i)) for i in range(1, 4)]
        rows += [(2, "proposed", self.claim("b.md", i)) for i in range(1, 3)]
        rows += [(0, "proposed", self.claim("c.md", 1))]
        ordered = core.order_queue(rows)
        self.assertEqual([r[2].file for r in ordered],
                         ["a.md", "b.md", "a.md", "b.md", "a.md", "c.md"])
        self.assertEqual([r[2].line for r in ordered if r[2].file == "a.md"], [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
