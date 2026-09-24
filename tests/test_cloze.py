"""ADR-016 tests: el vocabulario en contexto sale del mazo, sin modelo, y la app
no genera una lectura nueva mientras haya una sin leer."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import activities, db, jobs  # noqa: E402

EXAMPLES = {
    "forge": ("They forge a strong alliance every year.", "forjar"),
    "arise": ("Problems arise when nobody listens.", "surgir"),
    "endure": ("Plants endure the cold of winter here.", "soportar"),
    "prosper": ("Honest shops prosper in this town.", "prosperar"),
    "wrinkle": ("Wrinkle cream is sold in that shop.", "arruga"),
    "quarrel": ("They had a quarrel about money.", "pelea"),
}


def seeded(examples=EXAMPLES):
    conn = db.connect(":memory:")
    for w, (ex, es) in examples.items():
        db.upsert_word(conn, {"word": w, "status": "LEARNING", "meaning_es": es,
                              "example_en": ex})
    return conn


class TestCloze(unittest.TestCase):
    def test_it_cuts_the_deck_sentence_and_keeps_the_word_as_the_answer(self):
        qs = activities._cloze(seeded())
        self.assertEqual(len(qs), activities.CLOZE_QUESTIONS)
        for q in qs:
            self.assertEqual(q["prompt"].count("___"), 1)
            self.assertEqual(len(q["options"]), 3)
            self.assertEqual(len(set(q["options"])), 3)
            answer = q["options"][q["answer_index"]]
            self.assertIn(answer.lower(), EXAMPLES)
            self.assertEqual(q["prompt"].replace("___", answer).lower(),
                             EXAMPLES[answer.lower()][0].lower())
            self.assertEqual(q["category"], "Vocabulario")
            self.assertIn(EXAMPLES[answer.lower()][1], q["why"])

    def test_a_sentence_start_capitalizes_every_option_so_it_gives_nothing_away(self):
        qs = activities._cloze(seeded(), n=6)      # las 6, no sólo las 4 primeras
        q = next(q for q in qs if q["prompt"].startswith("___"))
        self.assertTrue(all(o[:1].isupper() for o in q["options"]))

    def test_inflected_forms_are_skipped_because_the_base_option_would_not_fit(self):
        ex = dict(EXAMPLES)
        ex["forge"] = ("He forged a strong alliance last year.", "forjar")
        for q in activities._cloze(seeded(ex)):
            self.assertNotIn("forged", q["prompt"])
            self.assertNotEqual(q["options"][q["answer_index"]].lower(), "forge")

    def test_a_word_that_appears_twice_is_skipped(self):
        ex = dict(EXAMPLES)
        ex["arise"] = ("Problems arise and arise again and again.", "surgir")
        for q in activities._cloze(seeded(ex)):
            self.assertNotEqual(q["options"][q["answer_index"]].lower(), "arise")

    def test_distractors_prefer_words_that_fit_the_same_slot(self):
        """Tras "the" va un sustantivo: un adjetivo o un verbo se descartarían
        sin pensar. Hay 3 sustantivos tras artículo y 3 palabras de otro tipo."""
        ex = {"coal": ("Many stations burn the coal here.", "carbón"),
              "dial": ("I looked at the dial again.", "esfera"),
              "beam": ("She fixed the beam yesterday.", "viga"),
              "sore": ("My back was very sore.", "dolorido"),
              "wrestle": ("They wish to wrestle tonight.", "luchar"),
              "deceive": ("Do not try to deceive them.", "engañar")}
        conn = seeded(ex)
        for _ in range(30):                       # el azar no puede romperlo
            for q in activities._cloze(conn, n=6):
                if not q["prompt"].endswith("the ___ here.") and "the ___" not in q["prompt"]:
                    continue
                self.assertTrue(set(o.lower() for o in q["options"]) <= {"coal", "dial", "beam"},
                                q["options"])

    def test_no_example_no_question_and_no_crash(self):
        self.assertEqual(activities._cloze(seeded({"a": ("", "x"), "b": ("", "y"),
                                                   "c": ("", "z")})), [])

    def test_it_never_asks_a_model_when_the_deck_has_enough(self):
        conn = seeded()
        with mock.patch.object(activities.ai, "get_provider",
                               side_effect=AssertionError("llamó a la IA")):
            built = activities._vocabulary_check(conn)
        self.assertEqual(built["kind"], "vocabulary_check")
        self.assertEqual(len(built["questions"]), activities.CLOZE_QUESTIONS)

    def test_with_too_few_examples_it_falls_back_to_the_model(self):
        conn = seeded({**{k: ("", "x") for k in ("a", "b", "c", "d", "e")},
                       "forge": EXAMPLES["forge"]})
        fake = mock.Mock()
        fake.generate_json.return_value = {"questions": [{
            "prompt": "He ___ ahead.", "options": ["a", "b", "c"], "answer_index": 0,
            "why": "porque", "category": "Vocabulario"}]}
        with mock.patch.object(activities.ai, "get_provider", return_value=fake):
            built = activities._vocabulary_check(conn)
        self.assertTrue(fake.generate_json.called)
        self.assertEqual(len(built["questions"]), 1)

    def test_the_activity_grades_and_feeds_the_error_table_like_any_other(self):
        conn = seeded()
        with mock.patch.object(activities.ai, "get_provider",
                               side_effect=AssertionError("llamó a la IA")), \
                mock.patch.object(activities, "_grammar_quiz",
                                  return_value={"kind": "grammar_quiz", "title": "g",
                                                "questions": []}):
            acts = activities.today_set(conn)
        vocab = next(a for a in acts if a["kind"] == "vocabulary_check")
        wrong = [(q["answer_index"] + 1) % 3 for q in vocab["questions"]]
        r = activities.submit(conn, vocab["id"], wrong)
        self.assertEqual(r["score"], 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM errors").fetchone()[0],
                         len(vocab["questions"]))


class TestDailyReadingGuard(unittest.TestCase):
    def setUp(self):
        self.conn = seeded()

    def _reading(self, days_ago, read):
        self.conn.execute(
            "INSERT INTO texts (kind, title, body, date, finished_at, created_at, "
            "updated_at) VALUES ('reading','T','b',date(?, ?),?,?,?)",
            (db.study_day(), f"-{days_ago} days", db.now_iso() if read else None,
             db.now_iso(), db.now_iso()))
        self.conn.commit()

    def test_closing_a_sitting_asks_for_a_reading_when_none_is_waiting(self):
        r = jobs.enqueue_daily(self.conn)
        self.assertFalse(r["reading_skipped"])
        self.assertEqual(len(r["queued"]), 4)

    def test_it_does_not_pile_up_when_an_unread_one_is_waiting(self):
        self._reading(1, read=False)
        r = jobs.enqueue_daily(self.conn)
        self.assertTrue(r["reading_skipped"])
        self.assertIn("unread", r["reading_skip_reason"])
        self.assertEqual(len(r["queued"]), 3, "sólo actividades, consejo y writing")

    def test_a_read_one_does_not_hold_the_next_back(self):
        self._reading(1, read=True)
        self.assertFalse(jobs.enqueue_daily(self.conn)["reading_skipped"])

    def test_an_old_unread_one_does_not_block_forever(self):
        self._reading(10, read=False)
        self.assertFalse(jobs.enqueue_daily(self.conn)["reading_skipped"])


if __name__ == "__main__":
    unittest.main()
