"""Own voice: mocked synthesis and isolated endpoint tests, never paid calls."""

import base64
from contextlib import closing
import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import numpy as np
import soundfile as sf

from app import db, tts


class OwnVoiceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.env = mock.patch.dict(os.environ, {
            "ELEVENLABS_API_KEY": "secret-test-key",
            "ELEVENLABS_VOICE_ID": "test-clone",
            "ENGLISHOS_DOTENV": "0",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        patch = mock.patch.object(tts, "TTS_DIR", self.root / "tts")
        patch.start()
        self.addCleanup(patch.stop)
        self.network = mock.patch("urllib.request.urlopen")
        self.urlopen = self.network.start()
        self.addCleanup(self.network.stop)

    def response(self, text):
        alignment = {
            "characters": list(text),
            "character_start_times_seconds": [i / 10 for i in range(len(text))],
            "character_end_times_seconds": [(i + 1) / 10 for i in range(len(text))],
        }
        pcm = np.array([-32768, 0, 16384, 32767], dtype="<i2")
        result = {"audio_base64": base64.b64encode(pcm.tobytes()).decode(),
                  "alignment": alignment}
        self.urlopen.return_value = io.BytesIO(json.dumps(result).encode())
        return alignment

    def test_full_text_alignment_cache_and_request(self):
        text = "  Hello world.\nAgain!  Hello world."
        alignment = self.response(text)
        first = tts.narrate_own(text)
        second = tts.narrate_own(text)
        self.urlopen.assert_called_once()
        request = self.urlopen.call_args.args[0]
        self.assertEqual(self.urlopen.call_args.kwargs, {"timeout": 300})
        self.assertEqual(request.full_url,
                         "https://api.elevenlabs.io/v1/text-to-speech/test-clone/"
                         "with-timestamps?output_format=pcm_24000")
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.get_header("Xi-api-key"), "secret-test-key")
        self.assertEqual(json.loads(request.data), {
            "text": text, "model_id": "eleven_multilingual_v2"})
        cursor = 0
        for mark, sentence in zip(first["marks"], tts.split_sentences(text)):
            start = text.find(sentence, cursor)
            cursor = start + len(sentence)
            self.assertEqual(mark, {"text": sentence,
                "start": alignment["character_start_times_seconds"][start],
                "end": alignment["character_end_times_seconds"][cursor - 1]})
        self.assertEqual(len(first["marks"]), 3)
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(first["marks"], second["marks"])
        self.assertEqual(first["provider"], "eleven")
        audio, rate = sf.read(self.root / first["path"])
        self.assertEqual(rate, 24000)
        np.testing.assert_allclose(audio, [-1, 0, .5, 32767 / 32768])
        self.assertTrue(tts.own_voice_cached("reading", text, []))
        (self.root / first["path"]).with_suffix(".json").unlink()
        self.assertFalse(tts.own_voice_cached("reading", text, []))

    def test_http_errors_never_expose_credentials(self):
        cases = [(401, b"secret-test-key", "ElevenLabs rechazó la clave"),
                 (402, b"", "Se acabaron los créditos de ElevenLabs"),
                 (429, b'{"status":"quota_exceeded"}',
                  "Se acabaron los créditos de ElevenLabs"),
                 (500, b"secret-test-key", "ElevenLabs no respondió (HTTP 500)")]
        for code, body, message in cases:
            with self.subTest(code=code):
                self.urlopen.side_effect = urllib.error.HTTPError(
                    "https://example.invalid/secret-test-key", code,
                    "secret-test-key", {}, io.BytesIO(body))
                with self.assertRaises(tts.TTSUnavailable) as raised:
                    tts._eleven("Hello.")
                self.assertEqual(str(raised.exception), message)
                self.assertNotIn("secret-test-key", str(raised.exception))

    def test_transport_and_invalid_json_errors_are_sanitized(self):
        for error in (urllib.error.URLError("secret-test-key"),
                      TimeoutError("secret-test-key")):
            self.urlopen.side_effect = error
            with self.assertRaises(tts.TTSUnavailable) as raised:
                tts._eleven("Hello.")
            self.assertNotIn("secret-test-key", str(raised.exception))
        self.urlopen.side_effect = None
        self.urlopen.return_value = io.BytesIO(b"secret-test-key")
        with self.assertRaises(tts.TTSUnavailable):
            tts._eleven("Hello.")

    def test_missing_either_setting_does_not_call_network(self):
        for name in ("ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID"):
            with mock.patch.dict(os.environ, {name: ""}):
                self.assertFalse(tts.own_voice_configured())
                with self.assertRaises(tts.TTSUnavailable):
                    tts._eleven("Hello.")
        self.urlopen.assert_not_called()

    def test_changed_clone_has_separate_cache(self):
        self.response("Hello.")
        first = tts.narrate_own("Hello.")
        with mock.patch.dict(os.environ, {"ELEVENLABS_VOICE_ID": "other-clone"}):
            self.assertFalse(tts.own_voice_cached("reading", "Hello.", []))
            self.response("Hello.")
            second = tts.narrate_own("Hello.")
        self.assertNotEqual(first["path"], second["path"])

    def test_podcast_only_b_uses_eleven_and_cache_preserves_gaps(self):
        turns = [{"speaker": "A", "text": "Hello."},
                 {"speaker": "B", "text": "Hi!"},
                 {"speaker": "A", "text": "How are you?"},
                 {"speaker": "B", "text": "Great."}]
        audio = np.zeros(tts.SAMPLE_RATE, dtype=np.float32)
        pipe = mock.Mock(return_value=[(None, None, audio)])
        with mock.patch.object(tts.KokoroProvider, "available", return_value=True), \
             mock.patch.object(tts.KokoroProvider, "_pipe", return_value=pipe), \
             mock.patch.object(tts, "_eleven", return_value=(audio, {})) as eleven, \
             mock.patch.object(tts, "get_provider", side_effect=AssertionError):
            first = tts.narrate_turns_own(turns)
            second = tts.narrate_turns_own(turns)
        self.assertEqual(eleven.call_args_list, [mock.call("Hi!"), mock.call("Great.")])
        self.assertEqual(pipe.call_args_list, [
            mock.call("Hello.", voice=tts.VOICES["speaker_a"]),
            mock.call("How are you?", voice=tts.VOICES["speaker_a"])])
        self.assertEqual(first["provider"], "eleven")
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertTrue(tts.own_voice_cached("podcast", "", turns))
        for i, mark in enumerate(first["marks"]):
            self.assertEqual(mark, {**turns[i], "turn": i,
                                   "start": round(i * 1.35, 3),
                                   "end": round(i * 1.35 + 1, 3)})
        samples, rate = sf.read(self.root / first["path"])
        self.assertEqual(len(samples), int(rate * 5.4))
        self.assertEqual(tts.own_voice_chars("podcast", "ignored", turns), 9)
        self.assertEqual(tts.own_voice_chars("reading", "Hello.", turns), 6)
        self.urlopen.assert_not_called()

    def test_podcast_retry_does_not_pay_twice_for_finished_turns(self):
        turns = [{"speaker": "B", "text": "One."}, {"speaker": "B", "text": "Two."}]
        audio = np.zeros(10, dtype=np.float32)
        pipe = mock.Mock(return_value=[])
        with mock.patch.object(tts.KokoroProvider, "available", return_value=True), \
             mock.patch.object(tts.KokoroProvider, "_pipe", return_value=pipe), \
             mock.patch.object(tts, "_eleven",
                               side_effect=[(audio, {}), tts.TTSUnavailable("out")]):
            with self.assertRaises(tts.TTSUnavailable):
                tts.narrate_turns_own(turns)
        with mock.patch.object(tts.KokoroProvider, "available", return_value=True), \
             mock.patch.object(tts.KokoroProvider, "_pipe", return_value=pipe), \
             mock.patch.object(tts, "_eleven", return_value=(audio, {})) as eleven:
            tts.narrate_turns_own(turns)
        self.assertEqual(eleven.call_args_list, [mock.call("Two.")])

    def test_podcast_requires_kokoro(self):
        with mock.patch.object(tts.KokoroProvider, "available", return_value=False):
            with self.assertRaises(tts.TTSUnavailable):
                tts.narrate_turns_own([{"speaker": "B", "text": "Hello."}])
        self.urlopen.assert_not_called()

    def client(self, kind="reading", body="Hello.", turns=None):
        from app import server
        from fastapi.testclient import TestClient
        path = self.root / "test.db"
        with closing(db.connect(str(path))) as conn:
            conn.execute("INSERT INTO texts (id, kind, body, correction, created_at, "
                         "updated_at) VALUES (1, ?, ?, ?, ?, ?)",
                         (kind, body, json.dumps({"turns": turns}), db.now_iso(), db.now_iso()))
            conn.commit()
        env = mock.patch.dict(os.environ, {"ENGLISH_DB_PATH": str(path)})
        env.start()
        self.addCleanup(env.stop)
        worker = mock.patch.object(server.jobs, "ensure_worker")
        worker.start()
        self.addCleanup(worker.stop)
        return TestClient(server.app)

    def test_get_unconfigured_and_missing_text(self):
        client = self.client()
        os.environ.pop("ELEVENLABS_API_KEY", None)
        os.environ.pop("ELEVENLABS_VOICE_ID", None)
        response = client.get("/api/texts/1/own-voice")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"configured": False, "cached": False, "chars": 6})
        for method in (client.get, client.post):
            self.assertEqual(method("/api/texts/99/own-voice").status_code, 404)
        self.assertEqual(client.post("/api/texts/1/own-voice").status_code, 503)
        self.urlopen.assert_not_called()

    def test_reading_endpoint_caches_without_changing_coach_fields(self):
        client = self.client(kind="imported")
        self.response("Hello.")
        with mock.patch("app.jobs._exclusive", side_effect=AssertionError):
            first = client.post("/api/texts/1/own-voice")
            second = client.post("/api/texts/1/own-voice")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(set(first.json()), {"path", "marks", "cached"})
        self.assertTrue(second.json()["cached"])
        self.assertTrue(client.get("/api/texts/1/own-voice").json()["cached"])
        self.urlopen.assert_called_once()
        with closing(db.connect(os.environ["ENGLISH_DB_PATH"])) as conn:
            row = conn.execute("SELECT tts_path, tts_marks FROM texts WHERE id=1").fetchone()
            self.assertIsNone(row["tts_path"])
            self.assertIsNone(row["tts_marks"])

    def test_podcast_endpoint_uses_turns_and_cpu_lock(self):
        turns = [{"speaker": "A", "text": "Hello."}, {"speaker": "B", "text": "Hi!"}]
        client = self.client(kind="podcast", turns=turns)
        self.assertEqual(client.get("/api/texts/1/own-voice").json()["chars"], 3)
        result = {"path": "tts/fake.wav", "marks": [], "cached": False, "provider": "eleven"}
        with mock.patch("app.jobs._exclusive") as lock, \
             mock.patch.object(tts, "narrate_turns_own", return_value=result) as narrate:
            response = client.post("/api/texts/1/own-voice")
        self.assertEqual(response.status_code, 200)
        narrate.assert_called_once_with(turns)
        lock.return_value.__enter__.assert_called_once()
        self.urlopen.assert_not_called()

    def test_endpoint_sanitizes_authentication_error(self):
        client = self.client()
        self.urlopen.side_effect = urllib.error.HTTPError(
            "https://example.invalid", 401, "secret-test-key", {}, io.BytesIO(b"secret-test-key"))
        response = client.post("/api/texts/1/own-voice")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "ElevenLabs rechazó la clave"})
        self.assertNotIn("secret-test-key", response.text)


if __name__ == "__main__":
    unittest.main()
