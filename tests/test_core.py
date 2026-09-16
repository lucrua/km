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


class IdentityTest(unittest.TestCase):
    """Same sentence in two documents must be two claims, or one approval covers both."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        docs = self.tmp / "docs"
        docs.mkdir()
        for name in ("a.md", "b.md"):
            (docs / name).write_text("# Decisão\n\n- **Descartado.**\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_boilerplate_in_two_files_does_not_share_a_key(self):
        claims = core.scan(self.tmp, core.DEFAULT_CONFIG)
        self.assertEqual(len(claims), 2)
        self.assertNotEqual(claims[0].key, claims[1].key)
        self.assertEqual(claims[0].text_hash, claims[1].text_hash)  # change detection is text-only

    def test_approving_one_leaves_the_other_proposed(self):
        claims = core.scan(self.tmp, core.DEFAULT_CONFIG)
        store = core.Store(self.tmp)
        store.approve(claims[0], by="human:test")
        store.save()
        store = core.Store(self.tmp)
        self.assertEqual(core.status_of(claims[0], store), "approved")
        self.assertEqual(core.status_of(claims[1], store), "proposed")


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

    def row(self, file: str, line: int, risk: int) -> core.QueueRow:
        return core.QueueRow(risk=risk, status="proposed", claim=self.claim(file, line))

    def test_risk_first_then_round_robin_between_documents(self):
        rows = [self.row("a.md", i, 2) for i in range(1, 4)]
        rows += [self.row("b.md", i, 2) for i in range(1, 3)]
        rows += [self.row("c.md", 1, 0)]
        ordered = core.order_queue(rows)
        self.assertEqual([r.claim.file for r in ordered],
                         ["a.md", "b.md", "a.md", "b.md", "a.md", "c.md"])
        self.assertEqual([r.claim.line for r in ordered if r.claim.file == "a.md"], [1, 2, 3])


class TriageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        shutil.copytree(FIXTURE, self.tmp / "docs")
        self.claims = core.scan(self.tmp, core.DEFAULT_CONFIG)
        self.store = core.Store(self.tmp)
        self.target = next(c for c in self.claims if "per contract" in c.text)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _triage(self, kind: str, text_hash: str | None = None, risk: int = 0) -> core.KeyedLog:
        log = core.KeyedLog(self.tmp, core.TRIAGE)
        log.put(self.target.key, kind=kind, risk=risk,
                text_hash=text_hash or self.target.text_hash)
        return log

    def _queue(self, triage, **kw):
        return core.build_queue(self.claims, self.store, core.DEFAULT_CONFIG, {"proposed"},
                                triage=triage, sample_every=0, **kw)

    def test_a_kind_other_than_norma_leaves_the_default_queue(self):
        rows = self._queue(self._triage("procedencia"))
        self.assertNotIn(self.target.key, [r.claim.key for r in rows])

    def test_the_hidden_kind_is_still_reachable_on_purpose(self):
        rows = self._queue(self._triage("procedencia"), kinds={"procedencia"})
        self.assertIn(self.target.key, [r.claim.key for r in rows])

    def test_stale_triage_is_no_triage(self):
        rows = self._queue(self._triage("procedencia", text_hash="deadbeef"))
        row = next(r for r in rows if r.claim.key == self.target.key)
        self.assertEqual(row.kind, "?")

    def test_triage_can_only_hide_and_order_never_approve(self):
        triage = self._triage("norma", risk=5)
        rows = self._queue(triage)
        row = next(r for r in rows if r.claim.key == self.target.key)
        self.assertEqual(row.risk, 5)
        self.assertEqual(row.status, "proposed")
        self.assertEqual(core.status_of(self.target, self.store), "proposed")

    def test_sampling_brings_hidden_claims_back_for_checking(self):
        triage = self._triage("procedencia")
        rows = core.build_queue(self.claims, self.store, core.DEFAULT_CONFIG, {"proposed"},
                                triage=triage, sample_every=1)
        row = next(r for r in rows if r.claim.key == self.target.key)
        self.assertTrue(row.sampled)


class DeferralTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        shutil.copytree(FIXTURE, self.tmp / "docs")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_deferred_claim_hides_until_the_date(self):
        claims = core.scan(self.tmp, core.DEFAULT_CONFIG)
        store = core.Store(self.tmp)
        target = next(c for c in claims if "per contract" in c.text)
        deferrals = core.KeyedLog(self.tmp, core.DEFERRALS)
        deferrals.put(target.key, until="2026-10-01")

        hidden = core.build_queue(claims, store, core.DEFAULT_CONFIG, {"proposed"},
                                  deferrals, today="2026-09-16")
        self.assertNotIn(target.key, [r.claim.key for r in hidden])

        back = core.build_queue(claims, store, core.DEFAULT_CONFIG, {"proposed"},
                                deferrals, today="2026-10-02")
        self.assertIn(target.key, [r.claim.key for r in back])

    def test_questions_never_enter_the_queue(self):
        claims = core.scan(self.tmp, core.DEFAULT_CONFIG)
        rows = core.build_queue(claims, core.Store(self.tmp), core.DEFAULT_CONFIG, {"proposed"})
        self.assertFalse(any(r.claim.is_question for r in rows))

    def test_undo_removes_the_approval(self):
        claims = core.scan(self.tmp, core.DEFAULT_CONFIG)
        store = core.Store(self.tmp)
        target = next(c for c in claims if "per contract" in c.text)
        store.approve(target, by="human:test")
        store.save()
        self.assertEqual(core.status_of(target, store), "approved")
        store.unapprove(target.key)
        store.save()
        self.assertEqual(core.status_of(target, core.Store(self.tmp)), "proposed")


class ConflictCandidateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        docs = self.tmp / "docs"
        docs.mkdir()
        (docs / "rules.md").write_text(
            "# Disponibilidade\n\n"
            "- A disponibilidade é medida por contrato, nunca pela soma dos clientes.\n"
            "- A disponibilidade é medida pela soma dos clientes de cada contrato.\n"
            "- O relatório mensal usa fuso de Brasília para fechar a janela.\n"
            "- **Changelog** — 2026-09-15: entrou a janela mensal, saiu o rascunho do "
            "catálogo, o glossário passou a valer, o gráfico mudou de escala, a exportação "
            "ganhou cabeçalho, a disponibilidade virou seção própria e o rodapé sumiu.\n",
            encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_pairs_only_against_settled_claims(self):
        claims = core.scan(self.tmp, core.DEFAULT_CONFIG)
        store = core.Store(self.tmp)
        self.assertEqual(core.candidate_pairs(claims, store), [])  # nothing settled yet

        first = next(c for c in claims if "nunca pela soma" in c.text)
        store.approve(first, by="human:test")
        store.save()

        pairs = core.candidate_pairs(claims, core.Store(self.tmp))
        self.assertTrue(pairs)
        self.assertTrue(all(p["against"] == first.key for p in pairs))
        top = pairs[0]
        self.assertIn("soma", top["shared"])
        self.assertIn("disponibilidade", top["text"].lower())

    def test_unrelated_claim_is_not_a_candidate(self):
        claims = core.scan(self.tmp, core.DEFAULT_CONFIG)
        store = core.Store(self.tmp)
        first = next(c for c in claims if "nunca pela soma" in c.text)
        store.approve(first, by="human:test")
        store.save()
        pairs = core.candidate_pairs(claims, core.Store(self.tmp))
        unrelated = next(c for c in claims if "Brasília" in c.text)
        self.assertNotIn(unrelated.key, [p["key"] for p in pairs])

    def test_triaged_non_norms_are_not_compared(self):
        """Measured: decision headers ("Data: … Estado: ativa") paired with each other."""
        claims = core.scan(self.tmp, core.DEFAULT_CONFIG)
        store = core.Store(self.tmp)
        anchor = next(c for c in claims if "nunca pela soma" in c.text)
        store.approve(anchor, by="human:test")
        store.save()
        other = next(c for c in claims if "soma dos clientes de cada contrato" in c.text)

        store = core.Store(self.tmp)
        self.assertIn(other.key, [p["key"] for p in core.candidate_pairs(claims, store)])

        triage = core.KeyedLog(self.tmp, core.TRIAGE)
        triage.put(other.key, kind="contexto", risk=0, text_hash=other.text_hash)
        pairs = core.candidate_pairs(claims, store, triage=triage)
        self.assertNotIn(other.key, [p["key"] for p in pairs])

    def test_a_long_paragraph_does_not_match_everything(self):
        """Measured on the real repository: a changelog line topped the ranking by sheer size."""
        claims = core.scan(self.tmp, core.DEFAULT_CONFIG)
        store = core.Store(self.tmp)
        first = next(c for c in claims if "nunca pela soma" in c.text)
        store.approve(first, by="human:test")
        store.save()
        pairs = core.candidate_pairs(claims, core.Store(self.tmp))
        changelog = next(c for c in claims if c.text.startswith("**Changelog**"))
        self.assertNotIn(changelog.key, [p["key"] for p in pairs])

    def test_numbers_alone_never_make_a_pair(self):
        docs = self.tmp / "docs"
        (docs / "numbers.md").write_text(
            "# Números\n\n"
            "- O painel mostra 8 colunas e 1 rodapé, com 7 filtros e 0 gráficos.\n",
            encoding="utf-8")
        claims = core.scan(self.tmp, core.DEFAULT_CONFIG)
        store = core.Store(self.tmp)
        anchor = next(c for c in claims if "soma dos clientes de cada contrato" in c.text)
        store.approve(anchor, by="human:test")
        store.save()
        pairs = core.candidate_pairs(claims, core.Store(self.tmp))
        numeric = next(c for c in claims if "8 colunas" in c.text)
        self.assertNotIn(numeric.key, [p["key"] for p in pairs])


class ServeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        shutil.copytree(FIXTURE, self.tmp / "docs")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_state_and_actions_write_only_inside_km(self):
        from km import serve

        state = serve._state(self.tmp)
        self.assertGreater(state["queue"], 0)
        self.assertEqual(state["approved"], 0)

        before = {p: p.stat().st_mtime_ns for p in (self.tmp / "docs").rglob("*")}
        key = state["cards"][0]["key"]
        result = serve._act(self.tmp, "human:test", {"key": key, "action": "approve"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["state"]["approved"], 1)

        after = {p: p.stat().st_mtime_ns for p in (self.tmp / "docs").rglob("*")}
        self.assertEqual(before, after)
        self.assertTrue((self.tmp / core.KM_DIR / core.APPROVALS).exists())

    def test_discuss_returns_a_prompt_and_defer_hides_the_card(self):
        from km import serve

        key = serve._state(self.tmp)["cards"][0]["key"]
        result = serve._act(self.tmp, "human:test", {"key": key, "action": "discuss"})
        self.assertIn("proposta, não aprovada", result["prompt"])

        result = serve._act(self.tmp, "human:test", {"key": key, "action": "defer",
                                                     "until": "2099-01-01"})
        self.assertNotIn(key, [c["key"] for c in result["state"]["cards"]])

    def test_note_is_recorded_and_the_claim_stays_proposed(self):
        from km import serve

        key = serve._state(self.tmp)["cards"][0]["key"]
        result = serve._act(self.tmp, "human:test",
                            {"key": key, "action": "note", "text": "a planilha está em $CH_DATA_DIR"})
        self.assertTrue(result["ok"])
        card = next(c for c in result["state"]["cards"] if c["key"] == key)
        self.assertEqual(card["status"], "proposed")
        self.assertIn("a planilha está em $CH_DATA_DIR", card["notes"])
        self.assertEqual(result["state"]["approved"], 0)

    def test_not_a_claim_leaves_the_queue_and_undo_brings_it_back(self):
        from km import serve

        key = serve._state(self.tmp)["cards"][0]["key"]
        result = serve._act(self.tmp, "human:test", {"key": key, "action": "ignore"})
        self.assertNotIn(key, [c["key"] for c in result["state"]["cards"]])
        result = serve._act(self.tmp, "human:test", {"key": key, "action": "undo"})
        self.assertIn(key, [c["key"] for c in result["state"]["cards"]])

    def test_card_carries_its_section(self):
        from km import serve

        card = serve._state(self.tmp)["cards"][0]
        self.assertTrue(any(s["target"] for s in card["siblings"]))
        self.assertIn("pending_in_section", card)

    def test_approving_a_section_marks_the_others_as_a_lot(self):
        from km import serve

        state = serve._state(self.tmp)
        card = next(c for c in state["cards"] if c["pending_in_section"] > 0)
        result = serve._act(self.tmp, "human:test",
                            {"key": card["key"], "action": "approve_section"})
        self.assertTrue(result["ok"])
        store = core.Store(self.tmp)
        approved = [rec for rec in store.records.values()]
        self.assertGreater(len(approved), 1)
        self.assertEqual(sum(1 for rec in approved if not rec.get("lot")), 1)

    def test_card_carries_the_neighbouring_lines(self):
        from km import serve

        cards = serve._state(self.tmp)["cards"]
        card = next(c for c in cards if "per contract" in c["text"])
        self.assertTrue(card["before"] or card["after"])
        self.assertTrue(all(isinstance(x, str) for x in card["before"] + card["after"]))

    def test_unknown_claim_is_reported_not_crashed(self):
        from km import serve

        result = serve._act(self.tmp, "human:test", {"key": "h:deadbeef", "action": "approve"})
        self.assertIn("not found", result["error"])


if __name__ == "__main__":
    unittest.main()
