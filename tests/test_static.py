"""La app se sirve desde FastAPI, sin Vite (opción A)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from fastapi.testclient import TestClient
except ImportError:
    raise unittest.SkipTest("fastapi no instalado en este intérprete")
from app import jobs, server  # noqa: E402


@unittest.skipUnless(server.DIST.is_dir(), "frontend sin compilar")
class TestServesTheApp(unittest.TestCase):
    def setUp(self):
        """Base temporal, nunca la real.

        `/api/review/queue` no es de sólo lectura de rebote: mira la sentada
        abierta, y una sentada de un día anterior se cierra sola — lo que
        encola el material del día. Un test no puede disparar eso sobre los
        datos de verdad. Y el worker se desactiva para que ningún trabajo
        encolado llame al modelo.
        """
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._prev = os.environ.get("ENGLISH_DB_PATH")
        os.environ["ENGLISH_DB_PATH"] = str(Path(self.tmp.name) / "test.db")
        self.addCleanup(self._restore_db_path)

        self._worker = jobs.ensure_worker
        jobs.ensure_worker = lambda: None
        self.addCleanup(setattr, jobs, "ensure_worker", self._worker)

        self.c = TestClient(server.app)

    def _restore_db_path(self):
        if self._prev is None:
            os.environ.pop("ENGLISH_DB_PATH", None)
        else:
            os.environ["ENGLISH_DB_PATH"] = self._prev

    def test_root_serves_the_page(self):
        r = self.c.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers["content-type"])

    def test_router_paths_fall_back_to_index(self):
        """/review no es un archivo: sin esta vuelta, recargar dentro de la
        app daría 404 y sólo funcionaría entrando por la raíz."""
        for path in ("/review", "/vocabulary", "/stats"):
            with self.subTest(path=path):
                r = self.c.get(path)
                self.assertEqual(r.status_code, 200)
                self.assertIn("text/html", r.headers["content-type"])

    def test_real_assets_are_served_as_themselves(self):
        asset = next((DIST_ASSETS := server.DIST / "assets").iterdir())
        r = self.c.get(f"/assets/{asset.name}")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("text/html", r.headers["content-type"])

    def test_unknown_api_path_is_a_404_not_the_page(self):
        """El comodín no puede tragarse los errores de la API: devolver HTML
        con un 200 esconde el fallo hasta muy lejos de su causa."""
        r = self.c.get("/api/no-existe")
        self.assertEqual(r.status_code, 404)

    def test_api_still_answers(self):
        r = self.c.get("/api/review/queue")
        self.assertEqual(r.status_code, 200)
        self.assertIn("application/json", r.headers["content-type"])

    def test_path_traversal_is_refused(self):
        """El comodín sirve archivos por ruta del usuario: es justo donde
        entra ../../. Debe caer al index, nunca leer fuera de dist."""
        r = self.c.get("/../../.env")
        self.assertNotIn("NOTION_TOKEN", r.text)
        r = self.c.get("/%2e%2e%2f%2e%2e%2f.env")
        self.assertNotIn("NOTION_TOKEN", r.text)


if __name__ == "__main__":
    unittest.main()
