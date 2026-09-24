"""M5 tests: the Personal English Model — honesty rules and level decisions."""

from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import db, model  # noqa: E402


def recent(days_ago: int) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


def add_writing(conn, days_ago: int, words: int, errors: int):
    db.upsert_text(conn, {"notion_page_id": f"w-{days_ago}-{words}",
                          "kind": "writing", "date": recent(days_ago),
                          "corrected": 1, "words_produced": words,
                          "errors_count": errors})


def add_session(conn, days_ago: int, cards: int, again: int):
    db.upsert_session(conn, recent(days_ago),
                      {"cards_reviewed": cards, "again": again,
                       "again_rate": again / cards if cards else None})


class TestHonestyRules(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")

    def test_accuracy_none_below_sample_threshold(self):
        add_writing(self.conn, 2, 100, 8)  # < 150 words in window
        e = model.errors(self.conn)
        self.assertFalse(e["enough_data"])
        self.assertIsNone(e["errors_per_100"])

    def test_accuracy_computed_with_enough_data(self):
        add_writing(self.conn, 2, 120, 6)
        add_writing(self.conn, 4, 100, 5)
        e = model.errors(self.conn)
        self.assertTrue(e["enough_data"])
        self.assertEqual(e["errors_per_100"], 5.0)

    def test_old_writing_outside_window_ignored(self):
        add_writing(self.conn, 30, 500, 5)
        e = model.errors(self.conn)
        self.assertEqual(e["words_produced"], 0)

    def test_again_rate_none_without_reviews(self):
        self.assertIsNone(model.review_performance(self.conn)["again_rate"])


class TestLevelDecision(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")

    def test_default_is_b1_without_data(self):
        rec = model.recommend_level(self.conn)
        self.assertEqual(rec["level"], "B1")
        self.assertIn("no evidence", rec["reason"])

    def test_weak_recall_forces_b1(self):
        """The weakest link governs (ADR-008 D1)."""
        add_session(self.conn, 1, 100, 30)  # 70% retention
        add_writing(self.conn, 2, 200, 4)   # even with great accuracy
        rec = model.recommend_level(self.conn)
        self.assertEqual(rec["level"], "B1")
        self.assertIn("consolidate", rec["reason"])

    def test_low_errors_and_solid_recall_earn_b2(self):
        add_session(self.conn, 1, 200, 20)  # 10% again
        add_writing(self.conn, 2, 200, 8)   # 4 errors/100
        self.assertEqual(model.recommend_level(self.conn)["level"], "B2")

    def test_middling_errors_earn_b1_plus(self):
        add_session(self.conn, 1, 200, 20)
        add_writing(self.conn, 2, 200, 16)  # 8 errors/100
        self.assertEqual(model.recommend_level(self.conn)["level"], "B1+")

    def test_solid_recall_alone_earns_gentle_stretch(self):
        add_session(self.conn, 1, 150, 12)  # 92% retention, nothing else
        rec = model.recommend_level(self.conn)
        self.assertEqual(rec["level"], "B1+")
        self.assertIn("retention", rec["reason"])
        self.assertEqual(rec["evidence"], ["recall"])


class TestSnapshot(unittest.TestCase):
    def test_shape(self):
        conn = db.connect(":memory:")
        db.upsert_word(conn, {"word": "forge", "status": "LEARNING"})
        s = model.snapshot(conn)
        for key in ("vocabulary", "learning_words", "errors", "review",
                    "reading", "streak_days", "recommendation"):
            self.assertIn(key, s)
        self.assertEqual(s["vocabulary"]["counts"]["LEARNING"], 1)
        self.assertEqual(s["learning_words"], ["forge"])


if __name__ == "__main__":
    unittest.main()
