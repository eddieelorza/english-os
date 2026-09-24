"""Conversación hablada en vivo (M19).

Speaking era un monólogo: una pregunta, grabas dos minutos, te corrige. Esto
es lo otro — hablar con alguien y que te conteste.

## La decisión que define la función: NO se corrige durante

Corregir cada turno mata la conversación. Se deja de hablar para pensar en
gramática, que es exactamente lo que Eddie pidió evitar ("que no sea
abrumante"). Aquí se hacen dos cosas en su lugar:

1. **Recast**: si dice "I have 30 years", el compañero contesta usando la
   forma correcta con naturalidad ("Nice, so you're 30 — what did you do...")
   sin señalar nada. Se corrige oyéndolo bien dicho, no siendo interrumpido.
2. **Al final, máximo 3 correcciones.** Elegidas por valor didáctico, no las
   tres primeras. Van a la tabla `errors`, así que alimentan Practice y Stats
   como las del writing.

## Latencia, medida en su M5

Whisper `small` 1.5 s sobre 6.6 s de audio · modelo 1.2 s en caliente ·
Kokoro 2.7 s. Un turno son ~5 s. No es instantáneo y no se finge que lo sea.
El historial se recorta a `CONTEXT_TURNS` para que el modelo no se vaya
frenando según crece la charla.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from difflib import SequenceMatcher
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from app import ai, db, speaking, tts  # noqa: E402

# Cuántos turnos ve el modelo. Con toda la charla el turno se va alargando
# hasta romper la ilusión de conversación.
CONTEXT_TURNS = 8
MAX_CORRECTIONS = 3

PARTNER_SYSTEM = """You are Eddie's English conversation partner inside a \
personal learning app. Eddie is a Spanish-speaking frontend engineer at Clip, a fintech in \
Mexico City, around B1 going to B2.

You are a PERSON having a conversation, not a teacher running a lesson.

Rules:
- Reply in ENGLISH, 1-2 sentences. Never more.
- Always end with a question that gives him the floor back.
- Natural spoken register: contractions, short sentences. No lists, no emoji, \
no stage directions.
- Stay on what he actually said. Real life: frontend work (React, UI, \
shipping features), his team and product decisions, Mexico City, \
family, food, plans.

The correction rule, and it matters:
- NEVER point out a mistake. No "you should say", no grammar talk, no \
asterisks, no repeating his sentence to fix it.
- Instead, if he said something wrong, use the CORRECT form naturally inside \
your reply, as if you were just talking. He said "I have 30 years" -> you say \
"So you're 30 — what were you doing at 25?" He said "I did a mistake" -> you \
say "Everyone makes that mistake. What happened next?"
- One recast per reply at most. If nothing is wrong, just talk."""

PARTNER_SCHEMA = {
    "type": "object",
    "properties": {"reply": {"type": "string"}},
    "required": ["reply"],
    "additionalProperties": False,
}

OPENER_SYSTEM = """You open a spoken English conversation with Eddie, a \
Spanish-speaking frontend engineer at Clip in Mexico City (B1 to B2).

Write ONE opening line: a greeting plus a concrete question about his real \
life or work. Max 25 words, spoken English, no lists.
Do not ask "how are you" — ask something he has to think about."""

SUMMARY_SYSTEM = """You review a spoken English conversation and give Eddie \
feedback afterwards. He is B1 going to B2 and Spanish-speaking.

Return AT MOST 3 corrections — the 3 most useful to learn from, not the first \
3 you find. Skip anything that is just a speech-to-text artifact (missing \
punctuation, a mangled proper name, a repeated word): he SPOKE this, it was \
transcribed by a machine, so only flag real language errors.

Each correction:
- category: exactly one of these, and pick by what the error IS:
    ART   article missing or wrong (a/an/the)
    PREP  wrong preposition (work IN a feature -> work ON)
    S-V   subject-verb agreement (the team agree -> agrees)
    COLL  wrong word pairing (do a mistake -> make a mistake)
    TENSE wrong tense or a broken verb chain (will can -> can)
    REG   register: too formal or too casual for the situation
    WORD  wrong word choice altogether
