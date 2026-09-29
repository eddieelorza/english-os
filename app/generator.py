"""Reading generator: the AI writes for Eddie's Personal English Model (M3).

The pedagogy comes from the proven cloud-routine conventions (CLAUDE.md +
docs/routine-prompt.md): the learner's LEARNING vocabulary is a HARD
constraint (derived forms allowed), stories are realistic with named
characters and a conflict, level B1→B2, and comprehension is 4 multiple-choice
questions whose explanations teach.

After generation the body is verified against the target words with the same
lemmatizer the reader uses; missing words are reported, never hidden.
"""

from __future__ import annotations

import json
import random
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from app import ai, db, lemma, model  # noqa: E402

LENGTH_WORDS = {5: "330-370", 10: "650-750", 15: "950-1100"}
TOPICS = ("Tech", "Work", "AI", "Fintech", "Daily Life", "Random")
LEVELS = ("B1", "B1+", "B2")

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "body": {"type": "string"},
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "answer_index": {"type": "integer", "enum": [0, 1, 2]},
                    "why": {"type": "string"},
                },
                "required": ["question", "options", "answer_index", "why"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "body", "questions"],
    "additionalProperties": False,
}

SYSTEM = """You are the English coach inside "English OS", a personal \
learning app for one student: Eddie, a Spanish-speaking frontend engineer at Clip in \
Mexico City moving from B1 toward C1. His L1 interference is Spanish: \
articles, prepositions, word order, false friends.

You write reading material calibrated to his exact vocabulary and level.

Hard rules:
- Use EVERY target word given, at least once. Derived forms are valid \
(forge → forged, prosper → prosperous, arise → arose).
- Style: realistic, contemporary or historical — never epic fantasy. Named \
characters, a concrete conflict, a resolution.
- Level discipline: B1 = simple tenses + present perfect; B1+ adds first \
conditional and comparatives; B2 adds conditionals, modals and passive voice \
where natural.
- Comprehension: exactly 4 multiple-choice questions with 3 options each — \
mix literal, inference and vocabulary-in-context; make one an opinion or \
application question. The "why" of each answer should teach, in one sentence.
- Paragraphs separated by blank lines. No markdown, no headings, no lists in \
the body — plain prose only."""


# The generator does not decide what to practice — the model does (Vision P3).
def pick_target_words(conn: sqlite3.Connection,
                      n: int = model.TARGET_WORD_COUNT) -> "list[dict]":
    return model.learning_words(conn, n)


def top_error_categories(conn: sqlite3.Connection) -> "list[str]":
    return model.errors(conn)["top_categories"]


def build_prompt(words: "list[dict]", level: str, minutes: int, topic: str,
                 error_categories: "list[str]") -> str:
    word_list = ", ".join(w["word"] for w in words)
    topic_line = ("Pick any realistic topic that suits the vocabulary."
                  if topic == "Random" else f"Topic: {topic}.")
    errors_line = ""
    if error_categories:
        errors_line = (
            "\nEddie's recurring error categories are: "
            + ", ".join(error_categories)
            + ". Where natural, include sentences that model the CORRECT "
              "usage in those areas (do not point them out — just model them).")
    return (
        f"Write a {LENGTH_WORDS.get(minutes, '330-370')}-word story at level "
        f"{level}. {topic_line}\n"
        f"Target words (use ALL of them): {word_list}.{errors_line}\n"
        f"Then write the 4 comprehension questions."
    )


def verify_words(body: str, words: "list[dict]") -> "list[str]":
    """Return target words NOT found in the body (derived forms count)."""
    found: set = set()
    for token in set(lemma.tokens(body)):
        for cand in lemma.candidates(token):
            found.add(cand)
    return [w["word"] for w in words if w["normalized"] not in found]


def _store_reading(conn: sqlite3.Connection, title: str, body: str, level: str,
                   topic: str, questions: list, words: "list[dict]",
                   source: str) -> int:
    tid = db.upsert_text(conn, {
        "kind": "reading",
        "title": title.strip(),
        "date": db.study_day(),
        "level": level,
        "topic": topic,
        "body": body.strip(),
        "source": source,
        "questions": json.dumps(questions, ensure_ascii=False),
        "words_target": json.dumps([w["word"] for w in words], ensure_ascii=False),
    })
    conn.commit()
    return tid


# ── Lectura escrita por una rutina de Claude Code (ADR-016) ──────────────
#
# La rutina corre con el plan de Claude de Eddie, no con la API. No toca la
# base ni el código: pide un `brief` (lo mismo que recibiría el generador
# local: reglas, esquema, palabras, nivel) y entrega su texto a `submit`,
# que valida con las MISMAS reglas y guarda. Si el texto no cumple, lo dice
# y la rutina corrige una vez; nunca se guarda a medias.

ROUTINE_SOURCE = "routine:claude-code"
MIN_WORDS, MAX_WORDS = 250, 450
UNREAD_WINDOW_DAYS = 3


class ReadingExists(Exception):
    """El día ya tiene lectura: duplicar el material del día está prohibido."""


