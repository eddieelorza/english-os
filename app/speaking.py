"""Speaking engine (ADR-006 M6): record → transcribe → correct → learn.

Pipeline, all local-first:
  1. The Personal English Model proposes a speaking prompt built around the
     words Eddie is learning and his recurring errors.
  2. faster-whisper transcribes the recording on this machine (resolves the
     old B-IN-1 blocker — no cloud STT).
  3. The AIProvider corrects the transcript: categorized errors (the Error
     Library taxonomy), a more natural version, one strength, one thing to
     practice — the same protocol the writing-correction routine uses.
  4. The correction BECOMES study material: each error lands in the errors
     table (source='Speaking', deduped by recurrence) and feeds the same
     model that plans tomorrow; speaking minutes land in sessions.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from app import ai, db, model  # noqa: E402

RECORDINGS_DIR = BASE / "data" / "recordings"
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small")

# Same category vocabulary the Error Library already uses.
ERROR_CATEGORIES = ("Artículos", "Preposiciones", "Concordancia",
                    "Tiempos verbales", "Colocación", "Registro",
                    "Vocabulario", "Orden de palabras")

_whisper = None  # lazy singleton — the model load takes seconds


# ── Speech to text ───────────────────────────────────────────────────────

def transcribe(audio_path: "str | Path", vad: bool = True,
               segments_out: bool = False) -> dict:
    """Local STT. Returns {text, duration_seconds, language}.

    `vad` recorta los silencios y es lo correcto para alguien hablando a un
    micrófono. Con música es lo contrario: el detector decide que la canción
    entera es "sin habla" y se la come. Medido sobre una canción de 3.4 min:
    con VAD salieron **31 palabras**; sin él, **282**, y la confianza pasó de
    -0.78 (dudoso) a -0.22 (fiable). Por eso es un parámetro y no una
    constante.

    `segments_out` añade los tramos con sus marcas de tiempo, que es lo que
    necesita el shadowing para reproducir línea por línea.
    """
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        _whisper = WhisperModel(WHISPER_MODEL, device="cpu",
                                compute_type="int8")
    segments, info = _whisper.transcribe(str(audio_path), language="en",
                                         vad_filter=vad)
    segments = list(segments)
    text = " ".join(s.text.strip() for s in segments).strip()
    out = {"text": text,
           "duration_seconds": round(info.duration, 1),
           "language": info.language}
    if segments_out:
        out["segments"] = [
            {"start": round(s.start, 2), "end": round(s.end, 2),
             "text": s.text.strip(),
             # `avg_logprob`: > -0.5 fiable, -0.8 o menos poco de fiar. Viaja
             # con la línea para poder avisar en pantalla en vez de presentar
             # una transcripción dudosa como si fuera cierta.
             "confidence": round(s.avg_logprob, 3)}
            for s in segments if s.text.strip()]
    return out


# ── The prompt: the model asks the question ──────────────────────────────

PROMPT_SCHEMA = {
    "type": "object",
    "properties": {"prompt": {"type": "string"}},
    "required": ["prompt"],
    "additionalProperties": False,
}

PROMPT_SYSTEM = """You are the speaking coach inside "English OS", a personal \
app for Eddie — a Spanish-speaking frontend engineer at Clip (a fintech in Mexico City) who cares about product, moving from \
B1 toward C1. You write ONE short speaking prompt (a single question or \
invitation, max 30 words) that he answers out loud for 1-2 minutes.