- original: his exact words, and ONLY the broken part — a few words, never the
  whole sentence
- correction: those same few words said correctly
- explanation: ONE short line in Spanish saying why

Also return `strength`: one concrete thing he did well, in Spanish, one line.

Hard rules for the feedback text:
- Address him as "tú" (second person). His name is Eddie — never write any
  other name, and do not invent one.
- Do NOT claim he moved between levels, and do not mention B1, B2 or C1 at
  all: one conversation cannot show that.
- Name what he actually said. "Usaste bien el pasado al contar lo del
  drop-off" is a strength; "buen manejo de los tiempos verbales" is not.

If he made no real errors, return an empty list. Do not invent errors."""

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "corrections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "original": {"type": "string"},
                    "correction": {"type": "string"},
                    "explanation": {"type": "string"},
                },
                "required": ["category", "original", "correction", "explanation"],
            },
        },
        "strength": {"type": "string"},
    },
    "required": ["corrections", "strength"],
}

CATEGORIES = {"ART", "PREP", "S-V", "COLL", "TENSE", "REG", "WORD"}


CONTEXT_WORDS = 2


def tighten(original: str, correction: str) -> "tuple[str, str]":
    """Recorta el par al trozo que de verdad cambia.

    El modelo devuelve la frase entera por mucho que el prompt pida el trozo
    roto, y una frase entera guardada en `errors` es inservible: la tabla
    deduplica por (categoría, original), así que dos veces el mismo fallo en
    frases distintas cuentan como dos errores diferentes y las recurrencias
    nunca suben. Esto no se le pide al modelo — se calcula.

    "We did a mistake last month..." / "We made a mistake last month..."
        -> ("We did a mistake", "We made a mistake")
    """
    a, b = original.split(), correction.split()
    ops = [op for op in SequenceMatcher(None, [w.lower() for w in a],
                                        [w.lower() for w in b]).get_opcodes()
           if op[0] != "equal"]
    if not ops:
        return original.strip(), correction.strip()
    # El PRIMER cambio, no la envolvente de todos. Con dos cambios en extremos
    # opuestos ("did"->"made" al principio y "drop off"->"drop-off" al final)
    # la envolvente vuelve a ser la frase entera, que es lo que se quería
    # evitar. Un error por corrección; si hay dos, el resumen ya trae otra.
    _, i1, i2, j1, j2 = ops[0]
    i1 = max(0, i1 - CONTEXT_WORDS)
    i2 = min(len(a), i2 + CONTEXT_WORDS)
    j1 = max(0, j1 - CONTEXT_WORDS)
    j2 = min(len(b), j2 + CONTEXT_WORDS)
    short_a = " ".join(a[i1:i2]).strip(" .,;:")
    short_b = " ".join(b[j1:j2]).strip(" .,;:")
    return (short_a or original.strip()), (short_b or correction.strip())


def _clean_strength(strength: str, corrections: list) -> str:
    """Una fortaleza no puede elogiar lo que se acaba de corregir.

    Caso real: corrigió "since two years" -> "for two years" y en la misma
    pantalla felicitó por "usaste bien el pasado simple al decir 'go there
    since two years'". Contradecirse así destruye la confianza en todo el
    resto del resumen, y no hay prompt que lo garantice — se comprueba.

    Sin fortaleza es mejor que con una falsa: la pantalla ya sabe no pintarla.
    """
    low = strength.lower()
    for c in corrections:
        broken = c.get("original", "").strip().lower()
        # Se comparan las palabras del trozo roto: citarlo entero o casi
        # entero es la señal de que está elogiando el error.
        words = [w for w in re.findall(r"[a-z']+", broken) if len(w) > 2]
        if words and sum(w in low for w in words) >= max(2, len(words) - 1):
            return ""
    return strength


def _add_turn(conn: sqlite3.Connection, conv_id: int, speaker: str, text: str,
              audio_path: "str | None" = None,
              seconds: "float | None" = None) -> int:
    idx = conn.execute(
        "SELECT COALESCE(MAX(idx), -1) + 1 FROM conversation_turns "
        "WHERE conversation_id=?", (conv_id,)).fetchone()[0]
    conn.execute(
        "INSERT INTO conversation_turns (conversation_id, idx, speaker, text, "
        "audio_path, seconds, created_at) VALUES (?,?,?,?,?,?,?)",
        (conv_id, idx, speaker, text, audio_path, seconds, db.now_iso()))
    conn.execute(
        "UPDATE conversations SET turns=?, updated_at=? WHERE id=?",
        (idx + 1, db.now_iso(), conv_id))
    return idx


def turns(conn: sqlite3.Connection, conv_id: int, limit: "int | None" = None) -> list:
    rows = conn.execute(
        "SELECT idx, speaker, text, audio_path, seconds FROM conversation_turns "
        "WHERE conversation_id=? ORDER BY idx", (conv_id,)).fetchall()
    rows = [dict(r) for r in rows]
    return rows[-limit:] if limit else rows


def start(conn: sqlite3.Connection, topic: "str | None" = None) -> dict:
    """Abre una conversación: el compañero habla primero."""
    # A propósito NO se le pasan las palabras de estudio. Con ellas, la
    # primera versión abrió con "have you heard about the coal shortage
    # causing power bursts in Mexico City?" — metió `coal` y `burst` con
    # calzador y dejó de ser una conversación. El vocabulario ya se trabaja en
    # Review, Reading y Practice; aquí lo que se practica es hablar.
    provider = ai.get_provider("conversation")
    result = provider.generate_json(
        OPENER_SYSTEM,
        f"Topic he chose: {topic or '(none — pick something ordinary)'}.",
        {"type": "object", "properties": {"reply": {"type": "string"}},
         "required": ["reply"]})
    line = (result.get("reply") or "").strip()

    cur = conn.execute(
        "INSERT INTO conversations (date, topic, started_at, created_at, updated_at) "
        "VALUES (?,?,?,?,?)",
        (db.study_day(), topic, db.now_iso(), db.now_iso(), db.now_iso()))
    conv_id = cur.lastrowid
    voice = tts.narrate(line, voice="speaker_a")
    _add_turn(conn, conv_id, "partner", line, voice.get("path"))
    conn.commit()
    return {"conversation_id": conv_id, "reply": line,
            "audio": voice.get("path"), "marks": voice.get("marks")}


def _history(conn: sqlite3.Connection, conv_id: int) -> str:
    lines = []
    for t in turns(conn, conv_id, limit=CONTEXT_TURNS):
        who = "Eddie" if t["speaker"] == "eddie" else "You"
        lines.append(f"{who}: {t['text']}")
    return "\n".join(lines)


def say(conn: sqlite3.Connection, conv_id: int, audio_path: "str | Path") -> dict:
    """Un turno: lo que dijo, lo que le contestan, y la voz."""
    heard = speaking.transcribe(audio_path)
    text = (heard.get("text") or "").strip()
    if not text:
        raise ValueError("No se oyó nada — ¿el micrófono está mudo?")
    _add_turn(conn, conv_id, "eddie", text, str(audio_path),
              heard.get("duration_seconds"))

    provider = ai.get_provider("conversation")
    result = provider.generate_json(
        PARTNER_SYSTEM,
        f"The conversation so far:\n{_history(conn, conv_id)}\n\n"
        f"Reply to his last line.", PARTNER_SCHEMA)
    line = (result.get("reply") or "").strip()
    voice = tts.narrate(line, voice="speaker_a")
    _add_turn(conn, conv_id, "partner", line, voice.get("path"))
    conn.commit()
    return {"you_said": text, "seconds": heard.get("duration_seconds"),
            "reply": line, "audio": voice.get("path"),
            "marks": voice.get("marks")}


def finish(conn: sqlite3.Connection, conv_id: int) -> dict:
    """Cierra y devuelve el resumen: <=3 correcciones y una fortaleza."""
    row = conn.execute("SELECT * FROM conversations WHERE id=?",
                       (conv_id,)).fetchone()
    if row is None:
        raise ValueError("esa conversación no existe")
    if row["ended_at"]:
        return {"conversation_id": conv_id, "already_closed": True,
                **(json.loads(row["summary"]) if row["summary"] else {})}

    mine = [t["text"] for t in turns(conn, conv_id) if t["speaker"] == "eddie"]
    spoken = sum(t["seconds"] or 0 for t in turns(conn, conv_id)
                 if t["speaker"] == "eddie")
    summary = {"corrections": [], "strength": ""}
    if mine:
        provider = ai.get_provider("conversation_summary")
        raw = provider.generate_json(
            SUMMARY_SYSTEM,
            "What Eddie said, turn by turn:\n"
            + "\n".join(f"- {m}" for m in mine), SUMMARY_SCHEMA)
        # Se recorta aquí y no sólo en el prompt: el tope es una promesa de la
        # función, no una sugerencia al modelo.
        corrections = []
        for c in (raw.get("corrections") or []):
            if c.get("category") not in CATEGORIES:
                continue
            if not (c.get("original") and c.get("correction")):
                continue
            short_o, short_c = tighten(c["original"], c["correction"])
            if short_o.lower() == short_c.lower():
                continue   # no cambia nada: no era un error
            corrections.append({**c, "original": short_o,
                                "correction": short_c})
        corrections = corrections[:MAX_CORRECTIONS]
        summary = {"corrections": corrections,
                   "strength": _clean_strength(
                       (raw.get("strength") or "").strip(), corrections)}
        speaking._store_errors(conn, summary["corrections"], source="Conversation")

    conn.execute(
        "UPDATE conversations SET ended_at=?, summary=?, updated_at=? WHERE id=?",
        (db.now_iso(), json.dumps(summary, ensure_ascii=False),
         db.now_iso(), conv_id))
    conn.commit()
    return {"conversation_id": conv_id, "turns": row["turns"],
            "spoken_seconds": round(spoken, 1), **summary}


def warm() -> dict:
    """Carga los dos modelos antes de que hagan falta.

    Ollama suelta el modelo tras 5 minutos parado y volver a cargarlo cuesta
    4.3 s; Kokoro cuesta 5.6 s la primera vez en el proceso. Sumados son ~10 s
    de silencio justo al pulsar "empezar a hablar" — el peor momento posible.
    Se dispara al abrir la pantalla, así que la carga ocurre mientras se lee
    la introducción.

    Nada de esto es crítico: si falla, el primer turno simplemente tarda.
    """
    out = {"model": False, "voice": False}
    try:
        provider = ai.get_provider("warm")
        # Precalentar sólo tiene sentido para el modelo LOCAL. Con la
        # conversación enrutada a la nube sería cargar 5 GB de Ollama para
        # nada — o pagar una llamada que no enseña nada.
        if getattr(provider, "chain", ["ollama"])[0] == "ollama":
            provider.generate_json(
                "Reply with one word.", "Say ok.",
                {"type": "object", "properties": {"reply": {"type": "string"}},
                 "required": ["reply"]})
            out["model"] = True
    except Exception:  # noqa: BLE001 — precalentar nunca puede romper nada
        pass
    try:
        tts.narrate("Ready when you are.", voice="speaker_a")
        out["voice"] = True
    except Exception:  # noqa: BLE001
        pass
    return out


def active(conn: sqlite3.Connection) -> "dict | None":
    row = conn.execute(
        "SELECT id, topic, turns, started_at FROM conversations "
        "WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None
