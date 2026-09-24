"""ADR-015 D8 tests: señales de lo que el alumno sí hace, sin inventar nada."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from app import learner  # noqa: E402  (load → backlog → fsrs)
except ImportError:
    raise unittest.SkipTest("fsrs not installed in this interpreter")
from app import db  # noqa: E402


def reading(conn, score, total):
    conn.execute(
        "INSERT INTO texts (kind, title, body, finished_at, quiz_score, quiz_total, "
        "created_at, updated_at) VALUES ('reading','t','b',?,?,?,?,?)",
        (db.now_iso(), score, total, db.now_iso(), db.now_iso()))
    conn.commit()


class TestSignals(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")

    def by_key(self):
        return {s["key"]: s for s in learner.signals(self.conn)}

    def test_a_small_sample_gives_no_number(self):
        for _ in range(learner.MIN_SAMPLE - 1):
            reading(self.conn, 1, 4)
        s = self.by_key()["comprehension"]
        self.assertIsNone(s["value"])
        self.assertEqual(s["sample"], learner.MIN_SAMPLE - 1)

    def test_with_enough_it_measures(self):
        for _ in range(learner.MIN_SAMPLE):
            reading(self.conn, 3, 4)
        self.assertEqual(self.by_key()["comprehension"]["value"], 0.75)

    def test_no_signal_claims_to_be_an_english_level(self):
        for s in learner.signals(self.conn):
            self.assertTrue(s["measures"])
            self.assertNotIn("level", s["label"].lower())

    def test_the_goal_is_never_assumed(self):
        self.assertIsNone(learner.goal(self.conn))
        self.assertNotIn("goal", learner.context(self.conn).lower())

    def test_context_describes_what_he_does_not_what_we_wish(self):
        for _ in range(3):
            reading(self.conn, 2, 4)
        ctx = learner.context(self.conn)
        self.assertIn("reads", ctx)
        self.assertIn("rarely", ctx)
        self.assertIn("short and safe", ctx)


if __name__ == "__main__":
    unittest.main()
