"""El vigilante de Anki forma parte del cut-over (ADR-011)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import cutover, db  # noqa: E402


class TestWatcherIsPartOfTheCutover(unittest.TestCase):
    """Se quedó dos semanas corriendo tras el corte porque `state()` no lo
    miraba y `revert()` no lo devolvía. Ahora ambas cosas."""

    def setUp(self):
        self.conn = db.connect(":memory:")

    def test_state_reports_the_watcher(self):
        with mock.patch.object(cutover, "watcher_loaded", return_value=True):
            self.assertTrue(cutover.state(self.conn)["anki_watcher_loaded"])
        with mock.patch.object(cutover, "watcher_loaded", return_value=False):
            self.assertFalse(cutover.state(self.conn)["anki_watcher_loaded"])

    def test_revert_brings_the_watcher_back(self):
        """Un revert que no reactiva el disparador del pipeline legacy es
        media promesa."""
        cutover._set(self.conn, cutover.KEY_DATE, "2026-08-21")
        with mock.patch.object(cutover, "watcher_start",
                               return_value={"started": True}) as start:
            r = cutover.revert(self.conn)
        self.assertTrue(r["reverted"])
        start.assert_called_once()
        self.assertEqual(r["watcher"], {"started": True})

    def test_starting_without_an_archived_plist_says_so(self):
        with mock.patch.object(cutover, "WATCHER_ARCHIVE", Path("/no/existe.plist")):
            self.assertEqual(cutover.watcher_start()["started"], False)

    def test_stopping_when_absent_is_not_an_error(self):
        with mock.patch.object(cutover, "watcher_loaded", return_value=False), \
             mock.patch.object(cutover, "WATCHER_PLIST", Path("/no/existe.plist")):
            self.assertEqual(cutover.watcher_stop()["stopped"], False)

    def test_the_archived_plist_is_in_the_repo(self):
        """Si no está archivado, `revert` no puede devolverlo y el corte deja
        de ser reversible."""
        self.assertTrue(cutover.WATCHER_ARCHIVE.is_file())


if __name__ == "__main__":
    unittest.main()
