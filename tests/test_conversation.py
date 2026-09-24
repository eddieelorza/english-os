"""Conversación hablada (M19): recorte de errores y ciclo de turnos."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import conversation, db  # noqa: E402


class TestTighten(unittest.TestCase):
    """El modelo devuelve la frase entera aunque el prompt pida el trozo roto.
    Se recorta con un diff porque `errors` deduplica por (categoría,
    original): con frases enteras, el mismo fallo dos veces cuenta como dos
    errores y las recurrencias nunca suben."""

    def test_it_keeps_only_what_changed(self):
        self.assertEqual(
            conversation.tighten("We did a mistake last month",
                                 "We made a mistake last month"),
            ("We did a mistake", "We made a mistake"))

    def test_two_distant_changes_do_not_swallow_the_sentence(self):
        """La envolvente de todos los cambios vuelve a ser la frase entera
        cuando hay uno al principio y otro al final. Se toma el primero."""
        o, c = conversation.tighten(
            "We did a mistake because we did not measure the drop off",
            "We made a mistake because we did not measure the drop-off")
        self.assertIn("did a mistake", o)
        self.assertIn("made a mistake", c)
        self.assertNotIn("drop", o)

    def test_identical_text_survives_unchanged(self):
        self.assertEqual(conversation.tighten("all good", "all good"),
                         ("all good", "all good"))

    def test_context_is_kept_so_the_fix_is_readable(self):
        """'in' -> 'on' a secas no se entiende; hace falta el vecindario."""
        o, c = conversation.tighten("I am working in a new feature",
                                    "I am working on a new feature")
        self.assertGreater(len(o.split()), 1)
        self.assertIn("working", o)


class TestStrength(unittest.TestCase):
    """Caso real: corrigió "since two years" y en la misma pantalla felicitó
    por "usaste bien el pasado simple al decir 'go there since two years'".
    Contradecirse así tira la confianza en todo el resumen."""

    CORRECTIONS = [{"original": "since two years", "correction": "for two years"}]

    def test_a_strength_that_praises_a_corrected_phrase_is_dropped(self):
        self.assertEqual(conversation._clean_strength(
            "Usaste bien el pasado simple al decir 'go there since two years'",
            self.CORRECTIONS), "")

    def test_a_real_strength_survives(self):
        text = "Contaste la anécdota del restaurante sin pararte a pensar"
        self.assertEqual(
            conversation._clean_strength(text, self.CORRECTIONS), text)

    def test_one_shared_word_is_not_enough_to_drop_it(self):
        """Compartir 'two' no es citar el error. Si bastara una palabra,
        cualquier fortaleza normal desaparecería."""
        text = 'Buen uso de "two" al dar cantidades'
        self.assertEqual(
            conversation._clean_strength(text, self.CORRECTIONS), text)

    def test_no_corrections_means_nothing_to_contradict(self):
        text = "Hablaste seguido y sin pausas largas"
        self.assertEqual(conversation._clean_strength(text, []), text)


class TestTurnCycle(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.tts = mock.patch.object(
            conversation.tts, "narrate",
            return_value={"path": "tts/x.wav", "marks": []}).start()
        self.addCleanup(mock.patch.stopall)

    def _provider(self, reply="Sure. What happened next?", summary=None):
        p = mock.Mock()
        p.generate_json.side_effect = lambda sysmsg, prompt, schema: (
            summary if summary is not None and "corrections" in str(schema)
            else {"reply": reply})
        return p

    def test_start_records_the_partner_speaking_first(self):
        with mock.patch.object(conversation.ai, "get_provider",
                               return_value=self._provider("Hey, how is the release going?")):
            r = conversation.start(self.conn, topic="work")
        turns = conversation.turns(self.conn, r["conversation_id"])
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["speaker"], "partner")

    def test_a_turn_stores_both_sides(self):
        with mock.patch.object(conversation.ai, "get_provider",
                               return_value=self._provider()), \
             mock.patch.object(conversation.speaking, "transcribe",
                               return_value={"text": "I did a mistake",
                                             "duration_seconds": 4.0}):
            r = conversation.start(self.conn)
            conversation.say(self.conn, r["conversation_id"], "x.wav")
        speakers = [t["speaker"] for t in
                    conversation.turns(self.conn, r["conversation_id"])]
        self.assertEqual(speakers, ["partner", "eddie", "partner"])

    def test_silence_is_refused_not_stored(self):
        with mock.patch.object(conversation.ai, "get_provider",
                               return_value=self._provider()), \
             mock.patch.object(conversation.speaking, "transcribe",
                               return_value={"text": "  ", "duration_seconds": 0}):
            r = conversation.start(self.conn)
            with self.assertRaises(ValueError):
                conversation.say(self.conn, r["conversation_id"], "x.wav")
        self.assertEqual(len(conversation.turns(self.conn, r["conversation_id"])), 1)

    def test_finish_caps_the_corrections(self):
        """El tope es una promesa de la función, no una sugerencia al modelo:
        cinco correcciones de golpe es justo lo abrumador que se evita."""
        many = {"corrections": [
            {"category": "PREP", "original": f"working in feature {i}",
             "correction": f"working on feature {i}", "explanation": "x"}
            for i in range(5)], "strength": "Hablaste sin pararte a pensar"}
        with mock.patch.object(conversation.ai, "get_provider",
                               return_value=self._provider(summary=many)), \
             mock.patch.object(conversation.speaking, "transcribe",
                               return_value={"text": "working in feature 1",
                                             "duration_seconds": 3.0}):
            r = conversation.start(self.conn)
            conversation.say(self.conn, r["conversation_id"], "x.wav")
            out = conversation.finish(self.conn, r["conversation_id"])
        self.assertEqual(len(out["corrections"]), conversation.MAX_CORRECTIONS)

    def test_invented_categories_are_dropped(self):
        bad = {"corrections": [
            {"category": "GRAMMAR", "original": "a", "correction": "b",
             "explanation": "x"}], "strength": "ok"}
        with mock.patch.object(conversation.ai, "get_provider",
                               return_value=self._provider(summary=bad)), \
             mock.patch.object(conversation.speaking, "transcribe",
                               return_value={"text": "hello", "duration_seconds": 2.0}):
            r = conversation.start(self.conn)
            conversation.say(self.conn, r["conversation_id"], "x.wav")
            out = conversation.finish(self.conn, r["conversation_id"])
        self.assertEqual(out["corrections"], [])

    def test_finish_twice_does_not_double_count_errors(self):
        one = {"corrections": [
            {"category": "PREP", "original": "working in the feature",
             "correction": "working on the feature", "explanation": "x"}],
            "strength": "ok"}
        with mock.patch.object(conversation.ai, "get_provider",
                               return_value=self._provider(summary=one)), \
             mock.patch.object(conversation.speaking, "transcribe",
                               return_value={"text": "working in the feature",
                                             "duration_seconds": 3.0}):
            r = conversation.start(self.conn)
            conversation.say(self.conn, r["conversation_id"], "x.wav")
            conversation.finish(self.conn, r["conversation_id"])
            again = conversation.finish(self.conn, r["conversation_id"])
        self.assertTrue(again["already_closed"])
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM errors").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
