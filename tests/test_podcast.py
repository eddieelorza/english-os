"""M11 tests: dialogue generation, two-voice marks, listening time."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import db, podcast, tts  # noqa: E402

FAKE_EPISODE = {
    "title": "Coal, deadlines and other disasters",
    "speaker_a_name": "Dani",
    "speaker_b_name": "Marcus",
    "turns": [
        {"speaker": "A", "text": "So, did you endure that meeting?"},
        {"speaker": "B", "text": "Barely. I thought I'd burst."},
        {"speaker": "A", "text": "Right? It went on forever."},
    ],
    "questions": [
        {"question": "What did Marcus say about the meeting?",
         "options": ["He enjoyed it", "He barely endured it", "He skipped it"],
         "answer_index": 1, "why": "Dijo 'barely'."},
    ] * 4,
}


class FakeAI:
    def generate_json(self, system, prompt, schema, max_tokens=4096):
        return json.loads(json.dumps(FAKE_EPISODE))


class FakeTTS:
    """Stands in for Kokoro: records which voice each turn asked for."""
    name = "fake"
    voices_used: "list[str]" = []


def fake_narrate_turns(turns):
    FakeTTS.voices_used = [f"speaker_{t['speaker'].lower()}" for t in turns]
    marks, cursor = [], 0.0
    for i, t in enumerate(turns):
        marks.append({"text": t["text"], "turn": i, "speaker": t["speaker"],
                      "start": cursor, "end": cursor + 2.0})
        cursor += 2.35
    return {"path": "tts/fake.wav", "marks": marks,
            "provider": "fake", "cached": False}


def seed(conn):
    for w in ("endure", "burst", "coal"):
        db.upsert_word(conn, {"word": w, "status": "LEARNING"})


class TestGeneration(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        seed(self.conn)

    def make(self, minutes=5):
        with mock.patch.object(podcast.ai, "get_provider", return_value=FakeAI()), \
             mock.patch.object(podcast.tts, "narrate_turns", fake_narrate_turns):
            return podcast.generate(self.conn, minutes=minutes, topic="Work")

    def test_stores_dialogue_audio_and_questions(self):
        ep = self.make()
        self.assertEqual(ep["speakers"], {"A": "Dani", "B": "Marcus"})
        self.assertEqual(len(ep["turns"]), 3)
        self.assertEqual(len(ep["questions"]), 4)
        self.assertEqual(ep["audio"], "tts/fake.wav")
        row = self.conn.execute("SELECT kind, body FROM texts WHERE id=?",
                                (ep["id"],)).fetchone()
        self.assertEqual(row["kind"], "podcast")
        self.assertIn("Dani: So, did you endure", row["body"])

    def test_marks_carry_turn_and_speaker(self):
        ep = self.make()
        self.assertEqual([m["speaker"] for m in ep["marks"]], ["A", "B", "A"])
        self.assertEqual(ep["marks"][1]["turn"], 1)
        self.assertGreater(ep["marks"][1]["start"], ep["marks"][0]["end"] - 1)

    def test_each_turn_asks_for_its_own_voice(self):
        self.make()
        self.assertEqual(FakeTTS.voices_used,
                         ["speaker_a", "speaker_b", "speaker_a"])

    def test_invalid_length_rejected(self):
        with self.assertRaises(ValueError):
            podcast.generate(self.conn, minutes=99)

    def test_listed_and_finish_track_listening_minutes(self):
        ep = self.make()
        self.assertEqual(len(podcast.listed(self.conn)), 1)
        r = podcast.finish(self.conn, ep["id"], seconds=300)
        self.assertEqual(r["listening_minutes_today"], 5.0)
        podcast.finish(self.conn, ep["id"], seconds=120)
        row = self.conn.execute("SELECT listening_minutes FROM sessions").fetchone()
        self.assertEqual(row[0], 7.0)  # accumulates across episodes
        self.assertTrue(podcast.listed(self.conn)[0]["finished"])

    def test_empty_dialogue_rejected(self):
        empty = {**FAKE_EPISODE, "turns": [{"speaker": "A", "text": "  "}]}
        with mock.patch.object(podcast.ai, "get_provider",
                               return_value=mock.Mock(
                                   generate_json=lambda *a, **k: empty)):
            with self.assertRaises(ValueError):
                podcast.generate(self.conn)


class TestVoiceRoster(unittest.TestCase):
    def test_two_distinct_voices_are_configured(self):
        self.assertNotEqual(tts.VOICES["speaker_a"], tts.VOICES["speaker_b"])


if __name__ == "__main__":
    unittest.main()
