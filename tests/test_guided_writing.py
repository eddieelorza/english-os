"""M20 tests: writing guiado, una oración a la vez.

Por qué existe este modo: Eddie escribió 3 veces en todo el proyecto. "4-6
oraciones" suena poco pero sigue siendo un recuadro vacío.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import db, writing  # noqa: E402


def sentence(text, ok=True, fixed=None, note="", category=""):
    return {"text": text, "ok": ok, "fixed": fixed or text,
            "note": note, "category": category}


class TestSpanishGuard(unittest.TestCase):
    """El modelo local tradujo una frase al español en vez de corregirla:
    "I think is very interesting" → "Creo que es muy interesante". Enseñarle
    español donde tocaba arreglar su inglés es peor que no corregir."""

    def test_detects_a_translated_correction(self):
        self.assertTrue(writing._looks_spanish("Creo que es muy interesante"))
        self.assertTrue(writing._looks_spanish(
            "Se cambió el verbo porque no concuerda"))

    def test_does_not_flag_normal_english(self):
        for good in ["I think it's very interesting because I like the fabric",
                     "Yesterday I went to the park",
                     "She has two brothers",
                     "The mayor opened the town hall"]:
            self.assertFalse(writing._looks_spanish(good), good)

    def test_a_translated_fix_is_discarded(self):
        conn = db.connect(":memory:")
        bad = {"ok": False, "fixed": "Creo que es muy interesante",
               "note": "traducción", "category": "WORD"}
        with mock.patch.object(writing.ai, "get_provider") as gp:
            gp.return_value.generate_json.return_value = bad
            r = writing.check(conn, "I think is very interesting")
        self.assertTrue(r["ok"], "debía darse por buena antes que enseñar español")
        self.assertEqual(r["fixed"], "I think is very interesting")
        self.assertEqual(r["discarded"], "translated")

    def test_a_real_english_fix_survives(self):
        conn = db.connect(":memory:")
        good = {"ok": False, "fixed": "I think it's very interesting",
                "note": "Se añadió 'it's'.", "category": "S-V"}
        with mock.patch.object(writing.ai, "get_provider") as gp:
            gp.return_value.generate_json.return_value = good
            r = writing.check(conn, "I think is very interesting")
        self.assertFalse(r["ok"])
        self.assertEqual(r["fixed"], "I think it's very interesting")
        self.assertNotIn("discarded", r)

    def test_too_short_is_rejected(self):
        conn = db.connect(":memory:")
        with self.assertRaises(ValueError):
            writing.check(conn, "Hi")


class TestFinish(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")

    def test_assembles_without_calling_the_model_again(self):
        """Las oraciones ya vienen corregidas: volver a llamar sería pagar dos
        veces por lo mismo y arriesgarse a que cambie de opinión."""
        with mock.patch.object(writing.ai, "get_provider") as gp:
            r = writing.finish(self.conn, [
                sentence("I think it's nice."),
                sentence("Yesterday I go there.", ok=False,
                         fixed="Yesterday I went there.",
                         note="pasado simple", category="TENSE"),
            ], scenario="Responder a Carlos")
            gp.assert_not_called()
        self.assertEqual(r["sentences"], 2)
        self.assertEqual(len(r["errors"]), 1)
        self.assertIn("went there", r["improved_version"])

    def test_it_counts_as_free_production(self):
        """Debe contar en la evidencia como cualquier otro writing, o el modo
        fácil no ayudaría a subir de nivel."""
        writing.finish(self.conn, [sentence("I like the new fabric a lot.")])
        row = self.conn.execute(
            "SELECT kind, corrected, words_produced, source FROM texts "
            "WHERE kind='writing'").fetchone()
        self.assertEqual(row["corrected"], 1)
        self.assertEqual(row["words_produced"], 7)
        self.assertEqual(row["source"], "app")

    def test_errors_reach_the_shared_loop(self):
        writing.finish(self.conn, [
            sentence("She have two brothers.", ok=False,
                     fixed="She has two brothers.",
                     note="concordancia", category="S-V")])
        n = self.conn.execute("SELECT COUNT(*) FROM errors").fetchone()[0]
        self.assertEqual(n, 1, "el error no entró a la tabla compartida")

    def test_empty_sentences_are_ignored(self):
        r = writing.finish(self.conn, [
            sentence("I like it."), {"text": "   ", "ok": True, "fixed": ""}])
        self.assertEqual(r["sentences"], 1)

    def test_nothing_written_is_an_error(self):
        with self.assertRaises(ValueError):
            writing.finish(self.conn, [{"text": "  ", "ok": True}])

    def test_a_clean_run_says_so(self):
        r = writing.finish(self.conn, [sentence("I went to the park."),
                                       sentence("It was very nice.")])
        self.assertEqual(r["errors"], [])
        self.assertIn("2 de 2", r["strength"])

    def test_the_stored_body_is_his_text_not_the_fix(self):
        """El cuerpo guarda lo que ESCRIBIÓ; la versión corregida va aparte.
        Si se guardara la corregida, sus errores desaparecerían del archivo."""
        writing.finish(self.conn, [
            sentence("Yesterday I go there.", ok=False,
                     fixed="Yesterday I went there.", category="TENSE")])
        row = self.conn.execute(
            "SELECT body, correction FROM texts WHERE kind='writing'").fetchone()
        self.assertIn("I go there", row["body"])
        self.assertIn("I went there",
                      json.loads(row["correction"])["improved_version"])


class TestSteps(unittest.TestCase):
    def test_steps_are_capped_and_cleaned(self):
        conn = db.connect(":memory:")
        raw = {"scenario": "x", "from_name": "Carlos", "message": "Hi!",
               "steps": [{"ask": f"a{i}", "starter": "I", "word": ""}
                         for i in range(6)] + [{"ask": "", "starter": "", "word": ""}]}
        with mock.patch.object(writing.ai, "get_provider") as gp:
            gp.return_value.generate_json.return_value = raw
            out = writing.steps(conn)
        self.assertEqual(len(out["steps"]), 4)
        self.assertTrue(all(s["ask"] for s in out["steps"]))
        self.assertIn("focus", out)


if __name__ == "__main__":
    unittest.main()
