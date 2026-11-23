"""Proponer no modifica tarjetas; sólo una decisión humana puede hacerlo."""

from __future__ import annotations

import sqlite3
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import ai, db, experiments, jobs, vocab_audit  # noqa: E402


def answer(**extra):
    return {"pos": "noun", "gloss_es": "cabaña",
            "definition_en": "a small wooden house in the countryside",
            "note_es": "No confundir con una cabina.", "imageable": True,
            "second": None, **extra}


SECOND = {"gloss_es": "cabina", "example_en": "The cabin of the plane was full.",
          "example_es": "La cabina del avión estaba llena."}


class FakeProvider:
    def __init__(self, *answers):
        self.answers = iter(answers)
        self.prompts = []

    def generate_json(self, system, prompt, schema):
        self.prompts.append(prompt)
        result = next(self.answers)
        if isinstance(result, Exception):
            raise result
        return result


class AuditCase(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.addCleanup(self.conn.close)
        # E1 se prueba en test_experiments; aquí toda palabra va a «repair».
        arm = mock.patch.object(experiments, "arm", return_value="repair")
        arm.start()
        self.addCleanup(arm.stop)

    def word(self, word="cabin", **extra):
        active = extra.pop("active", True)
        difficulty = extra.pop("difficulty", 5)
        seen = extra.pop("seen_in_text", None)
        wid = db.upsert_word(self.conn, {
            "word": word, "meaning_es": "Cabina", "meaning_en": None,
            "example_en": "They stayed in a cabin in the mountains.",
            "example_es": "Se quedaron en la cabaña de la montaña.",
            "lapses": 1, **extra})
        self.conn.execute(
            "UPDATE words SET fsrs_card=?, seen_in_text=?, difficulty=? WHERE id=?",
            ("{}" if active else None, seen, difficulty, wid))
        self.conn.commit()
        return wid

    def sense(self, wid, position=1, status="proposed", **extra):
        values = {"word_id": wid, "position": position, "status": status,
                  "gloss_es": "cabaña", "definition_en": answer()["definition_en"],
                  "created_at": db.now_iso(), **extra}
        cur = self.conn.execute(
            f"INSERT INTO senses ({', '.join(values)}) "
            f"VALUES ({', '.join('?' for _ in values)})", list(values.values()))
        self.conn.commit()
        return cur.lastrowid

    def stored_word(self, wid):
        return dict(self.conn.execute("SELECT * FROM words WHERE id=?", (wid,)).fetchone())

    def stored_sense(self, sid):
        return dict(self.conn.execute("SELECT * FROM senses WHERE id=?", (sid,)).fetchone())

    def propose(self, *answers, limit=20):
        fake = FakeProvider(*answers)
        with mock.patch.object(ai, "get_provider", return_value=fake) as provider:
            result = vocab_audit.propose(self.conn, limit)
        provider.assert_called_once_with("vocab_audit")
        return result, fake


class TestFlags(unittest.TestCase):
    def test_examples_from_the_deck(self):
        for gloss, example, mismatch in (
                ("Miedo", "Temo la posibilidad…", True),
                ("Cabina", "…la cabaña de la montaña…", True),
                ("Comerciante", "El comerciante estaba…", False),
                ("Unirse", "Las mujeres se unieron…", False),
                ("Morir De Hambre", "…murieron de hambre…", False),
                ("Avergonzado", "Se avergonzó cuando olvidó…", False),
                ("ÁRBOL", "El árbol crece aquí.", False)):
            with self.subTest(gloss=gloss):
                found = vocab_audit.flags({"meaning_es": gloss, "example_es": example,
                                          "meaning_en": "a valid definition"})
                self.assertEqual("gloss_not_in_example" in found, mismatch)
                self.assertNotIn("no_gloss", found)
                self.assertNotIn("no_definition", found)

    def test_missing_and_blank_fields(self):
        for empty in (None, "", "  "):
            self.assertEqual(vocab_audit.flags({"meaning_es": empty, "meaning_en": empty}),
                             ["no_gloss", "no_definition"])
        self.assertEqual(vocab_audit.flags({"meaning_es": "cabaña"}), ["no_definition"])

    def test_short_tokens_do_not_match(self):
        found = vocab_audit.flags({"meaning_es": "De Miedo", "example_es": "De pronto temió."})
        self.assertIn("gloss_not_in_example", found)


class TestCandidates(AuditCase):
    def test_filters_and_priority(self):
        self.word("inactive", active=False, lapses=99)
        self.word("definition_only", meaning_es="cabaña", lapses=99)
        self.word("no_example", example_en=" ")
        self.word("null_example", example_en=None)
        for status in ("proposed", "accepted", "rejected"):
            wid = self.word(status, lapses=99)
            self.sense(wid, status=status)
        # Incluso una segunda acepción aislada significa que ya se auditó.
        self.sense(self.word("second_only"), position=2)
        low = self.word("low", lapses=1, difficulty=10)
        middle = self.word("middle", lapses=4, difficulty=2)
        high = self.word("high", lapses=4, difficulty=8, active=False,
                         seen_in_text=db.now_iso(), meaning_es=None)
        self.assertEqual([r["id"] for r in vocab_audit.candidates(self.conn)],
                         [high, middle, low])
        self.assertEqual([r["id"] for r in vocab_audit.candidates(self.conn, 1)], [high])
        self.assertEqual(vocab_audit.candidates(self.conn, 0), [])


class TestPropose(AuditCase):
    def test_proposes_without_changing_the_card_and_queue_joins_context(self):
        wid = self.word()
        before = self.stored_word(wid)
        result, fake = self.propose(answer())
        self.assertEqual(result, {"proposed": 1, "skipped": []})
        self.assertEqual(self.stored_word(wid), before)
        queue = vocab_audit.queue(self.conn)
        self.assertEqual(queue["candidates"], 0)
        item, = queue["proposed"]
        self.assertEqual(item, {
            "id": item["id"], "word_id": wid, "word": "cabin", "current_gloss": "Cabina",
            "example_en": before["example_en"], "example_es": before["example_es"],
            "flags": ["gloss_not_in_example", "no_definition"], "pos": "noun",
            "gloss_es": "cabaña", "definition_en": answer()["definition_en"],
            "note_es": answer()["note_es"], "imageable": True, "second": None})
        stored = self.stored_sense(item["id"])
        self.assertEqual(stored["status"], "proposed")
        self.assertIsNone(stored["example_en"])
        self.assertIsNone(stored["example_es"])
        self.assertEqual(json.loads(stored["flags"]), item["flags"])
        self.assertIn(before["example_es"], fake.prompts[0])
        self.assertEqual(self.propose()[0], {"proposed": 0, "skipped": []})

    def test_retries_with_the_failed_rule(self):
        self.word()
        result, fake = self.propose(answer(gloss_es="choza"), answer())
        self.assertEqual(result["proposed"], 1)
        self.assertEqual(len(fake.prompts), 2)
        self.assertIn("gloss_not_in_example", fake.prompts[1])
        self.assertIn("choza", fake.prompts[1])

    def test_a_conjugated_verb_gloss_is_sent_back(self):
        """La regla del ejemplo no puede premiar «maldijo» sobre «maldecir»."""
        self.word("curse", meaning_es="Hechizo", example_en="The witch cursed the town.",
                  example_es="La bruja maldijo el pueblo.")
        result, fake = self.propose(
            answer(pos="verb", gloss_es="maldijo",
                   definition_en="to wish evil on someone with magic words"),
            answer(pos="verb", gloss_es="maldecir",
                   definition_en="to wish evil on someone with magic words"),
            answer(pos="verb", gloss_es="maldecir",
                   definition_en="to wish evil on someone with magic words"))
        self.assertEqual(result["proposed"], 0)
        self.assertIn("infinitivo", fake.prompts[1])
        self.assertEqual(result["skipped"][0][0], "curse")

    def test_three_failures_skip_one_word_and_continue(self):
        first = self.word()
        self.word("hut", lapses=0)
        result, fake = self.propose(*(3 * [answer(gloss_es="choza")]), answer())
        self.assertEqual(len(fake.prompts), 4)
        self.assertEqual(result["proposed"], 1)
        self.assertEqual(result["skipped"][0][0], "cabin")
        self.assertIn("gloss_not_in_example", result["skipped"][0][1])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM senses WHERE word_id=?",
                                           (first,)).fetchone()[0], 0)
        self.assertEqual(vocab_audit.queue(self.conn)["candidates"], 1)

    def test_provider_error_does_not_abort_the_batch(self):
        self.word()
        self.word("hut", lapses=0)
        result, _ = self.propose(RuntimeError("sin servicio"), answer())
        self.assertEqual(result["proposed"], 1)
        self.assertIn("sin servicio", result["skipped"][0][1])

    def test_valid_second_creates_a_sibling(self):
        self.word()
        result, _ = self.propose(answer(second=SECOND))
        self.assertEqual(result["proposed"], 1)
        rows = self.conn.execute("SELECT * FROM senses ORDER BY position").fetchall()
        self.assertEqual([r["position"] for r in rows], [1, 2])
        self.assertTrue(all(r["status"] == "proposed" for r in rows))
        self.assertEqual(rows[0]["word_id"], rows[1]["word_id"])
        self.assertEqual(vocab_audit.queue(self.conn)["proposed"][0]["second"], SECOND)

    def test_each_validation_failure_can_be_corrected(self):
        self.word()
        for bad, reason in (
                ({"gloss_es": ""}, "gloss_es vacía"),
                ({"gloss_es": "una cabaña en una montaña"}, "máximo 4"),
                ({"definition_en": "a cabin in the woods"}, "propia palabra"),
                ({"definition_en": "house"}, "demasiado corta"),
                ({"pos": "substantive"}, "pos"),
                ({"imageable": "true"}, "booleano"),
                ({"second": {}}, "second necesita"),
                ({"second": {**SECOND, "example_es": ""}}, "second necesita"),
                ({"second": {**SECOND, "example_en": "The plane was full."}}, "raíz"),
                # Casos reales: «nowhere» → «no se encontraba», «pat» → «dar un poco»,
                # «defeat» con un segundo sentido que su ejemplo no usa.
                ({"gloss_es": "se quedaron"}, "forma de diccionario"),
                ({"pos": "verb", "gloss_es": "quedarse un poco"}, "relleno"),
                ({"second": {**SECOND, "gloss_es": "choza"}}, "second.gloss_es no aparece")):
            with self.subTest(bad=bad):
                result, fake = self.propose(answer(**bad), answer())
                self.assertEqual(result["proposed"], 1)
                self.assertIn(reason, fake.prompts[1])
                self.conn.execute("DELETE FROM senses")
                self.conn.commit()

    def test_missing_translation_and_derived_second_are_allowed(self):
        self.word(example_es=None, meaning_es=None)
        result, _ = self.propose(answer(second={**SECOND, "example_en": "The cabins were full."}))
        self.assertEqual(result["proposed"], 1)

    def test_limit_counts_words(self):
        self.word()
        self.word("hut")
        result, fake = self.propose(answer(), limit=1)
        self.assertEqual(result["proposed"], 1)
        self.assertEqual(len(fake.prompts), 1)
        self.assertEqual(vocab_audit.queue(self.conn)["candidates"], 1)


