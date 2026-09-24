"""M17a tests: día de estudio con hora de corte, espejo consultable del
estado FSRS y ReviewLog completo (ADR-010)."""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from app import srs  # noqa: E402  (needs fsrs — venv only)
except ImportError:
    raise unittest.SkipTest("fsrs not installed in this interpreter")
from app import db, model  # noqa: E402


def seed_word(conn, word="endure", **extra):
    return db.upsert_word(conn, {"word": word, "meaning_es": "x", **extra})


class TestStudyDay(unittest.TestCase):
    """Estudiar a las 00:30 es seguir con el día anterior. Sin esto se rompen
    la racha y el cupo de palabras nuevas justo al trasnochar."""

    def test_before_rollover_belongs_to_yesterday(self):
        self.assertEqual(db.study_day(datetime(2026, 8, 22, 0, 30)), "2026-08-21")
        self.assertEqual(db.study_day(datetime(2026, 8, 22, 3, 59)), "2026-08-21")

    def test_after_rollover_is_the_new_day(self):
        self.assertEqual(db.study_day(datetime(2026, 8, 22, 4, 0)), "2026-08-22")
        self.assertEqual(db.study_day(datetime(2026, 8, 22, 23, 59)), "2026-08-22")

    def test_rollover_hour_is_configurable(self):
        with mock.patch.dict(os.environ, {"STUDY_DAY_ROLLOVER_HOUR": "0"}):
            self.assertEqual(db.study_day(datetime(2026, 8, 22, 0, 30)), "2026-08-22")

    def test_a_nonsense_value_falls_back_to_four(self):
        with mock.patch.dict(os.environ, {"STUDY_DAY_ROLLOVER_HOUR": "banana"}):
            self.assertEqual(db.rollover_hour(), 4)
        with mock.patch.dict(os.environ, {"STUDY_DAY_ROLLOVER_HOUR": "99"}):
            self.assertEqual(db.rollover_hour(), 23)

    def test_day_start_is_the_rollover_moment(self):
        self.assertEqual(db.study_day_start("2026-08-21"), "2026-08-21T04:00:00")


class TestStreakAcrossMidnight(unittest.TestCase):
    def test_a_late_night_review_does_not_split_the_streak(self):
        """Repasar a las 00:30 del día 22 cuenta como el día 21. Antes creaba
        un día 'activo' extra y dejaba un hueco donde no lo había."""
        conn = db.connect(":memory:")
        wid = seed_word(conn)
        for stamp in ("2026-08-20T21:00:00", "2026-08-22T00:30:00"):
            db.insert_review(conn, {"word_id": wid, "reviewed_at": stamp,
                                    "rating": 3, "source": "fsrs"})
        conn.commit()
        active = {r[0] for r in conn.execute(
            "SELECT DISTINCT substr(datetime(reviewed_at, ?), 1, 10) "
            "FROM review_history WHERE source='fsrs'",
            (f"-{db.rollover_hour()} hours",))}
        self.assertEqual(active, {"2026-08-20", "2026-08-21"})


