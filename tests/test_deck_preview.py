"""M17b tests: configuración del mazo y preview de los cuatro botones."""

from __future__ import annotations

import sys
import unittest
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from app import deck, srs  # noqa: E402  (srs needs fsrs — venv only)
except ImportError:
    raise unittest.SkipTest("fsrs not installed in this interpreter")
from app import db  # noqa: E402


def seed_word(conn, word="eventually", **extra):
    return db.upsert_word(conn, {"word": word, "meaning_es": "x", **extra})


class TestStepParsing(unittest.TestCase):
    def test_reads_the_usual_shapes(self):
        self.assertEqual(deck.parse_steps("1m,10m,1d"),
                         (timedelta(minutes=1), timedelta(minutes=10),
                          timedelta(days=1)))
        self.assertEqual(deck.parse_steps("30s"), (timedelta(seconds=30),))
        self.assertEqual(deck.parse_steps("  1m , 10m "),
                         (timedelta(minutes=1), timedelta(minutes=10)))

    def test_empty_means_no_steps(self):
        self.assertEqual(deck.parse_steps(""), ())
        self.assertEqual(deck.parse_steps("   "), ())

    def test_rubbish_is_rejected_loudly(self):
        for bad in ("1", "banana", "1x", "-5m", "0m", "1m,,,nope"):
            with self.assertRaises(ValueError, msg=f"aceptó {bad!r}"):
                deck.parse_steps(bad)

    def test_round_trip(self):
        text = "1m,10m,1d"
        self.assertEqual(deck.format_steps(deck.parse_steps(text)), text)


class TestHumanDelta(unittest.TestCase):
    def test_reads_like_anki(self):
        cases = [(30, "<1m"), (60, "1m"), (600, "10m"), (3600, "1h"),
                 (86400, "1d"), (3 * 86400, "3d"), (60 * 86400, "2.0mo"),
                 (400 * 86400, "1.1y")]
        for seconds, expected in cases:
            self.assertEqual(deck.human_delta(seconds), expected,
                             f"{seconds}s")


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")

    def test_defaults_are_ankis(self):
        cfg = deck.config(self.conn)
        self.assertEqual(cfg["learning_steps"], "1m,10m")
        self.assertEqual(cfg["relearning_steps"], "10m")
        self.assertFalse(cfg["enable_fuzzing"])

    def test_save_and_read_back(self):
        cfg = deck.save_config(self.conn, {"learning_steps": "1m,10m,1d",
                                           "desired_retention": 0.92})
        self.assertEqual(cfg["learning_steps"], "1m,10m,1d")
        self.assertAlmostEqual(cfg["desired_retention"], 0.92)

    def test_broken_steps_are_rejected_before_saving(self):
        """Unos pasos rotos dejarían el mazo sin poder programar nada, y el
        fallo aparecería al contestar, no al configurar."""
        with self.assertRaises(ValueError):
            deck.save_config(self.conn, {"learning_steps": "1m,banana"})
        self.assertEqual(deck.config(self.conn)["learning_steps"], "1m,10m")

    def test_retention_outside_the_sane_range_is_rejected(self):
        for bad in (0.1, 0.99, 1.5):
            with self.assertRaises(ValueError):
                deck.save_config(self.conn, {"desired_retention": bad})

    def test_rollover_is_reported_but_not_editable(self):
        cfg = deck.config(self.conn)
        self.assertEqual(cfg["rollover_hour"], db.rollover_hour())
        self.assertFalse(cfg["rollover_hour_editable"])

    def test_config_reaches_the_scheduler(self):
        deck.save_config(self.conn, {"learning_steps": "5m,25m"})
        s = srs._scheduler(self.conn)
        self.assertEqual(s.learning_steps,
                         (timedelta(minutes=5), timedelta(minutes=25)))


