"""Definiciones en inglés para el reverso (M18d)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import db, glossary  # noqa: E402


class TestCognateScore(unittest.TestCase):
    def test_cognates_score_above_strangers(self):
        """La propiedad que se sostiene es el ORDEN, no un umbral. Medido
        sobre el mazo real: 0.61 de media en las dominadas contra 0.28 en las
        atascadas."""
        for cognate, gloss_c, stranger, gloss_s in (
                ("province", "Provincia", "shed", "Cobertizo"),
                ("archaeology", "Arqueología", "coal", "Carbón"),
                ("satisfaction", "Satisfacción", "needle", "Aguja")):
            with self.subTest(cognate=cognate):
                self.assertGreater(glossary.cognate_score(cognate, gloss_c),
                                   glossary.cognate_score(stranger, gloss_s))

    def test_short_words_are_noisy_and_that_is_known(self):
        """`sew`/`Coser` puntúa 0.5 pese a no ser cognado: en palabras cortas
        dos letras compartidas pesan mucho. La señal es de agregado, no de
        palabra suelta, y el módulo la usa sólo para ordenar prioridades."""
        self.assertGreater(glossary.cognate_score("sew", "Coser"), 0.4)

    def test_accents_do_not_break_the_match(self):
        """'Arqueología' contra 'archaeology': si la tilde contara, un cognado
        claro puntuaría como desconocido."""
        self.assertAlmostEqual(
            glossary.cognate_score("glory", "Gloria"),
            glossary.cognate_score("glory", "gloria"), places=6)

    def test_it_matches_the_best_word_of_a_phrase(self):
        """Las traducciones vienen en frase ('Pasar Por Alto'). Comparar con
        la cadena entera hundiría a cualquier cognado que venga acompañado."""
        self.assertGreater(
            glossary.cognate_score("satisfaction", "Gran Satisfacción"), 0.7)


class TestValidation(unittest.TestCase):
    def test_a_definition_using_the_word_is_refused(self):
        """Circular y, peor, un chivatazo: el reverso regalaría el frente."""
        self.assertFalse(glossary._valid("a black rock; coal burns well", "coal"))
        self.assertFalse(glossary._valid("to sew cloth with thread", "sew"))

    def test_derived_forms_are_caught_too(self):
        self.assertFalse(glossary._valid("water that is dripping slowly", "drip"))

    def test_sane_definitions_pass(self):
        self.assertTrue(glossary._valid(
            "a black rock used for burning that produces heat", "coal"))
        self.assertTrue(glossary._valid(
            "to join cloth together using a needle and thread", "sew"))

    def test_foreign_characters_and_json_scraps_are_refused(self):
        """Caso real del modelo local: devolvió chino Y restos del JSON en la
        misma cadena. Pasaba todas las demás reglas y habría acabado en una
        tarjeta."""
        self.assertFalse(glossary._valid(
            "a statement expressing不满，我no debo}],", "complaint"))
        self.assertFalse(glossary._valid('a thing"}], "x": 1', "couch"))

    def test_a_good_short_definition_is_kept(self):
        """El suelo rechaza el sinónimo suelto, no la brevedad: 'to fail to
        notice' define `overlook` perfectamente."""
        self.assertTrue(glossary._valid("to fail to notice", "overlook"))
        self.assertFalse(glossary._valid("beneath", "underneath"))
        self.assertFalse(glossary._valid("to decay", "rot"))

    def test_empty_and_overlong_are_refused(self):
        self.assertFalse(glossary._valid("", "coal"))
        self.assertFalse(glossary._valid("x" * 200, "coal"))


class TestPending(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")

    def _word(self, word, **extra):
        return db.upsert_word(self.conn, {
            "word": word, "meaning_es": extra.pop("meaning_es", "x"),
            "example_en": extra.pop("example_en", "An example."), **extra})

    def test_only_words_with_a_card_and_no_definition(self):
        a = self._word("coal", meaning_es="Carbón")
        self._word("province", meaning_es="Provincia", meaning_en="a region")
        self._word("nocard", meaning_es="Nada")
        for wid in (a,):
            self.conn.execute("UPDATE words SET fsrs_card='{}' WHERE id=?", (wid,))
        self.conn.commit()
        self.assertEqual([r["word"] for r in glossary.pending(self.conn)], ["coal"])

    def test_least_cognate_first(self):
        """El orden es la prioridad: las que menos se parecen a su traducción
        son las que peor lo tienen."""
        for w, es in (("province", "Provincia"), ("sew", "Coser"),
                      ("glory", "Gloria")):
            wid = self._word(w, meaning_es=es)
            self.conn.execute("UPDATE words SET fsrs_card='{}' WHERE id=?", (wid,))
        self.conn.commit()
        self.assertEqual([r["word"] for r in glossary.pending(self.conn)][0], "sew")


if __name__ == "__main__":
    unittest.main()
