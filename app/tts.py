"""Text to speech, provider-agnostic (ADR-007 D1, M8).

    TTSProvider
     ├── KokoroProvider  (local neural, several voices → also the M11 podcast)
     └── SayProvider     (macOS `say`, always available fallback)

Narration is synthesized **sentence by sentence** and concatenated. That is
what makes karaoke highlighting possible without a forced aligner: the offset
of each sentence in the finished file is known exactly, so the reader can
follow along and the shadowing loop can repeat one sentence.

Selection (env): TTS_PROVIDER = kokoro | say | auto (default), TTS_VOICE.
Everything is cached under data/media/tts/ keyed by (text, voice, provider).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

TTS_DIR = BASE / "data" / "media" / "tts"
SAMPLE_RATE = 24000

# Kokoro voices. Two contrasting ones are named so the podcast (M11) can cast
# a dialogue without inventing new configuration.
VOICES = {
    "narrator": "af_heart",
    "speaker_a": "af_bella",
    "speaker_b": "am_michael",
}

SENTENCE_RE = re.compile(r"[^.!?]+[.!?]*\s*")


class TTSUnavailable(Exception):
    """No engine is usable; the UI shows setup guidance instead of failing."""


def split_sentences(text: str) -> "list[str]":
    """Sentences as the reader will highlight them (paragraph-aware)."""
    out: "list[str]" = []
    for para in text.split("\n"):
        for m in SENTENCE_RE.finditer(para):
            s = m.group().strip()
            if s:
                out.append(s)
    return out


def _key(text: str, voice: str, provider: str) -> str:
    h = hashlib.sha256(f"{provider}|{voice}|{text}".encode()).hexdigest()[:16]
    return h


def own_voice_configured() -> bool:
    return bool(os.environ.get("ELEVENLABS_API_KEY") and
                os.environ.get("ELEVENLABS_VOICE_ID"))


def test_own_voice() -> dict:
    """Read voice metadata only: no synthesis and no credits spent."""
    key = os.environ.get("ELEVENLABS_API_KEY", "")
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "")
    if not key or not voice_id:
        return {"ok": False, "error": "Save an ElevenLabs API key and voice ID first."}
    if not re.fullmatch(r"[A-Za-z0-9]{10,40}", voice_id):
        return {"ok": False, "error": "The voice ID must contain 10–40 letters and numbers."}
    try:
        request = urllib.request.Request(
            f"https://api.elevenlabs.io/v1/voices/{voice_id}",
            headers={"xi-api-key": key}, method="GET")
        with urllib.request.urlopen(request, timeout=15) as response:
            result = json.load(response)
        name = result.get("name")
        if not isinstance(name, str) or not name.strip():
            return {"ok": False, "error": "ElevenLabs returned invalid voice details."}
        # Never trust upstream text to keep credentials out of the response.
        return {"ok": True, "voice_name": name.replace(key, "[redacted]")}
    except urllib.error.HTTPError as exc:
        code = exc.code
        exc.close()
        message = {401: "ElevenLabs rejected the API key.",
                   403: "This API key cannot access the voice.",
                   404: "Voice not found. Check the saved voice ID.",
                   429: "ElevenLabs is busy. Try again shortly."}.get(
                       code, "ElevenLabs could not verify the voice. Try again later.")
        return {"ok": False, "error": message}
    except Exception:
        return {"ok": False, "error": "Could not reach ElevenLabs or read the voice details."}


def _eleven(text: str) -> tuple[np.ndarray, dict]:
    """One paid request, returning mono float PCM and character alignment."""
    import numpy as np

    if not own_voice_configured():
        raise TTSUnavailable("La voz propia de ElevenLabs no está configurada.")
    voice_id = urllib.parse.quote(os.environ["ELEVENLABS_VOICE_ID"], safe="")
    request = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        "/with-timestamps?output_format=pcm_24000",
        data=json.dumps({"text": text, "model_id": "eleven_multilingual_v2"}).encode(),
        headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"],
                 "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            result = json.load(response)
        audio = np.frombuffer(base64.b64decode(result["audio_base64"], validate=True),
                              dtype="<i2").astype(np.float32) / 32768.0
        alignment = result["alignment"]
        if not len(audio) or not isinstance(alignment, dict):
            raise ValueError("empty audio or alignment")
        return audio, alignment
    except urllib.error.HTTPError as exc:
        # Never surface the upstream body, URL, headers or exception: any of
        # them could echo credentials. Inspect only the quota status marker.
        try:
            quota = b"quota_exceeded" in exc.read()
        except Exception:
            quota = False
        finally:
            exc.close()
        if exc.code == 401:
            message = "ElevenLabs rechazó la clave"
        elif exc.code == 402 or quota:
            message = "Se acabaron los créditos de ElevenLabs"
        else:
            message = f"ElevenLabs no respondió (HTTP {exc.code})"
        raise TTSUnavailable(message) from None
    except Exception:
        raise TTSUnavailable("ElevenLabs no respondió o devolvió audio inválido") from None


def _own_key(kind: str, body: str, turns: list[dict]) -> str:
    signature = ("\n".join(f"{t['speaker']}: {t['text']}" for t in turns)
                 if kind == "podcast" else body)
    # A different clone must not reuse audio from the previous voice.
    voice = f"{kind}|{os.environ.get('ELEVENLABS_VOICE_ID', '')}|eleven_multilingual_v2"
    return _key(signature, voice, "eleven")


def own_voice_chars(kind: str, body: str, turns: list[dict]) -> int:
    return (sum(len(t["text"]) for t in turns if t["speaker"] == "B")
            if kind == "podcast" else len(body))


def own_voice_cached(kind: str, body: str, turns: list[dict]) -> bool:
    key = _own_key("podcast" if kind == "podcast" else "reading", body, turns)
    return all((TTS_DIR / f"{key}{ext}").is_file() for ext in (".wav", ".json"))


def narrate_own(text: str) -> dict:
    """Narrate the complete reading once; use character times for sentences."""
    import soundfile as sf

    sentences = split_sentences(text)
    if not sentences:
        raise ValueError("nothing to narrate")
    key = _own_key("reading", text, [])
    audio_path, marks_path = TTS_DIR / f"{key}.wav", TTS_DIR / f"{key}.json"
    if audio_path.is_file() and marks_path.is_file():
        return {"path": f"tts/{audio_path.name}",
                "marks": json.loads(marks_path.read_text(encoding="utf-8")),
                "provider": "eleven", "cached": True}

    audio, alignment = _eleven(text)
    marks, cursor = [], 0
    try:
        for sentence in sentences:
            start = text.find(sentence, cursor)
            if start < 0:
                raise ValueError("sentence not found")
            cursor = start + len(sentence)
            marks.append({"text": sentence,
                          "start": alignment["character_start_times_seconds"][start],
                          "end": alignment["character_end_times_seconds"][cursor - 1]})
    except (KeyError, IndexError, TypeError, ValueError):
        raise TTSUnavailable("ElevenLabs devolvió marcas de tiempo inválidas") from None
    TTS_DIR.mkdir(parents=True, exist_ok=True)
    sf.write(str(audio_path), audio, SAMPLE_RATE)
    marks_path.write_text(json.dumps(marks, ensure_ascii=False), encoding="utf-8")
    return {"path": f"tts/{audio_path.name}", "marks": marks,
            "provider": "eleven", "cached": False}


def _eleven_turn(text: str) -> "np.ndarray":
    """A paid podcast turn, kept on disk: a retry after a failure mid-episode
    does not pay again for the turns that already came back."""
    import numpy as np

    voice = f"{os.environ.get('ELEVENLABS_VOICE_ID', '')}|eleven_multilingual_v2"
    path = TTS_DIR / f"{_key(text, voice, 'eleven-turn')}.npy"
    if path.is_file():
        return np.load(path)
    audio, _ = _eleven(text)
    TTS_DIR.mkdir(parents=True, exist_ok=True)
    np.save(path, audio)
    return audio


def narrate_turns_own(turns: list[dict]) -> dict:
    return narrate_turns(turns, own_speaker="B")


class TTSProvider:
    name = "base"

    def available(self) -> bool:
        raise NotImplementedError

    def synth_sentences(self, sentences: "list[str]", voice: str,
                        out_path: Path) -> "list[dict]":
        """Write one audio file; return [{text, start, end}] in seconds."""
        raise NotImplementedError


class KokoroProvider(TTSProvider):
    name = "kokoro"
    _pipeline = None

    def available(self) -> bool:
        try:
            import kokoro  # noqa: F401
            import soundfile  # noqa: F401
            return True
        except Exception:
            return False

    def _pipe(self):
        if KokoroProvider._pipeline is None:
            from kokoro import KPipeline
            KokoroProvider._pipeline = KPipeline(lang_code="a")
        return KokoroProvider._pipeline

    def synth_sentences(self, sentences, voice, out_path):
        import numpy as np
        import soundfile as sf

        pipe = self._pipe()
        voice_id = VOICES.get(voice, voice)
        chunks, marks, cursor = [], [], 0.0
        for s in sentences:
            audio = np.concatenate([a for _, _, a in pipe(s, voice=voice_id)])
            dur = len(audio) / SAMPLE_RATE
            marks.append({"text": s, "start": round(cursor, 3),
                          "end": round(cursor + dur, 3)})
            chunks.append(audio)
            # a short breath between sentences, so shadowing has room
            chunks.append(np.zeros(int(SAMPLE_RATE * 0.25), dtype=audio.dtype))
            cursor += dur + 0.25
        sf.write(str(out_path), np.concatenate(chunks), SAMPLE_RATE)
        return marks


class SayProvider(TTSProvider):
    """macOS `say`. Lower quality, but needs no install — the safety net."""
    name = "say"

    def available(self) -> bool:
        return shutil.which("say") is not None

    def synth_sentences(self, sentences, voice, out_path):
        voice_name = os.environ.get("SAY_VOICE", "Samantha")
        aiff = out_path.with_suffix(".aiff")
        subprocess.run(["say", "-v", voice_name, "-o", str(aiff),
                        " ".join(sentences)], check=True, timeout=600)
        # Duration split proportionally to sentence length — approximate but
        # honest: `say` exposes no per-sentence timing.
        total = _audio_duration(aiff)
        shutil.move(str(aiff), str(out_path.with_suffix(".aiff")))
        chars = sum(len(s) for s in sentences) or 1
        marks, cursor = [], 0.0
        for s in sentences:
            dur = total * len(s) / chars
            marks.append({"text": s, "start": round(cursor, 3),
                          "end": round(cursor + dur, 3)})
            cursor += dur
        return marks


def _audio_duration(path: Path) -> float:
    try:
        out = subprocess.run(["afinfo", str(path)], capture_output=True,
                             text=True, timeout=30).stdout
        m = re.search(r"estimated duration: ([\d.]+)", out)
        return float(m.group(1)) if m else 0.0
    except Exception:
        return 0.0


def get_provider() -> TTSProvider:
    choice = os.environ.get("TTS_PROVIDER", "auto").strip().lower()
    kokoro, say = KokoroProvider(), SayProvider()
    if choice == "kokoro":
        if not kokoro.available():
            raise TTSUnavailable("Kokoro no está instalado (pip install kokoro soundfile).")
        return kokoro
    if choice == "say":
        if not say.available():
            raise TTSUnavailable("`say` no está disponible en este sistema.")
        return say
    if kokoro.available():
        return kokoro
    if say.available():
        return say
    raise TTSUnavailable("No hay motor de voz disponible.")


def status() -> dict:
    kokoro, say = KokoroProvider(), SayProvider()
    out = {"configured": False, "provider": None,
           "kokoro_available": kokoro.available(),
           "say_available": say.available(),
           "voices": list(VOICES)}
    try:
        p = get_provider()
        out.update(configured=True, provider=p.name)
    except TTSUnavailable:
        pass
    return out


def narrate_turns(turns: "list[dict]", own_speaker: str | None = None) -> dict:
    """Narrate a dialogue: each turn in its own voice, one audio file.

    Marks carry `turn` and `speaker` on top of the timings, so the podcast
    can highlight the line being spoken and repeat a single turn — the same
    trick as the reader's karaoke, one level up.
    """
    if own_speaker is not None:
        provider = KokoroProvider()
        if not provider.available():
            raise TTSUnavailable("Kokoro no está instalado (pip install kokoro soundfile).")
    else:
        provider = get_provider()
    provider_name = "eleven" if own_speaker is not None else provider.name
    if not turns:
        raise ValueError("nothing to narrate")

    TTS_DIR.mkdir(parents=True, exist_ok=True)
    signature = "\n".join(f"{t['speaker']}: {t['text']}" for t in turns)
    key = (_own_key("podcast", "", turns) if own_speaker is not None
           else _key(signature, "dialogue", provider.name))
    ext = ".wav" if provider.name == "kokoro" else ".aiff"
    audio_path = TTS_DIR / f"{key}{ext}"
    marks_path = TTS_DIR / f"{key}.json"

    if audio_path.exists() and marks_path.exists():
        return {"path": f"tts/{audio_path.name}",
                "marks": json.loads(marks_path.read_text(encoding="utf-8")),
                "provider": provider_name, "cached": True}

    if own_speaker is not None and not own_voice_configured():
        raise TTSUnavailable("La voz propia de ElevenLabs no está configurada.")

    if provider.name != "kokoro":
        # `say` has one voice per call; fall back to a single narrator so the
        # feature still works, just without the two-voice illusion.
        marks = provider.synth_sentences([t["text"] for t in turns],
                                         "narrator", audio_path)
        for i, m in enumerate(marks):
            m["turn"] = i
            m["speaker"] = turns[i]["speaker"]
    else:
        import numpy as np
        import soundfile as sf

        pipe = provider._pipe()
        chunks, marks, cursor = [], [], 0.0
        for i, turn in enumerate(turns):
            voice_id = VOICES.get(f"speaker_{turn['speaker'].lower()}",
                                  VOICES["narrator"])
            if turn["speaker"] == own_speaker:
                audio = _eleven_turn(turn["text"])
            else:
                audio = np.concatenate([a for _, _, a in
                                        pipe(turn["text"], voice=voice_id)])
            dur = len(audio) / SAMPLE_RATE
            marks.append({"text": turn["text"], "turn": i,
                          "speaker": turn["speaker"],
                          "start": round(cursor, 3),
                          "end": round(cursor + dur, 3)})
            chunks.append(audio)
            # a beat between speakers, so turns are audibly separate
            chunks.append(np.zeros(int(SAMPLE_RATE * 0.35), dtype=audio.dtype))
            cursor += dur + 0.35
        sf.write(str(audio_path), np.concatenate(chunks), SAMPLE_RATE)

    marks_path.write_text(json.dumps(marks, ensure_ascii=False), encoding="utf-8")
    return {"path": f"tts/{audio_path.name}", "marks": marks,
            "provider": provider_name, "cached": False}


def narrate(text: str, voice: str = "narrator") -> dict:
    """Synthesize (or serve from cache). Returns {path, marks, provider}."""
    provider = get_provider()
    sentences = split_sentences(text)
    if not sentences:
        raise ValueError("nothing to narrate")

    TTS_DIR.mkdir(parents=True, exist_ok=True)
    key = _key(text, voice, provider.name)
    ext = ".wav" if provider.name == "kokoro" else ".aiff"
    audio_path = TTS_DIR / f"{key}{ext}"
    marks_path = TTS_DIR / f"{key}.json"

    if audio_path.exists() and marks_path.exists():
        marks = json.loads(marks_path.read_text(encoding="utf-8"))
        return {"path": f"tts/{audio_path.name}", "marks": marks,
                "provider": provider.name, "cached": True}

    marks = provider.synth_sentences(sentences, voice, audio_path)
    marks_path.write_text(json.dumps(marks, ensure_ascii=False), encoding="utf-8")
    return {"path": f"tts/{audio_path.name}", "marks": marks,
            "provider": provider.name, "cached": False}
