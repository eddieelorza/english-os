"""Recall usa memoria: ni el mazo real ni su scheduling participan."""

from __future__ import annotations

import os
import sqlite3
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest import mock

from fsrs import Card, State

from app import db, experiments, model, recall, srs


class TestGrade(unittest.TestCase):
    def test_grades(self):
        cases = [
            ("defeat", "defeat", None, ("correct", 3)),
            ("cafe", "  ¡CAFÉ!  ", None, ("correct", 3)),
            ("give up", " ‘GIVE   UP.’ ", None, ("correct", 3)),
            ("defeat", "defeet", None, ("close", 2)),
            ("defeat", "defiit", None, ("wrong", 1)),
            ("understand", "understent", None, ("close", 2)),
            ("defeated", "defeat", "defeat", ("close", 2)),
            ("defeat", "", None, ("wrong", 1)),
            ("defeat", "   ", None, ("wrong", 1)),
            ("cat", "bat", None, ("wrong", 1)),
            ("give up", "giveup", None, ("close", 2)),
            ("can't", "cant", None, ("close", 2)),
        ]
        for expected, given, lemma, result in cases:
            with self.subTest(expected=expected, given=given):
                self.assertEqual(recall.grade(expected, given, lemma), result)


class TestSurface(unittest.TestCase):
    def test_inflected(self):
        self.assertEqual(recall.surface("defeat", "The champion defeated the challenger"),
                         "defeated")

    def test_phrase(self):
        self.assertEqual(recall.surface("give up", "Never GIVE UP!"), "GIVE UP")
        self.assertIsNone(recall.surface("give up", "Forgive upcoming mistakes"))

    def test_absent(self):
        self.assertIsNone(recall.surface("defeat", "The champion won"))
        self.assertIsNone(recall.surface("defeat", "An undefeated champion"))

    def test_case_and_accents(self):
        self.assertEqual(recall.surface("café", "A CAFE nearby"), "CAFE")


class TestChoose(unittest.TestCase):
    def test_new_and_unstable_step_down(self):
        for stability, wrong, reps in ((20, False, 0), (2, False, 5), (20, True, 5)):
            with self.subTest(stability=stability, wrong=wrong, reps=reps):
                self.assertEqual(recall.choose({"cloze", "meaning", "image"},
                                               stability, wrong, [], reps), "cloze")

    def test_stable(self):
        self.assertEqual(recall.choose({"cloze", "meaning"}, 7, False, [], 4), "meaning")

    def test_image_cadence_and_availability(self):
        for reps, expected in ((1, "meaning"), (2, "meaning"), (3, "image"),
                               (4, "meaning"), (6, "image")):
            self.assertEqual(recall.choose({"cloze", "meaning", "image"},
                                           7, False, [], reps), expected)
        self.assertEqual(recall.choose({"cloze", "meaning"}, 7, False, [], 3), "meaning")

    def test_no_three_in_a_row(self):
        self.assertEqual(recall.choose({"cloze", "meaning"}, 1, True,
                                       ["cloze", "cloze"], 2), "meaning")
        self.assertEqual(recall.choose({"cloze", "meaning", "image"}, 7, False,
                                       ["meaning", "meaning"], 4), "cloze")
        self.assertEqual(recall.choose({"cloze", "meaning", "image"}, 7, False,
                                       ["image", "image"], 6), "meaning")
        self.assertEqual(recall.choose({"meaning"}, 7, False,
                                       ["meaning", "meaning"], 4), "meaning")


