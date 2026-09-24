"""M16b tests: ajustes, ritmo medido, plan y el tope que la cola respeta."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from app import session, srs  # noqa: E402  (srs needs fsrs — venv only)
except ImportError:
    raise unittest.SkipTest("fsrs not installed in this interpreter")
from app import db  # noqa: E402


def seed_word(conn, word, **extra):
    return db.upsert_word(conn, {"word": word, "meaning_es": "x", **extra})


def fake_reviews(conn, word_id, n, seconds_apart, kind="review"):
    """n repasos in-app espaciados, para poder medir el ritmo."""
    start = datetime.fromisoformat(db.now_iso()) - timedelta(hours=2)
    for i in range(n):
        db.insert_review(conn, {
            "word_id": word_id,
            "reviewed_at": (start + timedelta(seconds=i * seconds_apart)).isoformat(),
            "rating": 3, "review_kind": kind, "source": "fsrs"})


class TestSettings(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")

    def test_defaults_when_nothing_saved(self):
        s = session.settings(self.conn)
        self.assertEqual(s["mode"], "time")
        self.assertEqual(s["minutes"], 20)

    def test_save_and_read_back(self):
        s = session.save_settings(self.conn, {"minutes": 30, "new": 6, "reviews": 25})
        self.assertEqual((s["minutes"], s["new"], s["reviews"]), (30, 6, 25))
        self.assertEqual(session.settings(self.conn)["minutes"], 30)

    def test_bad_mode_rejected(self):
        with self.assertRaises(ValueError):
            session.save_settings(self.conn, {"mode": "vibes"})

    def test_negative_values_clamped(self):
        s = session.save_settings(self.conn, {"reviews": -5})
        self.assertEqual(s["reviews"], 0)


class TestMigration(unittest.TestCase):
    """Una base que ya existía debe recibir las columnas nuevas.

    `CREATE TABLE IF NOT EXISTS` no toca una tabla ya creada: añadir una
    columna sólo al DDL deja rotas las bases existentes (pasó con
    `from_review_id`, y sólo se vio al abrir la app de verdad).
    """

    def test_existing_study_sessions_table_gains_from_review_id(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "old.db")
            old = db.connect(path)
            old.execute("DROP TABLE study_sessions")
            old.execute(  # el DDL tal como nació, sin la columna
                "CREATE TABLE study_sessions (id INTEGER PRIMARY KEY, "
                "started_at TEXT NOT NULL, ended_at TEXT, mode TEXT NOT NULL, "
                "minutes INTEGER, planned_new INTEGER NOT NULL, "
                "planned_reviews INTEGER NOT NULL)")
            old.commit()
            old.close()

            conn = db.connect(path)  # reabrir aplica migraciones
            cols = {r[1] for r in conn.execute("PRAGMA table_info(study_sessions)")}
            self.assertIn("from_review_id", cols)
            session.start(conn, mode="counts", new=1, reviews=0)
            self.assertTrue(session.progress(conn)["active"])


class TestPace(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")

    def test_without_sample_uses_the_conservative_default_and_says_so(self):
        p = session.pace(self.conn)
        self.assertFalse(p["measured"])
        self.assertEqual(p["seconds_per_card"], session.DEFAULT_SECONDS_PER_CARD)
        self.assertIn("not measured yet", p["note"])

    def test_with_enough_sample_it_measures(self):
        wid = seed_word(self.conn, "endure")
        fake_reviews(self.conn, wid, 40, seconds_apart=8)
        p = session.pace(self.conn)
        self.assertTrue(p["measured"])
        self.assertAlmostEqual(p["seconds_per_card"], 8.0, places=1)
        self.assertIsNone(p["note"])

    def test_long_gaps_are_not_counted_as_cards(self):
        """Levantarse por un café no significa que la card tardó 20 minutos."""
        wid = seed_word(self.conn, "endure")
        fake_reviews(self.conn, wid, 40, seconds_apart=8)
        db.insert_review(self.conn, {
            "word_id": wid, "reviewed_at": db.now_iso(),
            "rating": 3, "review_kind": "review", "source": "fsrs"})
        p = session.pace(self.conn)
        self.assertLess(p["seconds_per_card"], session.MAX_GAP_SECONDS)


class TestPlan(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        for i in range(40):
            seed_word(self.conn, f"word{i}")

    def test_time_mode_fits_the_budget(self):
        p = session.plan(self.conn, mode="time", minutes=20)
        self.assertLessEqual(p["estimated_minutes"], 20.5)
        self.assertEqual(p["total"], p["new"] + p["reviews"])

    def test_more_minutes_never_plans_less(self):
        short = session.plan(self.conn, mode="time", minutes=10)
        long = session.plan(self.conn, mode="time", minutes=30)
        self.assertGreaterEqual(long["total"], short["total"])

    def test_counts_mode_honours_the_numbers(self):
        session.save_settings(self.conn, {"new_per_day": 10})
        p = session.plan(self.conn, mode="counts", new=6, reviews=25)
        self.assertEqual(p["new"], 6)
        self.assertEqual(p["reviews"], 0)   # nada vencido todavía
        self.assertIn("nothing due right now", p["short"])

    def test_plan_never_promises_more_new_than_the_daily_cap(self):
        session.save_settings(self.conn, {"new_per_day": 3})
        p = session.plan(self.conn, mode="counts", new=20, reviews=0)
        self.assertEqual(p["new"], 3)

    def test_plan_is_empty_while_paused(self):
        from app import pause
        pause.start(self.conn, "vacaciones")
        p = session.plan(self.conn, mode="time", minutes=30)
        self.assertTrue(p["paused"])
        self.assertEqual(p["total"], 0)


class TestSessionLifecycle(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.words = [seed_word(self.conn, f"word{i}") for i in range(20)]

    def test_start_creates_one_active_session(self):
        session.start(self.conn, mode="counts", new=3, reviews=0)
        session.start(self.conn, mode="counts", new=2, reviews=0)
        open_rows = self.conn.execute(
            "SELECT COUNT(*) FROM study_sessions WHERE ended_at IS NULL").fetchone()[0]
        self.assertEqual(open_rows, 1, "dos sesiones abiertas a la vez")

    def test_progress_counts_from_the_review_log(self):
        session.start(self.conn, mode="counts", new=3, reviews=0)
        srs.answer(self.conn, self.words[0], 3)
        srs.answer(self.conn, self.words[1], 3)
        p = session.progress(self.conn)
        self.assertEqual(p["done_new"], 2)
        self.assertEqual(p["remaining_new"], 1)

    def test_learning_step_reviews_do_not_count_as_new_words(self):
        """Repasar una card en paso de aprendizaje NO es introducir una palabra.
        Se contaban iguales ('learn') y una sesión de 5 nuevas + 5 repasos
        cerraba diciendo "10 new · 0 reviewed" — y además gastaba el cupo
        equivocado."""
        wid = self.words[0]
        srs.answer(self.conn, wid, 3)   # introducción -> cuenta como nueva
        session.start(self.conn, mode="counts", new=5, reviews=5)
        srs.answer(self.conn, wid, 1)   # sigue en learning
        srs.answer(self.conn, wid, 3)   # repaso del paso de aprendizaje
        p = session.progress(self.conn)
        self.assertEqual(p["done_new"], 0, "contó repasos como palabras nuevas")
        self.assertEqual(p["done_reviews"], 2)
        # el cupo de nuevas sigue entero: dos repasos no lo tocan
        self.assertEqual(session.limits(self.conn)["new"], p["planned_new"],
                         "gastó el cupo de nuevas")

    def test_limits_shrink_as_you_work(self):
        session.start(self.conn, mode="counts", new=2, reviews=0)
        self.assertEqual(session.limits(self.conn)["new"], 2)
        srs.answer(self.conn, self.words[0], 3)
        self.assertEqual(session.limits(self.conn)["new"], 1)

    def test_no_session_means_no_limits(self):
        self.assertIsNone(session.limits(self.conn))

    def test_yesterdays_open_session_does_not_survive(self):
        """Levantarse sin cerrar no te deja dentro de la sentada al día
        siguiente: el contador arrastraría los repasos de ayer."""
        self.conn.execute(
            "INSERT INTO study_sessions (started_at, mode, minutes, "
            "planned_new, planned_reviews, from_review_id) "
            "VALUES ('2026-01-01T10:00:00','counts',NULL,5,10,0)")
        self.conn.commit()
        self.assertIsNone(session.active(self.conn))
        self.assertFalse(session.progress(self.conn)["active"])
        closed = self.conn.execute(
            "SELECT ended_at FROM study_sessions").fetchone()[0]
        self.assertIsNotNone(closed)

    def test_end_closes_it(self):
        session.start(self.conn, mode="counts", new=3, reviews=0)
        r = session.end(self.conn)
        self.assertTrue(r["ended"])
        self.assertIsNone(session.active(self.conn))
        self.assertFalse(session.end(self.conn)["ended"])


class TestQueueRespectsTheSession(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.words = [seed_word(self.conn, f"word{i}") for i in range(20)]

    def test_new_words_stop_when_the_session_budget_is_spent(self):
        session.save_settings(self.conn, {"new_per_day": 10})
        session.start(self.conn, mode="counts", new=2, reviews=0)
        for _ in range(2):
            q = srs.queue(self.conn, new_per_day=10, limits=session.limits(self.conn))
            srs.answer(self.conn, q["next"]["id"], 3)
        q = srs.queue(self.conn, new_per_day=10, limits=session.limits(self.conn))
        self.assertEqual(q["new_available"], 0, "siguió ofreciendo palabras nuevas")

    def test_capped_due_cards_are_hidden_but_still_counted(self):
        """El tope oculta repasos de ESTA sesión; no finge que dejaron de
        estar vencidos."""
        wid = self.words[0]
        srs.answer(self.conn, wid, 1)  # queda en learning, vencida enseguida
        q = srs.queue(self.conn, new_per_day=0, limits={"new": 0, "reviews": 0})
        self.assertEqual(q["due"], 0)
        self.assertGreaterEqual(q["due_total"], q["due"])

    def test_a_failed_word_still_comes_back_with_the_budget_spent(self):
        """El tope nunca deja una palabra a medio aprender (ADR-009)."""
        wid = self.words[0]
        srs.answer(self.conn, wid, 3)
        srs.answer(self.conn, wid, 1)   # Otra vez → learning
        q = srs.queue(self.conn, new_per_day=0, limits={"new": 0, "reviews": 0})
        # El paso se cumple de verdad (no se adelanta a cero segundos), pero
        # la palabra sigue en la cuenta y vuelve pasado su minuto.
        self.assertEqual(q["learning"], 1, "el tope abandonó una palabra fallada")
        from app import srs as _srs
        from datetime import timedelta
        stale = (_srs._now().astimezone().replace(tzinfo=None)
                 - timedelta(minutes=2)).isoformat(timespec="seconds")
        self.conn.execute("UPDATE words SET last_reviewed_on=? "
                          "WHERE card_state IN ('LEARNING','RELEARNING')", (stale,))
        q = srs.queue(self.conn, new_per_day=0, limits={"new": 0, "reviews": 0})
        self.assertIsNotNone(q["next"], "el tope abandonó una palabra fallada")
        self.assertEqual(q["next"]["id"], wid)


if __name__ == "__main__":
    unittest.main()