class TestMirrorColumns(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.wid = seed_word(self.conn)

    def _row(self):
        return self.conn.execute(
            "SELECT card_state, learning_step, stability, difficulty "
            "FROM words WHERE id=?", (self.wid,)).fetchone()

    def test_answering_fills_the_mirror(self):
        srs.answer(self.conn, self.wid, 3)
        r = self._row()
        self.assertEqual(r["card_state"], "LEARNING")
        self.assertEqual(r["learning_step"], 1)
        self.assertIsNotNone(r["stability"])
        self.assertIsNotNone(r["difficulty"])

    def test_the_mirror_matches_the_json(self):
        """El JSON sigue siendo la verdad; el espejo no puede desviarse."""
        for rating in (3, 1, 3, 3, 4):
            srs.answer(self.conn, self.wid, rating)
        row = self.conn.execute(
            "SELECT fsrs_card, card_state, learning_step, stability, difficulty "
            "FROM words WHERE id=?", (self.wid,)).fetchone()
        import json
        card = json.loads(row["fsrs_card"])
        self.assertEqual(row["card_state"], srs.STATE_NAMES[card["state"]])
        self.assertEqual(row["learning_step"], card["step"])
        self.assertAlmostEqual(row["stability"], card["stability"], places=6)

    def test_state_is_queryable_in_sql(self):
        """El motivo de existir del espejo: no se puede filtrar dentro de un
        blob y la cola diaria necesita separar LEARNING de REVIEW."""
        for _ in range(4):
            srs.answer(self.conn, self.wid, 4)   # gradúa a REVIEW
        n = self.conn.execute(
            "SELECT COUNT(*) FROM words WHERE card_state='REVIEW'").fetchone()[0]
        self.assertEqual(n, 1)

    def test_backfill_is_idempotent_and_invents_nothing(self):
        srs.answer(self.conn, self.wid, 3)
        other = seed_word(self.conn, "fresh")
        self.conn.execute("UPDATE words SET card_state=NULL, stability=NULL")
        self.conn.commit()

        first = srs.backfill(self.conn)
        self.assertEqual((first["cards"], first["new"]), (1, 1))
        again = srs.backfill(self.conn)
        self.assertEqual((again["cards"], again["new"]), (0, 0), "no fue idempotente")

        self.assertEqual(self.conn.execute(
            "SELECT card_state FROM words WHERE id=?", (other,)).fetchone()[0], "NEW")
        self.assertIsNotNone(self.conn.execute(
            "SELECT stability FROM words WHERE id=?", (self.wid,)).fetchone()[0])


class TestReviewLog(unittest.TestCase):
    """Una fila por respuesta, con el antes y el después. FSRS devuelve un
    ReviewLog pero sólo trae card_id/rating/fecha: la estabilidad previa se
    pierde si no se captura aquí."""

    def setUp(self):
        self.conn = db.connect(":memory:")
        self.wid = seed_word(self.conn)

    def _last(self):
        return self.conn.execute(
            "SELECT * FROM review_history ORDER BY id DESC LIMIT 1").fetchone()

    def test_an_introduction_comes_from_NEW(self):
        srs.answer(self.conn, self.wid, 3)
        r = self._last()
        self.assertEqual(r["state_before"], "NEW")
        self.assertEqual(r["state_after"], "LEARNING")
        self.assertIsNone(r["stability_before"], "una palabra nueva no tiene memoria")
        self.assertIsNotNone(r["stability_after"])
        self.assertIsNone(r["previous_due"])

    def test_graduation_is_recorded_as_a_transition(self):
        """Con los pasos por defecto (1m/10m) se gradúa al SEGUNDO Good. El
        test no fija en qué respuesta ocurre: busca la transición."""
        for _ in range(4):
            srs.answer(self.conn, self.wid, 3)
        rows = self.conn.execute(
            "SELECT state_before, state_after, step_before, step_after "
            "FROM review_history ORDER BY id").fetchall()
        grads = [r for r in rows
                 if r["state_before"] == "LEARNING" and r["state_after"] == "REVIEW"]
        self.assertEqual(len(grads), 1, "debía graduarse exactamente una vez")
        self.assertIsNone(grads[0]["step_after"], "en REVIEW no hay paso")
        self.assertEqual(rows[0]["state_before"], "NEW")

    def test_a_lapse_records_relearning_without_erasing_memory(self):
        for _ in range(4):
            srs.answer(self.conn, self.wid, 4)      # a REVIEW con memoria
        srs.answer(self.conn, self.wid, 1)          # Again = lapse
        r = self._last()
        self.assertEqual((r["state_before"], r["state_after"]), ("REVIEW", "RELEARNING"))
        self.assertLess(r["stability_after"], r["stability_before"],
                        "la estabilidad debía caer")
        self.assertGreater(r["difficulty_after"], r["difficulty_before"],
                           "la dificultad debía subir: la memoria no se borra")

    def test_nothing_is_ever_overwritten(self):
        for rating in (3, 1, 3, 2, 4):
            srs.answer(self.conn, self.wid, rating)
        n = self.conn.execute(
            "SELECT COUNT(*) FROM review_history WHERE word_id=?", (self.wid,)
        ).fetchone()[0]
        self.assertEqual(n, 5, "se perdió historial")

    def test_previous_due_and_elapsed_days_are_kept(self):
        srs.answer(self.conn, self.wid, 3)
        srs.answer(self.conn, self.wid, 3)
        r = self._last()
        self.assertIsNotNone(r["previous_due"])
        self.assertIsNotNone(r["elapsed_days"])


class TestNoFuzz(unittest.TestCase):
    """Decisión de Eddie (ADR-010): el intervalo que la UI promete debe ser
    el que se aplica. Con fuzz, seis llamadas idénticas dan 9, 9, 7, 11, 8, 9."""

    def test_the_scheduler_is_deterministic(self):
        from fsrs import Card, Rating
        now = datetime(2026, 8, 21, 16, 0, tzinfo=timezone.utc)
        s = srs._scheduler()
        days = {(s.review_card(Card(), Rating.Easy, now)[0].due - now).days
                for _ in range(6)}
        self.assertEqual(len(days), 1, f"el scheduler no es determinista: {days}")

    def test_seeding_and_answering_use_the_same_scheduler(self):
        conn = db.connect(":memory:")
        wid = seed_word(conn, "forge")
        stamp = (datetime.now() - timedelta(days=30)).isoformat()
        db.insert_review(conn, {"word_id": wid, "reviewed_at": stamp,
                                "rating": 3, "source": "anki"})
        conn.commit()
        import json

        def scheduling(raw):
            # card_id lo genera FSRS del reloj en milisegundos: cambia en cada
            # sembrado y no es parte del scheduling.
            return {k: v for k, v in json.loads(raw).items() if k != "card_id"}

        srs.seed_from_history(conn)
        seeded = conn.execute(
            "SELECT fsrs_card FROM words WHERE id=?", (wid,)).fetchone()[0]
        conn.execute("UPDATE words SET fsrs_card=NULL, fsrs_due=NULL, card_state=NULL "
                     "WHERE id=?", (wid,))
        conn.commit()
        srs.seed_from_history(conn)
        again = conn.execute(
            "SELECT fsrs_card FROM words WHERE id=?", (wid,)).fetchone()[0]
        self.assertEqual(scheduling(seeded), scheduling(again),
                         "sembrar dos veces dio resultados distintos")


if __name__ == "__main__":
    unittest.main()
