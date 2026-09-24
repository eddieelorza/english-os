"""M0 tests: schema, status/kind derivation, upsert idempotency (ADR-006).

Run: python3 -m unittest discover tests
Pure stdlib — no new dependencies, in-memory SQLite only.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import db  # noqa: E402


def fresh():
    return db.connect(":memory:")


class TestDerivations(unittest.TestCase):
    def test_status_new(self):
        self.assertEqual(db.derive_status(0, 0, 0), "NEW")

    def test_status_learning_queues(self):
        self.assertEqual(db.derive_status(1, 0, 0), "LEARNING")
        self.assertEqual(db.derive_status(3, 5, 0), "LEARNING")

    def test_status_review_thresholds(self):
        self.assertEqual(db.derive_status(2, 10, 0), "LEARNING")
        self.assertEqual(db.derive_status(2, 21, 0), "FAMILIAR")
        self.assertEqual(db.derive_status(2, 89, 0), "FAMILIAR")
        self.assertEqual(db.derive_status(2, 90, 0), "MASTERED")
        self.assertEqual(db.derive_status(2, 90, 1), "MASTERED")
        # too many lapses → not mastered even with long interval
        self.assertEqual(db.derive_status(2, 120, 3), "FAMILIAR")

    def test_kind(self):
        self.assertEqual(db.derive_kind("forge"), "word")
        self.assertEqual(db.derive_kind("figure out"), "phrasal_verb")
        self.assertEqual(db.derive_kind("run into"), "phrasal_verb")
        self.assertEqual(db.derive_kind("piece of cake"), "expression")
        self.assertEqual(db.derive_kind("I have been working here for years."),
                         "sentence")


class TestWordUpsert(unittest.TestCase):
    def test_insert_then_match_by_anki_note_id(self):
        conn = fresh()
        a = db.upsert_word(conn, {"word": "Forge", "anki_note_id": 11,
                                  "status": "NEW"})
        b = db.upsert_word(conn, {"word": "forge", "anki_note_id": 11,
                                  "status": "LEARNING"},
                           overwrite=("status",))
        self.assertEqual(a, b)
        row = conn.execute("SELECT * FROM words WHERE id=?", (a,)).fetchone()
        self.assertEqual(row["status"], "LEARNING")
        self.assertEqual(row["normalized"], "forge")

    def test_merge_fills_gaps_but_keeps_existing(self):
        conn = fresh()
        wid = db.upsert_word(conn, {"word": "arise", "anki_note_id": 1,
                                    "meaning_es": "surgir"})
        db.upsert_word(conn, {"word": "arise", "anki_note_id": 1,
                              "meaning_es": "aparecer",   # must NOT win
                              "meaning_en": "to happen"})  # fills the gap
        row = conn.execute("SELECT * FROM words WHERE id=?", (wid,)).fetchone()
        self.assertEqual(row["meaning_es"], "surgir")
        self.assertEqual(row["meaning_en"], "to happen")

    def test_notion_row_links_to_anki_word(self):
        conn = fresh()
        wid = db.upsert_word(conn, {"word": "prosper", "anki_note_id": 7})
        same = db.upsert_word(conn, {"word": "prosper", "anki_note_id": 7,
                                     "notion_page_id": "pg-1",
                                     "times_used": 3},
                              overwrite=("times_used",))
        self.assertEqual(wid, same)
        row = conn.execute("SELECT * FROM words WHERE id=?", (wid,)).fetchone()
        self.assertEqual(row["notion_page_id"], "pg-1")
        self.assertEqual(row["times_used"], 3)
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM words").fetchone()[0], 1)

    def test_match_by_normalized_when_no_ids(self):
        conn = fresh()
        a = db.upsert_word(conn, {"word": "Deadline"})
        b = db.upsert_word(conn, {"word": "deadline "})
        self.assertEqual(a, b)


class TestReviewsAndOthers(unittest.TestCase):
    def test_review_idempotent_by_revlog_id(self):
        conn = fresh()
        wid = db.upsert_word(conn, {"word": "forge", "anki_note_id": 1})
        row = {"word_id": wid, "reviewed_at": "2026-08-20T10:00:00",
               "rating": 3, "anki_revlog_id": 999}
        self.assertTrue(db.insert_review(conn, row))
        self.assertFalse(db.insert_review(conn, row))
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM review_history").fetchone()[0], 1)

    def test_error_upsert_by_page_id(self):
        conn = fresh()
        a = db.upsert_error(conn, {"notion_page_id": "e1", "category": "PREP",
                                   "recurrences": 1})
        b = db.upsert_error(conn, {"notion_page_id": "e1", "category": "PREP",
                                   "recurrences": 2})
        self.assertEqual(a, b)
        row = conn.execute("SELECT * FROM errors WHERE id=?", (a,)).fetchone()
        self.assertEqual(row["recurrences"], 2)

    def test_session_upsert(self):
        conn = fresh()
        db.upsert_session(conn, "2026-08-20", {"cards_reviewed": 10})
        db.upsert_session(conn, "2026-08-20", {"cards_reviewed": 53,
                                               "again_rate": 0.15})
        row = conn.execute("SELECT * FROM sessions").fetchone()
        self.assertEqual(row["cards_reviewed"], 53)
        self.assertAlmostEqual(row["again_rate"], 0.15)
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM sessions").fetchone()[0], 1)

    def test_text_upsert(self):
        conn = fresh()
        a = db.upsert_text(conn, {"notion_page_id": "t1", "kind": "writing",
                                  "corrected": 0})
        b = db.upsert_text(conn, {"notion_page_id": "t1", "kind": "writing",
                                  "corrected": 1, "words_produced": 80})
        self.assertEqual(a, b)
        row = conn.execute("SELECT * FROM texts WHERE id=?", (a,)).fetchone()
        self.assertEqual(row["corrected"], 1)
        self.assertEqual(row["words_produced"], 80)


if __name__ == "__main__":
    unittest.main()
