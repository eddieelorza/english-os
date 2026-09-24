"""The daily grammar tip (ADR-007 M9).

Eddie asked for "consejos de gramática rápida para entender" at the close of
each daily evaluation. This is not a lesson: it is 3-4 lines aimed at the one
error category he is actually repeating, generated from the Personal English
Model and cached once per day (it must not change between the activities
screen and the writing screen — a tip that shifts under you is noise).
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from app import ai, db, model  # noqa: E402

TIP_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string"},
        "rule": {"type": "string"},
        "wrong": {"type": "string"},
        "right": {"type": "string"},
        "remember": {"type": "string"},
    },
    "required": ["category", "rule", "wrong", "right", "remember"],
    "additionalProperties": False,
}

TIP_SYSTEM = """You write ONE micro grammar tip for Eddie (Spanish speaker, \
B1→C1) inside "English OS". He is not studying theory — he wants the rule \
that fixes the mistake he keeps making.

Format, and nothing more:
- rule: the rule in ONE sentence, in Spanish, plain language, no jargon.
- wrong / right: a minimal pair — the Spanish-interference version he would \
write, and the correct English. Short, realistic sentences.
- remember: a one-line hook he can recall mid-sentence while speaking.

Never longer than that. No preamble, no "as we saw", no lists."""


def _recent_examples(conn: sqlite3.Connection, category: str) -> "list[str]":
    return [f"{r['original']} → {r['correction']}" for r in conn.execute(
        "SELECT original, correction FROM errors WHERE category=? "
        "ORDER BY date DESC LIMIT 3", (category,)) if r["original"]]


def grammar_tip(conn: sqlite3.Connection, refresh: bool = False) -> "dict | None":
    """Today's tip, cached in `activities` (kind='tip') so every screen shows
    the same one. Returns None when there is no error data to teach from."""
    today = db.study_day()
    row = conn.execute(
        "SELECT * FROM activities WHERE date=? AND kind='tip'", (today,)).fetchone()
    if row is not None and not refresh:
        return json.loads(row["payload"])

    cats = model.errors(conn)["top_categories"]
    if not cats:
        return None
    category = cats[0]
    examples = _recent_examples(conn, category)
    user = (f"His most repeated error category this fortnight: {category}."
            + (f" Real examples from his own corrections: {'; '.join(examples)}."
               if examples else "")
            + " Write the tip.")
    tip = ai.get_provider("tip").generate_json(TIP_SYSTEM, user, TIP_SCHEMA,
                                          max_tokens=800)
    payload = json.dumps(tip, ensure_ascii=False)
    if row is not None:
        conn.execute("UPDATE activities SET payload=?, updated_at=? WHERE id=?",
                     (payload, db.now_iso(), row["id"]))
    else:
        conn.execute(
            "INSERT INTO activities (date, kind, title, payload, created_at, "
            "updated_at) VALUES (?, 'tip', ?, ?, ?, ?) "
            "ON CONFLICT(date, kind) DO NOTHING",
            (today, f"Grammar tip — {category}", payload,
             db.now_iso(), db.now_iso()))
    conn.commit()
    return tip
