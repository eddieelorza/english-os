"""M12 tests: multi-source evidence and the level it implies.

The case that motivated ADR-008: a fortnight with no writing at all must
still produce a founded level.
"""

from __future__ import annotations

import json
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import db, model  # noqa: E402


def recent(days_ago: int = 1) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


def add_reviews(conn, n, again, days_ago=1):
    db.upsert_session(conn, recent(days_ago), {
        "cards_reviewed": n, "again": again,
        "again_rate": again / n if n else None})


def add_comprehension(conn, score, total, days_ago=1, idx=0):
    db.upsert_text(conn, {
        "notion_page_id": f"comp-{days_ago}-{idx}", "kind": "reading",
        "date": recent(days_ago), "title": "t", "body": "b",
        "quiz_score": score, "quiz_total": total})


def add_activity(conn, score, total, days_ago=1, idx=0):
    conn.execute(
        "INSERT INTO activities (date, kind, title, payload, score, total, "
        "completed_at, created_at, updated_at) VALUES (?,?,?,'{}',?,?,?,?,?)",
        (recent(days_ago), f"grammar_quiz_{idx}", "q", score, total,
         db.now_iso(), db.now_iso(), db.now_iso()))
    conn.commit()


def add_production(conn, kind, words, errors, days_ago=1):
    db.upsert_text(conn, {
        "notion_page_id": f"{kind}-{days_ago}-{words}", "kind": kind,
        "date": recent(days_ago), "title": "t", "body": "b", "corrected": 1,
        "words_produced": words, "errors_count": errors})


class TestEvidenceSources(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")

    def test_each_source_reports_sample_and_signal(self):
        add_reviews(self.conn, 200, 20)          # 90% retention
        add_comprehension(self.conn, 18, 20)     # 90%
        add_activity(self.conn, 22, 25)          # 88%
        add_production(self.conn, "speaking", 200, 8)  # 4 errors/100
        ev = model.evidence(self.conn)
        for key in ("recall", "comprehension", "controlled", "production"):
            self.assertTrue(ev[key]["enough"], key)
            self.assertEqual(ev[key]["signal"], "stretch", key)
            self.assertIsNotNone(ev[key]["display"], key)

    def test_small_samples_report_not_enough(self):
        add_reviews(self.conn, 10, 1)
        add_comprehension(self.conn, 3, 4)
        ev = model.evidence(self.conn)
        self.assertFalse(ev["recall"]["enough"])
        self.assertIsNone(ev["recall"]["signal"])
        self.assertFalse(ev["comprehension"]["enough"])

    def test_speaking_counts_as_free_production(self):
        """Before M12 only writing counted — a spoken fortnight was invisible."""
        add_production(self.conn, "speaking", 180, 9)
        ev = model.evidence(self.conn)
        self.assertTrue(ev["production"]["enough"])
        self.assertEqual(ev["production"]["value"], 5.0)

    def test_writing_and_speaking_are_summed(self):
        add_production(self.conn, "writing", 100, 5, days_ago=2)
        add_production(self.conn, "speaking", 100, 5, days_ago=1)
        ev = model.evidence(self.conn)
        self.assertEqual(ev["production"]["n"], 200)
        self.assertEqual(ev["production"]["value"], 5.0)


class TestLevelWithoutWriting(unittest.TestCase):
    """The bug ADR-008 was written for."""

    def setUp(self):
        self.conn = db.connect(":memory:")

    def test_b2_is_reachable_with_no_writing_at_all(self):
        add_reviews(self.conn, 200, 18)        # 91% retention  → stretch
        add_comprehension(self.conn, 22, 24)   # 92%            → stretch
        add_activity(self.conn, 24, 28)        # 86%            → stretch
        rec = model.recommend_level(self.conn)
        self.assertEqual(rec["level"], "B2")
        self.assertNotIn("production", rec["evidence"])
        self.assertIn("comprehension", rec["evidence"])

    def test_no_evidence_holds_base_level_honestly(self):
        rec = model.recommend_level(self.conn)
        self.assertEqual(rec["level"], "B1")
        self.assertIn("no evidence", rec["reason"])
        self.assertEqual(rec["evidence"], [])

    def test_single_source_is_not_enough_to_stretch_far(self):
        add_reviews(self.conn, 200, 18)  # only recall
        rec = model.recommend_level(self.conn)
        self.assertEqual(rec["level"], "B1+")

    def test_weakest_link_governs(self):
        add_reviews(self.conn, 200, 60)        # 70% retention → consolidate
        add_comprehension(self.conn, 23, 24)   # excellent
        add_activity(self.conn, 27, 28)        # excellent
        rec = model.recommend_level(self.conn)
        self.assertEqual(rec["level"], "B1")
        self.assertIn("consolidate", rec["reason"])

    def test_comfortable_everywhere_stretches_gently(self):
        add_reviews(self.conn, 200, 30)        # 85% → hold
        add_comprehension(self.conn, 15, 20)   # 75% → hold
        rec = model.recommend_level(self.conn)
        self.assertEqual(rec["level"], "B1+")
        self.assertIn("comfortable", rec["reason"])

    def test_reason_names_its_sources(self):
        add_reviews(self.conn, 200, 18)
        add_comprehension(self.conn, 22, 24)
        rec = model.recommend_level(self.conn)
        self.assertIn("retention", rec["reason"])
        self.assertIn("comprehension", rec["reason"])


class TestQuizPersistence(unittest.TestCase):
    def test_quiz_result_lands_in_evidence(self):
        conn = db.connect(":memory:")
        tid = db.upsert_text(conn, {
            "notion_page_id": "r1", "kind": "reading", "date": recent(0),
            "title": "t", "body": "b",
            "questions": json.dumps([{"answer_index": 1}] * 4)})
        conn.execute("UPDATE texts SET quiz_score=3, quiz_total=4 WHERE id=?", (tid,))
        # a podcast quiz on the same fortnight adds to the same pool
        db.upsert_text(conn, {
            "notion_page_id": "p1", "kind": "podcast", "date": recent(1),
            "title": "t", "body": "b", "quiz_score": 8, "quiz_total": 8})
        conn.commit()
        ev = model.evidence(conn)
        self.assertEqual(ev["comprehension"]["n"], 12)
        self.assertTrue(ev["comprehension"]["enough"])


if __name__ == "__main__":
    unittest.main()
