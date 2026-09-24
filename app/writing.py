"""Interactive writing (ADR-007 M9) — the one typing activity of the day.

Deliberately short (4-6 sentences): heavy writing is what makes Eddie skip a
session, so the app asks for little and gives back a lot. The correction uses
the same protocol as speaking and the legacy routine, plus what he asked for
specifically: **an analysis of which verb tenses he actually used** against
the day's focus.

Time and word count are measured as a by-product of writing (Vision P2) —
nothing to log by hand.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from app import activities, ai, db, model, speaking  # noqa: E402

PROMPT_SCHEMA = {
    "type": "object",
    "properties": {"prompt": {"type": "string"}},
    "required": ["prompt"],
    "additionalProperties": False,
}

PROMPT_SYSTEM = """You write ONE short writing prompt for Eddie — a \
Spanish-speaking frontend engineer at Clip (a fintech in Mexico City) who cares about product, B1→C1 — inside "English OS".

Rules:
- The prompt asks for 4-6 sentences. Never more; he abandons long tasks.
- It must almost require the day's grammar focus and 2-3 of his learning words.
- Ground it in his real life: frontend engineering at a fintech, his team,
  product decisions he takes part in, daily life in CDMX.
- Max 35 words, plain B1 English, ending in a clear instruction."""

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
                    "category": {"type": "string",
                                 "enum": list(speaking.ERROR_CATEGORIES)},
                    "explanation": {"type": "string"},
                },
                "required": ["original", "correction", "category", "explanation"],
                "additionalProperties": False,
            },
        },
        "improved_version": {"type": "string"},
        "tenses_used": {"type": "array", "items": {"type": "string"}},
        "focus_hit": {"type": "boolean"},
        "focus_note": {"type": "string"},
        "strength": {"type": "string"},
        "practice_next": {"type": "string"},
    },
    "required": ["errors", "improved_version", "tenses_used", "focus_hit",
                 "focus_note", "strength", "practice_next"],
    "additionalProperties": False,
}

CORRECTION_SYSTEM = """You correct a short written answer from Eddie \
(Spanish speaker, B1→C1) inside "English OS".

Protocol:
- At most 8 errors, the most educational ones. Typical Spanish interference: \
articles, prepositions, verb tenses, false friends, word order.
- Each error: exact original fragment, corrected fragment, one category, and \
a one-sentence explanation IN SPANISH that teaches the rule.
- improved_version: his text rewritten at B2 — same ideas and voice, no \
embellishment.
- tenses_used: the English tense names you actually find in his text \
(e.g. "Present Simple", "Present Perfect"). Only what is really there.
- focus_hit / focus_note: did he use the day's grammar focus correctly? The \
note is one sentence in Spanish, encouraging and concrete.
- strength and practice_next: one sentence each, in Spanish."""


def writing_prompt(conn: sqlite3.Connection) -> dict:
    focus = activities.tense_focus()
    words = model.learning_words(conn, 6)
    user = (f"Grammar focus of the day: {focus}. "
            f"His learning words: {', '.join(w['word'] for w in words)}. "
            "Write the writing prompt.")
    result = ai.get_provider("writing_prompt").generate_json(PROMPT_SYSTEM, user,
                                             PROMPT_SCHEMA, max_tokens=200)
    return {"prompt": result["prompt"].strip(), "focus": focus,
            "learning_words": [w["word"] for w in words]}


# ── Modo guiado: una oración a la vez (M20) ─────────────────────────────
#
# La evidencia: Eddie escribió 3 veces en todo el proyecto. "4-6 oraciones"
# suena poco pero sigue siendo un recuadro vacío, y un recuadro vacío es el
# muro. La única vez que escribió con soltura fue una carta a una persona
# ("Hi Arnold…", 77 palabras), no un ejercicio.
#
# Así que: un destinatario real, una oración cada vez, y corrección en el
# momento — el mismo formato de la Practice que sí usa. Medido: el modelo
# local tarda 2-3 s por oración, así que la corrección inmediata es viable.

STEPS_SCHEMA = {
    "type": "object",
    "properties": {
        "scenario": {"type": "string"},
        "from_name": {"type": "string"},
        "message": {"type": "string"},
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ask": {"type": "string"},
                    "starter": {"type": "string"},
                    "word": {"type": "string"},
                },
                "required": ["ask", "starter", "word"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["scenario", "from_name", "message", "steps"],
    "additionalProperties": False,
}

STEPS_SYSTEM = """You design a SHORT guided writing task for Eddie, a Spanish \
speaker at B1 English.

