"""ADR-016 tests: una rutina de Claude Code escribe la lectura del día y la app
la valida con las mismas reglas que al generador local. Todo en memoria."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import ai, db, generator  # noqa: E402

WORDS = ["forge", "arise", "endure", "prosper"]
FILLER = ("The town was quiet and the people worked hard every single day of the "
          "week. ")
BODY = ("Marco decided to forge a new key. A problem began to arise when the "
        "lock would not open. He had to endure the cold. Soon he would prosper. "
        + FILLER * 20)


def good(**over):
    q = {"question": "What did Marco do?", "options": ["a", "b", "c"],
         "answer_index": 1, "why": "Because he forged a key."}
    d = {"title": "The Key", "body": BODY, "level": "B1",
         "questions": [dict(q) for _ in range(4)], "words_target": WORDS}
    d.update(over)
    return d


def seeded():
    conn = db.connect(":memory:")
    for w in WORDS:
        db.upsert_word(conn, {"word": w, "status": "LEARNING", "meaning_es": "x"})
    return conn


class TestBrief(unittest.TestCase):
    def setUp(self):
        self.conn = seeded()

    def test_it_hands_over_what_the_local_generator_would_use(self):
        b = generator.brief(self.conn)
        self.assertIsNone(b["skip"])
        self.assertEqual(sorted(b["target_words"]), sorted(WORDS))
        self.assertEqual(b["system"], generator.SYSTEM)
        self.assertEqual(b["schema"], generator.SCHEMA)
        self.assertIn("forge", b["prompt"])
        self.assertIn(b["level"], generator.LEVELS)

    def test_it_says_to_skip_when_today_already_has_a_reading(self):
        generator.submit_reading(self.conn, good())
        self.assertIn("today already has a reading", generator.brief(self.conn)["skip"])

    def test_it_does_not_pile_up_readings_nobody_read(self):
        self.conn.execute(
            "INSERT INTO texts (kind, title, body, date, created_at, updated_at) "
            "VALUES ('reading','Waiting','b',date(?, '-2 days'),?,?)",
            (db.study_day(), db.now_iso(), db.now_iso()))
        self.conn.commit()
        self.assertIn("unread reading", generator.brief(self.conn)["skip"])

    def test_a_read_one_does_not_block(self):
        self.conn.execute(
            "INSERT INTO texts (kind, title, body, date, finished_at, created_at, "
            "updated_at) VALUES ('reading','Done','b',date(?, '-2 days'),?,?,?)",
            (db.study_day(), db.now_iso(), db.now_iso(), db.now_iso()))
        self.conn.commit()
        self.assertIsNone(generator.brief(self.conn)["skip"])


class TestSubmit(unittest.TestCase):
    def setUp(self):
        self.conn = seeded()

    def test_a_valid_reading_is_stored_like_a_generated_one(self):
        r = generator.submit_reading(self.conn, good())
        row = self.conn.execute("SELECT * FROM texts WHERE id=?", (r["id"],)).fetchone()
        self.assertEqual((row["kind"], row["date"], row["source"], row["level"]),
                         ("reading", db.study_day(), "routine:claude-code", "B1"))
        self.assertEqual(len(__import__("json").loads(row["questions"])), 4)

    def test_it_refuses_to_duplicate_the_days_material(self):
        generator.submit_reading(self.conn, good())
        with self.assertRaises(generator.ReadingExists):
            generator.submit_reading(self.conn, good(title="Another"))

    def test_missing_target_words_are_named_and_nothing_is_saved(self):
        with self.assertRaisesRegex(ValueError, "missing.*prosper"):
            generator.submit_reading(self.conn, good(body=BODY.replace("prosper", "grow")))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM texts").fetchone()[0], 0)

    def test_length_is_enforced(self):
        with self.assertRaisesRegex(ValueError, "words"):
            generator.submit_reading(self.conn, good(body="forge arise endure prosper."))

    def test_markdown_is_rejected_because_the_reader_wants_plain_prose(self):
        with self.assertRaisesRegex(ValueError, "plain prose"):
            generator.submit_reading(self.conn, good(body="# Title\n" + BODY))

    def test_the_quiz_shape_matches_the_apps_schema(self):
        bad = good()
        bad["questions"][0]["options"] = ["a", "b"]
        with self.assertRaisesRegex(ValueError, "question 1"):
            generator.submit_reading(self.conn, bad)
        bad = good()
        bad["questions"][2]["answer_index"] = 3
        with self.assertRaisesRegex(ValueError, "question 3"):
            generator.submit_reading(self.conn, bad)

    def test_target_words_must_be_words_the_app_knows(self):
        with self.assertRaisesRegex(ValueError, "unknown target word"):
            generator.submit_reading(self.conn, good(words_target=WORDS + ["zzzz"]))

    def test_level_must_be_one_of_the_apps(self):
        with self.assertRaisesRegex(ValueError, "level"):
            generator.submit_reading(self.conn, good(level="C2"))

    def test_the_apps_own_fallback_skips_a_day_the_routine_already_covered(self):
        from app import jobs
        generator.submit_reading(self.conn, good())
        self.assertTrue(jobs.enqueue_daily(self.conn)["reading_skipped"])


class TestPerTaskChains(unittest.TestCase):
    def test_a_task_chain_beats_its_kinds_chain_but_never_the_local_only_rule(self):
        env = {"AI_ROUTE": "on", "AI_CHAIN_GENERATE": "gemini,ollama",
               "AI_CHAIN_PODCAST": "ollama", "AI_CHAIN_GLOSSARY": "gemini,anthropic"}
        with mock.patch.dict(os.environ, env):
            ai.reset()
            self.assertEqual(ai.Router("reading").chain, ["gemini", "ollama"])
            self.assertEqual(ai.Router("podcast").chain, ["ollama"])
            self.assertEqual(ai.Router("glossary").chain, ["ollama"],
                             "el trabajo en lote sigue siendo sólo local")
        ai.reset()


if __name__ == "__main__":
    unittest.main()
