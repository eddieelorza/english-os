"""M4 tests: FSRS seeding from history, answering, queue, status transitions."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from app import srs  # noqa: E402  (needs the fsrs package — venv only)
except ImportError:
    raise unittest.SkipTest("fsrs not installed in this interpreter")
from app import db  # noqa: E402


def age_last_review(conn, wid, minutes):
    """Envejece el último repaso. Los pasos miden tiempo transcurrido, así que
    un test que contesta tres veces en el mismo milisegundo no puede
    comprobar nada sobre ellos."""
    from datetime import timedelta
    stale = (srs._now().astimezone().replace(tzinfo=None)
             - timedelta(minutes=minutes)).isoformat(timespec="seconds")
    conn.execute("UPDATE words SET last_reviewed_on=? WHERE id=?", (stale, wid))


def seed_word(conn, word, reviews=(), **extra):
    wid = db.upsert_word(conn, {"word": word, "meaning_es": "x", **extra})
    for ts, rating in reviews:
        db.insert_review(conn, {"word_id": wid, "reviewed_at": ts,
                                "rating": rating, "source": "anki"})
    return wid


class TestSeeding(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")

    def test_replay_creates_card_with_due(self):
        wid = seed_word(self.conn, "forge", [
            ("2026-08-01T10:00:00", 3),
            ("2026-08-02T10:00:00", 3),
            ("2026-08-05T10:00:00", 4),
        ])
        stats = srs.seed_from_history(self.conn)
        self.assertEqual(stats["seeded"], 1)
        row = self.conn.execute("SELECT * FROM words WHERE id=?", (wid,)).fetchone()
        self.assertIsNotNone(row["fsrs_card"])
        self.assertIsNotNone(row["fsrs_due"])
        self.assertEqual(row["fsrs_since"], "2026-08-01")

    def test_seed_is_idempotent_and_preserves_live_progress(self):
        wid = seed_word(self.conn, "arise", [("2026-08-01T10:00:00", 3)])
        srs.seed_from_history(self.conn)
        first = self.conn.execute(
            "SELECT fsrs_card FROM words WHERE id=?", (wid,)).fetchone()[0]
        srs.answer(self.conn, wid, 3)  # live in-app review
        stats = srs.seed_from_history(self.conn)  # re-seed must not clobber
        self.assertEqual(stats["seeded"], 0)
        after = self.conn.execute(
            "SELECT fsrs_card FROM words WHERE id=?", (wid,)).fetchone()[0]
        self.assertNotEqual(first, after)

    def test_words_without_history_not_seeded(self):
        seed_word(self.conn, "new-word")
        stats = srs.seed_from_history(self.conn)
        self.assertEqual(stats["seeded"], 0)


class TestAnswering(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")

    def test_first_answer_introduces_card(self):
        wid = seed_word(self.conn, "forge")
        r = srs.answer(self.conn, wid, 3)
        self.assertTrue(r["introduced"])
        self.assertEqual(r["status"], "LEARNING")
        n = self.conn.execute(
            "SELECT COUNT(*) FROM review_history WHERE source='fsrs'").fetchone()[0]
        self.assertEqual(n, 1)

    def test_repeated_good_answers_grow_interval(self):
        wid = seed_word(self.conn, "endure")
        last = 0.0
        for _ in range(6):
            r = srs.answer(self.conn, wid, 4)
        self.assertGreater(r["interval_days"], last)
        row = self.conn.execute("SELECT * FROM words WHERE id=?", (wid,)).fetchone()
        self.assertGreaterEqual(row["review_count"], 6)

    def test_invalid_rating_rejected(self):
        wid = seed_word(self.conn, "forge")
        with self.assertRaises(ValueError):
            srs.answer(self.conn, wid, 5)


class TestQueue(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")

    def test_new_words_offered_within_budget(self):
        for i in range(8):
            seed_word(self.conn, f"word{i}")
        q = srs.queue(self.conn, new_per_day=5)
        self.assertEqual(q["due"], 0)
        self.assertEqual(q["new_available"], 5)
        self.assertTrue(q["next"]["is_new"])

    def test_introductions_consume_budget(self):
        wids = [seed_word(self.conn, f"w{i}") for i in range(4)]
        for wid in wids[:3]:
            srs.answer(self.conn, wid, 3)
        q = srs.queue(self.conn, new_per_day=5)
        self.assertEqual(q["introduced_today"], 3)
        self.assertEqual(q["new_available"], 1)

    def test_due_beats_new(self):
        wid = seed_word(self.conn, "due-word", [("2026-01-01T10:00:00", 3)])
        seed_word(self.conn, "fresh-word")
        srs.seed_from_history(self.conn)  # due long ago
        q = srs.queue(self.conn)
        self.assertGreaterEqual(q["due"], 1)
        self.assertEqual(q["next"]["id"], wid)
        self.assertFalse(q["next"]["is_new"])


class TestLearnAhead(unittest.TestCase):
    """A word rated Again must not vanish from the session for a whole
    minute — that is how you get told 'the deck is clear' while the word you
    just failed is still unlearned (ADR-009)."""

    def setUp(self):
        self.conn = db.connect(":memory:")

    def test_failed_word_comes_back_in_the_same_session(self):
        wid = seed_word(self.conn, "endure")
        srs.answer(self.conn, wid, 3)   # introduce it
        srs.answer(self.conn, wid, 1)   # Again → due in ~1 minute

        q = srs.queue(self.conn, new_per_day=0)
        self.assertEqual(q["due"], 0, "not due by the clock yet")
        self.assertEqual(q["learning"], 1, "the failed word disappeared")
        # Al instante no vuelve — su paso es un minuto y un paso mide tiempo.
        # Pero tampoco se esconde: la sentada sabe que sigue ahí y cuándo.
        self.assertEqual(q["cooling"], 1)
        self.assertIsNotNone(q["resume_at"])

        age_last_review(self.conn, wid, 2)
        q = srs.queue(self.conn, new_per_day=0)
        self.assertIsNotNone(q["next"], "no volvió ni pasado su paso")
        self.assertEqual(q["next"]["id"], wid)

    def test_new_word_is_offered_before_a_learn_ahead_card(self):
        failed = seed_word(self.conn, "endure")
        srs.answer(self.conn, failed, 3)
        srs.answer(self.conn, failed, 1)
        seed_word(self.conn, "fresh")

        q = srs.queue(self.conn, new_per_day=5)
        self.assertTrue(q["next"]["is_new"], "should space the failed word out")
        self.assertFalse(q["ahead"])
        self.assertEqual(q["learning"], 1, "still counted as pending")

    def test_settled_card_is_not_shown_ahead(self):
        """Only Learning/Relearning cards get the early pass. A card due in
        three weeks must stay where it is."""
        wid = seed_word(self.conn, "prosper")
        for _ in range(4):
            srs.answer(self.conn, wid, 4)  # push it into Review with a long gap
        q = srs.queue(self.conn, new_per_day=0)
        self.assertEqual(q["learning"], 0)
        self.assertIsNone(q["next"])

    def test_the_clock_rules_while_there_is_other_work(self):
        """Con algo más que hacer, una card que acabas de ACERTAR no se
        adelanta: si no, la sentada se alimenta sola y un plan de 9 cards se
        va a 16 (ADR-009 D2 rev.)."""
        wid = seed_word(self.conn, "endure")
        srs.answer(self.conn, wid, 3)   # introducir
        srs.answer(self.conn, wid, 1)   # Otra vez -> vuelve al minuto
        srs.answer(self.conn, wid, 3)   # acertada -> paso de 10 min
        seed_word(self.conn, "fresh")   # queda otra cosa que hacer

        q = srs.queue(self.conn, new_per_day=5)
        self.assertEqual(q["learning_now"], 0, "se adelantó teniendo alternativa")
        self.assertTrue(q["next"]["is_new"], "debía ofrecer la palabra nueva")

    def test_with_nothing_else_left_it_comes_back_anyway(self):
        """Y aquí la otra mitad: sin nada más que hacer, esperar 10 minutos
        mirando "nothing to study" no enseña nada. La card vuelve ya."""
        wid = seed_word(self.conn, "endure")
        srs.answer(self.conn, wid, 3)
        srs.answer(self.conn, wid, 1)
        srs.answer(self.conn, wid, 3)   # paso de 10 min
        age_last_review(self.conn, wid, 2)   # ya se enfrió el paso corto

        q = srs.queue(self.conn, new_per_day=0)
        self.assertEqual(q["learning_now"], 0, "no vence por reloj todavía")
        self.assertEqual(q["learning"], 1, "pero sigue pendiente")
        self.assertIsNotNone(q["next"], "dijo que no quedaba nada y sí quedaba")
        self.assertEqual(q["next"]["id"], wid)
        self.assertTrue(q["ahead"])

    def test_the_sitting_still_ends(self):
        """Abrir la ventana no puede volverla infinita: al graduarse, la card
        sale de la escalera y ya no vuelve."""
        wid = seed_word(self.conn, "endure")
        for _ in range(6):
            q = srs.queue(self.conn, new_per_day=0)
            if q["next"] is None:
                break
            srs.answer(self.conn, q["next"]["id"], 3)
        else:
            self.fail("la sentada no terminó en 6 respuestas")
        self.assertIsNone(srs.queue(self.conn, new_per_day=0)["next"])

    def test_it_does_not_pull_tomorrows_work(self):
        """La ventana ancha llega hasta la escalera de aprendizaje, no más.
        Una card graduada a días vista no es 'learn-ahead'."""
        wid = seed_word(self.conn, "prosper")
        for _ in range(4):
            srs.answer(self.conn, wid, 4)   # a REVIEW con intervalo largo
        q = srs.queue(self.conn, new_per_day=0)
        self.assertEqual(q["learning"], 0)
        self.assertIsNone(q["next"])

    def test_a_card_just_answered_does_not_come_straight_back(self):
        """El bug de 2026-08-24: sin nada más que hacer, la ventana ancha
        servía la MISMA card dos segundos después de contestarla. Seis
        respuestas en 55 segundos hunden la estabilidad (0.21 -> 0.07) y
        entonces hasta Easy ofrece 1d. Un paso mide tiempo transcurrido; si no
        transcurre, no es un paso."""
        wid = seed_word(self.conn, "trim")
        srs.answer(self.conn, wid, 3)   # introducir -> paso de 1 min
        srs.answer(self.conn, wid, 1)   # Otra vez   -> vuelve al minuto

        q = srs.queue(self.conn, new_per_day=0)
        self.assertIsNone(q["next"], "la sirvió al instante otra vez")
        self.assertEqual(q["cooling"], 1, "sigue pendiente, sólo enfriándose")
        self.assertEqual(q["learning"], 1, "no puede desaparecer de la cuenta")
        self.assertIsNotNone(q["resume_at"], "hay que poder decir cuándo vuelve")

    def test_the_floor_is_the_shortest_step_not_the_longest(self):
        """El suelo no cancela el adelanto, sólo lo acota: pasado el paso
        corto, una card parada en el de 10 minutos sí se adelanta."""
        wid = seed_word(self.conn, "upwards")
        srs.answer(self.conn, wid, 3)   # introducir -> paso de 10 min
        # Pasó el paso corto (1 min), no el largo (10 min).
        age_last_review(self.conn, wid, 2)

        q = srs.queue(self.conn, new_per_day=0)
        self.assertEqual(q["cooling"], 0)
        self.assertIsNotNone(q["next"], "se pasó de prudente y volvió a esperar")
        self.assertTrue(q["ahead"])

    def test_pause_reports_nothing_learning(self):
        from app import pause
        wid = seed_word(self.conn, "endure")
        srs.answer(self.conn, wid, 3)
        srs.answer(self.conn, wid, 1)
        pause.start(self.conn, "vacaciones")
        q = srs.queue(self.conn)
        self.assertEqual(q["learning"], 0)
        self.assertIsNone(q["next"])
        self.assertTrue(q["paused"])


if __name__ == "__main__":
    unittest.main()
