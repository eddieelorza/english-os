"""M16c tests: repartir el rezago, proyectar la carga y medir lo que cuesta."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from app import backlog, session, srs  # noqa: E402  (srs needs fsrs)
except ImportError:
    raise unittest.SkipTest("fsrs not installed in this interpreter")
from app import db  # noqa: E402


def overdue_word(conn, word, days_ago=3):
    """Una palabra con card FSRS vencida hace `days_ago` días."""
    wid = db.upsert_word(conn, {"word": word, "meaning_es": "x"})
    srs.answer(conn, wid, 3)                      # crea la card
    due = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    conn.execute("UPDATE words SET fsrs_due=? WHERE id=?", (due, wid))
    conn.commit()
    return wid


class TestCapacityAndStatus(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")

    def test_capacity_follows_the_manual_numbers(self):
        session.save_settings(self.conn, {"mode": "counts", "reviews": 25})
        self.assertEqual(backlog.capacity(self.conn), 25)

    def test_capacity_from_minutes_when_planning_by_time(self):
        session.save_settings(self.conn, {"mode": "time", "minutes": 20})
        # 20 min a 10 s/card darían 120, pero manda el tope de cards
        # (ADR-014 D1): 2.5 por minuto.
        self.assertEqual(backlog.capacity(self.conn), 50)

    def test_a_small_backlog_is_not_overloaded(self):
        session.save_settings(self.conn, {"mode": "counts", "reviews": 25})
        for i in range(5):
            overdue_word(self.conn, f"w{i}")
        st = backlog.status(self.conn)
        self.assertEqual(st["due"], 5)
        self.assertFalse(st["overloaded"])


class TestSpread(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        session.save_settings(self.conn, {"mode": "counts", "reviews": 10})
        self.ids = [overdue_word(self.conn, f"w{i}", days_ago=i + 1)
                    for i in range(35)]

    def test_spread_leaves_exactly_one_day_of_work(self):
        r = backlog.spread(self.conn)
        self.assertTrue(r["spread"])
        self.assertEqual(backlog.due_total(self.conn), 10,
                         "la cola de hoy debía quedar en la capacidad diaria")
        self.assertEqual(r["cards"], 25)

    def test_the_most_overdue_stay_today(self):
        """Si algo se retrasa más, que sea lo que menos lleva esperando."""
        oldest = self.conn.execute(
            "SELECT id FROM words WHERE fsrs_due IS NOT NULL "
            "ORDER BY fsrs_due LIMIT 10").fetchall()
        backlog.spread(self.conn)
        now = datetime.now(timezone.utc).isoformat()
        still_due = {r["id"] for r in self.conn.execute(
            "SELECT id FROM words WHERE fsrs_due <= ?", (now,))}
        self.assertEqual({r["id"] for r in oldest}, still_due)

    def test_nothing_is_lost(self):
        before = self.conn.execute(
            "SELECT COUNT(*) FROM words WHERE fsrs_due IS NOT NULL").fetchone()[0]
        backlog.spread(self.conn)
        after = self.conn.execute(
            "SELECT COUNT(*) FROM words WHERE fsrs_due IS NOT NULL").fetchone()[0]
        self.assertEqual(before, after, "repartir no puede perder cartas")

    def test_no_day_ends_up_above_capacity(self):
        """El reparto no puede construir un muro nuevo dentro de dos días."""
        backlog.spread(self.conn)
        now = datetime.now(timezone.utc)
        by_day: dict[int, int] = {}
        for row in self.conn.execute(
                "SELECT fsrs_due FROM words WHERE fsrs_due > ?", (now.isoformat(),)):
            d = (datetime.fromisoformat(row["fsrs_due"]) - now).days + 1
            by_day[d] = by_day.get(d, 0) + 1
        worst = max(by_day.values())
        self.assertLessEqual(worst, 10, f"un día quedó con {worst} cartas: {by_day}")

    def test_it_counts_what_was_already_scheduled_there(self):
        """Un segundo reparto no debe amontonar sobre lo que dejó el primero."""
        backlog.spread(self.conn)                  # deja 10 hoy, resto repartido
        for i in range(30):                        # llega más rezago
            overdue_word(self.conn, f"later{i}", days_ago=1)
        backlog.spread(self.conn)

        now = datetime.now(timezone.utc)
        by_day: dict[int, int] = {}
        for row in self.conn.execute(
                "SELECT fsrs_due FROM words WHERE fsrs_due > ?", (now.isoformat(),)):
            d = (datetime.fromisoformat(row["fsrs_due"]) - now).days + 1
            by_day[d] = by_day.get(d, 0) + 1
        worst = max(by_day.values())
        self.assertLessEqual(worst, 10, f"amontonó {worst} en un día: {by_day}")

    def test_a_backlog_too_big_for_the_horizon_stays_even(self):
        """Con capacidad 3 y 165 cartas no caben en 14 días: los días salen
        más cargados, pero PAREJOS. Apilar el sobrante en el último día
        construye un muro a dos semanas vista."""
        conn = db.connect(":memory:")
        session.save_settings(conn, {"mode": "counts", "reviews": 3})
        for i in range(120):
            overdue_word(conn, f"w{i}", days_ago=(i % 9) + 1)
        r = backlog.spread(conn)
        self.assertTrue(r["over_capacity"])
        self.assertGreater(r["per_day"], 3)

        now = datetime.now(timezone.utc)
        by_day: dict[int, int] = {}
        for row in conn.execute(
                "SELECT fsrs_due FROM words WHERE fsrs_due > ?", (now.isoformat(),)):
            d = (datetime.fromisoformat(row["fsrs_due"]) - now).days + 1
            by_day[d] = by_day.get(d, 0) + 1
        heaviest, lightest = max(by_day.values()), min(by_day.values())
        self.assertLessEqual(heaviest - lightest, 1,
                             f"reparto desigual: {by_day}")

    def test_spread_is_recorded(self):
        backlog.spread(self.conn)
        row = backlog.spread_today(self.conn)
        self.assertIsNotNone(row)
        self.assertEqual(row["cards"], 25)
        self.assertEqual(row["kept_today"], 10)

    def test_a_second_spread_the_same_day_does_nothing(self):
        backlog.spread(self.conn)
        again = backlog.spread(self.conn)
        self.assertFalse(again["spread"], "volvió a mover cartas ya repartidas")

    def test_small_backlog_is_left_alone(self):
        conn = db.connect(":memory:")
        session.save_settings(conn, {"mode": "counts", "reviews": 10})
        for i in range(12):
            overdue_word(conn, f"x{i}")
        r = backlog.spread(conn)
        self.assertFalse(r["spread"], "se peleó con FSRS por dos cartas")


class TestProjection(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        session.save_settings(self.conn, {"mode": "counts", "reviews": 25})

    def test_without_history_it_says_it_is_not_measured(self):
        p = backlog.projection(self.conn, new_per_day=6)
        self.assertFalse(p["reviews_per_word"]["measured"])
        self.assertEqual(p["steady_daily_reviews"],
                         round(6 * backlog.DEFAULT_REVIEWS_PER_WORD))

    def test_more_new_words_means_more_daily_load(self):
        low = backlog.projection(self.conn, new_per_day=3)
        high = backlog.projection(self.conn, new_per_day=20)
        self.assertGreater(high["steady_daily_reviews"], low["steady_daily_reviews"])
        self.assertFalse(high["sustainable"])
        self.assertIsNotNone(high["note"])

    def test_a_sustainable_pace_carries_no_warning(self):
        p = backlog.projection(self.conn, new_per_day=2)
        self.assertTrue(p["sustainable"])
        self.assertIsNone(p["note"])

    def test_it_measures_from_real_history_when_there_is_enough(self):
        for i in range(40):
            wid = db.upsert_word(self.conn, {"word": f"w{i}", "meaning_es": "x"})
            for _ in range(4):
                db.insert_review(self.conn, {
                    "word_id": wid, "reviewed_at": db.now_iso(),
                    "rating": 3, "source": "fsrs"})
        self.conn.commit()
        r = backlog.reviews_per_word(self.conn)
        self.assertTrue(r["measured"])
        self.assertAlmostEqual(r["value"], 4.0, places=1)


class TestLateness(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")

    def test_no_data_is_reported_as_no_data(self):
        lat = backlog.lateness(self.conn)
        self.assertIsNone(lat["avg_days_late"])
        self.assertFalse(lat["enough"])

    def test_answering_late_is_recorded(self):
        wid = overdue_word(self.conn, "endure", days_ago=4)
        srs.answer(self.conn, wid, 3)
        row = self.conn.execute(
            "SELECT days_late FROM review_history WHERE source='fsrs' "
            "ORDER BY id DESC LIMIT 1").fetchone()
        self.assertIsNotNone(row["days_late"])
        self.assertGreater(row["days_late"], 3.5)

    def test_an_introduction_has_no_lateness(self):
        wid = db.upsert_word(self.conn, {"word": "fresh", "meaning_es": "x"})
        srs.answer(self.conn, wid, 3)
        row = self.conn.execute(
            "SELECT days_late FROM review_history ORDER BY id DESC LIMIT 1").fetchone()
        self.assertIsNone(row["days_late"], "una palabra nueva no llega tarde")


class TestRecallByLateness(unittest.TestCase):
    """La factura del reparto, medida. Un porcentaje sin muestra no se
    afirma: un 100% sobre tres cartas no dice nada."""

    def setUp(self):
        self.conn = db.connect(":memory:")
        self.wid = db.upsert_word(self.conn, {"word": "endure", "meaning_es": "x"})

    def _log(self, n, days_late, rating):
        for _ in range(n):
            db.insert_review(self.conn, {
                "word_id": self.wid, "reviewed_at": db.now_iso(), "rating": rating,
                "review_kind": "review", "days_late": days_late, "source": "fsrs"})
        self.conn.commit()

    def test_small_buckets_report_no_number(self):
        self._log(3, 0.1, 3)
        on_time = backlog.recall_by_lateness(self.conn)[0]
        self.assertEqual(on_time["reviews"], 3)
        self.assertIsNone(on_time["recall"], "afirmó un porcentaje sobre 3 cartas")
        self.assertFalse(on_time["enough"])

    def test_it_separates_on_time_from_late(self):
        self._log(25, 0.2, 3)     # a tiempo, acertadas
        self._log(25, 6.0, 1)     # muy tarde, falladas
        by = {b["label"]: b for b in backlog.recall_by_lateness(self.conn)}
        self.assertEqual(by["on time"]["recall"], 1.0)
        self.assertEqual(by["4+ days late"]["recall"], 0.0)
        self.assertEqual(by["1-3 days late"]["reviews"], 0)

    def test_introductions_are_excluded(self):
        for _ in range(25):
            db.insert_review(self.conn, {
                "word_id": self.wid, "reviewed_at": db.now_iso(), "rating": 3,
                "review_kind": "new", "days_late": 0.0, "source": "fsrs"})
        self.conn.commit()
        self.assertEqual(backlog.recall_by_lateness(self.conn)[0]["reviews"], 0)

    def test_spread_count_separates_cause_from_effect(self):
        """Sin esto no se sabe si una carta llegó tarde porque el sistema la
        aplazó o porque ese día no estudiaste."""
        self.assertEqual(backlog.spreads_in(self.conn)["times"], 0)
        self.conn.execute(
            "INSERT INTO backlog_spreads (date, cards, days, kept_today, created_at) "
            "VALUES (?,?,?,?,?)", (db.now_iso()[:10], 42, 5, 10, db.now_iso()))
        self.conn.commit()
        s = backlog.spreads_in(self.conn)
        self.assertEqual((s["times"], s["cards"]), (1, 42))

    def test_weekly_series_leaves_honest_gaps(self):
        series = backlog.lateness_series(self.conn, weeks=4)
        self.assertEqual(len(series), 4)
        self.assertTrue(all(w["avg_days_late"] is None for w in series),
                        "una semana sin repasos no puede parecer puntualidad")


class TestSessionEndSpreads(unittest.TestCase):
    def test_closing_a_sitting_tidies_the_backlog(self):
        conn = db.connect(":memory:")
        session.save_settings(conn, {"mode": "counts", "reviews": 10})
        for i in range(40):
            overdue_word(conn, f"w{i}", days_ago=i + 1)
        session.start(conn, mode="counts", new=0, reviews=10)
        # sentarse ya ordenó el día (ADR-014 D2); se simula rezago nuevo
        for i in range(40, 60):
            overdue_word(conn, f"w{i}", days_ago=1)
        r = session.end(conn)
        self.assertTrue(r["backlog"]["spread"])
        self.assertEqual(backlog.due_total(conn), 10)

    def test_sitting_down_tidies_the_backlog(self):
        """El reparto no puede depender de cerrar la sentada: en un mes de
        uso real no se cerró ninguna a mano y nunca corrió (ADR-014 D2)."""
        conn = db.connect(":memory:")
        for i in range(40):
            overdue_word(conn, f"w{i}", days_ago=i + 1)
        r = session.start(conn, mode="counts", new=0, reviews=10)
        self.assertTrue(r["backlog"]["spread"])
        self.assertEqual(backlog.due_total(conn), 10)
        self.assertEqual(r["plan"]["reviews"], 10)

    def test_it_does_not_touch_anything_while_paused(self):
        from app import pause
        conn = db.connect(":memory:")
        session.save_settings(conn, {"mode": "counts", "reviews": 10})
        for i in range(40):
            overdue_word(conn, f"w{i}")
        session.start(conn, mode="counts", new=0, reviews=10)
        pause.start(conn, "vacaciones")
        r = session.end(conn)
        self.assertFalse(r["backlog"]["spread"])


if __name__ == "__main__":
    unittest.main()
