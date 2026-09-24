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

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

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


def narrate_turns(turns: "list[dict]") -> dict:
    """Narrate a dialogue: each turn in its own voice, one audio file.

    Marks carry `turn` and `speaker` on top of the timings, so the podcast
    can highlight the line being spoken and repeat a single turn — the same
    trick as the reader's karaoke, one level up.
    """
    provider = get_provider()
    if not turns:
        raise ValueError("nothing to narrate")

    TTS_DIR.mkdir(parents=True, exist_ok=True)
    signature = "\n".join(f"{t['speaker']}: {t['text']}" for t in turns)
    key = _key(signature, "dialogue", provider.name)
    ext = ".wav" if provider.name == "kokoro" else ".aiff"
    audio_path = TTS_DIR / f"{key}{ext}"
    marks_path = TTS_DIR / f"{key}.json"

    if audio_path.exists() and marks_path.exists():
        return {"path": f"tts/{audio_path.name}",
                "marks": json.loads(marks_path.read_text(encoding="utf-8")),
                "provider": provider.name, "cached": True}

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
            "provider": provider.name, "cached": False}


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
