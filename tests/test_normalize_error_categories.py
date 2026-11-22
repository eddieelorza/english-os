"""La migración ensaya sin escribir y aplica sólo categorías conocidas."""

import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent


class TestNormalizeErrorCategories(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "test.db"
        self.conn = sqlite3.connect(self.path)
        self.addCleanup(self.conn.close)
        self.conn.execute("CREATE TABLE errors (category TEXT)")
        self.categories_original = [
            "Artículos", "Artículos", " prep ", "Falsos amigos",
            "Orden de palabras", "TENSE", "Desconocida", None]
        self.conn.executemany("INSERT INTO errors VALUES (?)",
                              [(c,) for c in self.categories_original])
        self.conn.commit()

    def run_script(self, *args, check=True):
        return subprocess.run(
            [sys.executable, str(BASE / "scripts/normalize_error_categories.py"),
             str(self.path), *args], cwd=BASE, capture_output=True, text=True,
            check=check)

    def categories(self):
        return [r[0] for r in self.conn.execute("SELECT category FROM errors ORDER BY rowid")]

    def test_dry_run_prints_mappings_and_changes_nothing(self):
        before = self.path.read_bytes()
        result = self.run_script()
        self.assertIn("old category → new category → rows", result.stdout)
        self.assertIn("Artículos → ART → 2", result.stdout)
        self.assertIn("Categorías desconocidas: None, Desconocida", result.stdout)
        self.assertEqual(self.categories(), self.categories_original)
        self.assertEqual(self.path.read_bytes(), before)

    def test_apply_rewrites_known_categories_only(self):
        self.run_script("--apply")
        self.assertEqual(self.categories(),
                         ["ART", "ART", "PREP", "WORD", "ORDER", "TENSE",
                          "Desconocida", None])

    def test_apply_rolls_back_all_mappings_on_failure(self):
        self.conn.execute(
            "CREATE TRIGGER reject_word BEFORE UPDATE ON errors "
            "WHEN NEW.category='WORD' BEGIN SELECT RAISE(ABORT, 'fallo'); END")
        self.conn.commit()
        self.assertNotEqual(self.run_script("--apply", check=False).returncode, 0)
        self.assertEqual(self.categories(), self.categories_original)


if __name__ == "__main__":
    unittest.main()
