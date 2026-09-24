"""Sentence explanations (ADR-007 M10).

Tapping a word gives a dictionary entry; tapping a *sentence* answers the
question a learner actually has mid-paragraph: "I know all these words —
why is it built like that?"

So an explanation has four parts: what it means in context, the grammar it
uses and why, a natural Spanish equivalent (not a word-for-word gloss), and
the trap a Spanish speaker falls into with that structure.

Cached by sentence hash — the same sentence costs one generation ever, and
re-reading a text is instant.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from app import ai, db  # noqa: E402

MAX_SENTENCE_CHARS = 400

SCHEMA = {
    "type": "object",
    "properties": {
        "meaning": {"type": "string"},
        "grammar": {"type": "string"},
        "spanish": {"type": "string"},
        "watch_out": {"type": "string"},
    },
    "required": ["meaning", "grammar", "spanish", "watch_out"],
    "additionalProperties": False,
}

SYSTEM = """You explain ONE English sentence to Eddie — a Spanish-speaking \
frontend engineer at Clip (B1→C1) reading inside "English OS". He understands the \
individual words; what he needs is why the sentence is built the way it is.

Answer in Spanish, four short parts, no preamble:
- meaning: what the sentence actually says in its context, in one or two \
sentences. Plain language, not a translation.
- grammar: name the structure (tense, voice, conditional, phrasal verb, \
whatever carries the weight) and explain in ONE sentence why it is used here \
instead of an alternative.
- spanish: how a Mexican would naturally say the same thing. A natural \
equivalent, never a word-for-word gloss.
- watch_out: the mistake a Spanish speaker typically makes with this \
structure, in one sentence. If there is genuinely none, say what to reuse \
from this sentence instead.

Never longer than that."""


def _hash(sentence: str) -> str:
    norm = re.sub(r"\s+", " ", sentence.strip().lower())
    return hashlib.sha256(norm.encode()).hexdigest()[:20]


def explain(conn: sqlite3.Connection, sentence: str,
            context: "str | None" = None) -> dict:
    """Explain a sentence, serving from cache when it has been seen before."""
    sentence = (sentence or "").strip()
    if not sentence:
        raise ValueError("empty sentence")
    if len(sentence) > MAX_SENTENCE_CHARS:
        sentence = sentence[:MAX_SENTENCE_CHARS]

    key = _hash(sentence)
    row = conn.execute("SELECT * FROM explanations WHERE sentence_hash=?",
                       (key,)).fetchone()
    if row is not None:
        return {"sentence": row["sentence"], "meaning": row["meaning"],
                "grammar": row["grammar"], "spanish": row["spanish"],
                "watch_out": row["watch_out"], "cached": True}

    user = (f'Sentence: "{sentence}"'
            + (f'\nIt appears in this text: "{context[:1200]}"' if context else ""))
    result = ai.get_provider("explain").generate_json(SYSTEM, user, SCHEMA, max_tokens=1200)

    conn.execute(
        "INSERT INTO explanations (sentence_hash, sentence, meaning, grammar, "
        "spanish, watch_out, created_at) VALUES (?,?,?,?,?,?,?) "
        "ON CONFLICT(sentence_hash) DO NOTHING",
        (key, sentence, result["meaning"], result["grammar"],
         result["spanish"], result["watch_out"], db.now_iso()))
    conn.commit()
    return {"sentence": sentence, **result, "cached": False}
