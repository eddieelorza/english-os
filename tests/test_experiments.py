"""MVP 5: E1 y E2 asignan, excluyen al control y miden con una prueba diferida."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fsrs import Card  # noqa: E402

from app import db, experiments, recall, vocab_audit  # noqa: E402


class Case(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.addCleanup(self.conn.close)

    def word(self, text, stability=8, **fields):
        wid = db.upsert_word(self.conn, {
            "word": text, "meaning_es": "algo", "meaning_en": "something",
            "example_en": f"They saw the {text} yesterday.", "example_es": "Vieron algo ayer.",
            **fields})
        self.conn.execute(
            "UPDATE words SET card_state='REVIEW', stability=?, fsrs_card=?, fsrs_due=? WHERE id=?",
            (stability, Card().to_json(), db.now_iso(), wid))
        self.conn.commit()
        return wid

    def probes(self, wid):
        return self.conn.execute(
            "SELECT experiment, arm, after_days, due_at FROM probes WHERE word_id=? "
            "ORDER BY after_days", (wid,)).fetchall()

    def past_due(self):
        self.conn.execute("UPDATE probes SET due_at='2000-01-01T00:00:00'")
        self.conn.commit()


class TestAssignment(Case):
    def test_arms_alternate_and_stick(self):
        ids = [self.word(f"w{i}") for i in range(10)]
        arms = [experiments.arm(self.conn, "E2", i) for i in ids]
        self.assertEqual(arms.count("recall"), 5)
        self.assertEqual(arms.count("control"), 5)
        self.assertEqual(experiments.arm(self.conn, "E2", ids[0]), arms[0])

    def test_assignment_schedules_both_probes(self):
        wid = self.word("cabin")
        a = experiments.arm(self.conn, "E1", wid)
        rows = self.probes(wid)
        self.assertEqual([(r["experiment"], r["arm"], r["after_days"]) for r in rows],
                         [("E1", a, 7), ("E1", a, 30)])
        gap = datetime.fromisoformat(rows[1]["due_at"]) - datetime.fromisoformat(rows[0]["due_at"])
        self.assertEqual(gap, timedelta(days=23))


class TestUnmeasurable(Case):
    def test_a_word_without_a_blank_stays_out_and_is_treated(self):
        wid = self.word("sting", example_en="The bee hurt him badly.")
        self.assertEqual(experiments.arm(self.conn, "E2", wid), "recall")
        self.assertEqual(self.probes(wid), [])
        self.assertIsNone(self.conn.execute(
            "SELECT 1 FROM experiment_arms WHERE word_id=?", (wid,)).fetchone())


class TestE2(Case):
    def test_control_words_never_reach_recall(self):
        first, second = self.word("first", 20), self.word("second", 10)
        with mock.patch.object(experiments.random, "choice", return_value="control"):
            nxt = recall.next_item(self.conn)
        # La primera fue a control; la segunda queda en «recall» por alternancia.
        self.assertEqual(nxt["item"]["word_id"], second)
        self.assertEqual(experiments.arm(self.conn, "E2", first), "control")
        with self.assertRaises(ValueError):
            recall.answer(self.conn, first, "meaning", "first")


class TestE1(Case):
    def test_control_keeps_its_gloss_out_of_the_queue(self):
        ids = [self.word(w, meaning_es="Cabina", example_es="Se quedaron en la cabaña.")
               for w in ("cabin", "hut")]
        kept = [r["id"] for r in vocab_audit.candidates(self.conn)]
        self.assertEqual(len(kept), 1)
        arms = {i: experiments.arm(self.conn, "E1", i) for i in ids}
        self.assertEqual(sorted(arms.values()), ["control", "repair"])
        self.assertEqual(arms[kept[0]], "repair")


class TestQuiz(Case):
    def test_nothing_before_it_is_due(self):
        experiments.arm(self.conn, "E2", self.word("cabin"))
        self.assertIsNone(experiments.quiz(self.conn)["item"])

    def test_answer_is_graded_and_does_not_touch_scheduling(self):
        wid = self.word("cabin")
        experiments.arm(self.conn, "E2", wid)
        self.past_due()
        before = self.conn.execute("SELECT fsrs_card FROM words WHERE id=?", (wid,)).fetchone()[0]
        q = experiments.quiz(self.conn)
        self.assertEqual(q["item"]["sentence"], "They saw the ____ yesterday.")
        self.assertEqual(q["item"]["hint"], "c·5")
        self.assertNotIn("expected", q["item"])           # la respuesta no viaja
        out = experiments.answer(self.conn, q["item"]["probe_id"], "Cabin")
        self.assertEqual(out["item"]["probe_id"], q["item"]["probe_id"] + 1)
        self.assertNotIn("verdict", out)                   # tampoco el veredicto
        row = self.conn.execute("SELECT verdict, expected FROM probes WHERE id=?",
                                (q["item"]["probe_id"],)).fetchone()
        self.assertEqual(tuple(row), ("correct", "cabin"))
        after = self.conn.execute("SELECT fsrs_card FROM words WHERE id=?", (wid,)).fetchone()[0]
        self.assertEqual(before, after)
        with self.assertRaises(ValueError):
            experiments.answer(self.conn, q["item"]["probe_id"], "cabin")

    def test_daily_cap(self):
        for i in range(8):
            experiments.arm(self.conn, "E2", self.word(f"word{i}"))
        self.past_due()
        for _ in range(experiments.QUIZ_PER_DAY):
            pid = experiments.quiz(self.conn)["item"]["probe_id"]
            experiments.answer(self.conn, pid, "x")
        self.assertIsNone(experiments.quiz(self.conn)["item"])

    def test_summary_counts_by_arm(self):
        ids = [self.word(f"word{i}") for i in range(2)]
        for i in ids:
            experiments.arm(self.conn, "E2", i)
        self.past_due()
        while (q := experiments.quiz(self.conn))["item"]:
            experiments.answer(self.conn, q["item"]["probe_id"], "nope")
        s = experiments.summary(self.conn)["E2"]
        self.assertEqual(s["recall"]["words"], 1)
        self.assertEqual(s["control"]["probes"]["7"], {"answered": 1, "right": 0})


if __name__ == "__main__":
    unittest.main()
