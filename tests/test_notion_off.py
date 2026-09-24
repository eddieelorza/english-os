"""M19 tests: apagar Notion (ADR-012).

El caso que motivó todo esto: la app tenía las 77 páginas de writing con el
cuerpo VACÍO porque el importador solo leía propiedades. Apagar Notion sin
rescatar el contenido lo habría dejado inalcanzable.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from app import cutover, db  # noqa: E402


def page(conn, kind, title, body=None, page_id="p1"):
    return db.upsert_text(conn, {
        "kind": kind, "title": title, "date": db.study_day(),
        "notion_page_id": page_id, "body": body})


class TestPreflight(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")

    def test_blocks_while_a_page_has_no_content(self):
        page(self.conn, "writing", "Writing Session – hoy", body=None)
        pre = cutover.notion_preflight(self.conn)
        self.assertFalse(pre["ok"])
        check = next(c for c in pre["checks"] if c["name"] == "content_rescued")
        self.assertIn("writing", check["detail"])

    def test_an_empty_string_counts_as_missing(self):
        """Un cuerpo en blanco es un cascarón igual que un NULL."""
        page(self.conn, "writing", "vacío", body="   ")
        self.assertFalse(cutover.notion_preflight(self.conn)["ok"])

    def test_passes_once_everything_has_content(self):
        page(self.conn, "writing", "con texto", body="I go to the park.")
        pre = cutover.notion_preflight(self.conn)
        check = next(c for c in pre["checks"] if c["name"] == "content_rescued")
        self.assertTrue(check["ok"])

    def test_off_is_blocked_by_a_failing_preflight(self):
        page(self.conn, "writing", "vacío", body=None)
        r = cutover.notion_off(self.conn)
        self.assertFalse(r["notion_off"])
        self.assertFalse(cutover.notion_done(self.conn))

    def test_force_overrides(self):
        page(self.conn, "writing", "vacío", body=None)
        self.assertTrue(cutover.notion_off(self.conn, force=True)["notion_off"])


class TestLifecycle(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        page(self.conn, "writing", "con texto", body="I go to the park.")

    def test_off_records_date_and_snapshot(self):
        r = cutover.notion_off(self.conn)
        self.assertTrue(r["notion_off"])
        self.assertEqual(r["date"], db.study_day())
        self.assertEqual(r["snapshot"]["texts"]["writing"], 1)

    def test_twice_is_idempotent(self):
        first = cutover.notion_off(self.conn)
        again = cutover.notion_off(self.conn)
        self.assertTrue(again["already"])
        self.assertEqual(first["date"], again["date"])

    def test_on_puts_it_back(self):
        cutover.notion_off(self.conn)
        self.assertTrue(cutover.notion_on(self.conn)["reverted"])
        self.assertFalse(cutover.notion_done(self.conn))

    def test_anki_and_notion_are_independent(self):
        """Apagar uno no puede apagar el otro."""
        cutover.notion_off(self.conn)
        self.assertTrue(cutover.notion_done(self.conn))
        self.assertFalse(cutover.done(self.conn))


class TestWriteGuard(unittest.TestCase):
    """Un solo cerrojo para las seis rutas que escriben en Notion. Sin él,
    apagar es una etiqueta."""

    def test_writes_are_blocked_reads_are_not(self):
        from notion_client import NotionOff, _guard_write

        with mock.patch.object(cutover, "notion_done", return_value=True), \
             mock.patch.object(cutover, "notion_state",
                               return_value={"date": "2026-08-21"}):
            for method, path in [("POST", "/pages"),
                                 ("PATCH", "/pages/abc"),
                                 ("PATCH", "/blocks/abc/children"),
                                 ("DELETE", "/blocks/abc")]:
                with self.assertRaises(NotionOff, msg=f"{method} {path} pasó"):
                    _guard_write(method, path)

            # las lecturas siguen: apagar es dejar de alimentarlo, no perder
            # el acceso al archivo
            _guard_write("GET", "/pages/abc")
            _guard_write("GET", "/blocks/abc/children")
            _guard_write("POST", "/databases/abc/query")

    def test_nothing_is_blocked_while_notion_is_on(self):
        from notion_client import _guard_write
        with mock.patch.object(cutover, "notion_done", return_value=False):
            _guard_write("POST", "/pages")
            _guard_write("DELETE", "/blocks/abc")


class TestImporterGuard(unittest.TestCase):
    def test_importer_stops_once_notion_is_off(self):
        conn = db.connect(":memory:")
        page(conn, "writing", "con texto", body="x")
        cutover.notion_off(conn)
        from app.importers import notion as notion_importer
        r = notion_importer.run(conn)
        self.assertEqual(r["skipped"], "notion-off")
        self.assertEqual(r["vocab"], 0)


class TestRescueParsing(unittest.TestCase):
    """El rescate guarda la página entera y separa la corrección."""

    def _blocks(self):
        return [
            {"type": "heading_2", "heading_2": {}},
            {"type": "paragraph", "paragraph": {}},
            {"type": "divider", "divider": {}},
            {"type": "heading_2", "heading_2": {}},
            {"type": "paragraph", "paragraph": {}},
        ]

    def test_splits_the_correction_out(self):
        from app.importers import notion_content
        # Sin entrada para el divider: se salta ANTES de pedirle el texto, así
        # que darle una desalinea el iterador y mueve la corrección de sitio.
        texts = iter(["Writing Practice", "I go to the park every day.",
                      "✅ Corrección — 2026-08-17", "Fortaleza: buen uso."])
        client = mock.Mock()
        client.get_block_children.return_value = self._blocks()
        with mock.patch.object(notion_content, "page_text",
                               wraps=notion_content.page_text):
            with mock.patch.dict(sys.modules):
                import notion_blocks
                with mock.patch.object(notion_blocks, "block_plain_text",
                                       side_effect=lambda b: next(texts)):
                    body, correction = notion_content.page_text(client, "pid")
        self.assertIn("I go to the park", body)
        self.assertIn("Corrección", body, "la página entera se guarda")
        self.assertIsNotNone(correction)
        self.assertIn("Fortaleza", correction)
        self.assertNotIn("I go to the park", correction,
                         "la corrección no debe arrastrar el ejercicio")

    def test_a_placeholder_story_is_flagged(self):
        from app.importers import notion_content
        self.assertTrue(notion_content._is_placeholder(
            "## Story\n⏳ Generando tu historia…"))
        self.assertFalse(notion_content._is_placeholder(
            "## Story\nMayor Diaz walked along the bay."))


if __name__ == "__main__":
    unittest.main()
