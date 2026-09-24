"""M9 tests: activities grading feeds the error loop; listening is
deterministic; writing correction stores tense analysis. AI is faked."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import activities, coach, db, writing  # noqa: E402

FAKE_QUIZ = {"questions": [
    {"prompt": "She ___ here for two years.",
     "options": ["works", "has been working", "work"],
     "answer_index": 1, "why": "Duración hasta ahora: presente perfecto continuo.",
     "category": "Tiempos verbales"},
    {"prompt": "The people ___ nice.", "options": ["is", "are", "be"],
     "answer_index": 1, "why": "'People' es plural.", "category": "Concordancia"},
]}


class FakeAI:
    """Dispatches on the requested schema — prompt text is too ambiguous
    (the word "correct" appears in both the quiz and correction systems)."""

    def generate_json(self, system, prompt, schema, max_tokens=4096):
        props = set(schema["properties"])
        if "questions" in props:
            return FAKE_QUIZ
        if "remember" in props:
            return {"category": "Preposiciones", "rule": "Usa 'for' con duración.",
                    "wrong": "I live here since 2 years.",
                    "right": "I've lived here for two years.",
                    "remember": "for + cuánto tiempo."}
        if props == {"prompt"}:
            return {"prompt": "Describe a problem you solved this week."}
        return {
                "errors": [{"original": "I have 2 years working",
                            "correction": "I have been working for two years",
                            "category": "Tiempos verbales",
                            "explanation": "Presente perfecto continuo."}],
                "improved_version": "I have been working here for two years.",
                "tenses_used": ["Present Simple", "Present Perfect"],
                "focus_hit": True, "focus_note": "Usaste el foco correctamente.",
                "strength": "Ideas claras.", "practice_next": "Preposiciones.",
        }


def seed_words(conn, n=6, audio=True):
    for i in range(n):
        db.upsert_word(conn, {
            "word": f"word{i}", "status": "LEARNING", "meaning_es": f"palabra{i}",
            "audio_word": f"audio/w{i}.mp3" if audio else None})


class TestListening(unittest.TestCase):
    """Deterministic — built from the DB, never from the AI."""

    def setUp(self):
        self.conn = db.connect(":memory:")

    def test_questions_use_deck_audio_with_three_options(self):
        seed_words(self.conn, 8)
        act = activities._listening(self.conn, n=4)
        self.assertEqual(len(act["questions"]), 4)
        for q in act["questions"]:
            self.assertTrue(q["audio"].startswith("audio/"))
            self.assertEqual(len(q["options"]), 3)
            self.assertIn(q["options"][q["answer_index"]],
                          [f"word{i}" for i in range(8)])
            self.assertEqual(len(set(q["options"])), 3)  # no repeated options

    def test_skips_when_not_enough_audio(self):
        seed_words(self.conn, 2)
        self.assertEqual(activities._listening(self.conn)["questions"], [])


class TestGrading(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        seed_words(self.conn)
        with mock.patch.object(activities.ai, "get_provider", return_value=FakeAI()):
            self.acts = activities.today_set(self.conn)
        self.quiz = next(a for a in self.acts if a["kind"] == "grammar_quiz")

    def test_all_correct_scores_full_and_records_nothing(self):
        answers = [q["answer_index"] for q in self.quiz["questions"]]
        r = activities.submit(self.conn, self.quiz["id"], answers, seconds=30)
        self.assertEqual(r["score"], r["total"])
        n = self.conn.execute("SELECT COUNT(*) FROM errors").fetchone()[0]
        self.assertEqual(n, 0)

    def test_wrong_answers_feed_the_error_table(self):
        answers = [(q["answer_index"] + 1) % 3 for q in self.quiz["questions"]]
        r = activities.submit(self.conn, self.quiz["id"], answers)
        self.assertEqual(r["score"], 0)
        rows = self.conn.execute(
            "SELECT category, source FROM errors").fetchall()
        self.assertEqual(len(rows), len(self.quiz["questions"]))
        self.assertTrue(all(x["source"] == "Activity" for x in rows))
        self.assertIn("Tiempos verbales", [x["category"] for x in rows])

    def test_repeated_miss_bumps_recurrence(self):
        answers = [(q["answer_index"] + 1) % 3 for q in self.quiz["questions"]]
        activities.submit(self.conn, self.quiz["id"], answers)
        activities.submit(self.conn, self.quiz["id"], answers)
        rec = self.conn.execute("SELECT MAX(recurrences) FROM errors").fetchone()[0]
        self.assertEqual(rec, 2)

    def test_answer_count_must_match(self):
        with self.assertRaises(ValueError):
            activities.submit(self.conn, self.quiz["id"], [0])

    def test_completed_activity_is_not_regenerated(self):
        answers = [q["answer_index"] for q in self.quiz["questions"]]
        activities.submit(self.conn, self.quiz["id"], answers)
        with mock.patch.object(activities.ai, "get_provider", return_value=FakeAI()):
            again = activities.today_set(self.conn, regenerate=True)
        quiz = next(a for a in again if a["kind"] == "grammar_quiz")
        self.assertEqual(quiz["id"], self.quiz["id"])
        self.assertIsNotNone(quiz["completed_at"])


class TestWriting(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        seed_words(self.conn)

    def test_submit_stores_text_tenses_and_errors(self):
        with mock.patch.object(writing.ai, "get_provider", return_value=FakeAI()):
            r = writing.submit(self.conn,
                               "I have 2 years working here with my team.",
                               prompt="Tell me about your job", seconds=120)
        self.assertEqual(r["tenses_used"], ["Present Simple", "Present Perfect"])
        self.assertTrue(r["focus_hit"])
        row = self.conn.execute("SELECT * FROM texts WHERE id=?", (r["id"],)).fetchone()
        self.assertEqual(row["kind"], "writing")
        self.assertEqual(row["corrected"], 1)
        self.assertEqual(row["words_produced"], 9)
        stored = json.loads(row["correction"])
        self.assertIn("tenses_used", stored)
        src = self.conn.execute("SELECT source FROM errors").fetchone()[0]
        self.assertEqual(src, "Writing")

    def test_too_short_is_rejected(self):
        with self.assertRaises(ValueError):
            writing.submit(self.conn, "Too short")


class TestGrammarTip(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")

    def test_none_without_error_data(self):
        self.assertIsNone(coach.grammar_tip(self.conn))

    def test_tip_is_cached_per_day(self):
        self.conn.execute(
            "INSERT INTO errors (date, category, original, correction, source, "
            "recurrences, created_at, updated_at) VALUES "
            "(date('now'),'Preposiciones','x','y','Writing',3,'','')")
        self.conn.commit()
        fake = FakeAI()
        with mock.patch.object(coach.ai, "get_provider", return_value=fake), \
             mock.patch.object(fake, "generate_json",
                               wraps=fake.generate_json) as spy:
            first = coach.grammar_tip(self.conn)
            second = coach.grammar_tip(self.conn)
        self.assertEqual(first, second)
        self.assertEqual(spy.call_count, 1)  # cached, not regenerated
        self.assertEqual(first["category"], "Preposiciones")


if __name__ == "__main__":
    unittest.main()
