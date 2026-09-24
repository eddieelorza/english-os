"""Palabras atascadas: detectarlas y meterlas en el material (M22).

11 palabras (6% de las cards) se llevaban el 16% de todos los repasos y
seguían sin despegar. Repetir la misma card no las movía.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import db, model  # noqa: E402


def word(conn, w, *, difficulty=5.0, reviews=10, interval=30,
         status="LEARNING", lapses=0):
    wid = db.upsert_word(conn, {"word": w, "meaning_es": f"m-{w}",
                                "status": status})
    conn.execute(
        "UPDATE words SET difficulty=?, review_count=?, interval_days=?, "
        "lapses=?, fsrs_card='{}' WHERE id=?",
        (difficulty, reviews, interval, lapses, wid))
    conn.commit()
    return wid


class TestDetection(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")

    def test_a_hard_word_that_will_not_settle_is_stuck(self):
        word(self.conn, "rear", difficulty=9.9, reviews=22, interval=1)
        self.assertEqual([w["word"] for w in model.stuck_words(self.conn)], ["rear"])

    def test_an_easy_word_is_not(self):
        word(self.conn, "table", difficulty=4.0, reviews=20, interval=60)
        self.assertEqual(model.stuck_words(self.conn), [])

    def test_a_young_word_is_not_judged_yet(self):
        """Dificultad alta con pocos repasos es una palabra nueva, no un
        problema: juzgarla ya sería castigarla por ser reciente."""
        word(self.conn, "fresh", difficulty=10.0, reviews=2, interval=1)
        self.assertEqual(model.stuck_words(self.conn), [])

    def test_a_hard_word_that_did_settle_is_not_stuck(self):
        """Difícil pero ya con intervalo largo = la aprendiste. Salió."""
        word(self.conn, "grasp", difficulty=9.9, reviews=20, interval=45)
        self.assertEqual(model.stuck_words(self.conn), [])

    def test_worst_first(self):
        word(self.conn, "mild", difficulty=9.6, reviews=8, interval=5)
        word(self.conn, "awful", difficulty=10.0, reviews=8, interval=5)
        self.assertEqual([w["word"] for w in model.stuck_words(self.conn)],
                         ["awful", "mild"])

    def test_difficulty_catches_before_lapses_do(self):
        """El motivo de usar dificultad y no contar fallos: `mill` y `needle`
        ya estaban atascadas con CERO lapses."""
        word(self.conn, "needle", difficulty=10.0, reviews=10, interval=0, lapses=0)
        stuck = model.stuck_words(self.conn)
        self.assertEqual(len(stuck), 1)
        self.assertEqual(stuck[0]["lapses"], 0)

    def test_limit_is_respected(self):
        for i in range(8):
            word(self.conn, f"w{i}", difficulty=9.9, reviews=10, interval=1)
        self.assertEqual(len(model.stuck_words(self.conn, limit=3)), 3)


class TestTheyReachTheMaterial(unittest.TestCase):
    """learning_words() es el cuello de botella de TODOS los generadores —
    lecturas, actividades, podcast, speaking y writing. Meterlas ahí es lo que
    convierte "repetir la card" en "encontrártela en una historia"."""

    def setUp(self):
        self.conn = db.connect(":memory:")

    def test_stuck_words_lead(self):
        word(self.conn, "easy1", difficulty=3.0, interval=60)
        word(self.conn, "stuck1", difficulty=9.9, reviews=15, interval=1)
        out = [w["word"] for w in model.learning_words(self.conn, 4)]
        self.assertEqual(out[0], "stuck1")

    def test_they_do_not_take_over_the_material(self):
        """Una lectura hecha sólo de palabras difíciles es un texto raro y sin
        contexto donde agarrarse."""
        for i in range(10):
            word(self.conn, f"stuck{i}", difficulty=9.9, reviews=15, interval=1)
        for i in range(10):
            word(self.conn, f"known{i}", difficulty=3.0, interval=60)
        out = [w["word"] for w in model.learning_words(self.conn, 12)]
        stuck = sum(1 for w in out if w.startswith("stuck"))
        self.assertLessEqual(stuck, 6, f"demasiadas difíciles: {out}")
        self.assertGreater(stuck, 0)

    def test_no_duplicates(self):
        """Una palabra atascada también es LEARNING: no puede salir dos veces."""
        word(self.conn, "stuck1", difficulty=9.9, reviews=15, interval=1,
             status="LEARNING")
        out = [w["word"] for w in model.learning_words(self.conn, 8)]
        self.assertEqual(len(out), len(set(out)))

    def test_shape_is_what_generators_expect(self):
        word(self.conn, "stuck1", difficulty=9.9, reviews=15, interval=1)
        for w in model.learning_words(self.conn, 4):
            self.assertEqual(set(w), {"word", "normalized", "meaning_es"})

    def test_it_still_works_with_nothing_stuck(self):
        for i in range(4):
            word(self.conn, f"ok{i}", difficulty=3.0, interval=60)
        self.assertEqual(len(model.learning_words(self.conn, 4)), 4)


if __name__ == "__main__":
    unittest.main()