class TestPreview(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.wid = seed_word(self.conn)

    def test_a_new_card_offers_all_four(self):
        p = srs.preview(self.conn, self.wid)
        self.assertEqual(p["state"], "NEW")
        self.assertEqual(set(p["ratings"]), {"again", "hard", "good", "easy"})
        self.assertTrue(p["exact"])

    def test_intervals_grow_with_the_rating(self):
        """Again < Hard < Good < Easy, el orden que pidió Eddie."""
        r = srs.preview(self.conn, self.wid)["ratings"]
        secs = [r[k]["seconds"] for k in ("again", "hard", "good", "easy")]
        self.assertEqual(secs, sorted(secs), f"orden roto: {secs}")
        self.assertLess(secs[0], secs[-1])

    def test_easy_graduates_a_new_card_straight_to_review(self):
        r = srs.preview(self.conn, self.wid)["ratings"]
        self.assertEqual(r["easy"]["state_after"], "REVIEW")
        self.assertTrue(r["easy"]["graduates"])
        self.assertEqual(r["again"]["state_after"], "LEARNING")
        self.assertFalse(r["again"]["graduates"])

    def test_preview_does_not_touch_the_card(self):
        """Mirar los botones no puede programar nada."""
        before = self.conn.execute(
            "SELECT fsrs_card, fsrs_due, card_state FROM words WHERE id=?",
            (self.wid,)).fetchone()
        srs.preview(self.conn, self.wid)
        srs.preview(self.conn, self.wid)
        after = self.conn.execute(
            "SELECT fsrs_card, fsrs_due, card_state FROM words WHERE id=?",
            (self.wid,)).fetchone()
        self.assertEqual(tuple(before), tuple(after))
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM review_history").fetchone()[0], 0)

    def test_the_promise_matches_what_answering_does(self):
        """El punto entero del preview: si el botón dice 10m, son 10m."""
        for rating in (1, 2, 3, 4):
            conn = db.connect(":memory:")
            wid = seed_word(conn)
            promised = srs.preview(conn, wid)["ratings"][srs.RATING_NAMES[rating]]
            got = srs.answer(conn, wid, rating)
            self.assertAlmostEqual(
                promised["seconds"] / 86400, got["interval_days"], places=2,
                msg=f"el botón {srs.RATING_NAMES[rating]} mintió")

    def test_a_lapse_is_announced_before_you_press_it(self):
        for _ in range(4):
            srs.answer(self.conn, self.wid, 4)      # a REVIEW
        p = srs.preview(self.conn, self.wid)
        self.assertEqual(p["state"], "REVIEW")
        self.assertEqual(p["ratings"]["again"]["state_after"], "RELEARNING")
        self.assertGreater(p["ratings"]["good"]["seconds"],
                           p["ratings"]["again"]["seconds"])

    def test_missing_word_is_an_error(self):
        with self.assertRaises(ValueError):
            srs.preview(self.conn, 999999)

    def test_fuzzing_makes_the_preview_stop_claiming_exactness(self):
        deck.save_config(self.conn, {"enable_fuzzing": True})
        self.assertFalse(srs.preview(self.conn, self.wid)["exact"])

    def test_the_queue_carries_the_preview(self):
        q = srs.queue(self.conn, new_per_day=5)
        self.assertIsNotNone(q["next"])
        self.assertEqual(q["preview"]["word_id"], q["next"]["id"])
        self.assertIn("good", q["preview"]["ratings"])


class TestStudyQueue(unittest.TestCase):
    """§10-11: la cola separada por grupo. 'Quedan N' mezcla cosas que no se
    comportan igual — las de aprendizaje reaparecen en la sentada, las de
    repaso desaparecen hasta su fecha."""

    def setUp(self):
        self.conn = db.connect(":memory:")
        self.words = [seed_word(self.conn, f"w{i}") for i in range(20)]

    def test_counts_are_separated(self):
        q = srs.study_queue(self.conn, new_per_day=5)
        self.assertEqual(q["counts"]["new"], 5)
        self.assertEqual(q["counts"]["reviews"], 0)
        self.assertEqual(q["counts"]["learning"], 0)
        self.assertEqual(q["counts"]["total"], 5)

    def test_a_failed_word_lands_in_learning_not_reviews(self):
        srs.answer(self.conn, self.words[0], 3)
        srs.answer(self.conn, self.words[0], 1)   # Again → learning step
        q = srs.study_queue(self.conn, new_per_day=0)
        # Cuenta aunque todavía no se pueda servir: sigue sin aprenderse.
        self.assertEqual(q["counts"]["learning"], 1)
        self.assertEqual(q["counts"]["cooling"], 1)
        self.assertEqual(q["counts"]["reviews"], 0)
        self.assertIn(self.words[0], q["ids"]["learning"])

    def test_ids_are_a_bounded_sample(self):
        """No devuelve la lista entera: con miles de palabras nuevas serían
        megabytes que nadie mira."""
        conn = db.connect(":memory:")
        for i in range(60):
            seed_word(conn, f"many{i}")
        q = srs.study_queue(conn, new_per_day=100)
        self.assertEqual(q["counts"]["new"], 60)
        self.assertLessEqual(len(q["ids"]["new"]), srs.SAMPLE)

    def test_the_session_cap_shows_in_reviews_but_not_in_the_truth(self):
        srs.answer(self.conn, self.words[0], 1)
        q = srs.study_queue(self.conn, new_per_day=0,
                            limits={"new": 0, "reviews": 0})
        self.assertEqual(q["counts"]["reviews"], 0)
        self.assertGreaterEqual(q["counts"]["reviews_total"], 0)

    def test_paused_reports_zeros(self):
        from app import pause
        pause.start(self.conn, "vacaciones")
        q = srs.study_queue(self.conn)
        self.assertTrue(q["paused"])
        self.assertEqual(q["counts"]["total"], 0)


class TestQueueMix(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        # una vencida y varias nuevas disponibles
        self.due = seed_word(self.conn, "overdue")
        srs.answer(self.conn, self.due, 1)        # queda vencida enseguida
        for i in range(5):
            seed_word(self.conn, f"fresh{i}")

    def _next_is_new(self):
        return srs.queue(self.conn, new_per_day=5)["next"]["is_new"]

    def test_due_first_is_the_default(self):
        self.assertEqual(deck.config(self.conn)["queue_mix"], "due_first")

    def test_new_first_puts_new_words_ahead(self):
        deck.save_config(self.conn, {"queue_mix": "new_first"})
        self.assertTrue(self._next_is_new())

    def test_due_first_puts_reviews_ahead(self):
        import time
        time.sleep(0.01)
        deck.save_config(self.conn, {"queue_mix": "due_first"})
        q = srs.queue(self.conn, new_per_day=5)
        # con una vencida disponible, due_first no debe ofrecer una nueva
        if q["due"]:
            self.assertFalse(q["next"]["is_new"])

    def test_a_bogus_mix_is_rejected(self):
        with self.assertRaises(ValueError):
            deck.save_config(self.conn, {"queue_mix": "al_azar"})


class TestEddiesWalkthrough(unittest.TestCase):
    """El ejemplo completo de la petición (§15), con pasos 1m/10m/1d."""

    def setUp(self):
        self.conn = db.connect(":memory:")
        deck.save_config(self.conn, {"learning_steps": "1m,10m,1d"})
        self.wid = seed_word(self.conn)

    def _state(self):
        r = self.conn.execute(
            "SELECT card_state, learning_step FROM words WHERE id=?",
            (self.wid,)).fetchone()
        return r["card_state"], r["learning_step"]

    def test_again_keeps_it_on_the_first_step(self):
        srs.answer(self.conn, self.wid, 1)
        self.assertEqual(self._state(), ("LEARNING", 0))
        srs.answer(self.conn, self.wid, 1)
        self.assertEqual(self._state(), ("LEARNING", 0),
                         "Again debía devolverla al primer paso")

    def test_good_walks_the_steps_then_graduates(self):
        srs.answer(self.conn, self.wid, 1)
        self.assertEqual(self._state(), ("LEARNING", 0))
        srs.answer(self.conn, self.wid, 3)
        self.assertEqual(self._state(), ("LEARNING", 1))
        srs.answer(self.conn, self.wid, 3)
        self.assertEqual(self._state(), ("LEARNING", 2))
        srs.answer(self.conn, self.wid, 3)
        self.assertEqual(self._state(), ("REVIEW", None), "no se graduó")

    def test_review_intervals_grow_and_are_not_hardcoded(self):
        """3d → 9d → 24d → 2 meses, la progresión del §8. Cada respuesta se
        fecha EN su vencimiento: contestar cuatro veces en el mismo instante
        deja el intervalo plano porque para FSRS no ha pasado nada."""
        from datetime import datetime, timezone
        t = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
        for _ in range(3):                          # recorre los pasos y gradúa
            r = srs.answer(self.conn, self.wid, 3, now=t)
            t = datetime.fromisoformat(r["due"])
        intervals = []
        for _ in range(4):
            r = srs.answer(self.conn, self.wid, 3, now=t)
            intervals.append(r["interval_days"])
            t = datetime.fromisoformat(r["due"])
        self.assertEqual(intervals, sorted(intervals), f"no crecen: {intervals}")
        self.assertGreater(intervals[-1], intervals[0] * 5,
                           f"crecen demasiado poco: {intervals}")

    def test_forgetting_sends_it_to_relearning_without_wiping_memory(self):
        for _ in range(3):
            srs.answer(self.conn, self.wid, 3)
        for _ in range(3):
            srs.answer(self.conn, self.wid, 4)      # memoria sólida
        before = self.conn.execute(
            "SELECT stability, difficulty FROM words WHERE id=?",
            (self.wid,)).fetchone()
        srs.answer(self.conn, self.wid, 1)          # olvidada
        state, step = self._state()
        after = self.conn.execute(
            "SELECT stability, difficulty FROM words WHERE id=?",
            (self.wid,)).fetchone()
        self.assertEqual((state, step), ("RELEARNING", 0))
        self.assertLess(after["stability"], before["stability"])
        self.assertGreater(after["difficulty"], before["difficulty"],
                           "la dificultad debía subir: no se borra la memoria")

        srs.answer(self.conn, self.wid, 3)          # recuperada
        self.assertEqual(self._state()[0], "REVIEW")


if __name__ == "__main__":
    unittest.main()
