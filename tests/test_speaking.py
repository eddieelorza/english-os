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
        self.assertIn("Tiempos verbales", cats)

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
