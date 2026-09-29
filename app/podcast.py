"""Podcast studio (ADR-007 M11) — two voices, two ways to listen.

Eddie listens to the English Leap Podcast to tune his ear. This makes the
same shape from his own vocabulary: a natural conversation between two
people, produced with two Kokoro voices, that he can use two ways:

  shadowing — transcript visible, the spoken turn lit, speed and repeat-turn
  ear only  — no transcript at all, then a comprehension quiz that can only
              be answered by having actually listened

The dialogue is stored as a text (kind='podcast') so it files itself into the
library by day like everything else.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from app import ai, db, model, tts  # noqa: E402

MINUTES = (3, 5, 8)
TURNS_FOR = {3: "14-18", 5: "22-28", 8: "34-42"}

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "speaker_a_name": {"type": "string"},
        "speaker_b_name": {"type": "string"},
        "turns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "speaker": {"type": "string", "enum": ["A", "B"]},
                    "text": {"type": "string"},
                },
                "required": ["speaker", "text"],
                "additionalProperties": False,
            },
        },
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                    "answer_index": {"type": "integer", "enum": [0, 1, 2]},
                    "why": {"type": "string"},
                },
                "required": ["question", "options", "answer_index", "why"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "speaker_a_name", "speaker_b_name", "turns", "questions"],
    "additionalProperties": False,
}

SYSTEM = """You write a two-person English podcast episode for Eddie — a \
Spanish-speaking frontend engineer at Clip (a fintech in Mexico City) who cares about product, B1→C1 — inside "English OS".

It must sound like a real conversation, not a lesson read aloud:
- Two hosts, A and B, with names. They interrupt, agree, disagree, tell small \
personal stories, and react to each other.
- Eddie is the LISTENER, never a character. The hosts never address him, never \
say his name, and never speak to "you".
- Short turns. One to three sentences each; nobody lectures for a paragraph.
- Natural spoken English at the level given: contractions, discourse markers \
("well", "actually", "I mean", "right?"), and everyday idiom. No written-prose \
register, no bullet points, no stage directions, no sound effects.
- Weave in the target words where they genuinely fit, in the way people \
actually use them. Never define them, never say "today's word". **A word used \
wrongly teaches him the wrong thing: if a target word does not fit this \
conversation naturally, leave it out.** Using six of them well beats using all \
of them badly.
- One concrete topic with a small arc: an opening hook, a middle where a real \
example or disagreement appears, and a close.

Then write 4 comprehension questions (3 options each) that can ONLY be \
answered by someone who listened to the whole thing — about what was said, \
who said it, and what they concluded. Never about vocabulary definitions.