class RecallCase(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.now = datetime(2026, 11, 22, 12).astimezone(timezone.utc)
        rollover = mock.patch.object(db, "rollover_hour", return_value=4)
        rollover.start()
        self.addCleanup(rollover.stop)
        # E2 se prueba en test_experiments; aquí toda palabra entra a Recall.
        arm = mock.patch.object(experiments, "arm", return_value="recall")
        arm.start()
        self.addCleanup(arm.stop)

    def word(self, text="defeat", stability=8, state="REVIEW", **fields):
        wid = db.upsert_word(self.conn, {
            "word": text, "meaning_es": "derrotar", "meaning_en": "to win against someone",
            "example_en": "The champion defeated the challenger", "example_es": "El campeón ganó",
            **fields,
        })
        self.conn.execute(
            "UPDATE words SET card_state=?, stability=?, fsrs_card=?, fsrs_due=? WHERE id=?",
            (state, stability, Card().to_json(), self.now.isoformat(), wid))
        self.conn.commit()
        return wid

    def sense(self, wid, status="accepted", position=1, imageable=1):
        self.conn.execute(
            "INSERT INTO senses(word_id, status, position, imageable, pos, gloss_es, created_at) "
            "VALUES(?, ?, ?, ?, 'verb', 'derrotar', ?)",
            (wid, status, position, imageable, db.now_iso()))
        self.conn.commit()

    def stored_card(self, wid):
        return self.conn.execute(
            "SELECT * FROM cards WHERE word_id=? AND track='productive'", (wid,)).fetchone()

    def answer(self, wid, exercise="meaning", given="defeat", now=None):
        return recall.answer(self.conn, wid, exercise, given, now or self.now)


class TestNextItem(RecallCase):
    def test_variety_is_measured_across_the_sitting(self):
        """Dos cloze seguidos de palabras distintas: la tercera no es cloze."""
        for text in ("defeat", "defeats"):
            self.answer(self.word(text, stability=20), "cloze", "defeated")
        self.word("defeater", stability=9)
        self.assertEqual(recall.next_item(self.conn, self.now)["item"]["exercise"], "meaning")

    def test_eligibility_and_order(self):
        self.word("weak", stability=6.99)
        self.word("learning", stability=100, state="LEARNING")
        self.word("no gloss", stability=100, meaning_es=" ")
        self.word("no example", stability=100, example_en=None)
        first = self.word("first", stability=10)
        second = self.word("second", stability=10)
        highest = self.word("highest", stability=20)
        self.assertEqual(recall.next_item(self.conn, self.now)["item"]["word_id"], highest)
        self.answer(highest, given="highest")
        self.assertEqual(recall.next_item(self.conn, self.now)["item"]["word_id"], first)
        self.answer(first, given="first")
        self.assertEqual(recall.next_item(self.conn, self.now)["item"]["word_id"], second)
        self.answer(second, given="second")
        self.assertIsNone(recall.next_item(self.conn, self.now)["item"])

    def test_due_before_new_and_oldest_first(self):
        oldest = self.word("oldest")
        newer = self.word("newer")
        self.answer(oldest, given="oldest", now=self.now - timedelta(days=2))
        self.answer(newer, given="newer", now=self.now - timedelta(days=1))
        self.word("strongest", stability=100)
        result = recall.next_item(self.conn, self.now)
        self.assertEqual(result["due"], 2)
        self.assertEqual(result["item"]["word_id"], oldest)
        self.assertEqual(result["item"]["card_id"], self.stored_card(oldest)["id"])
        self.assertFalse(result["item"]["is_new"])

    def test_cap_and_rollover(self):
        before = datetime(2026, 11, 22, 3, 59).astimezone(timezone.utc)
        for i in range(5):
            wid = self.word(f"word {i}")
            self.answer(wid, given=f"word {i}", now=before)
        extra = self.word("extra")
        result = recall.next_item(self.conn, before)
        self.assertEqual(result["new_left"], 0)
        self.assertIsNone(result["item"])
        with self.assertRaisesRegex(ValueError, "cupo"):
            self.answer(extra, given="extra", now=before)
        after = before + timedelta(minutes=1)
        result = recall.next_item(self.conn, after)
        self.assertEqual(result["new_left"], 5)
        self.assertEqual(result["item"]["word_id"], extra)
        self.answer(extra, given="extra", now=after)
        self.assertEqual(recall.next_item(self.conn, after)["new_left"], 4)
        self.assertEqual(recall.next_item(self.conn, before)["new_left"], 0)

    def test_payload_does_not_disclose_answer(self):
        self.word(example_en="They defeated him; she defeated them too.")
        item = recall.next_item(self.conn, self.now)["item"]
        self.assertEqual(item, {
            "word_id": 1, "card_id": None, "exercise": "cloze", "is_new": True,
            "meaning_es": "derrotar", "definition_en": "to win against someone",
            "sentence": "They ____ him; she ____ them too.", "hint": "d·8",
            "translation": "El campeón ganó",
        })
        for forbidden in ("word", "expected", "answer", "example_en", "audio"):
            self.assertNotIn(forbidden, item)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0], 0)

    def test_meaning_without_cloze(self):
        self.word(example_en="The champion won", meaning_en="")
        item = recall.next_item(self.conn, self.now)["item"]
        self.assertEqual(item["exercise"], "meaning")
        self.assertIsNone(item["definition_en"])
        for field in ("sentence", "hint", "translation", "image"):
            self.assertNotIn(field, item)

    def test_choices_use_card_history(self):
        wid = self.word()
        self.answer(wid, "cloze", "defeated")
        self.answer(wid, "cloze", "defeated", self.now + timedelta(minutes=10))
        due = datetime.fromisoformat(self.stored_card(wid)["due"])
        self.assertEqual(recall.next_item(self.conn, due)["item"]["exercise"], "meaning")
        self.answer(wid, "meaning", "wrong", due)
        due = datetime.fromisoformat(self.stored_card(wid)["due"])
        self.assertEqual(recall.next_item(self.conn, due)["item"]["exercise"], "cloze")

    def test_other_tracks_do_not_consume_budget_or_block_eligibility(self):
        wid = self.word()
        self.answer(wid)
        self.conn.execute("UPDATE cards SET track='other'")
        self.conn.commit()
        result = recall.next_item(self.conn, self.now + timedelta(days=2))
        self.assertEqual(result["due"], 0)
        self.assertTrue(result["item"]["is_new"])
        self.assertEqual(recall.next_item(self.conn, self.now)["new_left"], 5)


