"""M2 tests: lemmatizer candidates + lexicon building against a temp DB."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import db, lemma  # noqa: E402


class TestCandidates(unittest.TestCase):
    def assert_lemma(self, token: str, expected: str):
        self.assertIn(expected, lemma.candidates(token))

    def test_regular_forms(self):
        self.assert_lemma("forged", "forge")
        self.assert_lemma("walked", "walk")
        self.assert_lemma("stopped", "stop")
        self.assert_lemma("running", "run")
        self.assert_lemma("forging", "forge")
        self.assert_lemma("stories", "story")
        self.assert_lemma("boxes", "box")
        self.assert_lemma("words", "word")
        self.assert_lemma("happier", "happy")
        self.assert_lemma("quickly", "quick")
        self.assert_lemma("happily", "happy")

    def test_irregulars(self):
        self.assert_lemma("arose", "arise")
        self.assert_lemma("went", "go")
        self.assert_lemma("children", "child")
        self.assert_lemma("wrote", "write")

    def test_clitics(self):
        self.assert_lemma("it's", "it")
        self.assert_lemma("don’t", "don")  # clitic stripped; 'do' via exact match

    def test_exact_first(self):
        self.assertEqual(lemma.candidates("Forge")[0], "forge")


class TestLexicon(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        for w, status in (("forge", "LEARNING"), ("arise", "FAMILIAR"),
                          ("story", "NEW"), ("prosper", "MASTERED")):
            db.upsert_word(self.conn, {"word": w, "status": status})

    def test_derived_forms_match(self):
        lex = lemma.build_lexicon(
            "He forged ahead as new problems arose; their stories prospered.",
            self.conn)
        self.assertEqual(lex["forged"]["word"], "forge")
        self.assertEqual(lex["arose"]["word"], "arise")
        self.assertEqual(lex["stories"]["word"], "story")
        self.assertEqual(lex["prospered"]["word"], "prosper")
        self.assertNotIn("problems", lex)  # unknown stays unknown

    def test_exact_beats_derived(self):
        db.upsert_word(self.conn, {"word": "forges", "status": "FAMILIAR"})
        lex = lemma.build_lexicon("He forges tools.", self.conn)
        self.assertEqual(lex["forges"]["word"], "forges")


class TestTextsMigration(unittest.TestCase):
    def test_new_columns_exist(self):
        conn = db.connect(":memory:")
        cols = {r[1] for r in conn.execute("PRAGMA table_info(texts)")}
        self.assertIn("reading_seconds", cols)
        self.assertIn("finished_at", cols)


if __name__ == "__main__":
    unittest.main()
