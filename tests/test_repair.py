"""El replay que deshace el bucle de learn-ahead (ADR-009 D2 rev.3)."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from app import repair, srs  # noqa: E402
except ImportError:
    raise unittest.SkipTest("fsrs no instalado en este intérprete")
from app import db  # noqa: E402


def rows(*specs):
    """(segundos desde t0, rating, source) -> filas como las de la tabla."""
    t0 = datetime(2026, 8, 24, 22, 0, 0)
    return [{"id": i, "reviewed_at": (t0 + timedelta(seconds=s)).isoformat(),
             "rating": r, "source": src}
            for i, (s, r, src) in enumerate(specs, 1)]


class TestSplit(unittest.TestCase):
    def test_keeps_the_first_of_a_burst(self):
        """La primera respuesta de la ráfaga es la única que llegó tras una
        espera real; las demás miden el bug."""
        kept, dropped = repair.split(rows(
            (0, 3, "fsrs"), (2, 1, "fsrs"), (3, 1, "fsrs"), (9, 3, "fsrs")))
        self.assertEqual([r["id"] for r in kept], [1])
        self.assertEqual(len(dropped), 3)

    def test_a_burst_is_measured_against_the_last_kept(self):
        """Si cada una se midiera contra la anterior, una ráfaga de seis a 30 s
        pasaría entera aunque abarque menos que un solo paso."""
        kept, _ = repair.split(rows(
            (0, 3, "fsrs"), (30, 3, "fsrs"), (59, 3, "fsrs"), (61, 3, "fsrs")))
        self.assertEqual([r["id"] for r in kept], [1, 4])

    def test_anki_history_is_never_touched(self):
        """Anki repetía cards a los segundos en sus pasos de aprendizaje: era
        su funcionamiento, no un fallo. Un prototipo sin esta distinción
        'reparaba' 42 palabras reescribiendo historial sano."""
        kept, dropped = repair.split(rows(
            (0, 3, "anki"), (2, 3, "anki"), (4, 1, "anki")))
        self.assertEqual(len(kept), 3)
        self.assertEqual(dropped, [])

    def test_honest_history_is_left_alone(self):
        kept, dropped = repair.split(rows(
            (0, 3, "fsrs"), (600, 3, "fsrs"), (90000, 4, "fsrs")))
        self.assertEqual(len(kept), 3)
        self.assertEqual(dropped, [])


class TestPlanAndApply(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.wid = db.upsert_word(self.conn, {"word": "trim", "meaning_es": "x"})

    def _hammer(self):
        """Reproduce el bucle: contestar la misma palabra cada 2 segundos."""
        now = srs._now()
        for i, rating in enumerate((3, 1, 1, 3, 3)):
            srs.answer(self.conn, self.wid, rating,
                       now=now + timedelta(seconds=2 * i))

    def test_plan_reports_without_writing(self):
        self._hammer()
        before = self.conn.execute(
            "SELECT stability FROM words WHERE id=?", (self.wid,)).fetchone()[0]
        items = repair.plan(self.conn)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["word"], "trim")
        self.assertGreater(items[0]["dropped"], 0)
        after = self.conn.execute(
            "SELECT stability FROM words WHERE id=?", (self.wid,)).fetchone()[0]
        self.assertEqual(before, after, "plan() escribió")

    def test_apply_changes_the_card(self):
        self._hammer()
        before = self.conn.execute(
            "SELECT fsrs_card FROM words WHERE id=?", (self.wid,)).fetchone()[0]
        r = repair.apply(self.conn)
        self.assertEqual(r["repaired"], ["trim"])
        after = self.conn.execute(
            "SELECT fsrs_card FROM words WHERE id=?", (self.wid,)).fetchone()[0]
        self.assertNotEqual(before, after)

    def test_history_is_preserved(self):
        """Las respuestas ocurrieron. Lo que estaba mal era leerlas como
        repasos, no que estuvieran escritas."""
        self._hammer()
        n = self.conn.execute(
            "SELECT COUNT(*) FROM review_history WHERE word_id=?",
            (self.wid,)).fetchone()[0]
        repair.apply(self.conn)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM review_history WHERE word_id=?",
            (self.wid,)).fetchone()[0], n)

    def test_apply_is_idempotent(self):
        self._hammer()
        repair.apply(self.conn)
        once = self.conn.execute(
            "SELECT fsrs_card FROM words WHERE id=?", (self.wid,)).fetchone()[0]
        self.assertEqual(repair.apply(self.conn)["count"], 1)
        twice = self.conn.execute(
            "SELECT fsrs_card FROM words WHERE id=?", (self.wid,)).fetchone()[0]
        self.assertEqual(once, twice)

    def test_a_clean_word_is_not_in_the_plan(self):
        now = srs._now()
        srs.answer(self.conn, self.wid, 3, now=now)
        srs.answer(self.conn, self.wid, 3, now=now + timedelta(minutes=20))
        self.assertEqual(repair.plan(self.conn), [])

    def test_review_count_is_not_rewritten(self):
        """`lapses` lo deriva el scheduler y se recalcula. `review_count`
        cuenta lo que Eddie hizo, y eso no lo cambia un bug."""
        self._hammer()
        n = self.conn.execute(
            "SELECT review_count FROM words WHERE id=?", (self.wid,)).fetchone()[0]
        repair.apply(self.conn)
        self.assertEqual(self.conn.execute(
            "SELECT review_count FROM words WHERE id=?",
            (self.wid,)).fetchone()[0], n)


if __name__ == "__main__":
    unittest.main()