def skip_reason(conn: sqlite3.Connection, today: str,
                kind: str = "reading") -> "str | None":
    """¿Toca escribir una lectura? None si sí; si no, el porqué. UNA regla para
    todos los que la piden (la rutina de Claude Code y el trabajo diario de la
    app): 97 de 102 lecturas estaban sin leer, y lo que nadie lee es cómputo
    gastado."""
    row = conn.execute("SELECT title FROM texts WHERE kind=? AND date=? "
                       "LIMIT 1", (kind, today)).fetchone()
    if row:
        return f"today already has a {kind} ({row['title']})"
    since = (date.fromisoformat(today) - timedelta(days=UNREAD_WINDOW_DAYS)).isoformat()
    row = conn.execute(
        "SELECT title FROM texts WHERE kind=? AND finished_at IS NULL "
        "AND date >= ? ORDER BY id DESC LIMIT 1", (kind, since)).fetchone()
    if row:
        # Sin esto la rutina apilaría una lectura por día aunque no estudie.
        word = "unread" if kind == "reading" else "unfinished"
        return f"an {word} {kind} is still waiting ({row['title']})"
    return None


def brief(conn: sqlite3.Connection) -> dict:
    today = db.study_day()
    level = model.recommend_level(conn)["level"]
    words = pick_target_words(conn)
    random.shuffle(words)
    recent = [r["title"] for r in conn.execute(
        "SELECT title FROM texts WHERE kind='reading' ORDER BY id DESC LIMIT 10")]
    return {
        "date": today,
        "skip": skip_reason(conn, today),
        "level": level,
        "target_words": [w["word"] for w in words],
        "system": SYSTEM,
        "prompt": build_prompt(words, level, 5, "Random", top_error_categories(conn)),
        "schema": SCHEMA,
        "recent_titles": recent,
        "limits": {"min_words": MIN_WORDS, "max_words": MAX_WORDS},
    }


def check_questions(questions: list) -> list:
    """Las preguntas de comprensión bien formadas, o un ValueError que dice
    qué falta. Misma regla para la lectura y para el podcast."""
    if not 3 <= len(questions) <= 5:
        raise ValueError("questions: send 4 (3-5 accepted)")
    for i, q in enumerate(questions):
        opts = q.get("options")
        ok = (isinstance(q.get("question"), str) and q["question"].strip()
              and isinstance(q.get("why"), str) and q["why"].strip()
              and isinstance(opts, list) and len(opts) == 3
              and all(isinstance(o, str) and o.strip() for o in opts)
              and isinstance(q.get("answer_index"), int) and 0 <= q["answer_index"] <= 2)
        if not ok:
            raise ValueError(f"question {i + 1}: needs question, why, exactly 3 "
                             f"options and answer_index 0-2")
    return questions


def submit_reading(conn: sqlite3.Connection, data: dict) -> dict:
    today = db.study_day()
    if conn.execute("SELECT 1 FROM texts WHERE kind='reading' AND date=? LIMIT 1",
                    (today,)).fetchone():
        raise ReadingExists("today already has a reading")
    title = (data.get("title") or "").strip()
    body = (data.get("body") or "").strip()
    level = data.get("level")
    if not title or not body:
        raise ValueError("title and body are required")
    if level not in LEVELS:
        raise ValueError(f"level must be one of {LEVELS}")
    if "**" in body or any(l.lstrip().startswith(("#", "- ", "* ")) for l in body.splitlines()):
        raise ValueError("body must be plain prose: no markdown, headings or lists")
    n = len(lemma.tokens(body))
    if not MIN_WORDS <= n <= MAX_WORDS:
        raise ValueError(f"body has {n} words; it must have {MIN_WORDS}-{MAX_WORDS}")
    questions = check_questions(data.get("questions") or [])
    words = []
    for w in data.get("words_target") or []:
        row = conn.execute("SELECT word, normalized FROM words WHERE normalized=?",
                           (db.normalize(w),)).fetchone()
        if row is None:
            raise ValueError(f"unknown target word: {w}")
        words.append(dict(row))
    if not words:
        raise ValueError("words_target is required (use the brief's target_words)")
    missing = verify_words(body, words)
    if missing:
        raise ValueError(f"target words missing from the body: {', '.join(missing)}")
    tid = _store_reading(conn, title, body, level, "Random", questions, words,
                         ROUTINE_SOURCE)
    return {"id": tid, "title": title, "word_count": n, "level": level,
            "source": ROUTINE_SOURCE}


def generate_reading(conn: sqlite3.Connection, level: "str | None", minutes: int,
                     topic: str) -> dict:
    """Generate, verify, store. Returns {id, title, missing_words, provider}.
    With level=None, the Personal English Model decides (Vision P3/P4)."""
    if level is None:
        level = model.recommend_level(conn)["level"]
    if level not in LEVELS:
        raise ValueError(f"level must be one of {LEVELS}")
    if topic not in TOPICS:
        raise ValueError(f"topic must be one of {TOPICS}")

    provider = ai.get_provider("reading")
    words = pick_target_words(conn)
    if not words:
        raise ValueError("no vocabulary to build a reading from")
    random.shuffle(words)

    prompt = build_prompt(words, level, minutes, topic,
                          top_error_categories(conn))
    result = provider.generate_json(SYSTEM, prompt, SCHEMA, max_tokens=8192)

    missing = verify_words(result["body"], words)
    tid = _store_reading(conn, result["title"], result["body"], level, topic,
                         result["questions"], words, f"generated:{provider.name}")
    return {
        "id": tid,
        "title": result["title"].strip(),
        "word_count": len(lemma.tokens(result["body"])),
        "target_words": [w["word"] for w in words],
        "missing_words": missing,
        "provider": provider.name,
        "model": provider.model,
    }
