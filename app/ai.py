"""AI layer: provider-agnostic interface (ADR-006 D6, M3).

Product logic never talks to a vendor SDK directly — it calls
`get_provider().generate_json(...)` and gets a validated dict back.

    AIProvider
     ├── AnthropicProvider  (official `anthropic` SDK; structured outputs)
     └── OllamaProvider     (local, http://localhost:11434; format=schema)

Selection (env):
    AI_PROVIDER = anthropic | ollama | auto (default)
    AI_MODEL    = Anthropic model id (default claude-opus-5)
    OLLAMA_MODEL / OLLAMA_URL

`auto` prefers Anthropic when credentials resolve (ANTHROPIC_API_KEY or an
`ant auth login` profile), else Ollama when the daemon answers. `status()`
reports what is usable so the UI can render an honest setup state.

Hybrid routing (ADR-015 D7), OFF unless `AI_ROUTE=on`
------------------------------------------------------
Measured 2026-09-20 on the M5/16 GB: both local 7-8B models generate ~18
tokens/s. A short reply (30-60 tokens) is ~2 s warm; a reading (~900 tokens)
is ~50 s and a podcast ~160 s. No Ollama option changes that — and changing
`num_ctx` between calls RELOADS the model (3.6-5.5 s), so there is one context
and one local model, always.

So the split is by what the text is, not by how "big" the model is:

    personal  — what Eddie wrote or said (corrections, conversation, explain).
                Short outputs, already fast locally, and private: never leaves
                the Mac unless he edits the chain himself.
    generate  — material written FOR him (reading, podcast, drills, tip).
                Long outputs, no personal text: a free cloud tier first, local
                as the fallback when the quota or the network says no.

    AI_CHAIN_GENERATE = gemini,ollama   (default)
    AI_CHAIN_PERSONAL = ollama          (default)

A paid provider (anthropic) is used only if he puts it in a chain AND sets
`AI_CLOUD_BUDGET_USD` > 0 AND the per-token prices — with no prices the guard
cannot count, so it refuses. Every call is logged to `logs/ai_calls.jsonl`
with its latency, so "is it faster?" is answered by a file, not a feeling.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path


class AIUnavailable(Exception):
    """No provider is configured/reachable; the UI shows setup guidance."""


class AIProvider:
    name = "base"
    model = ""

    def generate_json(self, system: str, prompt: str, schema: dict,
                      max_tokens: int = 4096) -> dict:
        raise NotImplementedError

    def available(self) -> bool:
        raise NotImplementedError


# ── Anthropic ────────────────────────────────────────────────────────────

def _anthropic_schema(schema):
    """Claude's structured outputs need `additionalProperties: false` on EVERY
    object (a 400 otherwise). Ollama and Gemini don't care, so the app's
    schemas never carried it everywhere — they had never met Claude. Returns a
    normalized copy; the original is left alone."""
    if isinstance(schema, list):
        return [_anthropic_schema(x) for x in schema]
    if not isinstance(schema, dict):
        return schema
    out = {k: _anthropic_schema(v) for k, v in schema.items()}
    if out.get("type") == "object":
        out["additionalProperties"] = False
    return out


class AnthropicProvider(AIProvider):
    name = "anthropic"

    def __init__(self) -> None:
        self.model = os.environ.get("AI_MODEL", "claude-opus-5").strip()
        self._client = None

    def _get_client(self):
        if self._client is None:
            import anthropic
            # Zero-arg: resolves ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN, or
            # an `ant auth login` profile — never hardcode a key.
            self._client = anthropic.Anthropic()
        return self._client

    def available(self) -> bool:
        if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
            return True
        # `ant auth login` stores profiles under ~/.config/anthropic/
        cfg = os.environ.get("ANTHROPIC_CONFIG_DIR",
                             os.path.expanduser("~/.config/anthropic"))
        return os.path.isdir(os.path.join(cfg, "credentials"))

    def generate_json(self, system: str, prompt: str, schema: dict,
                      max_tokens: int = 4096) -> dict:
        client = self._get_client()
        with client.messages.stream(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema",
                                      "schema": _anthropic_schema(schema)}},
        ) as stream:
            response = stream.get_final_message()
        # Tokens reales: sin esto el guardia de presupuesto contaba el techo
        # (max_tokens) en cada llamada y "gastaba" 5-10 veces lo cierto.
        self.last_usage = (response.usage.input_tokens, response.usage.output_tokens)
        if response.stop_reason == "refusal":
            raise AIUnavailable("The model declined this request.")
        text = next(b.text for b in response.content if b.type == "text")
        return json.loads(text)


# ── Ollama ───────────────────────────────────────────────────────────────

class OllamaProvider(AIProvider):
    name = "ollama"

    def __init__(self) -> None:
        self.url = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
        self.model = os.environ.get("OLLAMA_MODEL", "").strip()

    def _models(self) -> "list[str]":
        try:
            with urllib.request.urlopen(f"{self.url}/api/tags", timeout=3) as r:
                data = json.loads(r.read())
            return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []

    def available(self) -> bool:
        models = self._models()
        if not models:
            return False
        if not self.model:
            self.model = models[0]
        return True

    def generate_json(self, system: str, prompt: str, schema: dict,
                      max_tokens: int = 4096) -> dict:
        if not self.model and not self.available():
            raise AIUnavailable("Ollama is not running or has no models.")
        body = json.dumps({
            "model": self.model,
            "stream": False,
            "format": schema,  # Ollama structured outputs: schema as format
            # Loading and unloading the model costs its own CPU spike. In a
            # batch (the job queue) keeping it resident between jobs avoids
            # paying that repeatedly; it costs RAM, not heat.
            # Resident = 5 GB of a 16 GB Mac. With the cloud chains on, set
            # OLLAMA_KEEP_ALIVE=1m in .env so a fallback call frees it at once.
            "keep_alive": os.environ.get("OLLAMA_KEEP_ALIVE", "10m"),
            "options": {"num_predict": max_tokens},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }).encode()
        req = urllib.request.Request(
            f"{self.url}/api/chat", data=body,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=600) as r:
            data = json.loads(r.read())
        return json.loads(data["message"]["content"])


# ── Gemini (free tier) ───────────────────────────────────────────────────

_GEMINI_SCHEMA_KEYS = {"type", "properties", "required", "items", "enum",
                       "description", "minItems", "maxItems", "nullable"}


def _gemini_schema(schema):
    """Gemini's `responseSchema` is an OpenAPI subset: unknown keywords
    (`additionalProperties`, `$schema`, `title`…) are a 400, not a no-op."""
    if isinstance(schema, list):
        return [_gemini_schema(x) for x in schema]
    if not isinstance(schema, dict):
        return schema
    out = {}
    for key, value in schema.items():
        if key not in _GEMINI_SCHEMA_KEYS:
            continue
        if key == "properties":
            out[key] = {k: _gemini_schema(v) for k, v in value.items()}
        elif key == "type" and isinstance(value, list):     # ["string","null"]
            kinds = [v for v in value if v != "null"]
            out["type"] = kinds[0] if kinds else "string"
            out["nullable"] = "null" in value
        else:
            out[key] = _gemini_schema(value)
    # Gemini sólo acepta `enum` de TEXTO: `{"type":"integer","enum":[0,1,2]}` es
    # un 400 (así falló la lectura). Se quita el enum; el tipo se conserva y la
    # app ya valida el rango al usarlo.
    if out.get("enum") and out.get("type") in ("integer", "number"):
        del out["enum"]
    return out


class GeminiProvider(AIProvider):
    name = "gemini"

    def __init__(self) -> None:
        self.model = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest").strip()
        self.key = os.environ.get("GEMINI_API_KEY", "").strip()

    def available(self) -> bool:
        return bool(self.key)

    def generate_json(self, system: str, prompt: str, schema: dict,
                      max_tokens: int = 4096) -> dict:
        if not self.key:
            raise AIUnavailable("GEMINI_API_KEY is not set.")
        body = json.dumps({
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": _gemini_schema(schema),
                "maxOutputTokens": max_tokens,
            },
        }).encode()
        req = urllib.request.Request(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent", data=body,
            # the key travels in a header, never in the URL (logs, proxies)
            headers={"Content-Type": "application/json", "x-goog-api-key": self.key})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as exc:
            raise AIUnavailable(f"Gemini returned no text: {str(data)[:160]}") from exc
        usage = data.get("usageMetadata", {})
        self.last_usage = (usage.get("promptTokenCount"), usage.get("candidatesTokenCount"))
        return json.loads(text)


# ── Router ───────────────────────────────────────────────────────────────

BASE = Path(__file__).resolve().parent.parent

# What the text IS decides where it may go. Unknown tasks are personal: the
# safe default is "stays on the Mac".
GENERATE_TASKS = {"reading", "podcast", "activities", "tip", "writing_task",
                  "writing_prompt", "speaking_prompt"}
# Trabajo en lote: un bucle sobre miles de palabras con hasta 3 intentos cada
# una se comería la cuota gratuita y luego el dinero en una tarde. Sólo local.
LOCAL_ONLY_TASKS = {"glossary"}

# Los candados de la nube: la nube SUSTITUYE a Ollama, no lo reemplaza sin
# límite. Cada tope se lee de .env; si se alcanza, esa llamada baja al
# siguiente de la cadena (más lenta, nunca rota).
DAILY_CALLS_DEFAULT = {"gemini": 20, "anthropic": 25}
DAILY_USD_DEFAULT = 0.10          # sólo Anthropic: una sentada no puede gastarse el mes
COOLDOWN_SECONDS = 600            # tras un fallo, ese proveedor descansa 10 min
_cooldown: "dict[str, float]" = {}

_providers: "dict[str, AIProvider]" = {}


def _provider(name: str) -> AIProvider:
    """One instance per provider for the life of the process. They used to be
    rebuilt — Anthropic client included — on every single call."""
    if name not in _providers:
        _providers[name] = {"ollama": OllamaProvider, "gemini": GeminiProvider,
                            "anthropic": AnthropicProvider}[name]()
    return _providers[name]


def reset() -> None:
    _providers.clear()
    _cooldown.clear()


def _calls_log() -> Path:
    return Path(os.environ.get("AI_CALLS_LOG", BASE / "logs" / "ai_calls.jsonl"))


def _log_call(entry: dict) -> None:
    try:
        path = _calls_log()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass                      # a full disk must not break a lesson


def spent_this_month() -> float:
    """USD logged against paid providers this calendar month."""
    month = datetime.now().strftime("%Y-%m")
    total = 0.0
    try:
        with _calls_log().open() as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if str(e.get("at", "")).startswith(month):
                    total += float(e.get("usd") or 0)
    except OSError:
        pass
    return round(total, 4)


def usage_today(provider: str) -> dict:
    """Llamadas correctas y dólares de HOY para un proveedor, del propio log."""
    today = datetime.now().strftime("%Y-%m-%d")
    calls, usd = 0, 0.0
    try:
        with _calls_log().open() as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if (e.get("ok") and e.get("provider") == provider
                        and str(e.get("at", "")).startswith(today)):
                    calls += 1
                    usd += float(e.get("usd") or 0)
    except OSError:
        pass
    return {"calls": calls, "usd": round(usd, 4)}


def _caps(name: str) -> dict:
    def num(var, default):
        try:
            return float(os.environ.get(var, "") or default)
        except ValueError:
            return default
    return {"calls": int(num(f"AI_DAILY_CALLS_{name.upper()}",
                             DAILY_CALLS_DEFAULT.get(name, 0))),
            "usd": num("AI_DAILY_USD", DAILY_USD_DEFAULT) if name == "anthropic" else None}


def _cap_guard(name: str) -> None:
    """Raises AIUnavailable when this provider already gave its share today or
    is resting after a failure. Cheap: one pass over a small log."""
    if time.time() < _cooldown.get(name, 0):
        raise AIUnavailable(f"{name} is resting after a failure")
    caps, used = _caps(name), usage_today(name)
    if caps["calls"] and used["calls"] >= caps["calls"]:
        raise AIUnavailable(f"{name} reached today's {caps['calls']}-call limit")
    if caps["usd"] and used["usd"] >= caps["usd"]:
        raise AIUnavailable(f"{name} reached today's ${caps['usd']:g} limit")


def _paid_guard() -> "tuple[float, float]":
    """Prices (USD per million tokens, in/out) if the paid arm may be used
    right now; raises AIUnavailable otherwise. No price, no spend: a guard
    that cannot count is not a guard."""
    try:
        budget = float(os.environ.get("AI_CLOUD_BUDGET_USD", "0") or 0)
        p_in = float(os.environ.get("AI_PRICE_IN_PER_MTOK", "0") or 0)
        p_out = float(os.environ.get("AI_PRICE_OUT_PER_MTOK", "0") or 0)
    except ValueError as exc:
        raise AIUnavailable("paid AI: budget/prices are not numbers") from exc
    if budget <= 0:
        raise AIUnavailable("paid AI is off (AI_CLOUD_BUDGET_USD is 0)")
    if p_in <= 0 or p_out <= 0:
        raise AIUnavailable("paid AI: set AI_PRICE_IN_PER_MTOK / AI_PRICE_OUT_PER_MTOK")
    if spent_this_month() >= budget:
        raise AIUnavailable(f"paid AI: this month's ${budget:g} budget is spent")
    return p_in, p_out


class Router(AIProvider):
    """Tries each provider of the task's chain in order; the first that
    answers wins. A quota error, a timeout or a dead network falls through to
    the next one, so the free tier running dry means "slower", never "broken"."""
    name = "router"

    def __init__(self, task: "str | None") -> None:
        self.task = task or "general"
        kind = ("local" if self.task in LOCAL_ONLY_TASKS else
                "generate" if self.task in GENERATE_TASKS else "personal")
        default = "gemini,ollama" if kind == "generate" else "ollama"
        # Una cadena por tarea manda sobre la de su clase (AI_CHAIN_PODCAST=
        # ollama); el trabajo en lote sigue siendo sólo local pase lo que pase.
        raw = "ollama" if kind == "local" else (
            os.environ.get(f"AI_CHAIN_{self.task.upper()}")
            or os.environ.get(f"AI_CHAIN_{kind.upper()}", default))
        self.kind = kind
        self.chain = [n.strip().lower() for n in raw.split(",")
                      if n.strip().lower() in ("ollama", "gemini", "anthropic")]
        self.model = ""

    def available(self) -> bool:
        return any(_provider(n).available() for n in self.chain)

    def generate_json(self, system: str, prompt: str, schema: dict,
                      max_tokens: int = 4096) -> dict:
        errors = []
        for name in self.chain:
            provider = _provider(name)
            prices = None
            try:
                if name != "ollama":
                    _cap_guard(name)
                if name == "anthropic":
                    prices = _paid_guard()
                if not provider.available():
                    raise AIUnavailable(f"{name} is not configured")
                started = time.time()
                out = provider.generate_json(system, prompt, schema, max_tokens)
            except Exception as exc:  # noqa: BLE001 — cualquier fallo baja al siguiente
                errors.append(f"{name}: {type(exc).__name__}: {exc}"[:160])
                if isinstance(exc, AIUnavailable):
                    continue      # tope o sin configurar: no es un fallo, no se loguea
                # Un fallo real (cuota, red, timeout): descansa, y las
                # siguientes llamadas no pierden segundos reintentándolo.
                # Un 400/404/422 es de ESTA petición (esquema, prompt): el
                # proveedor está bien y no debe descansar por ello.
                status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
                if name != "ollama" and status not in (400, 404, 422):
                    _cooldown[name] = time.time() + COOLDOWN_SECONDS
                _log_call({"at": datetime.now().isoformat(timespec="seconds"),
                           "task": self.task, "provider": name, "ok": False,
                           "error": errors[-1]})
                continue
            self.model = provider.model
            tok_in, tok_out = getattr(provider, "last_usage", (None, None))
            usd = 0.0
            if prices:
                # Without real usage, count the ceiling: overestimating is the
                # safe direction for a budget.
                usd = ((tok_in or (len(system) + len(prompt)) // 3) * prices[0]
                       + (tok_out or max_tokens) * prices[1]) / 1_000_000
            _log_call({"at": datetime.now().isoformat(timespec="seconds"),
                       "task": self.task, "kind": self.kind, "provider": name,
                       "model": provider.model, "ok": True,
                       "seconds": round(time.time() - started, 2),
                       "tokens_in": tok_in, "tokens_out": tok_out,
                       "usd": round(usd, 6)})
            return out
        raise AIUnavailable("No AI provider answered — " + " | ".join(errors))


# ── Factory ──────────────────────────────────────────────────────────────

def get_provider(task: "str | None" = None) -> AIProvider:
    """Resolve the configured provider or raise AIUnavailable.

    `task` names what is being asked for ("reading", "conversation"…). It only
    matters with `AI_ROUTE=on`; otherwise the single-provider behaviour below
    is exactly what it always was.
    """
    if os.environ.get("AI_ROUTE", "").strip().lower() == "on":
        router = Router(task)
        if not router.available():
            raise AIUnavailable(
                f"No provider in the {router.kind} chain is usable "
                f"({', '.join(router.chain) or 'empty'}).")
        return router
    choice = os.environ.get("AI_PROVIDER", "auto").strip().lower()
    anthropic_p = AnthropicProvider()
    ollama_p = OllamaProvider()

    if choice == "anthropic":
        if not anthropic_p.available():
            raise AIUnavailable(
                "Anthropic selected but no credentials found "
                "(set ANTHROPIC_API_KEY in .env, or run `ant auth login`).")
        return anthropic_p
    if choice == "ollama":
        if not ollama_p.available():
            raise AIUnavailable(
                "Ollama selected but not reachable — run `ollama serve` "
                "and pull a model (e.g. `ollama pull qwen2.5:7b`).")
        return ollama_p
    # auto
    if anthropic_p.available():
        return anthropic_p
    if ollama_p.available():
        return ollama_p
    raise AIUnavailable(
        "No AI provider configured. Either set ANTHROPIC_API_KEY in .env, "
        "or start Ollama (`ollama serve`) and pull a model.")


def status() -> dict:
    """What the UI needs to render an honest AI setup state."""
    anthropic_p = AnthropicProvider()
    ollama_p = OllamaProvider()
    ollama_models = ollama_p._models()
    out = {
        "usage": {n: {**usage_today(n), "caps": _caps(n)} for n in ("gemini", "anthropic")}
                 | {"anthropic_month_usd": spent_this_month()},
        "configured": False,
        "provider": None,
        "model": None,
        "anthropic_available": anthropic_p.available(),
        "ollama_running": bool(ollama_models),
        "ollama_models": ollama_models,
    }
    try:
        p = get_provider()
        out.update(configured=True, provider=p.name, model=p.model or None)
    except AIUnavailable:
        pass
    return out
