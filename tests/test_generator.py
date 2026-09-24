"""M3 tests: generator prompt building, word verification, storage — with a
fake provider so no network or credentials are needed."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import ai, db, generator  # noqa: E402


class FakeProvider(ai.AIProvider):
    name = "fake"
    model = "fake-1"

    def __init__(self, body: str):
        self.body = body
        self.last_prompt = None

    def available(self) -> bool:
        return True

    def generate_json(self, system, prompt, schema, max_tokens=4096):
        self.last_prompt = prompt
        return {
            "title": "Maria's Workshop",
            "body": self.body,
            "questions": [
                {"question": "Q1?", "options": ["a", "b", "c"],
                 "answer_index": 1, "why": "because"},
            ] * 4,
        }


def seed(conn):
    for w, status in (("forge", "LEARNING"), ("arise", "LEARNING"),
                      ("endure", "LEARNING"), ("prosper", "FAMILIAR")):
        db.upsert_word(conn, {"word": w, "status": status})


class TestGenerator(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        seed(self.conn)

    def test_pick_targets_learning_first(self):
        words = generator.pick_target_words(self.conn, n=4)
        names = [w["word"] for w in words]
        self.assertEqual(set(names[:3]), {"forge", "arise", "endure"})
        self.assertIn("prosper", names)

    def test_prompt_contains_words_level_topic(self):
        words = generator.pick_target_words(self.conn, n=3)
        p = generator.build_prompt(words, "B1", 5, "Work", ["Preposiciones"])
        self.assertIn("B1", p)
        self.assertIn("Work", p)
        self.assertIn("330-370", p)
        self.assertIn("Preposiciones", p)
        for w in words:
            self.assertIn(w["word"], p)

    def test_verify_words_accepts_derived_forms(self):
        words = [{"word": "forge", "normalized": "forge"},
                 {"word": "arise", "normalized": "arise"},
                 {"word": "endure", "normalized": "endure"}]
        missing = generator.verify_words(
            "She forged ahead. Problems arose daily.", words)
        self.assertEqual(missing, ["endure"])

    def test_generate_stores_text_with_questions(self):
        fake = FakeProvider("Maria forged tools while problems arose. "
                            "She endured and prospered.")
        with mock.patch.object(generator.ai, "get_provider", return_value=fake):
            result = generator.generate_reading(self.conn, "B1", 5, "Work")
        self.assertEqual(result["missing_words"], [])
        self.assertEqual(result["provider"], "fake")
        row = self.conn.execute("SELECT * FROM texts WHERE id=?",
                                (result["id"],)).fetchone()
        self.assertEqual(row["source"], "generated:fake")
        self.assertEqual(row["level"], "B1")
        self.assertEqual(len(json.loads(row["questions"])), 4)
        self.assertIn("forge", json.loads(row["words_target"]))

    def test_generate_reports_missing_words(self):
        fake = FakeProvider("A short story with none of the vocabulary.")
        with mock.patch.object(generator.ai, "get_provider", return_value=fake):
            result = generator.generate_reading(self.conn, "B1", 5, "Random")
        self.assertEqual(len(result["missing_words"]), 4)

    def test_invalid_level_rejected(self):
        with self.assertRaises(ValueError):
            generator.generate_reading(self.conn, "C2", 5, "Work")


class TestProviderFactory(unittest.TestCase):
    def test_unavailable_when_nothing_configured(self):
        env = {"AI_PROVIDER": "auto", "OLLAMA_URL": "http://127.0.0.1:1",
               "ANTHROPIC_API_KEY": "", "ANTHROPIC_AUTH_TOKEN": "",
               "ANTHROPIC_CONFIG_DIR": "/nonexistent"}
        with mock.patch.dict("os.environ", env):
            with self.assertRaises(ai.AIUnavailable):
                ai.get_provider()

    def test_anthropic_selected_with_key(self):
        # AI_ROUTE puede venir del .env real (lo carga app.server al importarse
        # en otros tests): aquí se prueba la fábrica clásica, sin enrutador.
        with mock.patch.dict("os.environ", {"AI_PROVIDER": "anthropic", "AI_ROUTE": "",
                                            "ANTHROPIC_API_KEY": "sk-test"}):
            p = ai.get_provider()
        self.assertEqual(p.name, "anthropic")

    def test_status_shape(self):
        env = {"AI_PROVIDER": "auto", "OLLAMA_URL": "http://127.0.0.1:1",
               "ANTHROPIC_API_KEY": "", "ANTHROPIC_AUTH_TOKEN": "",
               "ANTHROPIC_CONFIG_DIR": "/nonexistent"}
        with mock.patch.dict("os.environ", env):
            s = ai.status()
        self.assertFalse(s["configured"])
        self.assertFalse(s["ollama_running"])


if __name__ == "__main__":
    unittest.main()
