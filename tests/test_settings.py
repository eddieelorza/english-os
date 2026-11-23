"""Settings tests use only a temporary .env and mocked HTTP requests."""

import io
import json
import os
import stat
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient


class SettingsTests(unittest.TestCase):
    def setUp(self):
        environment = mock.patch.dict(os.environ, {"ENGLISHOS_DOTENV": "0"}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        from app import server, settings
        self.settings = settings
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / ".env"
        path = mock.patch.object(settings, "ENV_PATH", self.path)
        path.start()
        self.addCleanup(path.stop)
        self.client = TestClient(server.app, base_url="http://localhost:8771")
        self.addCleanup(self.client.close)
        network = mock.patch("urllib.request.urlopen")
        self.urlopen = network.start()
        self.addCleanup(network.stop)

    def put(self, values, **kwargs):
        return self.client.put("/api/settings", json={"values": values}, **kwargs)

    def voice(self, **kwargs):
        return self.client.post("/api/settings/test/elevenlabs", json={}, **kwargs)

    def configure_voice(self):
        os.environ.update(ELEVENLABS_API_KEY="secret-eleven-key", ELEVENLABS_VOICE_ID="AbCd0123456789")

    def test_get_masks_all_secrets(self):
        secrets = {key: f"secret-{key}-abcd" for key, field in self.settings.BY_KEY.items()
                   if field["kind"] == "secret"}
        os.environ.update(secrets)
        response = self.client.get("/api/settings")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual([group["name"] for group in response.json()["groups"]], ["AI", "Voice", "Budget"])
        for group in response.json()["groups"]:
            for field in group["fields"]:
                if field["kind"] == "secret":
                    self.assertNotIn("value", field)
                    self.assertEqual((field["set"], field["hint"]), (True, "…abcd"))
        for secret in secrets.values():
            self.assertNotIn(secret, response.text)
        os.environ["GEMINI_API_KEY"] = "xyz"
        self.assertNotIn("xyz", self.client.get("/api/settings").text)

    def test_put_replaces_adds_deletes_and_preserves_bytes(self):
        original = b'# Keep this comment\r\nAI_PROVIDER=auto\r\nOTHER="untouched" # comment\r\n\r\nGEMINI_MODEL=old\r\nAI_MODEL=old\r\n# Last comment'
        self.path.write_bytes(original)
        os.environ.update(GEMINI_MODEL="old", AI_MODEL="old")
        response = self.put({"AI_PROVIDER": "ollama", "GEMINI_MODEL": None,
                             "AI_MODEL": "", "ELEVENLABS_API_KEY": "secret-added-abcd"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.path.read_bytes(), b'# Keep this comment\r\nAI_PROVIDER=ollama\r\nOTHER="untouched" # comment\r\n\r\n# Last comment\r\nELEVENLABS_API_KEY=secret-added-abcd\r\n')
        backup = self.path.with_name(".env.bak")
        self.assertEqual(backup.read_bytes(), original)
        for path in (self.path, backup):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(os.environ["AI_PROVIDER"], "ollama")
        self.assertEqual(os.environ["ELEVENLABS_API_KEY"], "secret-added-abcd")
        self.assertNotIn("AI_MODEL", os.environ)
        self.assertNotIn("GEMINI_MODEL", os.environ)
        self.assertNotIn("secret-added-abcd", response.text)
        self.assertEqual(response.json(), self.client.get("/api/settings").json())

    def test_missing_file_and_noop(self):
        self.assertEqual(self.put({}).status_code, 200)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.put({"AI_PROVIDER": "auto"}).status_code, 200)
        self.assertEqual(self.path.read_text(), "AI_PROVIDER=auto\n")
        self.assertEqual(self.path.with_name(".env.bak").read_bytes(), b"")

    def test_duplicates_cannot_resurrect_removed_value(self):
        self.path.write_text("AI_MODEL=one\nAI_MODEL=two\n")
        self.assertEqual(self.put({"AI_MODEL": "new"}).status_code, 200)
        self.assertEqual(self.path.read_text(), "AI_MODEL=new\n")
        self.assertEqual(self.put({"AI_MODEL": None}).status_code, 200)
        self.assertEqual(self.path.read_text(), "")

    def test_comments_on_changed_lines_survive(self):
        self.path.write_text('AI_MODEL="old # part of value" # model note\nGEMINI_MODEL=old # keep note\n')
        self.assertEqual(self.put({"AI_MODEL": "new", "GEMINI_MODEL": None}).status_code, 200)
        self.assertEqual(self.path.read_text(), '# model note\nAI_MODEL=new\n# keep note\n')

    def test_review_settings_remain_available_separately(self):
        from app import server
        with mock.patch.object(server, "get_db") as database, \
                mock.patch.object(server.session, "settings", return_value={"mode": "auto"}), \
                mock.patch.object(server.session, "save_settings", return_value={"mode": "counts"}) as save:
            self.assertEqual(self.client.get("/api/session/settings").json(), {"mode": "auto"})
            response = self.client.patch("/api/session/settings", json={"mode": "counts"})
            self.assertEqual(response.json(), {"mode": "counts"})
            save.assert_called_once_with(database.return_value.__enter__.return_value, {"mode": "counts"})

    def test_invalid_values_are_atomic_and_redacted(self):
        original = b"# unchanged\nAI_PROVIDER=auto\n"
        self.path.write_bytes(original)
        cases = [("NOT_ALLOWED", "secret-value"), ("ANTHROPIC_API_KEY", "secret\nINJECTED=yes"),
                 ("GEMINI_API_KEY", "secret\rvalue"), ("AI_MODEL", "x" * 301),
                 ("AI_MODEL", "secret\u2028INJECTED=yes"), ("AI_ROUTE", "enabled"),
                 ("AI_DAILY_USD", "-1"), ("AI_DAILY_USD", "nan"),
                 ("AI_CLOUD_BUDGET_USD", "inf"), ("AI_CLOUD_BUDGET_USD", "abc"),
                 ("ELEVENLABS_VOICE_ID", "short"), ("ELEVENLABS_VOICE_ID", "abcdefghij/"),
                 ("OLLAMA_URL", "http://localhost.evil.test:11434"),
                 ("OLLAMA_URL", "http://127.0.0.1@evil.test"),
                 ("OLLAMA_URL", "https://localhost:11434"),
                 ("OLLAMA_URL", "http://localhost:99999"),
                 ("OLLAMA_URL", "http://user@localhost:11434")]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                response = self.put({"AI_PROVIDER": "ollama", key: value})
                self.assertEqual(response.status_code, 422, response.text)
                self.assertNotIn(value, response.text)
                if key != "NOT_ALLOWED":
                    self.assertIn(key, response.text)
                self.assertEqual(self.path.read_bytes(), original)
                self.assertFalse(self.path.with_name(".env.bak").exists())
                self.assertNotIn("AI_PROVIDER", os.environ)

    def test_valid_url_numbers_and_voice(self):
        for url in ("http://localhost:11434", "http://127.0.0.1:11434", "http://localhost"):
            self.assertEqual(self.put({"OLLAMA_URL": url, "AI_DAILY_USD": "0",
                "AI_CLOUD_BUDGET_USD": "1.25", "ELEVENLABS_VOICE_ID": "AbCd0123456789"}).status_code, 200)

    def test_host_origin_and_content_type_protection(self):
        for headers in ({"Host": "evil.test:8771"}, {"Host": "localhost.evil.test:8771"},
                        {"Host": "localhost"}, {"Host": "127.0.0.1:0"},
                        {"Origin": "https://evil.test"}, {"Origin": "null"},
                        {"Origin": "http://localhost:5173.evil.test"},
                        {"Origin": "http://localhost:5173/"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.put({"AI_PROVIDER": "auto"}, headers=headers).status_code, 403)
                self.assertEqual(self.voice(headers=headers).status_code, 403)
        self.assertFalse(self.path.exists())
        self.urlopen.assert_not_called()
        for origin in ("http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:8771"):
            self.assertEqual(self.put({}, headers={"Origin": origin}).status_code, 200)
        self.assertEqual(self.put({}, headers={"Host": "127.0.0.1:8771"}).status_code, 200)
        response = self.client.put("/api/settings", content='{"values":{}}', headers={"Content-Type": "text/plain"})
        self.assertEqual(response.status_code, 415)

    def test_pydantic_errors_never_echo_inputs(self):
        secret = "do-not-echo-this-key"
        for body in ({"values": {"GEMINI_API_KEY": [secret]}}, {"values": secret},
                     {"values": {}, "extra": secret}, {"values": {"AI_MODEL": 12}}):
            response = self.client.put("/api/settings", json=body)
            self.assertEqual(response.status_code, 422)
            self.assertNotIn(secret, response.text)
        response = self.client.put("/api/settings", content='{"values":{"GEMINI_API_KEY":"' + secret,
                                   headers={"Content-Type": "application/json"})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn(secret, response.text)
        self.assertFalse(self.path.exists())

    def test_atomic_replace_failure_keeps_environment_and_file(self):
        original = b"AI_MODEL=original\n"
        self.path.write_bytes(original)
        replace = os.replace
        def fail_settings(source, target):
            if target == self.path:
                raise OSError("secret-in-exception")
            replace(source, target)
        with mock.patch.object(self.settings.os, "replace", side_effect=fail_settings):
            response = self.put({"AI_MODEL": "new"})
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("secret-in-exception", response.text)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertNotIn("AI_MODEL", os.environ)
        self.assertEqual(sorted(path.name for path in self.path.parent.iterdir()), [".env", ".env.bak"])

    def test_voice_metadata_request(self):
        self.configure_voice()
        self.urlopen.return_value = io.BytesIO(b'{"name":"Eddie"}')
        response = self.voice()
        self.assertEqual(response.json(), {"ok": True, "voice_name": "Eddie"})
        self.urlopen.assert_called_once()
        request = self.urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.elevenlabs.io/v1/voices/AbCd0123456789")
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.data)
        self.assertEqual(request.get_header("Xi-api-key"), "secret-eleven-key")
        self.assertNotIn("secret-eleven-key", response.text)

    def test_voice_missing_config_errors_and_upstream_redaction(self):
        self.assertFalse(self.voice().json()["ok"])
        self.urlopen.assert_not_called()
        self.configure_voice()
        for code in (401, 403, 404, 429, 500):
            self.urlopen.side_effect = urllib.error.HTTPError("url", code, "secret-eleven-key", {},
                                                            io.BytesIO(b"secret-eleven-key"))
            response = self.voice()
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json()["ok"])
            self.assertNotIn("secret-eleven-key", response.text)
        self.urlopen.side_effect = OSError("secret-eleven-key")
        self.assertNotIn("secret-eleven-key", self.voice().text)
        self.urlopen.side_effect = None
        self.urlopen.return_value = io.BytesIO(b'{"name":"secret-eleven-key"}')
        self.assertNotIn("secret-eleven-key", self.voice().text)
        self.urlopen.return_value = io.BytesIO(b'not json')
        self.assertFalse(self.voice().json()["ok"])


if __name__ == "__main__":
    unittest.main()
