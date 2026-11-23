"""Allowlisted local settings. Secrets never leave this module unmasked."""

import math
import os
import re
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlsplit

# Overridable so a preview server can never write the real .env.
ENV_PATH = Path(os.environ.get("ENGLISHOS_ENV_PATH") or Path(__file__).resolve().parent.parent / ".env")
LOCK = threading.RLock()

FIELDS = [
    dict(group="AI", key="AI_PROVIDER", label="AI provider", kind="select", options=["auto", "anthropic", "ollama"], help="Choose the provider used when task routing is off."),
    dict(group="AI", key="AI_ROUTE", label="Task routing", kind="select", options=["off", "on"], help="Use the configured provider chains for each task."),
    dict(group="AI", key="AI_MODEL", label="Anthropic model", kind="text", options=[], help="Leave blank to use the default Anthropic model."),
    dict(group="AI", key="ANTHROPIC_API_KEY", label="Anthropic API key", kind="secret", options=[], help="Your Anthropic key is stored locally and never shown again."),
    dict(group="AI", key="GEMINI_API_KEY", label="Gemini API key", kind="secret", options=[], help="Your Gemini key is used by task routing."),
    dict(group="AI", key="GEMINI_MODEL", label="Gemini model", kind="text", options=[], help="Leave blank to use the default Gemini model."),
    dict(group="AI", key="OLLAMA_MODEL", label="Ollama model", kind="text", options=[], help="Name of a model installed in Ollama."),
    dict(group="AI", key="OLLAMA_URL", label="Ollama URL", kind="text", options=[], help="Local HTTP address, such as http://localhost:11434."),
    dict(group="Voice", key="ELEVENLABS_API_KEY", label="ElevenLabs API key", kind="secret", options=[], help="Your ElevenLabs key is used for My voice."),
    dict(group="Voice", key="ELEVENLABS_VOICE_ID", label="ElevenLabs voice ID", kind="text", options=[], help="Use the 10–40 character voice ID from ElevenLabs."),
    dict(group="Budget", key="AI_DAILY_USD", label="Daily AI budget (USD)", kind="number", options=[], help="Maximum daily spending on paid AI calls; blank uses the default."),
    dict(group="Budget", key="AI_CLOUD_BUDGET_USD", label="Monthly cloud budget (USD)", kind="number", options=[], help="Maximum monthly cloud spending; zero disables paid AI calls."),
]
BY_KEY = {field["key"]: field for field in FIELDS}


class InvalidSetting(ValueError):
    """A safe validation message containing a field name, never its value."""


def snapshot() -> dict:
    with LOCK:
        groups = {}
        for field in FIELDS:
            item = {k: v for k, v in field.items() if k != "group"}
            value = os.environ.get(field["key"], "")
            if field["kind"] == "secret":
                # Short malformed keys must not be disclosed in full either.
                item.update(set=bool(value), hint="…" + value[-4:] if len(value) > 4 else "")
            else:
                item["value"] = value
            groups.setdefault(field["group"], []).append(item)
        return {"groups": [{"name": name, "fields": fields} for name, fields in groups.items()]}


def validate(values: dict[str, str | None]) -> None:
    for key, value in values.items():
        if key not in BY_KEY:
            raise InvalidSetting("values: unknown setting")
        if value is None or value == "":
            continue
        if len(value) > 300 or any(c in value for c in "\n\r\0\v\f\x1c\x1d\x1e\x85\u2028\u2029"):
            raise InvalidSetting(f"{key}: use a single line of at most 300 characters")
        field = BY_KEY[key]
        if field["kind"] == "select" and value not in field["options"]:
            raise InvalidSetting(f"{key}: choose one of the listed options")
        if field["kind"] == "number":
            try:
                number = float(value)
            except ValueError:
                number = -1
            if not math.isfinite(number) or number < 0:
                raise InvalidSetting(f"{key}: enter a finite number greater than or equal to zero")
        if key == "ELEVENLABS_VOICE_ID" and not re.fullmatch(r"[A-Za-z0-9]{10,40}", value):
            raise InvalidSetting(f"{key}: use 10–40 letters and numbers")
        if key == "OLLAMA_URL":
            try:
                url = urlsplit(value)
                valid = (url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1")
                         and not url.username and not url.password and not url.fragment
                         and not any(c.isspace() for c in value) and "\\" not in value)
                valid = valid and (url.port is None or 0 < url.port <= 65535)
            except ValueError:
                valid = False
            if not valid:
                raise InvalidSetting(f"{key}: use an HTTP URL on localhost or 127.0.0.1")


def _atomic_write(path: Path, data: bytes) -> None:
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _inline_comment(assignment: str) -> str:
    quote = None
    escaped = False
    for index, char in enumerate(assignment):
        if escaped:
            escaped = False
        elif char == "\\" and quote:
            escaped = True
        elif char == quote:
            quote = None
        elif char in ("'", '"') and quote is None:
            quote = char
        elif char == "#" and quote is None and (index == 0 or assignment[index - 1].isspace()):
            return assignment[index:]
    return ""


def update(values: dict[str, str | None]) -> dict:
    validate(values)
    with LOCK:
        if not values:
            return snapshot()
        original = ENV_PATH.read_bytes() if ENV_PATH.exists() else b""
        lines = original.decode("utf-8").splitlines(keepends=True)
        newline = "\r\n" if b"\r\n" in original else "\n"
        pending = dict(values)
        output = []
        for line in lines:
            match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
            key = match[1] if match else None
            if key not in values:
                output.append(line)
                continue
            # Keep comments on edited/deleted assignments as standalone lines.
            comment = _inline_comment(line[match.end():])
            if comment:
                output.append(comment if comment.endswith(("\n", "\r")) else comment + newline)
            if key in pending and pending[key]:
                ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
                output.append(f"{key}={pending[key]}{ending}")
            pending.pop(key, None)
        for key, value in pending.items():
            if value:
                if output and not output[-1].endswith(("\n", "\r")):
                    output.append(newline)
                output.append(f"{key}={value}{newline}")
        _atomic_write(ENV_PATH.with_name(ENV_PATH.name + ".bak"), original)
        _atomic_write(ENV_PATH, "".join(output).encode("utf-8"))
        for key, value in values.items():
            if value:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)
        return snapshot()