Shape: someone writes him a brief message and he replies, one sentence at a \
time. A real recipient is what makes him write; an exercise is what makes him \
quit.

LANGUAGE RULE — get this wrong and the task is useless:
- `message` and `starter` are ENGLISH. He is practising English; a message in
  Spanish gives him nothing to reply to.
- `scenario` and `ask` are SPANISH. They explain the task, they are not the
  practice.

Return:
- scenario: one line in SPANISH setting the situation.
- from_name: the sender's first name.
- message: what they wrote him, IN ENGLISH. 2-3 sentences, natural, B1.
  Someone real writing to a friend — a question or a piece of news he can
  react to. Not a quiz, not a request for definitions.
- steps: EXACTLY 4. Each is one sentence of HIS REPLY:
    - ask: what that sentence should say, in SPANISH, concrete and small.
    - starter: the first 2-4 words of that sentence, IN ENGLISH, so he never
      faces a blank. It must read as the natural beginning of a sentence
      ("I think", "Last week I", "The best part"). Never a bare adjective,
      never a whole sentence.
    - word: one word from his list he should use here (or "" if none fits).

Rules:
- The four sentences together must read as ONE natural reply to the message,
  in order. Not four unrelated answers about a topic.
- Use his words ONLY where they fit naturally. A word that does not fit is
  left out — forcing it makes a sentence no one would write.
- Each step must be answerable in ONE sentence by a B1 learner."""

CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "fixed": {"type": "string"},
        "note": {"type": "string"},
        "category": {"type": "string"},
    },
    "required": ["ok", "fixed", "note"],
    "additionalProperties": False,
}

CHECK_SYSTEM = """You check ONE English sentence written by Eddie, a Spanish \
speaker at B1.

TWO FIELDS, TWO LANGUAGES. Never mix them up:

- `fixed` is ALWAYS ENGLISH. It is his sentence with the mistakes repaired.
  NEVER translate it to Spanish. Translating his English into Spanish is the
  worst thing you can do here — he is learning English.
    his: "I think is very interesting"
    fixed: "I think it's very interesting"     ← correct
    fixed: "Creo que es muy interesante"       ← WRONG, never do this
- `note` is ALWAYS SPANISH. It explains what changed, for a Spanish speaker.

- ok: true only if the sentence is correct and natural as it stands.
- fixed: his sentence repaired, IN ENGLISH. If ok, repeat it unchanged.
- note: ONE short line IN SPANISH — qué cambió y por qué. Empty string if ok.
- category: one of ART, PREP, S-V, COLL, TENSE, REG, WORD. Empty if ok.

