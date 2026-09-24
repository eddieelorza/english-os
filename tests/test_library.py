"""M10 tests: sentence explanation caching + library grouping and deletion."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import db, explain, library  # noqa: E402

FAKE_EXPLANATION = {
    "meaning": "Dice que lleva dos años trabajando ahí.",
    "grammar": "Presente perfecto continuo para duración hasta ahora.",
    "spanish": "Llevo dos años trabajando aquí.",
    "watch_out": "En español usamos presente; en inglés no.",
}


class FakeAI:
    calls = 0

    def generate_json(self, system, prompt, schema, max_tokens=4096):
        FakeAI.calls += 1
        return dict(FAKE_EXPLANATION)


class TestExplain(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        FakeAI.calls = 0

    def test_explains_and_caches(self):
        with mock.patch.object(explain.ai, "get_provider", return_value=FakeAI()):
            first = explain.explain(self.conn, "I've been working here for years.")
            second = explain.explain(self.conn, "I've been working here for years.")
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(FakeAI.calls, 1)
        self.assertEqual(first["spanish"], FAKE_EXPLANATION["spanish"])

    def test_cache_ignores_case_and_spacing(self):
        with mock.patch.object(explain.ai, "get_provider", return_value=FakeAI()):
            explain.explain(self.conn, "The people are nice.")
            again = explain.explain(self.conn, "  the   PEOPLE are nice.  ")
        self.assertTrue(again["cached"])
        self.assertEqual(FakeAI.calls, 1)

    def test_empty_sentence_rejected(self):
        with self.assertRaises(ValueError):
            explain.explain(self.conn, "   ")


def add_text(conn, kind, date, title, **extra):
    return db.upsert_text(conn, {
        "kind": kind, "date": date, "title": title, "body": "Some body text.",
        "notion_page_id": f"{kind}-{date}-{title}", **extra})


class TestLibrary(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        add_text(self.conn, "reading", "2026-08-20", "Monday reading",
                 source="generated:ollama")
        add_text(self.conn, "reading", "2026-08-21", "Friday reading",
                 finished_at="2026-08-21T10:00:00")
        add_text(self.conn, "writing", "2026-08-21", "Friday writing",
                 words_produced=60, errors_count=2)
        self.conn.execute(
            "INSERT INTO activities (date, kind, title, payload, score, total, "
            "completed_at, created_at, updated_at) VALUES "
            "('2026-08-21','listening','Listening','{}',4,5,'x','','')")
        self.conn.execute(
            "INSERT INTO activities (date, kind, title, payload, created_at, "
            "updated_at) VALUES ('2026-08-21','tip','Tip','{}','','')")
        self.conn.commit()

    def test_groups_by_day_newest_first(self):
        days = library.by_day(self.conn)
        self.assertEqual([d["date"] for d in days], ["2026-08-21", "2026-08-20"])
        friday = days[0]
        self.assertEqual(len(friday["reading"]), 1)
        self.assertEqual(len(friday["writing"]), 1)
        self.assertEqual(len(friday["activities"]), 1)  # the tip is not material

    def test_reading_flags_travel(self):
        friday = library.by_day(self.conn)[0]
        self.assertTrue(friday["reading"][0]["finished"])
        monday = library.by_day(self.conn)[1]
        self.assertTrue(monday["reading"][0]["generated"])
        self.assertFalse(monday["reading"][0]["finished"])

    def test_filter_by_kind(self):
        days = library.by_day(self.conn, kind="writing")
        self.assertEqual(len(days), 1)
        self.assertEqual(days[0]["writing"][0]["title"], "Friday writing")
        self.assertEqual(days[0]["reading"], [])

    def test_delete_text_keeps_learning_history(self):
        wid = db.upsert_word(self.conn, {"word": "forge", "status": "LEARNING"})
        db.insert_review(self.conn, {"word_id": wid, "reviewed_at": "2026-08-21T10:00:00",
                                     "rating": 3, "source": "fsrs"})
        tid = library.by_day(self.conn)[0]["reading"][0]["id"]
        library.delete_text(self.conn, tid)
        self.assertEqual(len(library.by_day(self.conn)[0]["reading"]), 0)
        # the word and its review survive the artifact
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM words").fetchone()[0], 1)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM review_history").fetchone()[0], 1)

    def test_delete_missing_raises(self):
        with self.assertRaises(ValueError):
            library.delete_text(self.conn, 999)
        with self.assertRaises(ValueError):
            library.delete_activity(self.conn, 999)

    def test_delete_activity(self):
        aid = library.by_day(self.conn)[0]["activities"][0]["id"]
        library.delete_activity(self.conn, aid)
        self.assertEqual(len(library.by_day(self.conn)[0]["activities"]), 0)


if __name__ == "__main__":
    unittest.main()