class TestDecide(AuditCase):
    def test_accept_snapshots_current_values_and_revert_restores_exactly(self):
        wid = self.word(meaning_en="an old definition")
        sid = self.sense(wid)
        sibling = self.sense(wid, position=2)
        # La copia se toma al aceptar, aunque la tarjeta cambie desde la propuesta.
        self.conn.execute("UPDATE words SET meaning_es='  Cabina  ' WHERE id=?", (wid,))
        self.conn.commit()
        result = vocab_audit.decide(self.conn, sid, "accept")
        self.assertEqual(result, {"id": sid, "word_id": wid, "status": "accepted"})
        self.assertEqual(self.stored_word(wid)["meaning_es"], "cabaña")
        self.assertEqual(self.stored_word(wid)["meaning_en"], answer()["definition_en"])
        stored = self.stored_sense(sid)
        self.assertEqual(stored["old_meaning_es"], "  Cabina  ")
        self.assertEqual(stored["old_meaning_en"], "an old definition")
        self.assertIsNotNone(stored["decided_at"])
        self.assertEqual(self.stored_sense(sibling)["status"], "accepted")
        vocab_audit.decide(self.conn, sid, "revert")
        self.assertEqual(self.stored_word(wid)["meaning_es"], "  Cabina  ")
        self.assertEqual(self.stored_word(wid)["meaning_en"], "an old definition")
        self.assertEqual(self.stored_sense(sid)["status"], "rejected")
        self.assertEqual(self.stored_sense(sibling)["status"], "rejected")

    def test_human_edits_need_not_match_the_example(self):
        wid = self.word()
        sid = self.sense(wid)
        definition = "a small house made of wood"
        vocab_audit.decide(self.conn, sid, "accept", "choza", definition)
        self.assertEqual(self.stored_word(wid)["meaning_es"], "choza")
        self.assertEqual(self.stored_sense(sid)["gloss_es"], "choza")
        self.assertEqual(self.stored_word(wid)["meaning_en"], definition)

    def test_nulls_restore_and_absent_definition_preserves_the_word(self):
        for old in (None, "", "an old definition"):
            with self.subTest(old=old):
                wid = self.word(f"word-{old}", meaning_es=None, meaning_en=old)
                sid = self.sense(wid, definition_en=None)
                vocab_audit.decide(self.conn, sid, "accept")
                self.assertEqual(self.stored_word(wid)["meaning_en"], old)
                vocab_audit.decide(self.conn, sid, "revert")
                self.assertIsNone(self.stored_word(wid)["meaning_es"])
                self.assertEqual(self.stored_word(wid)["meaning_en"], old)

    def test_reject_leaves_words_untouched_and_removes_both_from_queue(self):
        wid = self.word()
        sid, sibling = self.sense(wid), self.sense(wid, position=2)
        before = self.stored_word(wid)
        vocab_audit.decide(self.conn, sid, "reject")
        self.assertEqual(self.stored_word(wid), before)
        self.assertEqual(self.stored_sense(sibling)["status"], "rejected")
        self.assertEqual(vocab_audit.queue(self.conn), {"candidates": 0, "proposed": []})

    def test_invalid_transitions_and_unknown_ids(self):
        sid = self.sense(self.word())
        for action in ("revert", "unknown"):
            with self.assertRaises(ValueError):
                vocab_audit.decide(self.conn, sid, action)
        with self.assertRaises(vocab_audit.SenseNotFound):
            vocab_audit.decide(self.conn, 99999, "accept")
        vocab_audit.decide(self.conn, sid, "accept")
        for action in ("accept", "reject"):
            with self.assertRaises(ValueError):
                vocab_audit.decide(self.conn, sid, action)
        vocab_audit.decide(self.conn, sid, "revert")
        for action in ("accept", "reject", "revert"):
            with self.assertRaises(ValueError):
                vocab_audit.decide(self.conn, sid, action)

    def test_invalid_edits_and_secondary_decisions_do_not_mutate(self):
        wid = self.word()
        sid = self.sense(wid)
        sibling = self.sense(wid, position=2)
        before = self.stored_word(wid)
        for edit in ({"gloss_es": " "}, {"gloss_es": "una casa de madera pequeña"},
                     {"definition_en": "cabin"}, {"definition_en": ""}):
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                vocab_audit.decide(self.conn, sid, "accept", **edit)
            self.assertEqual(self.stored_word(wid), before)
            self.assertEqual(self.stored_sense(sid)["status"], "proposed")
        with self.assertRaises(ValueError):
            vocab_audit.decide(self.conn, sibling, "accept")

    def test_failure_rolls_back_word_snapshot_and_sibling_together(self):
        wid = self.word()
        sid, sibling = self.sense(wid), self.sense(wid, position=2)
        before = self.stored_word(wid)
        self.conn.execute(
            "CREATE TRIGGER fail_sibling BEFORE UPDATE OF status ON senses "
            "WHEN OLD.position=2 BEGIN SELECT RAISE(ABORT, 'fallo simulado'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            vocab_audit.decide(self.conn, sid, "accept")
        self.assertEqual(self.stored_word(wid), before)
        self.assertIsNone(self.stored_sense(sid)["old_meaning_es"])
        self.assertEqual(self.stored_sense(sid)["status"], "proposed")
        self.assertEqual(self.stored_sense(sibling)["status"], "proposed")


class TestRoutes(AuditCase):
    def setUp(self):
        import sqlite3
        from fastapi.testclient import TestClient

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = str(Path(self.tmp.name) / "audit.db")
        env = mock.patch.dict(os.environ, {"ENGLISHOS_DOTENV": "0", "ENGLISH_DB_PATH": path})
        env.start()
        self.addCleanup(env.stop)
        from app import server
        worker = mock.patch.object(jobs, "ensure_worker")
        self.worker = worker.start()
        self.addCleanup(worker.stop)
        self.conn = db.connect(path)
        self.addCleanup(self.conn.close)
        self.client = TestClient(server.app)
        self.addCleanup(self.client.close)
        self.sid = self.sense(self.word())

    def test_invalid_edits_are_422_with_the_reason(self):
        for edit, reason in (({"gloss_es": " "}, "vacía"),
                             ({"definition_en": "cabin"}, "demasiado corta")):
            response = self.client.post(f"/api/vocab/audit/{self.sid}",
                                        json={"action": "accept", **edit})
            self.assertEqual(response.status_code, 422)
            self.assertIn(reason, response.json()["detail"])

    def test_unknown_id_is_404(self):
        response = self.client.post("/api/vocab/audit/99999", json={"action": "accept"})
        self.assertEqual(response.status_code, 404)

    def test_queue_accept_and_revert(self):
        response = self.client.get("/api/vocab/audit")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["proposed"][0]["id"], self.sid)
        for action, status in (("accept", "accepted"), ("revert", "rejected")):
            response = self.client.post(f"/api/vocab/audit/{self.sid}", json={"action": action})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], status)
        response = self.client.post(f"/api/vocab/audit/{self.sid}", json={"action": "accept"})
        self.assertEqual(response.status_code, 422)

    def test_propose_returns_a_job_and_validates_limits(self):
        for payload, limit in (({}, 20), ({"limit": 1}, 1), ({"limit": 50}, 50)):
            response = self.client.post("/api/vocab/audit/propose", json=payload)
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.json()["kind"], "vocab_audit")
            self.assertEqual(response.json()["params"], {"limit": limit})
            self.assertEqual(response.json()["status"], "queued")
        for limit in (0, -1, 51, 1.5):
            response = self.client.post("/api/vocab/audit/propose", json={"limit": limit})
            self.assertEqual(response.status_code, 422)
        self.assertEqual(self.worker.call_count, 3)


class TestWiring(AuditCase):
    def test_job_handler_passes_default_and_explicit_limits(self):
        for params, expected in (({}, 20), ({"limit": 3}, 3)):
            with mock.patch.object(vocab_audit, "propose", return_value={"proposed": 2}) as propose:
                result = jobs.HANDLERS["vocab_audit"](self.conn, params)
                propose.assert_called_once_with(self.conn, limit=expected)
                self.assertEqual(result, {"proposed": 2})
        self.assertIn("vocab_audit", jobs.KINDS)
        self.assertIn("vocab_audit", ai.GENERATE_TASKS)
        self.assertNotIn("vocab_audit", ai.LOCAL_ONLY_TASKS)

    def test_daily_generation_does_not_enqueue_an_audit(self):
        from app import generator
        with mock.patch.object(generator, "skip_reason", return_value=None):
            jobs.enqueue_daily(self.conn)
        self.assertNotIn("vocab_audit", [j["kind"] for j in jobs.recent(self.conn)])


if __name__ == "__main__":
    unittest.main()