Be encouraging but honest. Do not rewrite his meaning or make it fancier: fix \
what is wrong, keep his voice. A clumsy but correct sentence is ok=true."""


def steps(conn: sqlite3.Connection, use_cache: bool = True) -> dict:
    """El encargo del día, partido en cuatro oraciones.

    Si la pre-generación nocturna ya lo dejó escrito, se sirve de ahí: los
    ~10 s que tarda el modelo son fricción, y quitar fricción es el punto
    entero de este modo.
    """
    if use_cache:
        from app import jobs
        cached = jobs.cached_writing_task(conn)
        if cached and cached.get("steps"):
            return {**cached, "cached": True}

    words = [w["word"] for w in model.learning_words(conn, n=8)]
    focus = activities.tense_focus()
    out = ai.get_provider("writing_task").generate_json(
        STEPS_SYSTEM,
        f"His words: {', '.join(words) or '(none yet)'}\n"
        f"Grammar focus of the day: {focus}",
        STEPS_SCHEMA, max_tokens=1200)
    out["steps"] = [s for s in out.get("steps", []) if s.get("ask")][:4]
    out["focus"] = focus
    out["cached"] = False
    return out


# Palabras que sólo aparecen en español. Si la "corrección" las trae, el
# modelo tradujo en vez de corregir.
_SPANISH_TELLS = {
    "que", "porque", "muy", "creo", "es", "está", "para", "con", "pero",
    "cambió", "usa", "más", "los", "las", "del", "una", "por", "gusta",
}


def _looks_spanish(text: str) -> bool:
    words = [w.strip(".,¡!¿?\"'").lower() for w in text.split()]
    if not words:
        return False
    hits = sum(1 for w in words if w in _SPANISH_TELLS)
    return hits >= 2 or hits / len(words) > 0.25


def check(conn: sqlite3.Connection, sentence: str,
          ask: "str | None" = None) -> dict:
    """Corrige UNA oración. Rápido a propósito: es lo que se espera en vivo.

    Con red: el modelo local ya tradujo una vez la frase al español en vez de
    corregirla ("I think is very interesting" → "Creo que es muy
    interesante"). Enseñarle español donde tocaba arreglar su inglés es peor
    que no corregir, así que una corrección que parece española se descarta y
    la oración se da por buena.
    """
    sentence = (sentence or "").strip()
    if len(sentence.split()) < 2:
        raise ValueError("Escribe al menos unas palabras.")
    out = ai.get_provider("writing_check").generate_json(
        CHECK_SYSTEM,
        (f'What the sentence should say: {ask}\n' if ask else "")
        + f'His sentence: "{sentence}"',
        CHECK_SCHEMA, max_tokens=400)

    if not out.get("ok") and _looks_spanish(out.get("fixed", "")):
        return {"ok": True, "fixed": sentence, "note": "", "category": "",
                "discarded": "translated"}
    return out


def finish(conn: sqlite3.Connection, sentences: "list[dict]",
           scenario: "str | None" = None, seconds: int = 0) -> dict:
    """Cierra la sesión guiada.

    Las oraciones ya vienen corregidas una a una, así que **no se vuelve a
    llamar al modelo**: se ensambla lo que ya se sabe. Los errores entran al
    mismo bucle que el resto (`errors`), y la fila queda igual que la de un
    writing normal para que cuente como producción libre en la evidencia.
    """
    kept = [s for s in sentences if (s.get("text") or "").strip()]
    if not kept:
        raise ValueError("No hay nada escrito todavía.")

    body = " ".join(s["text"].strip() for s in kept)
    improved = " ".join((s.get("fixed") or s["text"]).strip() for s in kept)
    errors = [
        {"original": s["text"].strip(),
         "correction": (s.get("fixed") or "").strip(),
         "category": s.get("category") or "WORD",
         "explanation": s.get("note") or ""}
        for s in kept if not s.get("ok", True)
    ]
    words_produced = len(body.split())
    right = len(kept) - len(errors)

    correction = {
        "errors": errors,
        "improved_version": improved,
        "strength": (f"{right} de {len(kept)} oraciones salieron bien a la primera."
                     if right else "Terminaste las cuatro oraciones."),
        "practice_next": (errors[0]["explanation"] if errors
                          else "Prueba a alargar una oración con 'because'."),
        "mode": "guided",
    }
    tid = db.upsert_text(conn, {
        "kind": "writing",
        "title": (scenario or body)[:60] + "…",
        "date": db.study_day(),
        "body": body,
        "topic": activities.tense_focus(),
        "source": "app",
        "correction": json.dumps(correction, ensure_ascii=False),
        "words_produced": words_produced,
        "errors_count": len(errors),
        "corrected": 1,
    })
    speaking._store_errors(conn, errors, source="Writing")
    conn.commit()
    return {"id": tid, "words_produced": words_produced, "seconds": seconds,
            "sentences": len(kept), "errors": errors,
            "improved_version": improved,
            "strength": correction["strength"],
            "practice_next": correction["practice_next"]}


def submit(conn: sqlite3.Connection, text: str, prompt: "str | None" = None,
           seconds: int = 0) -> dict:
    """Correct, store, and feed the error loop."""
    text = (text or "").strip()
    if len(text.split()) < 5:
        raise ValueError("Write at least a couple of sentences first.")

    focus = activities.tense_focus()
    correction = ai.get_provider("writing_correction").generate_json(
        CORRECTION_SYSTEM,
        f"Grammar focus of the day: {focus}.\n"
        + (f'Prompt he answered: "{prompt}"\n' if prompt else "")
        + f'His text:\n"{text}"',
        CORRECTION_SCHEMA, max_tokens=4096)

    words_produced = len(text.split())
    tid = db.upsert_text(conn, {
        "kind": "writing",
        "title": (prompt or text)[:60] + "…",
        "date": db.study_day(),
        "body": text,
        "topic": focus,
        "source": "app",
        "correction": json.dumps(correction, ensure_ascii=False),
        "words_produced": words_produced,
        "errors_count": len(correction["errors"]),
        "corrected": 1,
    })
    speaking._store_errors(conn, correction["errors"], source="Writing")
    # Writing minutes ride along with the day's session row.
    conn.commit()
    return {
        "id": tid, "words_produced": words_produced, "seconds": seconds,
        "focus": focus, **correction,
    }
