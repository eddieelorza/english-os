"""MVP 3: la sesión del día se deduce de la base, sin estado propio."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import day, db, experiments, pause, recall, session, srs, writing  # noqa: E402

QUEUE = {"due": 0, "new_available": 0, "learning_now": 0, "reviewed_today": 0}
NOTHING = {"item": None, "due": 0, "new_left": 5}


class DayCase(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.addCleanup(self.conn.close)

    def plan(self, queue=None, nxt=None, progress=None):
        with mock.patch.object(srs, "queue", return_value={**QUEUE, **(queue or {})}), \
             mock.patch.object(recall, "next_item", return_value=nxt or NOTHING), \
             mock.patch.object(session, "active", return_value={"id": 1} if progress else None), \
             mock.patch.object(session, "progress", return_value=progress):
            return day.plan(self.conn)

    def reading(self, title, created, finished=None):
        self.conn.execute(
            "INSERT INTO texts (kind, title, body, date, created_at, updated_at, finished_at) "
            "VALUES ('reading', ?, 'body', ?, ?, ?, ?)",
            (title, created[:10], created, created, finished))
        self.conn.commit()

    def keys(self, p):
        return [(b["key"], b["done"]) for b in p["blocks"]]


class TestPlan(DayCase):
    def test_nothing_to_do_is_an_empty_session(self):
        self.assertEqual(self.plan(), {"paused": False, "blocks": [], "next": None})

    def test_order_and_next_is_the_first_undone_block(self):
        self.reading("old", "2026-08-01T10:00:00")
        self.reading("new", "2026-11-01T10:00:00")
        p = self.plan({"due": 3}, {"item": {"word_id": 1}, "due": 1, "new_left": 4})
        self.assertEqual(self.keys(p), [("review", False), ("recall", False), ("reading", False)])
        self.assertEqual(p["next"]["key"], "review")
        # La lectura propuesta es la más antigua, no una nueva.
        self.assertEqual(p["blocks"][2]["detail"], "old")

    def test_a_full_sitting_finishes_review_even_with_cards_left(self):
        p = self.plan({"due": 3, "reviewed_today": 10}, progress={"done": 10, "planned": 10})
        self.assertEqual(self.keys(p), [("review", True)])
        self.assertIsNone(p["next"])

    def test_an_open_sitting_with_work_left_is_not_done(self):
        p = self.plan({"due": 3}, progress={"done": 2, "planned": 10})
        self.assertEqual(self.keys(p), [("review", False)])

    def test_recall_is_done_when_nothing_is_left_after_answering(self):
        wid = db.upsert_word(self.conn, {"word": "x"})
        self.conn.execute(
            "INSERT INTO cards (id, word_id, fsrs_card, due, created_at) "
            "VALUES (1, ?, '{}', ?, ?)", (wid, db.now_iso(), db.now_iso()))
        self.conn.execute(
            "INSERT INTO recall_log (card_id, word_id, reviewed_at, exercise, expected, "
            "answer, verdict, rating) VALUES (1, ?, ?, 'meaning', 'x', 'x', 'correct', 3)",
            (wid, db.now_iso()))
        self.conn.commit()
        p = self.plan()
        # La palabra recién recordada pasa a la micro-producción.
        self.assertEqual(self.keys(p), [("recall", True), ("write", False)])
        self.assertEqual(p["blocks"][0]["detail"], "1 recalled today")
        self.assertEqual(p["next"]["key"], "write")
        self.assertEqual(writing.micro(self.conn)["steps"][0]["word"], "x")

        db.upsert_text(self.conn, {"kind": "writing", "title": "Micro: x…",
                                   "date": db.study_day(), "body": "I x."})
        self.conn.commit()
        p = self.plan()
        self.assertEqual(self.keys(p), [("recall", True), ("write", True)])
        self.assertIsNone(p["next"])

    def test_a_due_quiz_goes_first(self):
        wid = db.upsert_word(self.conn, {"word": "cabin", "example_en": "A small cabin."})
        experiments.arm(self.conn, "E2", wid)
        self.conn.execute("UPDATE probes SET due_at='2000-01-01T00:00:00'")
        self.conn.commit()
        p = self.plan({"due": 3})
        self.assertEqual(self.keys(p)[:2], [("quiz", False), ("review", False)])
        self.assertEqual(p["blocks"][0]["detail"], "2 surprise questions")

    def test_micro_needs_words(self):
        self.assertEqual(writing.micro(self.conn)["steps"], [])

    def test_a_reading_finished_today_closes_the_block(self):
        self.reading("old", "2026-08-01T10:00:00")
        self.reading("done", "2026-08-02T10:00:00", finished=db.now_iso())
        p = self.plan()
        self.assertEqual(self.keys(p), [("reading", True)])
        self.assertEqual(p["blocks"][0]["detail"], "done")

    def test_paused(self):
        with mock.patch.object(pause, "is_paused", return_value=True):
            self.assertEqual(day.plan(self.conn), {"paused": True, "blocks": [], "next": None})


if __name__ == "__main__":
    unittest.main()