Rules:
- Weave in 2-3 of his current learning words naturally, so answering well \
almost requires using them.
- Ground it in his real life: frontend engineering, code review, shipping \
features, working with product and design, daily life in \
Mexico City. Never abstract philosophy.
- Plain conversational English at B1 level."""


def speaking_prompt(conn: sqlite3.Connection) -> dict:
    words = model.learning_words(conn, 6)
    err = model.errors(conn)["top_categories"]
    user = ("His current learning words: "
            + ", ".join(w["word"] for w in words) + "."
            + (f" His recurring error areas: {', '.join(err)}." if err else "")
            + " Write the speaking prompt.")
    provider = ai.get_provider("speaking_prompt")
    result = provider.generate_json(PROMPT_SYSTEM, user, PROMPT_SCHEMA,
                                    max_tokens=200)
    return {"prompt": result["prompt"].strip(),
            "learning_words": [w["word"] for w in words]}


# ── The correction: same protocol as the writing routine ─────────────────

CORRECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "errors": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "original": {"type": "string"},
                    "correction": {"type": "string"},
                    "category": {"type": "string", "enum": list(ERROR_CATEGORIES)},
                    "explanation": {"type": "string"},
                },
                "required": ["original", "correction", "category", "explanation"],
                "additionalProperties": False,
            },
        },
        "natural_version": {"type": "string"},
        "strength": {"type": "string"},
        "practice_next": {"type": "string"},
    },
    "required": ["errors", "natural_version", "strength", "practice_next"],
    "additionalProperties": False,
}

CORRECTION_SYSTEM = """You are the speaking coach inside "English OS" \
correcting a TRANSCRIBED spoken answer from Eddie (Spanish speaker, B1→C1, \
frontend engineer). It is speech: ignore punctuation, filler words and \
transcription artifacts — correct only real language errors.

Protocol (the same one his writing coach uses):
- At most 8 errors; if there are more, keep the most educational ones. \
Typical Spanish-interference: articles, prepositions, verb tenses \
("I have 2 years working here" → "I've been working here for two years"), \
false friends, word order.
- Each error: the exact original fragment, the corrected fragment, one \
category, and a one-sentence explanation that teaches.
- natural_version: his whole answer rewritten as a fluent B2 speaker would \
say it — keep his ideas and voice, don't embellish.
- strength: one concrete thing he did well. practice_next: one specific \
thing to work on. Both one sentence."""


def correct(transcript: str) -> dict:
    provider = ai.get_provider("speaking_correction")
    return provider.generate_json(
        CORRECTION_SYSTEM,
        f'Transcript of his spoken answer:\n"{transcript}"',
        CORRECTION_SCHEMA, max_tokens=4096)


# ── Persistence: the correction becomes study material ───────────────────

def _store_errors(conn: sqlite3.Connection, errors: "list[dict]",
                  source: str = "Speaking") -> int:
    """Each error feeds the same table writing and activities use. Dedup by
    (category, original): a repeat bumps Recurrences instead of duplicating."""
    stored = 0
    today = db.study_day()
    for e in errors:
        existing = conn.execute(
            "SELECT id, recurrences FROM errors WHERE category=? AND original=?",
            (e["category"], e["original"])).fetchone()
        if existing:
            conn.execute(
                "UPDATE errors SET recurrences=?, date=?, updated_at=? WHERE id=?",
                (existing["recurrences"] + 1, today, db.now_iso(), existing["id"]))
        else:
            conn.execute(
                "INSERT INTO errors (date, category, error, original, correction, "
                "explanation, source, recurrences, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,1,?,?)",
                (today, e["category"], e["correction"], e["original"],
                 e["correction"], e["explanation"], source,
                 db.now_iso(), db.now_iso()))
        stored += 1
    return stored


def submit(conn: sqlite3.Connection, audio_path: "str | Path",
           prompt: "str | None" = None) -> dict:
    """The full loop: transcribe → correct → store text + errors + minutes."""
    tr = transcribe(audio_path)
    if not tr["text"]:
        raise ValueError("Nothing was transcribed — the recording seems silent.")
    correction = correct(tr["text"])

    title = (prompt or tr["text"])[:60] + "…"
    tid = db.upsert_text(conn, {
        "kind": "speaking",
        "title": title,
        "date": db.study_day(),
        "body": tr["text"],
        "topic": prompt,
        "source": "speaking",
        "correction": json.dumps(correction, ensure_ascii=False),
        "audio_path": str(audio_path),
        "words_produced": len(tr["text"].split()),
        "errors_count": len(correction["errors"]),
        "corrected": 1,
    })
    _store_errors(conn, correction["errors"])

    today = db.study_day()
    prev = conn.execute(
        "SELECT speaking_minutes FROM sessions WHERE date=?", (today,)).fetchone()
    minutes = round(((prev["speaking_minutes"] or 0) if prev else 0)
                    + tr["duration_seconds"] / 60, 2)
    db.upsert_session(conn, today, {"speaking_minutes": minutes})
    conn.commit()

    return {
        "id": tid,
        "transcript": tr["text"],
        "duration_seconds": tr["duration_seconds"],
        "words_produced": len(tr["text"].split()),
        **correction,
        "speaking_minutes_today": minutes,
    }
