"""ADR-015 D7 tests: the hybrid router. No network: providers are fakes."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import ai  # noqa: E402


class Fake(ai.AIProvider):
    def __init__(self, name, ok=True, error=None, usage=(None, None)):
        self.name, self.model, self.ok, self.error = name, f"{name}-model", ok, error
        self.calls, self.last_usage = 0, usage

    def available(self):
        return self.ok

    def generate_json(self, system, prompt, schema, max_tokens=4096):
        self.calls += 1
        if self.error:
            raise self.error
        return {"from": self.name}


class RouterCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Path(self.tmp.name) / "calls.jsonl"
        self.env = mock.patch.dict(os.environ, {
            "AI_ROUTE": "on", "AI_CALLS_LOG": str(self.log)}, clear=False)
        self.env.start()
        # Nada del .env real puede colarse: otros tests importan app.server, que
        # lo carga, y una AI_CHAIN_<TAREA> suya pisaría la cadena que fija la prueba.
        for k in [k for k in os.environ if k.startswith(("AI_CHAIN_", "AI_DAILY_"))] + [
                "AI_CLOUD_BUDGET_USD", "AI_PRICE_IN_PER_MTOK", "AI_PRICE_OUT_PER_MTOK"]:
            os.environ.pop(k, None)
        ai.reset()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()
        ai.reset()

    def use(self, **fakes):
        ai._providers.update(fakes)

    def entries(self):
        return [json.loads(x) for x in self.log.read_text().splitlines()]


class TestRouting(RouterCase):
    def test_off_by_default_nothing_changes(self):
        os.environ.pop("AI_ROUTE")
        with mock.patch.object(ai.OllamaProvider, "available", return_value=True), \
                mock.patch.object(ai.AnthropicProvider, "available", return_value=False):
            self.assertIsInstance(ai.get_provider("reading"), ai.OllamaProvider)

    def test_generated_material_tries_the_free_cloud_first(self):
        self.use(gemini=Fake("gemini"), ollama=Fake("ollama"))
        out = ai.get_provider("reading").generate_json("s", "p", {})
        self.assertEqual(out, {"from": "gemini"})

    def test_what_he_wrote_or_said_never_leaves_the_mac(self):
        g, o = Fake("gemini"), Fake("ollama")
        self.use(gemini=g, ollama=o)
        for task in ("writing_correction", "writing_check", "speaking_correction",
                     "conversation", "explain", None, "something_new"):
            self.assertEqual(ai.get_provider(task).generate_json("s", "p", {}),
                             {"from": "ollama"}, task)
        self.assertEqual(g.calls, 0)

    def test_a_dry_quota_means_slower_not_broken(self):
        quota = urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)
        self.use(gemini=Fake("gemini", error=quota), ollama=Fake("ollama"))
        out = ai.get_provider("podcast").generate_json("s", "p", {})
        self.assertEqual(out, {"from": "ollama"})
        log = self.entries()
        self.assertEqual([(e["provider"], e["ok"]) for e in log],
                         [("gemini", False), ("ollama", True)])

    def test_no_key_falls_through_silently(self):
        self.use(gemini=Fake("gemini", ok=False), ollama=Fake("ollama"))
        self.assertEqual(ai.get_provider("tip").generate_json("s", "p", {}),
                         {"from": "ollama"})

    def test_everything_down_says_why(self):
        self.use(gemini=Fake("gemini", ok=False), ollama=Fake("ollama", ok=False))
        with self.assertRaises(ai.AIUnavailable):
            ai.get_provider("reading")

    def test_every_call_is_timed_in_the_log(self):
        self.use(gemini=Fake("gemini", usage=(120, 800)), ollama=Fake("ollama"))
        ai.get_provider("reading").generate_json("s", "p", {})
        e = self.entries()[0]
        self.assertEqual((e["task"], e["provider"], e["tokens_out"], e["usd"]),
                         ("reading", "gemini", 800, 0.0))
        self.assertIn("seconds", e)


class TestPaidArm(RouterCase):
    def setUp(self):
        super().setUp()
        os.environ["AI_CHAIN_GENERATE"] = "anthropic,ollama"
        self.paid = Fake("anthropic", usage=(1000, 2000))
        self.use(anthropic=self.paid, ollama=Fake("ollama"))

    def ask(self):
        return ai.get_provider("reading").generate_json("s", "p", {}, max_tokens=4096)

    def test_it_spends_nothing_by_default(self):
        self.assertEqual(self.ask(), {"from": "ollama"})
        self.assertEqual(self.paid.calls, 0)

    def test_a_budget_without_prices_is_refused(self):
        os.environ["AI_CLOUD_BUDGET_USD"] = "5"
        self.assertEqual(self.ask(), {"from": "ollama"})
        self.assertEqual(self.paid.calls, 0)

    def test_with_budget_and_prices_it_counts_every_cent(self):
        os.environ.update(AI_CLOUD_BUDGET_USD="5", AI_PRICE_IN_PER_MTOK="1",
                          AI_PRICE_OUT_PER_MTOK="5")
        self.assertEqual(self.ask(), {"from": "anthropic"})
        self.assertAlmostEqual(ai.spent_this_month(), (1000 * 1 + 2000 * 5) / 1e6)

    def test_it_stops_at_the_budget(self):
        os.environ.update(AI_CLOUD_BUDGET_USD="0.02", AI_PRICE_IN_PER_MTOK="1",
                          AI_PRICE_OUT_PER_MTOK="5")
        answers = [self.ask()["from"] for _ in range(4)]
        self.assertEqual(answers, ["anthropic", "anthropic", "ollama", "ollama"])
        self.assertLessEqual(ai.spent_this_month(), 0.033)

    def test_unknown_usage_is_counted_at_the_ceiling(self):
        self.paid.last_usage = (None, None)
        os.environ.update(AI_CLOUD_BUDGET_USD="5", AI_PRICE_IN_PER_MTOK="1",
                          AI_PRICE_OUT_PER_MTOK="5")
        self.ask()
        self.assertGreaterEqual(ai.spent_this_month(), 4096 * 5 / 1e6)


class TestDurability(RouterCase):
    """La nube sustituye a Ollama pero no sin límite: tiene que durar."""

    def _log(self, provider, n, usd=0.0):
        with self.log.open("a") as f:
            for _ in range(n):
                f.write(json.dumps({"at": ai.datetime.now().isoformat(timespec="seconds"),
                                    "provider": provider, "ok": True, "usd": usd}) + "\n")

    def test_a_provider_stops_at_its_daily_calls(self):
        os.environ["AI_DAILY_CALLS_GEMINI"] = "3"
        g, o = Fake("gemini"), Fake("ollama")
        self.use(gemini=g, ollama=o)
        self._log("gemini", 3)
        self.assertEqual(ai.get_provider("reading").generate_json("s", "p", {}),
                         {"from": "ollama"})
        self.assertEqual(g.calls, 0, "ni siquiera se le pregunta")

    def test_anthropic_has_a_daily_dollar_cap_below_the_month(self):
        os.environ.update(AI_CHAIN_PERSONAL="anthropic,ollama", AI_CLOUD_BUDGET_USD="3",
                          AI_PRICE_IN_PER_MTOK="1", AI_PRICE_OUT_PER_MTOK="5",
                          AI_DAILY_USD="0.10")
        a = Fake("anthropic", usage=(1000, 1000))
        self.use(anthropic=a, ollama=Fake("ollama"))
        self._log("anthropic", 1, usd=0.10)         # ya gastó el día
        self.assertEqual(ai.get_provider("explain").generate_json("s", "p", {}),
                         {"from": "ollama"})
        self.assertEqual(a.calls, 0)

    def test_a_failure_makes_it_rest_so_later_calls_do_not_wait(self):
        boom = urllib.error.URLError("network down")
        g = Fake("gemini", error=boom)
        self.use(gemini=g, ollama=Fake("ollama"))
        for _ in range(4):
            ai.get_provider("reading").generate_json("s", "p", {})
        self.assertEqual(g.calls, 1, "tras el primer fallo descansa 10 min")

    def test_hitting_a_cap_is_not_logged_as_a_failure(self):
        os.environ["AI_DAILY_CALLS_GEMINI"] = "1"
        self.use(gemini=Fake("gemini"), ollama=Fake("ollama"))
        self._log("gemini", 1)
        ai.get_provider("reading").generate_json("s", "p", {})
        self.assertFalse([e for e in self.entries() if e.get("ok") is False])
        self.assertNotIn("gemini", ai._cooldown)

    def test_bulk_glossary_work_never_reaches_the_cloud(self):
        os.environ["AI_CHAIN_GENERATE"] = "gemini,anthropic,ollama"
        g, a, o = Fake("gemini"), Fake("anthropic"), Fake("ollama")
        self.use(gemini=g, anthropic=a, ollama=o)
        for _ in range(5):
            ai.get_provider("glossary").generate_json("s", "p", {})
        self.assertEqual((g.calls, a.calls, o.calls), (0, 0, 5))

    def test_status_reports_what_is_left(self):
        self._log("gemini", 2)
        with mock.patch.object(ai.OllamaProvider, "_models", return_value=[]):
            u = ai.status()["usage"]
        self.assertEqual(u["gemini"]["calls"], 2)
        self.assertEqual(u["gemini"]["caps"]["calls"], ai.DAILY_CALLS_DEFAULT["gemini"])


class ApiError(Exception):
    """Como anthropic.APIStatusError: NO es URLError ni OSError."""
    def __init__(self, status):
        super().__init__(f"error {status}")
        self.status_code = status


class TestAnyFailureFallsThrough(RouterCase):
    def test_a_claude_style_error_falls_to_ollama_instead_of_crashing(self):
        os.environ["AI_CHAIN_PERSONAL"] = "anthropic,ollama"
        os.environ.update(AI_CLOUD_BUDGET_USD="5", AI_PRICE_IN_PER_MTOK="1",
                          AI_PRICE_OUT_PER_MTOK="5")
        self.use(anthropic=Fake("anthropic", error=ApiError(429)), ollama=Fake("ollama"))
        self.assertEqual(ai.get_provider("explain").generate_json("s", "p", {}),
                         {"from": "ollama"})
        self.assertIn("anthropic", ai._cooldown, "un 429 sí hace descansar")

    def test_a_request_shaped_error_does_not_bench_the_provider(self):
        os.environ["AI_CHAIN_PERSONAL"] = "anthropic,ollama"
        os.environ.update(AI_CLOUD_BUDGET_USD="5", AI_PRICE_IN_PER_MTOK="1",
                          AI_PRICE_OUT_PER_MTOK="5")
        self.use(anthropic=Fake("anthropic", error=ApiError(400)), ollama=Fake("ollama"))
        ai.get_provider("explain").generate_json("s", "p", {})
        self.assertNotIn("anthropic", ai._cooldown, "un 400 es del esquema, no de Claude")

    def test_claude_schemas_get_additional_properties_false_everywhere(self):
        schema = {"type": "object", "properties": {"a": {"type": "array", "items": {
            "type": "object", "properties": {"b": {"type": "string"}}}}}}
        out = ai._anthropic_schema(schema)
        self.assertIs(out["additionalProperties"], False)
        self.assertIs(out["properties"]["a"]["items"]["additionalProperties"], False)
        self.assertNotIn("additionalProperties", schema, "no muta el original")


class TestWarmUp(RouterCase):
    def test_a_cloud_first_chain_is_never_warmed(self):
        """Abrir Speaking no debe cargar Ollama ni gastar una llamada de pago."""
        from app import conversation
        os.environ["AI_CHAIN_PERSONAL"] = "anthropic,ollama"
        paid, local = Fake("anthropic"), Fake("ollama")
        self.use(anthropic=paid, ollama=local)
        with mock.patch.object(conversation.tts, "narrate"):
            out = conversation.warm()
        self.assertFalse(out["model"])
        self.assertEqual((paid.calls, local.calls), (0, 0))

    def test_a_local_chain_still_warms(self):
        from app import conversation
        local = Fake("ollama")
        self.use(ollama=local)
        with mock.patch.object(conversation.tts, "narrate"):
            self.assertTrue(conversation.warm()["model"])
        self.assertEqual(local.calls, 1)


class TestGeminiSchema(unittest.TestCase):
    def test_unsupported_keywords_are_stripped_recursively(self):
        schema = {"type": "object", "additionalProperties": False, "title": "x",
                  "properties": {"items": {"type": "array", "items": {
                      "type": "object", "additionalProperties": False,
                      "properties": {"word": {"type": ["string", "null"]}},
                      "required": ["word"]}}},
                  "required": ["items"]}
        out = ai._gemini_schema(schema)
        self.assertNotIn("additionalProperties", json.dumps(out))
        self.assertNotIn("title", out)
        word = out["properties"]["items"]["items"]["properties"]["word"]
        self.assertEqual(word, {"type": "string", "nullable": True})
        self.assertEqual(out["required"], ["items"])

    def test_numeric_enums_are_dropped_because_gemini_only_takes_text(self):
        out = ai._gemini_schema({"type": "object", "properties": {
            "answer_index": {"type": "integer", "enum": [0, 1, 2]},
            "level": {"type": "string", "enum": ["A2", "B1"]}}})
        self.assertEqual(out["properties"]["answer_index"], {"type": "integer"})
        self.assertEqual(out["properties"]["level"]["enum"], ["A2", "B1"])

    def test_every_real_app_schema_is_acceptable_to_gemini(self):
        """Regresión: la lectura falló con un 400 y nadie lo vio hasta usarla."""
        import importlib
        def bad(s, path=""):
            if isinstance(s, dict):
                if s.get("enum") and s.get("type") != "string":
                    yield path
                for k, v in s.items():
                    yield from bad(v, f"{path}.{k}")
            elif isinstance(s, list):
                for i, v in enumerate(s):
                    yield from bad(v, f"{path}[{i}]")
        for m in ("generator", "activities", "coach", "explain", "podcast", "speaking",
                  "writing", "conversation"):
            mod = importlib.import_module(f"app.{m}")
            for name in dir(mod):
                v = getattr(mod, name)
                if name.endswith("SCHEMA") and isinstance(v, dict):
                    self.assertEqual(list(bad(ai._gemini_schema(v), name)), [], f"{m}.{name}")

    def test_the_key_never_travels_in_the_url(self):
        seen = {}

        class Resp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self):
                return json.dumps({"candidates": [{"content": {"parts": [
                    {"text": "{\"ok\": true}"}]}}]}).encode()

        def fake_open(req, timeout=0):
            seen["url"], seen["headers"] = req.full_url, dict(req.header_items())
            return Resp()

        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "secret-key"}), \
                mock.patch.object(ai.urllib.request, "urlopen", fake_open):
            out = ai.GeminiProvider().generate_json("s", "p", {"type": "object"})
        self.assertEqual(out, {"ok": True})
        self.assertNotIn("secret-key", seen["url"])
        self.assertIn("secret-key", seen["headers"].values())


if __name__ == "__main__":
    unittest.main()
