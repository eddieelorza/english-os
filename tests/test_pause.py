"""M13 tests: pause freezes the queue, protects the streak, and returns the
backlog as a ramp instead of a wall."""

from __future__ import annotations

import sys
import json
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import db, model, pause  # noqa: E402

try:
    from app import srs
except ImportError:  # fsrs not installed in this interpreter
    srs = None


def day(offset: int) -> str:
    """Día de estudio, no fecha de calendario.

    Usaba `date.today()`, y desde que existe la hora de corte de las 4:00
    (ADR-010 D6) los dos dejan de coincidir entre medianoche y las 4: la app
    guardaba la pausa con el día de estudio y el test la comparaba contra el
    día natural. La suite fallaba **todas las noches en esa franja** y estaba
    bien el código, no el test.
    """
    return (date.fromisoformat(db.study_day())
            + timedelta(days=offset)).isoformat()


def overdue_word(conn, name: str, days_ago: int = 3) -> int:
    """Una palabra vencida con una card FSRS **real**.

    Antes se guardaba '{}' como card: bastaba porque nadie la deserializaba.
    Desde M17b el preview sí lo hace, y un JSON inventado no es una card.
    """
    from fsrs import Card
    wid = db.upsert_word(conn, {"word": name, "meaning_es": "x"})
    due = datetime.now(timezone.utc) - timedelta(days=days_ago)
    card = Card()
    card.due = due
    conn.execute(
        "UPDATE words SET fsrs_card=?, fsrs_due=?, card_state='LEARNING' "
        "WHERE id=?", (json.dumps(card.to_dict()), due.isoformat(), wid))
    conn.commit()
    return wid


class TestPauseState(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")

    def test_starts_and_reports(self):
        self.assertFalse(pause.state(self.conn)["paused"])
        st = pause.start(self.conn, "viaje de trabajo")
        self.assertTrue(st["paused"])
        self.assertEqual(st["reason"], "viaje de trabajo")
        self.assertEqual(st["since"], day(0))

    def test_starting_twice_is_idempotent(self):
        pause.start(self.conn)
        pause.start(self.conn)
        n = self.conn.execute("SELECT COUNT(*) FROM pauses").fetchone()[0]
        self.assertEqual(n, 1)

    def test_resume_when_not_paused_is_a_no_op(self):
        r = pause.resume(self.conn, touch_anki=False)
        self.assertFalse(r["resumed"])


class TestQueueFrozen(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")

    @unittest.skipIf(srs is None, "fsrs not installed")
    def test_nothing_is_due_while_paused(self):
        overdue_word(self.conn, "forge")
        db.upsert_word(self.conn, {"word": "fresh", "meaning_es": "x"})
        before = srs.queue(self.conn)
        self.assertGreaterEqual(before["due"], 1)

        pause.start(self.conn)
        during = srs.queue(self.conn)
        self.assertEqual(during["due"], 0)
        self.assertEqual(during["new_available"], 0)
        self.assertIsNone(during["next"])
        self.assertTrue(during["paused"])

    @unittest.skipIf(srs is None, "fsrs not installed")
    def test_queue_returns_after_resume(self):
        overdue_word(self.conn, "forge")
        pause.start(self.conn)
        pause.resume(self.conn, touch_anki=False)
        self.assertGreaterEqual(srs.queue(self.conn)["due"], 1)


class TestStreakProtection(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")

    def _studied(self, offset: int):
        db.upsert_session(self.conn, day(offset), {"cards_reviewed": 30})

    def test_gap_without_pause_breaks_the_streak(self):
        self._studied(0)
        self._studied(-3)  # hole at -1 and -2
        self.assertEqual(model.streak(self.conn), 1)

    def test_paused_days_do_not_break_the_streak(self):
        self._studied(0)
        self._studied(-3)
        self.conn.execute(
            "INSERT INTO pauses (start_date, end_date, created_at) VALUES (?,?,?)",
            (day(-2), day(-1), db.now_iso()))
        self.conn.commit()
        # 2 study days survive across the paused gap
        self.assertEqual(model.streak(self.conn), 2)

    def test_paused_days_do_not_inflate_the_streak(self):
        """Neutral means neutral: a pause never credits days you didn't study."""
        self._studied(0)
        self.conn.execute(
            "INSERT INTO pauses (start_date, end_date, created_at) VALUES (?,?,?)",
            (day(-5), day(-1), db.now_iso()))
        self.conn.commit()
        self.assertEqual(model.streak(self.conn), 1)


class TestBacklogRamp(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")

    def test_small_backlog_is_left_alone(self):
        for i in range(5):
            overdue_word(self.conn, f"w{i}")
        pause.start(self.conn)
        r = pause.resume(self.conn, touch_anki=False)
        self.assertEqual(r["cards_spread"], 5)
        self.assertEqual(r["ramp_days"], 1)

    def test_large_backlog_is_spread_over_days(self):
        for i in range(100):
            overdue_word(self.conn, f"w{i}")
        pause.start(self.conn)
        r = pause.resume(self.conn, touch_anki=False)
        self.assertEqual(r["cards_spread"], 100)
        self.assertEqual(r["ramp_days"], 3)  # ceil(100/40)

        now = datetime.now(timezone.utc)
        due_today = self.conn.execute(
            "SELECT COUNT(*) FROM words WHERE fsrs_due <= ?",
            (now.isoformat(),)).fetchone()[0]
        self.assertLessEqual(due_today, 40)   # no wall on day one
        self.assertGreater(due_today, 0)      # but something to do today

    def test_ramp_is_capped(self):
        self.assertEqual(pause._ramp_days(10_000), pause.MAX_RAMP_DAYS)

    def test_resume_records_the_episode(self):
        overdue_word(self.conn, "forge")
        self.conn.execute(
            "INSERT INTO pauses (start_date, reason, created_at) VALUES (?,?,?)",
            (day(-4), "vacaciones", db.now_iso()))
        self.conn.commit()
        r = pause.resume(self.conn, touch_anki=False)
        self.assertEqual(r["days_paused"], 4)
        hist = pause.history(self.conn)
        self.assertEqual(hist[0]["reason"], "vacaciones")
        self.assertEqual(hist[0]["days_paused"], 4)


class TestAnkiIsBestEffort(unittest.TestCase):
    def test_resume_survives_anki_being_closed(self):
        conn = db.connect(":memory:")
        overdue_word(conn, "forge")
        pause.start(conn)
        with mock.patch.object(pause, "_anki", return_value=None):
            r = pause.resume(conn)
        self.assertTrue(r["resumed"])
        self.assertFalse(r["anki"]["reachable"])

    def test_anki_gets_a_range_matching_the_ramp(self):
        conn = db.connect(":memory:")
        for i in range(100):
            overdue_word(conn, f"w{i}")
        pause.start(conn)
        calls = []

        def fake(action, params):
            calls.append((action, params))
            return {"result": [1, 2, 3]} if action == "findCards" else {"result": None}

        with mock.patch.object(pause, "_anki", side_effect=fake):
            r = pause.resume(conn)
        self.assertTrue(r["anki"]["reachable"])
        set_due = [c for c in calls if c[0] == "setDueDate"]
        self.assertEqual(set_due[0][1]["days"], "1-3")


if __name__ == "__main__":
    unittest.main()
