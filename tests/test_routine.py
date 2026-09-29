"""ADR-016 D5: Claude Code escribe el podcast y la práctica del día, y la app
los valida con las mismas reglas que al generador local. Todo en memoria; el
audio (Kokoro) está parcheado — aquí se prueba la validación, no la voz."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import activities, db, routine  # noqa: E402

WORDS = ["forge", "arise", "endure", "prosper"]


def seeded():
    conn = db.connect(":memory:")
    for w in WORDS:
        db.upsert_word(conn, {"word": w, "status": "LEARNING", "meaning_es": "x"})
    return conn


def episode(turns=16, **over):
    q = {"question": "What did Ana say?", "options": ["a", "b", "c"],
         "answer_index": 1, "why": "Porque lo dijo al final."}
    d = {"title": "Two Engineers Talk", "speaker_a_name": "Ana",
         "speaker_b_name": "Beto",
         "turns": [{"speaker": "A" if i % 2 == 0 else "B",
                    "text": f"Turn number {i}, and it says something."}
                   for i in range(turns)],
         "questions": [dict(q) for _ in range(4)]}
    d.update(over)
    return d


def quiz(n=6, **over):
    d = {"title": "Grammar — Test",
         "questions": [{"prompt": f"Question {i}?", "options": ["a", "b", "c"],
                        "answer_index": 0, "why": "Regla.", "category": "Artículos"}
                       for i in range(n)]}
    d.update(over)
    return d


def b_id(conn):
    return conn.execute("SELECT id FROM activities WHERE kind='grammar_quiz'").fetchone()["id"]


FAKE_AUDIO = {"path": "podcast/x.wav", "marks": [{"turn": 0, "speaker": "A"}]}


class TestPodcast(unittest.TestCase):
    def setUp(self):
        self.conn = seeded()

    def test_the_brief_is_what_the_local_generator_would_ask_for(self):
        b = routine.brief(self.conn, "podcast")
        self.assertIsNone(b["skip"])
        self.assertEqual(sorted(b["target_words"]), sorted(WORDS))
        self.assertIn("forge", b["prompt"])
        self.assertEqual(b["limits"]["min_turns"], routine.MIN_TURNS)

    @mock.patch("app.tts.narrate_turns", return_value=FAKE_AUDIO)
    def test_it_stores_the_episode_and_refuses_a_second_one_today(self, _tts):
        out = routine.submit(self.conn, "podcast", episode())
        self.assertEqual(out["turns"], 16)
        self.assertEqual(out["source"], "routine:claude-code")
        self.assertIn("today already has a podcast", routine.brief(self.conn, "podcast")["skip"])
        with self.assertRaises(routine.AlreadyExists):
            routine.submit(self.conn, "podcast", episode())

    @mock.patch("app.tts.narrate_turns", return_value=FAKE_AUDIO)
    def test_a_short_dialogue_is_refused_before_the_audio_is_made(self, tts_mock):
        with self.assertRaises(ValueError) as e:
            routine.submit(self.conn, "podcast", episode(turns=6))
        self.assertIn("usable turns", str(e.exception))
        tts_mock.assert_not_called()

    @mock.patch("app.tts.narrate_turns", return_value=FAKE_AUDIO)
    def test_bad_questions_are_refused(self, tts_mock):
        with self.assertRaises(ValueError):
            routine.submit(self.conn, "podcast",
                           episode(questions=[{"question": "a", "options": ["x"],
                                               "answer_index": 0, "why": "y"}] * 4))
        tts_mock.assert_not_called()


class TestPractice(unittest.TestCase):
    def setUp(self):
        self.conn = seeded()

    def test_the_brief_carries_the_focus_and_the_same_schema(self):
        b = routine.brief(self.conn, "practice")
        self.assertIsNone(b["skip"])
        self.assertEqual(b["schema"], activities.QUIZ_SCHEMA)
        self.assertIn(b["focus"], activities.TENSES)

    def test_the_brief_says_to_skip_once_the_day_has_a_quiz(self):
        routine.submit(self.conn, "practice", quiz())
        b = routine.brief(self.conn, "practice")
        self.assertIn("already has a grammar quiz", b["skip"])
        activities.submit(self.conn, b_id(self.conn), [0] * 6)
        self.assertIn("already answered", routine.brief(self.conn, "practice")["skip"])

    def test_it_stores_the_quiz_and_replaces_it_only_while_unanswered(self):
        out = routine.submit(self.conn, "practice", quiz())
        self.assertEqual(out["questions"], 6)
        again = routine.submit(self.conn, "practice", quiz(n=5))
        self.assertEqual(again["id"], out["id"])       # misma actividad del día
        self.assertEqual(again["questions"], 5)
        activities.submit(self.conn, out["id"], [0] * 5)
        with self.assertRaises(ValueError):
            routine.submit(self.conn, "practice", quiz())

    def test_malformed_questions_are_dropped_and_too_few_is_an_error(self):
        bad = quiz(questions=[{"prompt": "p", "options": ["a", "b"],
                               "answer_index": 0, "why": "w", "category": "c"}] * 6)
        with self.assertRaises(ValueError) as e:
            routine.submit(self.conn, "practice", bad)
        self.assertIn("usable", str(e.exception))


class TestKinds(unittest.TestCase):
    def test_an_unknown_kind_is_a_value_error(self):
        conn = seeded()
        with self.assertRaises(ValueError):
            routine.brief(conn, "novela")
        with self.assertRaises(ValueError):
            routine.submit(conn, "novela", {})


if __name__ == "__main__":
    unittest.main()
