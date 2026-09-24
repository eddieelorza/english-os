"""M8 tests: apkg import mapping + TTS sentence splitting and caching."""

from __future__ import annotations

import json
import sys
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import db, tts  # noqa: E402
from app.importers import apkg  # noqa: E402


def make_apkg(tmp: Path) -> Path:
    """A miniature .apkg: two notes, one matching a local word."""
    col = tmp / "collection.anki2"
    import sqlite3
    c = sqlite3.connect(col)
    c.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, flds TEXT)")
    c.execute("INSERT INTO notes VALUES (1, ?)",
              ("forge\x1f<img src=\"w1.jpg\">\x1f[sound:w1.mp3]\x1f"
               "[sound:w1_example.mp3]\x1fforjar",))
    c.execute("INSERT INTO notes VALUES (2, ?)",
              ("absent\x1f\x1f[sound:w2.mp3]\x1f\x1fausente",))
    c.commit()
    c.close()
    for name in ("m0", "m1", "m2", "m3"):
        (tmp / name).write_bytes(b"fake-media")
    (tmp / "media").write_text(json.dumps(
        {"m0": "w1.mp3", "m1": "w1_example.mp3", "m2": "w1.jpg", "m3": "w2.mp3"}))
    path = tmp / "deck.apkg"
    with zipfile.ZipFile(path, "w") as z:
        for f in ("collection.anki2", "media", "m0", "m1", "m2", "m3"):
            z.write(tmp / f, f)
    return path


class TestApkgImport(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        db.upsert_word(self.conn, {"word": "Forge"})  # case-insensitive match

    def test_links_audio_and_image_to_matching_word(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            deck = make_apkg(tmp)
            media = tmp / "out"
            with mock.patch.object(apkg, "AUDIO_DIR", media / "audio"), \
                 mock.patch.object(apkg, "IMAGE_DIR", media / "images"):
                stats = apkg.run(self.conn, deck)
            self.assertEqual(stats["words_linked"], 1)
            self.assertEqual(stats["unmatched"], 1)  # 'absent' not in local DB
            row = self.conn.execute(
                "SELECT * FROM words WHERE normalized='forge'").fetchone()
            self.assertEqual(row["audio_word"], "audio/w1.mp3")
            self.assertEqual(row["audio_example"], "audio/w1_example.mp3")
            self.assertEqual(row["image_path"], "images/w1.jpg")

    def test_import_is_idempotent(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            deck = make_apkg(tmp)
            media = tmp / "out"
            with mock.patch.object(apkg, "AUDIO_DIR", media / "audio"), \
                 mock.patch.object(apkg, "IMAGE_DIR", media / "images"):
                apkg.run(self.conn, deck)
                apkg.run(self.conn, deck)
            n = self.conn.execute(
                "SELECT COUNT(*) FROM words WHERE audio_word IS NOT NULL").fetchone()[0]
            self.assertEqual(n, 1)

    def test_missing_apkg_is_a_skip_not_a_crash(self):
        stats = apkg.run(self.conn, Path("/nonexistent/deck.apkg"))
        self.assertEqual(stats["words_linked"], 0)


class TestSentenceSplitting(unittest.TestCase):
    def test_splits_on_terminators_keeping_them(self):
        s = tts.split_sentences("Carlos worked hard. Was it enough? Yes!")
        self.assertEqual(s, ["Carlos worked hard.", "Was it enough?", "Yes!"])

    def test_paragraphs_do_not_merge(self):
        s = tts.split_sentences("First para\n\nSecond para")
        self.assertEqual(s, ["First para", "Second para"])

    def test_empty_text_yields_nothing(self):
        self.assertEqual(tts.split_sentences("   \n  "), [])


class FakeTTS(tts.TTSProvider):
    name = "fake"
    calls = 0

    def available(self):
        return True

    def synth_sentences(self, sentences, voice, out_path):
        FakeTTS.calls += 1
        out_path.write_bytes(b"fake-audio")
        marks, cursor = [], 0.0
        for s in sentences:
            marks.append({"text": s, "start": cursor, "end": cursor + 1.0})
            cursor += 1.0
        return marks


class TestNarrateCache(unittest.TestCase):
    def test_second_call_is_served_from_cache(self):
        import tempfile
        FakeTTS.calls = 0
        with tempfile.TemporaryDirectory() as t:
            with mock.patch.object(tts, "TTS_DIR", Path(t)), \
                 mock.patch.object(tts, "get_provider", return_value=FakeTTS()):
                first = tts.narrate("One sentence. Two sentences.")
                second = tts.narrate("One sentence. Two sentences.")
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(FakeTTS.calls, 1)
        self.assertEqual(len(first["marks"]), 2)
        self.assertEqual(first["marks"][1]["start"], 1.0)


if __name__ == "__main__":
    unittest.main()
