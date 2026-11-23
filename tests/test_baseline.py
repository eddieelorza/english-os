"""MVP 5: línea base de vocabulario y dictado, calificada sin modelo."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import baseline, db  # noqa: E402

REAL = {w: (b, width) for b, width, s in baseline.VOCAB_BANDS for w in s.split()}


def answers(known_bands=(), pseudo_yes=0):
    out = {w: b in known_bands for w, (b, _) in REAL.items()}
    out.update({p: i < pseudo_yes for i, p in enumerate(baseline.PSEUDO)})
    return out


class TestVocab(unittest.TestCase):
    def test_items_are_disjoint_and_pseudowords_are_not_in_the_bank(self):
        self.assertEqual(len(REAL), 60)
        self.assertFalse(set(REAL) & set(baseline.PSEUDO))
        self.assertEqual(sorted(baseline.vocab_items(1)), sorted([*REAL, *baseline.PSEUDO]))

    def test_size_sums_the_known_bands(self):
        r = baseline.score_vocab(answers(known_bands=(1, 2, 3)))
        self.assertEqual(r["size"], 4000)
        self.assertEqual(r["cefr"], "C1")
        self.assertEqual(r["false_alarms"], 0)

    def test_false_alarms_discount_the_hits(self):
        honest = baseline.score_vocab(answers(known_bands=(1, 2)))
        guessing = baseline.score_vocab(answers(known_bands=(1, 2), pseudo_yes=5))
        self.assertEqual(honest["size"], 2000)
        self.assertEqual(guessing["size"], 2000)        # bandas al 100% siguen al 100%
        everything = baseline.score_vocab({w: True for w in [*REAL, *baseline.PSEUDO]})
        self.assertEqual(everything["size"], 0)          # decir sí a todo no mide nada
        self.assertEqual(everything["confidence"], "very low")

    def test_incomplete_or_foreign_answers_are_rejected(self):
        partial = answers()
        partial.pop("window")
        with self.assertRaises(ValueError):
            baseline.score_vocab(partial)
        with self.assertRaises(ValueError):
            baseline.score_vocab({**answers(), "banana": True})


class TestDictation(unittest.TestCase):
    def perfect(self):
        return [t for _, t in baseline.DICTATION]

    def test_perfect_is_the_top_band(self):
        r = baseline.score_dictation(self.perfect())
        self.assertEqual((r["band"], r["accuracy"]), ("C2", 1.0))

    def test_case_punctuation_and_curly_apostrophes_do_not_count(self):
        given = [t.upper().replace("'", "’").rstrip(".") for t in self.perfect()]
        self.assertEqual(baseline.score_dictation(given)["accuracy"], 1.0)

    def test_contractions_written_out_count_as_heard(self):
        given = self.perfect()
        given[3] = "If the build fails again I will check the logs tonight"
        given[4] = "The client was not happy with the delay but they agreed to a new deadline"
        self.assertEqual(baseline.score_dictation(given)["accuracy"], 1.0)

    def test_the_first_failed_level_caps_the_band(self):
        given = self.perfect()
        given[4] = given[5] = ""                         # B2 en blanco
        r = baseline.score_dictation(given)
        self.assertEqual(r["band"], "B1")

    def test_word_errors_lower_accuracy(self):
        given = self.perfect()
        given[0] = "I usually take a bus to work in the morning."   # 1 de 10 palabras
        self.assertEqual(baseline.score_dictation(given)["items"][0]["accuracy"], 0.9)

    def test_wrong_count_is_rejected(self):
        with self.assertRaises(ValueError):
            baseline.score_dictation(["hello"])


class TestSave(unittest.TestCase):
    def test_latest_is_per_kind(self):
        conn = db.connect(":memory:")
        self.addCleanup(conn.close)
        self.assertEqual(baseline.latest(conn), {"vocab": None, "dictation": None})
        a = answers(known_bands=(1,))
        baseline.save(conn, "vocab", baseline.score_vocab(a), a)
        out = baseline.latest(conn)
        self.assertEqual(out["vocab"]["size"], 1000)
        self.assertIn("taken_at", out["vocab"])
        self.assertIsNone(out["dictation"])


if __name__ == "__main__":
    unittest.main()
