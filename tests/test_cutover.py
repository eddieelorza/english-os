"""M18 tests: el cut-over de Anki (ADR-011).

Lo que importa aquí no es que la marca se guarde, sino que las **guardas**
funcionen: sin ellas, cortar es sólo una etiqueta y el importador seguiría
pisando el estado de la app.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import cutover, db  # noqa: E402

try:
    from app import jobs, session, srs  # noqa: E402
except ImportError:
    srs = None


SNAPSHOT = {"taken_at": "2026-08-21T18:00:00", "cards": 2402,
            "by_type": {"new": 2236, "review": 166}, "notes_studied": [11, 22]}


def word_with_note(conn, word, note_id, state="REVIEW"):
    wid = db.upsert_word(conn, {"word": word, "meaning_es": "x",
                                "anki_note_id": note_id})
    conn.execute("UPDATE words SET card_state=? WHERE id=?", (state, wid))
    conn.commit()
    return wid


class TestState(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")

    def test_starts_uncut(self):
        self.assertFalse(cutover.done(self.conn))
        self.assertIsNone(cutover.state(self.conn)["date"])

    def test_run_records_date_and_snapshot(self):
        with mock.patch.object(cutover, "_anki_snapshot", return_value=SNAPSHOT):
            word_with_note(self.conn, "ivory", 11)
            word_with_note(self.conn, "mill", 22)
            r = cutover.run(self.conn)
        self.assertTrue(r["cut_over"])
        self.assertEqual(r["date"], db.study_day())
        self.assertEqual(r["anki_snapshot"]["cards"], 2402)

    def test_running_twice_is_idempotent(self):
        with mock.patch.object(cutover, "_anki_snapshot", return_value=SNAPSHOT):
            word_with_note(self.conn, "ivory", 11)
            word_with_note(self.conn, "mill", 22)
            first = cutover.run(self.conn)
            again = cutover.run(self.conn)
        self.assertTrue(again["already"])
        self.assertEqual(first["date"], again["date"])

    def test_revert_puts_it_back(self):
        with mock.patch.object(cutover, "_anki_snapshot", return_value=SNAPSHOT):
            word_with_note(self.conn, "ivory", 11)
            word_with_note(self.conn, "mill", 22)
            cutover.run(self.conn)
        self.assertTrue(cutover.revert(self.conn)["reverted"])
        self.assertFalse(cutover.done(self.conn))
        # la foto se conserva: borrarla no ayuda a nadie
        self.assertIsNotNone(cutover.state(self.conn)["anki_snapshot"])


class TestPreflight(unittest.TestCase):
    """La única condición que de verdad importa: que Anki no sepa nada que la
    app no sepa."""

    def setUp(self):
        self.conn = db.connect(":memory:")

    def test_blocks_when_anki_knows_something_the_app_does_not(self):
        word_with_note(self.conn, "ivory", 11)          # 22 falta
        with mock.patch.object(cutover, "_anki_snapshot", return_value=SNAPSHOT):
            pre = cutover.preflight(self.conn)
        self.assertFalse(pre["ok"])
        check = next(c for c in pre["checks"] if c["name"] == "nothing_only_in_anki")
        self.assertFalse(check["ok"])
        self.assertIn(22, check["note_ids"])

    def test_a_new_card_in_the_app_does_not_count_as_known(self):
        word_with_note(self.conn, "ivory", 11)
        word_with_note(self.conn, "mill", 22, state="NEW")
        with mock.patch.object(cutover, "_anki_snapshot", return_value=SNAPSHOT):
            pre = cutover.preflight(self.conn)
        check = next(c for c in pre["checks"] if c["name"] == "nothing_only_in_anki")
        self.assertFalse(check["ok"], "una palabra NEW no conserva progreso")

    def test_blocked_run_does_not_cut(self):
        word_with_note(self.conn, "ivory", 11)
        with mock.patch.object(cutover, "_anki_snapshot", return_value=SNAPSHOT):
            r = cutover.run(self.conn)
        self.assertFalse(r["cut_over"])
        self.assertFalse(cutover.done(self.conn))

    def test_force_overrides_a_blocked_preflight(self):
        word_with_note(self.conn, "ivory", 11)
        with mock.patch.object(cutover, "_anki_snapshot", return_value=SNAPSHOT):
            r = cutover.run(self.conn, force=True)
        self.assertTrue(r["cut_over"])

    def test_unreachable_anki_blocks(self):
        with mock.patch.object(cutover, "_anki_snapshot", return_value=None):
            pre = cutover.preflight(self.conn)
        self.assertFalse(pre["ok"])


class TestImporterGuard(unittest.TestCase):
    """Sin esto el cut-over es una etiqueta. El importador escribe con
    overwrite=('status', ...): tras el corte devolvería palabras que la app ya
    avanzó al estado que Anki recuerda."""

    def setUp(self):
        self.conn = db.connect(":memory:")

    def test_importer_stops_after_the_cut(self):
        from app.importers import anki as anki_importer
        word_with_note(self.conn, "ivory", 11)
        word_with_note(self.conn, "mill", 22)
        with mock.patch.object(cutover, "_anki_snapshot", return_value=SNAPSHOT):
            cutover.run(self.conn)
        r = anki_importer.run(self.conn)
        self.assertEqual(r["skipped"], "cut-over")
        self.assertEqual(r["words_new"], 0)

    def test_force_still_lets_it_run(self):
        """Una salida de emergencia explícita, no un silencio."""
        from app.importers import anki as anki_importer
        word_with_note(self.conn, "ivory", 11)
        word_with_note(self.conn, "mill", 22)
        with mock.patch.object(cutover, "_anki_snapshot", return_value=SNAPSHOT):
            cutover.run(self.conn)
        with self.assertRaises(FileNotFoundError):
            # llega hasta buscar la colección: la guarda ya no lo detuvo
            anki_importer.run(self.conn, collection_path=Path("/no/existe.anki2"),
                              force=True)


@unittest.skipIf(srs is None, "fsrs not installed")
class TestSessionBecomesTheTrigger(unittest.TestCase):
    """Tras el corte nadie abre Anki, así que el add-on ya no dispara el
    material. Lo hace el cierre de sentada."""

    def setUp(self):
        self.conn = db.connect(":memory:")
        for i in range(6):
            db.upsert_word(self.conn, {"word": f"w{i}", "meaning_es": "x"})

    def test_closing_a_sitting_asks_for_the_material(self):
        session.start(self.conn, mode="counts", new=2, reviews=0)
        with mock.patch.object(jobs, "ensure_worker"):
            r = session.end(self.conn)
        self.assertIsNotNone(r["material"])
        self.assertGreaterEqual(len(r["material"]["queued"]), 2)

    def test_it_does_not_ask_twice_for_the_reading(self):
        """El otro disparador puede haber corrido ya. Dos lecturas el mismo
        día es justo lo que CLAUDE.md prohíbe."""
        db.upsert_text(self.conn, {"kind": "reading", "title": "hoy",
                                   "date": db.study_day(), "body": "x"})
        session.start(self.conn, mode="counts", new=2, reviews=0)
        with mock.patch.object(jobs, "ensure_worker"):
            r = session.end(self.conn)
        self.assertTrue(r["material"]["reading_skipped"])

    def test_a_paused_course_asks_for_nothing(self):
        from app import pause
        session.start(self.conn, mode="counts", new=2, reviews=0)
        pause.start(self.conn, "vacaciones")
        with mock.patch.object(jobs, "ensure_worker"):
            r = session.end(self.conn)
        self.assertIsNone(r["material"])

    def test_closing_survives_a_broken_queue(self):
        """Cerrar la sentada nunca puede fallar por el material."""
        session.start(self.conn, mode="counts", new=2, reviews=0)
        with mock.patch.object(jobs, "enqueue_daily",
                               side_effect=RuntimeError("boom")):
            r = session.end(self.conn)
        self.assertTrue(r["ended"])
        self.assertIn("boom", r["material"]["error"])


if __name__ == "__main__":
    unittest.main()