class TestAnswer(RecallCase):
    def due(self, wid):
        return datetime.fromisoformat(self.stored_card(wid)["due"])

    def test_creates_and_updates_without_touching_receptive_word(self):
        wid = self.word(audio_word="word.mp3", image_path="word.jpg")
        before = dict(self.conn.execute("SELECT * FROM words WHERE id=?", (wid,)).fetchone())
        result = self.answer(wid, "cloze", "defeat")
        self.assertEqual((result["verdict"], result["rating"], result["expected"]),
                         ("close", 2, "defeated"))
        # Sin sentido aceptado `imageable`, la imagen no se muestra ni después.
        self.assertEqual((result["audio"], result["image"], result["new_left"]),
                         ("word.mp3", None, 4))
        self.assertIsInstance(result["interval"], str)
        self.assertEqual(result["due"], 0)
        card = self.stored_card(wid)
        self.assertEqual((card["reps"], card["lapses"]), (1, 0))
        self.assertEqual(Card.from_json(card["fsrs_card"]).due.isoformat(), card["due"])
        log = self.conn.execute("SELECT * FROM recall_log").fetchone()
        self.assertEqual((log["card_id"], log["answer"], log["expected"]),
                         (card["id"], "defeat", "defeated"))
        self.assertIsNone(log["stability_before"])
        self.assertEqual(log["stability_after"], card["stability"])
        self.assertIsNone(datetime.fromisoformat(log["reviewed_at"]).tzinfo)
        self.answer(wid, now=datetime.fromisoformat(card["due"]))
        updated = self.stored_card(wid)
        self.assertEqual((updated["id"], updated["reps"]), (card["id"], 2))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM recall_log").fetchone()[0], 2)
        self.assertEqual(dict(self.conn.execute("SELECT * FROM words WHERE id=?", (wid,)).fetchone()),
                         before)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM review_history").fetchone()[0], 0)
        self.assertFalse(self.conn.in_transaction)

    def test_image_after_the_attempt_only_for_concrete_words(self):
        wid = self.word(image_path="word.jpg")
        self.sense(wid)
        self.assertEqual(self.answer(wid, "cloze", "defeated")["image"], "word.jpg")

    def test_wrong_returns_soon_and_lapses_only_in_review(self):
        wid = self.word()
        result = self.answer(wid, given="")
        self.assertEqual((result["verdict"], result["rating"]), ("wrong", 1))
        self.assertLessEqual(self.due(wid) - self.now,
                             timedelta(minutes=10))
        self.assertEqual(self.stored_card(wid)["lapses"], 0)
        when = self.due(wid)
        for _ in range(2):
            result = self.answer(wid, now=when)
            when = self.due(wid)
        self.assertEqual(Card.from_json(self.stored_card(wid)["fsrs_card"]).state, State.Review)
        result = self.answer(wid, given="", now=when)
        self.assertEqual(self.stored_card(wid)["lapses"], 1)
        self.assertLessEqual(self.due(wid) - when, timedelta(minutes=10))

    def test_invalid_word_exercise_and_eligibility(self):
        wid = self.word(example_en="The champion won")
        weak = self.word("weak", stability=6)
        for word_id, exercise in ((999, "meaning"), (wid, "cloze"), (wid, "image"),
                                   (wid, "audio"), (weak, "meaning")):
            with self.subTest(word_id=word_id, exercise=exercise):
                with self.assertRaises(ValueError):
                    self.answer(word_id, exercise)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0], 0)

    def test_image_requires_accepted_primary_imageable_sense_and_path(self):
        wid = self.word(image_path="defeat.jpg")
        for status, position, imageable in (("proposed", 1, 1), ("accepted", 2, 1),
                                            ("accepted", 1, 0)):
            self.sense(wid, status, position, imageable)
            with self.assertRaises(ValueError):
                self.answer(wid, "image")
        self.sense(wid)
        for exercise in ("image", "cloze", "meaning"):
            card = self.stored_card(wid)
            self.answer(wid, exercise, given="defeated" if exercise == "cloze" else "defeat",
                        now=datetime.fromisoformat(card["due"]) if card else None)
        card = self.stored_card(wid)
        item = recall.next_item(self.conn, datetime.fromisoformat(card["due"]))["item"]
        self.assertEqual((item["exercise"], item["pos"], item["image"]),
                         ("image", "verb", "defeat.jpg"))
        self.conn.execute("UPDATE words SET image_path=NULL WHERE id=?", (wid,))
        self.conn.commit()
        with self.assertRaises(ValueError):
            self.answer(wid, "image")

    def test_existing_card_does_not_need_receptive_eligibility(self):
        wid = self.word()
        self.answer(wid)
        self.conn.execute("UPDATE words SET stability=1, card_state='RELEARNING' WHERE id=?", (wid,))
        self.conn.commit()
        self.assertEqual(self.answer(wid)["verdict"], "correct")

    def test_log_failure_rolls_back_card_creation_and_update(self):
        existing = self.word("existing")
        self.answer(existing, given="existing")
        new = self.word()
        before = dict(self.stored_card(existing))
        self.conn.execute(
            "CREATE TRIGGER fail_recall BEFORE INSERT ON recall_log "
            "BEGIN SELECT RAISE(ABORT, 'fallo simulado'); END")
        self.conn.commit()
        for wid in (new, existing):
            with self.assertRaises(sqlite3.IntegrityError):
                self.answer(wid)
        self.assertIsNone(self.stored_card(new))
        self.assertEqual(dict(self.stored_card(existing)), before)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM recall_log").fetchone()[0], 1)

    def test_uses_receptive_scheduler_settings(self):
        wid = self.word()
        with mock.patch.object(srs, "_scheduler", wraps=srs._scheduler) as scheduler:
            self.answer(wid)
        scheduler.assert_called_once_with(self.conn)


