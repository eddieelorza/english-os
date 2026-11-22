"""M6 tests: speaking corrections become study material — with fakes for
whisper and the AI provider (no models, no network)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import db, speaking  # noqa: E402

FAKE_CORRECTION = {
    "errors": [
        {"original": "I have 2 years working here",
         "correction": "I've been working here for two years",
         "category": "Tiempos verbales",
         "explanation": "Duration up to now takes the present perfect continuous."},
        {"original": "the people is",
         "correction": "people are",
         "category": "Concordancia",
         "explanation": "'People' is plural in English."},
    ],
    "natural_version": "I've been working here for two years and people are great.",
    "strength": "Clear structure.",
    "practice_next": "Present perfect for durations.",
}


class TestCategories(unittest.TestCase):
    def test_codes_and_aliases_normalize(self):
        for code in ("ART", "PREP", "S-V", "COLL", "TENSE", "REG", "WORD", "ORDER"):
            with self.subTest(code=code):
                self.assertEqual(speaking.normalize_category(code), code)
                self.assertEqual(speaking.normalize_category(f"  {code.lower()}\t"), code)
        aliases = {"Artículos": "ART", "Preposiciones": "PREP",
                   "Concordancia": "S-V", "Tiempos verbales": "TENSE",
                   "Colocación": "COLL", "Registro": "REG", "Vocabulario": "WORD",
                   "Falsos amigos": "WORD", "Orden de palabras": "ORDER"}
        for alias, code in aliases.items():
            with self.subTest(alias=alias):
                raw = "  " + alias.upper().replace(" ", " \t ") + "\n"
                self.assertEqual(speaking.normalize_category(raw), code)
        for unknown in ("GRAMMAR", "", None):
            self.assertIsNone(speaking.normalize_category(unknown))

    def test_unknown_category_is_not_stored_or_counted(self):
        conn = db.connect(":memory:")
        self.addCleanup(conn.close)
        error = {"category": "GRAMMAR", "original": "bad", "correction": "good",
                 "explanation": "x"}
        self.assertEqual(speaking._store_errors(conn, [error]), 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM errors").fetchone()[0], 0)

    def test_alias_and_code_share_recurrences(self):
        conn = db.connect(":memory:")
        self.addCleanup(conn.close)
        error = {"category": "Preposiciones", "original": "work in a feature",
                 "correction": "work on a feature", "explanation": "x"}
        self.assertEqual(speaking._store_errors(conn, [error]), 1)
        self.assertEqual(speaking._store_errors(conn, [{**error, "category": " prep "}]), 1)
        rows = conn.execute("SELECT category, recurrences FROM errors").fetchall()
        self.assertEqual([tuple(row) for row in rows], [("PREP", 2)])

    def test_correction_schemas_share_the_canonical_codes(self):
        from app import conversation, writing
        for schema, field in ((speaking.CORRECTION_SCHEMA, "errors"),
                              (writing.CORRECTION_SCHEMA, "errors"),
                              (conversation.SUMMARY_SCHEMA, "corrections")):
            category = schema["properties"][field]["items"]["properties"]["category"]
            self.assertEqual(category["enum"], list(speaking.ERROR_CATEGORIES))
        self.assertEqual(writing.CHECK_SCHEMA["properties"]["category"]["enum"],
                         [*speaking.ERROR_CATEGORIES, ""])


class TestSubmit(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")

    def run_submit(self, transcript="I have 2 years working here and the people is nice",
                   correction=FAKE_CORRECTION):
        with mock.patch.object(speaking, "transcribe",
                               return_value={"text": transcript,
                                             "duration_seconds": 45.0,
                                             "language": "en"}), \
             mock.patch.object(speaking, "correct", return_value=correction):
            return speaking.submit(self.conn, "/tmp/fake.webm", prompt="Tell me about your job")

    def test_full_loop_stores_text_errors_and_minutes(self):
        r = self.run_submit()
        self.assertEqual(len(r["errors"]), 2)
        row = self.conn.execute("SELECT * FROM texts WHERE id=?", (r["id"],)).fetchone()
        self.assertEqual(row["kind"], "speaking")
        self.assertEqual(row["corrected"], 1)
        self.assertEqual(row["errors_count"], 2)
        n = self.conn.execute(
            "SELECT COUNT(*) FROM errors WHERE source='Speaking'").fetchone()[0]
        self.assertEqual(n, 2)
        s = self.conn.execute("SELECT speaking_minutes FROM sessions").fetchone()
        self.assertAlmostEqual(s[0], 0.75, places=2)

    def test_repeat_error_bumps_recurrences(self):
        self.run_submit()
        self.run_submit()
        row = self.conn.execute(
            "SELECT recurrences FROM errors WHERE original=?",
            ("I have 2 years working here",)).fetchone()
        self.assertEqual(row[0], 2)
        n = self.conn.execute("SELECT COUNT(*) FROM errors").fetchone()[0]
        self.assertEqual(n, 2)  # deduped, not duplicated

    def test_speaking_errors_feed_the_model(self):
        from app import model
        self.run_submit()
        cats = model.errors(self.conn)["top_categories"]
        self.assertIn("TENSE", cats)

    def test_silent_recording_rejected(self):
        with mock.patch.object(speaking, "transcribe",
                               return_value={"text": "", "duration_seconds": 1.0,
                                             "language": "en"}):
            with self.assertRaises(ValueError):
                speaking.submit(self.conn, "/tmp/fake.webm")

    def test_minutes_accumulate_same_day(self):
        self.run_submit()
        self.run_submit()
        s = self.conn.execute("SELECT speaking_minutes FROM sessions").fetchone()
        self.assertAlmostEqual(s[0], 1.5, places=2)


if __name__ == "__main__":
    unittest.main()
