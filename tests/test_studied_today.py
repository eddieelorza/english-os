"""Tests de "palabras estudiadas hoy" en Vocabulary.

El ledger tiene 3,100 filas y no puede responder "¿qué hice hoy?". Esto sí,
y tiene que usar el día de estudio, no la fecha de calendario.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from unittest import mock  # noqa: E402

from app import db, jobs  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def review(conn, word_id, rating=3, kind="review", when=None):
    db.insert_review(conn, {
        "word_id": word_id, "reviewed_at": when or db.now_iso(),
        "rating": rating, "review_kind": kind, "source": "fsrs"})
    conn.commit()


class TestStudiedToday(unittest.TestCase):
    def setUp(self):
        import os
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "t.db")
        os.environ["ENGLISH_DB_PATH"] = self.path
        self.conn = db.connect(self.path)
        from app import server

        # Sin este parche, el hook de arranque del servidor lanza el hilo
        # trabajador de jobs. Ese hilo SOBREVIVE al test: cuando tearDown
        # quita ENGLISH_DB_PATH, su siguiente vuelta abre data/english.db —
        # la base REAL — y puede ejecutar un trabajo de verdad contra Ollama.
        # Se vio como una corrida de 18 s con un fallo que no reproducía.
        self._worker = mock.patch.object(jobs, "ensure_worker")
        self._worker.start()
        self.client = TestClient(server.app)

    def tearDown(self):
        import os
        self._worker.stop()
        self.conn.close()
        os.environ.pop("ENGLISH_DB_PATH", None)
        self.tmp.cleanup()

    def _get(self):
        return self.client.get("/api/words/studied-today").json()

    def test_empty_day_reports_nothing(self):
        d = self._get()
        self.assertEqual(d["total"], 0)
        self.assertEqual(d["items"], [])

    def test_lists_what_was_touched(self):
        a = db.upsert_word(self.conn, {"word": "mill", "meaning_es": "Molino"})
        b = db.upsert_word(self.conn, {"word": "ivory", "meaning_es": "Marfil"})
        review(self.conn, a)
        review(self.conn, b)
        d = self._get()
        self.assertEqual(d["total"], 2)
        self.assertEqual({i["word"] for i in d["items"]}, {"mill", "ivory"})

    def test_counts_repeats_instead_of_duplicating(self):
        """Ver `mill` ocho veces es UNA palabra vista ocho veces."""
        wid = db.upsert_word(self.conn, {"word": "mill", "meaning_es": "x"})
        for _ in range(8):
            review(self.conn, wid)
        d = self._get()
        self.assertEqual(d["total"], 1)
        self.assertEqual(d["items"][0]["times"], 8)

    def test_a_word_failed_once_is_flagged(self):
        wid = db.upsert_word(self.conn, {"word": "grasp", "meaning_es": "x"})
        review(self.conn, wid, rating=3)
        review(self.conn, wid, rating=1)   # falló
        review(self.conn, wid, rating=3)
        d = self._get()
        self.assertEqual(d["struggled"], 1)
        self.assertEqual(d["items"][0]["worst_rating"], 1,
                         "un fallo en el día debe marcar la palabra")

    def test_introductions_are_counted_apart(self):
        a = db.upsert_word(self.conn, {"word": "fresh", "meaning_es": "x"})
        b = db.upsert_word(self.conn, {"word": "old", "meaning_es": "x"})
        review(self.conn, a, kind="new")
        review(self.conn, b, kind="review")
        d = self._get()
        self.assertEqual(d["introduced"], 1)

    def test_yesterday_is_not_today(self):
        wid = db.upsert_word(self.conn, {"word": "old", "meaning_es": "x"})
        two_days = (datetime.now() - timedelta(days=2)).isoformat(timespec="seconds")
        review(self.conn, wid, when=two_days)
        self.assertEqual(self._get()["total"], 0)

    def test_a_late_night_review_belongs_to_the_day_before(self):
        """A las 00:30 sigues en la sesión de anoche (ADR-010 D6). Con fecha
        de calendario esto habría contado como un día nuevo."""
        wid = db.upsert_word(self.conn, {"word": "mill", "meaning_es": "x"})
        day = db.study_day()
        review(self.conn, wid, when=f"{day}T23:40:00")
        # la misma noche, ya pasada la medianoche
        after = (datetime.fromisoformat(f"{day}T23:40:00")
                 + timedelta(hours=1)).isoformat(timespec="seconds")
        review(self.conn, wid, when=after)
        d = self._get()
        self.assertEqual(d["date"], day)
        self.assertEqual(d["total"], 1)
        self.assertEqual(d["items"][0]["times"], 2,
                         "los dos repasos son de la misma sesión")

    def test_anki_history_is_not_counted(self):
        """Sólo repasos in-app: el revlog importado no es "lo que hice hoy"."""
        wid = db.upsert_word(self.conn, {"word": "old", "meaning_es": "x"})
        db.insert_review(self.conn, {
            "word_id": wid, "reviewed_at": db.now_iso(), "rating": 3,
            "review_kind": "review", "source": "anki"})
        self.conn.commit()
        self.assertEqual(self._get()["total"], 0)


if __name__ == "__main__":
    unittest.main()