class TestRecallStreak(RecallCase):
    def test_only_recall_and_rollover(self):
        wid = self.word()
        with mock.patch.object(db, "study_day", return_value="2026-11-22"):
            self.assertEqual(model.streak(self.conn), 0)
        self.answer(wid, now=datetime(2026, 11, 22, 3, 59).astimezone(timezone.utc))
        with mock.patch.object(db, "study_day", return_value="2026-11-22"):
            self.assertEqual(model.streak(self.conn), 1)
        self.answer(wid, now=datetime(2026, 11, 22, 4).astimezone(timezone.utc))
        with mock.patch.object(db, "study_day", return_value="2026-11-22"):
            self.assertEqual(model.streak(self.conn), 2)


class TestRecallRoutes(RecallCase):
    def setUp(self):
        # TestClient atiende en otro hilo; la base sigue siendo sólo memoria.
        connect = sqlite3.connect
        with mock.patch.object(sqlite3, "connect", side_effect=lambda *a, **kw:
                               connect(*a, **kw, check_same_thread=False)):
            super().setUp()
        with mock.patch.dict(os.environ, {"ENGLISHOS_DOTENV": "0"}):
            from app import server
        from fastapi.testclient import TestClient

        @contextmanager
        def get_db():
            yield self.conn

        database = mock.patch.object(server, "get_db", get_db)
        database.start()
        self.addCleanup(database.stop)
        self.client = TestClient(server.app)
        self.addCleanup(self.client.close)
        self.wid = self.word()

    def test_200_shapes_and_empty_answer(self):
        response = self.client.get("/api/recall/next")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(set(data), {"item", "due", "new_left"})
        self.assertEqual(data["item"]["word_id"], self.wid)
        response = self.client.post("/api/recall/answer", json={
            "word_id": self.wid, "exercise": "cloze", "answer": "",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["verdict"], "wrong")
        self.assertEqual(set(response.json()), {
            "verdict", "rating", "expected", "word", "given", "example_en", "example_es",
            "meaning_es", "image", "audio", "interval_days", "interval", "due", "new_left",
        })

    def test_422_validation_and_domain_errors(self):
        for changes in ({"word_id": 999}, {"exercise": "image"}, {"exercise": "audio"},
                        {"answer": "a" * 81}, {"word_id": "invalid"}):
            with self.subTest(changes=changes):
                response = self.client.post("/api/recall/answer", json={
                    "word_id": self.wid, "exercise": "meaning", "answer": "defeat", **changes,
                })
                self.assertEqual(response.status_code, 422)
                self.assertTrue(response.json()["detail"])
        response = self.client.post("/api/recall/answer", json={
            "word_id": 999, "exercise": "meaning", "answer": "",
        })
        self.assertEqual(response.json()["detail"], "Palabra 999 no encontrada")


if __name__ == "__main__":
    unittest.main()