LANGUAGE RULE: the dialogue, the questions and the options are all in ENGLISH \
— he is training his ear and reading comprehension. Only each "why" is written \
in Spanish, because that is the explanation."""


def build_prompt(conn: sqlite3.Connection, minutes: int = 5,
                 topic: str = "Random", level: "str | None" = None) -> dict:
    """El encargo del episodio: mismo texto para el modelo local y la rutina."""
    if minutes not in MINUTES:
        raise ValueError(f"minutes must be one of {MINUTES}")
    if level is None:
        level = model.recommend_level(conn)["level"]

    words = model.learning_words(conn, 10)
    if not words:
        raise ValueError("no vocabulary to build an episode from")
    topic_line = ("Pick a topic two colleagues would actually talk about."
                  if topic == "Random" else f"Topic: {topic}.")
    return {
        "level": level, "topic": topic, "minutes": minutes, "words": words,
        "prompt": (
            f"Write an episode of about {minutes} minutes "
            f"({TURNS_FOR[minutes]} turns) at level {level}.\n{topic_line}\n"
            f"Target words to weave in: {', '.join(w['word'] for w in words)}.\n"
            "Then the 4 comprehension questions."),
    }


def store(conn: sqlite3.Connection, result: dict, words: "list[dict]",
          level: str, topic: str, source: str = "generated:podcast") -> dict:
    """Valida el diálogo, produce el audio de dos voces y lo guarda.

    El audio (Kokoro, local) es lo caro: quien llame desde fuera de la cola
    debe hacerlo dentro de `jobs._exclusive()` para no poner dos inferencias
    a pelearse el CPU.
    """
    turns = [t for t in result.get("turns", [])
             if t.get("speaker") in ("A", "B") and str(t.get("text", "")).strip()]
    if not turns:
        raise ValueError("the dialogue is empty")
    names = {"A": (result.get("speaker_a_name") or "A").strip(),
             "B": (result.get("speaker_b_name") or "B").strip()}
    audio = tts.narrate_turns(turns)

    transcript = "\n".join(f"{names[t['speaker']]}: {t['text']}" for t in turns)
    tid = db.upsert_text(conn, {
        "kind": "podcast",
        "title": (result.get("title") or "").strip(),
        "date": db.study_day(),
        "level": level,
        "topic": topic,
        "body": transcript,
        "source": source,
        "questions": json.dumps(result.get("questions", [])[:4], ensure_ascii=False),
        "words_target": json.dumps([w["word"] for w in words], ensure_ascii=False),
        "correction": json.dumps({"speakers": names, "turns": turns},
                                 ensure_ascii=False),
        "tts_path": audio["path"],
        "tts_marks": json.dumps(audio["marks"], ensure_ascii=False),
    })
    conn.commit()
    return detail(conn, tid)


def generate(conn: sqlite3.Connection, minutes: int = 5,
             topic: str = "Random", level: "str | None" = None) -> dict:
    """Write the dialogue, produce the two-voice audio, store it."""
    spec = build_prompt(conn, minutes, topic, level)
    result = ai.get_provider("podcast").generate_json(
        SYSTEM, spec["prompt"], SCHEMA, max_tokens=8192)
    return store(conn, result, spec["words"], spec["level"], spec["topic"])


def detail(conn: sqlite3.Connection, text_id: int) -> dict:
    row = conn.execute("SELECT * FROM texts WHERE id=? AND kind='podcast'",
                       (text_id,)).fetchone()
    if row is None:
        raise ValueError(f"podcast {text_id} not found")
    meta = json.loads(row["correction"] or "{}")
    return {
        "id": row["id"], "title": row["title"], "date": row["date"],
        "level": row["level"], "topic": row["topic"],
        "speakers": meta.get("speakers", {"A": "A", "B": "B"}),
        "turns": meta.get("turns", []),
        "questions": json.loads(row["questions"] or "[]"),
        "words_target": json.loads(row["words_target"] or "[]"),
        "audio": row["tts_path"],
        "marks": json.loads(row["tts_marks"] or "[]"),
        "finished_at": row["finished_at"],
        "seconds": row["reading_seconds"],
    }


def listed(conn: sqlite3.Connection) -> "list[dict]":
    return [{"id": r["id"], "title": r["title"], "date": r["date"],
             "level": r["level"], "finished": r["finished_at"] is not None}
            for r in conn.execute(
                "SELECT id, title, date, level, finished_at FROM texts "
                "WHERE kind='podcast' ORDER BY date DESC, id DESC LIMIT 60")]


def finish(conn: sqlite3.Connection, text_id: int, seconds: int) -> dict:
    """Listening time counts as listening, not reading."""
    conn.execute("UPDATE texts SET finished_at=?, reading_seconds=?, updated_at=? "
                 "WHERE id=?", (db.now_iso(), seconds, db.now_iso(), text_id))
    today = db.study_day()
    prev = conn.execute("SELECT listening_minutes FROM sessions WHERE date=?",
                        (today,)).fetchone()
    minutes = round(((prev["listening_minutes"] or 0) if prev else 0)
                    + seconds / 60, 2)
    db.upsert_session(conn, today, {"listening_minutes": minutes})
    conn.commit()
    return {"ok": True, "listening_minutes_today": minutes}
