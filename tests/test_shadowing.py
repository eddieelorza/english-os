"""Shadowing sobre vídeo (M20). Nada aquí toca la red."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import db, shadowing  # noqa: E402


class TestSplitLong(unittest.TestCase):
    """Whisper suelta tramos de 20 s que son imposibles de repetir de una
    respiración."""

    def test_a_long_segment_is_broken_up(self):
        segs = [{"start": 0.0, "end": 20.0, "confidence": -0.2,
                 "text": " ".join(f"w{i}" for i in range(12))}]
        out = shadowing.split_long(segs)
        self.assertGreater(len(out), 1)
        self.assertTrue(all(s["end"] - s["start"] <= shadowing.MAX_LINE_SECONDS
                            for s in out))

    def test_no_words_are_lost(self):
        segs = [{"start": 0.0, "end": 30.0, "confidence": -0.2,
                 "text": " ".join(f"w{i}" for i in range(20))}]
        joined = " ".join(s["text"] for s in shadowing.split_long(segs))
        self.assertEqual(joined.split(), [f"w{i}" for i in range(20)])

    def test_short_segments_are_left_alone(self):
        segs = [{"start": 0.0, "end": 5.0, "text": "a short line",
                 "confidence": -0.3}]
        self.assertEqual(shadowing.split_long(segs), segs)

    def test_the_timeline_stays_in_order(self):
        segs = [{"start": 10.0, "end": 40.0, "confidence": -0.2,
                 "text": " ".join(f"w{i}" for i in range(20))}]
        out = shadowing.split_long(segs)
        self.assertEqual(out[0]["start"], 10.0)
        self.assertAlmostEqual(out[-1]["end"], 40.0, places=1)
        for a, b in zip(out, out[1:]):
            self.assertLessEqual(a["end"], b["start"] + 0.01)


class TestUrlGuards(unittest.TestCase):
    def test_a_non_url_is_refused_before_touching_the_network(self):
        for bad in ("", "not a url", "ftp://x/y", "javascript:alert(1)"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                shadowing._check_url(bad)

    def test_http_and_https_pass(self):
        self.assertTrue(shadowing._check_url("https://youtu.be/abc"))
        self.assertTrue(shadowing._check_url("http://example.com/v"))


class TestCreate(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")

    def test_a_long_video_is_refused_before_downloading(self):
        """Negarse pronto: bajar y transcribir una hora de vídeo son minutos
        de espera para acabar en el mismo error."""
        with mock.patch.object(shadowing, "probe", return_value={
                "video_id": "x", "title": "t", "channel": "c",
                "seconds": shadowing.MAX_SECONDS + 1}) as probe, \
             mock.patch.object(shadowing, "_download") as dl:
            with self.assertRaises(ValueError):
                shadowing.create(self.conn, "https://y/1")
        probe.assert_called_once()
        dl.assert_not_called()

    def test_the_same_video_is_not_transcribed_twice(self):
        meta = {"video_id": "vid1", "title": "t", "channel": "c", "seconds": 60}
        heard = {"duration_seconds": 60.0, "segments": [
            {"start": 0.0, "end": 3.0, "text": "hello there", "confidence": -0.2}]}
        with mock.patch.object(shadowing, "probe", return_value=meta), \
             mock.patch.object(shadowing, "_download",
                               return_value=Path("/tmp/vid1.m4a")), \
             mock.patch.object(shadowing.speaking, "transcribe",
                               return_value=heard) as tr:
            first = shadowing.create(self.conn, "https://y/1")
            again = shadowing.create(self.conn, "https://y/1")
        self.assertEqual(first["id"], again["id"])
        tr.assert_called_once()

    def test_transcription_runs_without_the_voice_filter(self):
        """Con VAD, una canción de 3.4 min dio 31 palabras; sin él, 282. Es la
        diferencia entre servir y no servir."""
        meta = {"video_id": "v2", "title": "t", "channel": "c", "seconds": 60}
        heard = {"duration_seconds": 60.0, "segments": [
            {"start": 0.0, "end": 3.0, "text": "hello", "confidence": -0.2}]}
        with mock.patch.object(shadowing, "probe", return_value=meta), \
             mock.patch.object(shadowing, "_download",
                               return_value=Path("/tmp/v2.m4a")), \
             mock.patch.object(shadowing.speaking, "transcribe",
                               return_value=heard) as tr:
            shadowing.create(self.conn, "https://y/2")
        self.assertIs(tr.call_args.kwargs["vad"], False)
        self.assertIs(tr.call_args.kwargs["segments_out"], True)

    def test_a_silent_video_is_an_error_not_an_empty_session(self):
        meta = {"video_id": "v3", "title": "t", "channel": "c", "seconds": 60}
        with mock.patch.object(shadowing, "probe", return_value=meta), \
             mock.patch.object(shadowing, "_download",
                               return_value=Path("/tmp/v3.m4a")), \
             mock.patch.object(shadowing.speaking, "transcribe",
                               return_value={"duration_seconds": 60.0,
                                             "segments": []}):
            with self.assertRaises(ValueError):
                shadowing.create(self.conn, "https://y/3")
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM shadow_sessions").fetchone()[0], 0)

    def test_marking_a_line_advances_the_count(self):
        meta = {"video_id": "v4", "title": "t", "channel": "c", "seconds": 60}
        heard = {"duration_seconds": 60.0, "segments": [
            {"start": 0.0, "end": 3.0, "text": "one", "confidence": -0.2},
            {"start": 3.0, "end": 6.0, "text": "two", "confidence": -0.2}]}
        with mock.patch.object(shadowing, "probe", return_value=meta), \
             mock.patch.object(shadowing, "_download",
                               return_value=Path("/tmp/v4.m4a")), \
             mock.patch.object(shadowing.speaking, "transcribe",
                               return_value=heard):
            s = shadowing.create(self.conn, "https://y/4")
        self.assertEqual(s["done"], 0)
        after = shadowing.mark(self.conn, s["lines"][0]["id"], True)
        self.assertEqual(after["done"], 1)
        self.assertEqual(shadowing.mark(
            self.conn, s["lines"][0]["id"], False)["done"], 0)


if __name__ == "__main__":
    unittest.main()
