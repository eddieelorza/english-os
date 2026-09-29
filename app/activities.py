"""Interactive practice sets (ADR-007 D5, M9).

Ports the philosophy proven in `docs/routine-prompt.md`: **almost everything is
multiple choice**, because heavy typing makes Eddie skip the session. Three
kinds per day:

  grammar_quiz      — 6 MC questions on the day's tense focus + his top errors
  vocabulary_check  — 4 gap-fills using the words he is learning, cut from the
                      deck's OWN example sentences (no AI); the model writes
                      them only when too few words have a usable example
  listening         — the deck's own MP3 plays, he picks the word he heard
                      (generated deterministically from the DB — no AI, no
                      latency, and it only exists because M8 imported audio)

Wrong answers feed the SAME `errors` table as writing and speaking
(`source='Activity'`), so a missed quiz item shapes tomorrow's material.
"""

from __future__ import annotations

import json
import random
import re
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from app import ai, db, model  # noqa: E402

KINDS = ("grammar_quiz", "vocabulary_check", "listening")
LISTENING_QUESTIONS = 5
CLOZE_QUESTIONS = 4
CLOZE_MIN = 3          # con menos ejemplos utilizables, escribe el modelo
CLOZE_POOL = 16

# Rotating focus, same list the legacy pipeline used.
TENSES = ("Present Simple", "Past Simple", "Present Perfect",
          "Present Continuous", "Future (will / going to)",
          "Conditionals", "Modals")

QUIZ_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                    "answer_index": {"type": "integer", "enum": [0, 1, 2]},
                    "why": {"type": "string"},
                    "category": {"type": "string"},
                },
                "required": ["prompt", "options", "answer_index", "why", "category"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["questions"],
    "additionalProperties": False,
}

QUIZ_SYSTEM = """You write interactive practice for "English OS", a personal \
app for Eddie — a Spanish-speaking frontend engineer at Clip (a fintech in Mexico City) who cares about product, B1→C1.

Non-negotiable format: every question is MULTIPLE CHOICE with exactly 3 \
options and one correct answer. No free writing. Questions are short enough \
to answer on a phone.

Question styles to mix: pick the correct form, fill the gap, and find the \
error (show a sentence with a mistake a Spanish speaker would make, ask which \
correction fixes it).

LANGUAGE RULE — this matters: every "prompt" and every option is in ENGLISH. \
He is practising English, so the material he reads must be English. Only the \
"why" is written in Spanish, because that is the explanation.

Each "why" teaches in ONE sentence explaining the rule — not just restating \
the answer. Each "category" is one of: Artículos, Preposiciones, \
Concordancia, Tiempos verbales, Colocación, Registro, Vocabulario, \
Orden de palabras."""


def tense_focus(day: "str | None" = None) -> str:
    """Deterministic rotation by weekday — same idea as the legacy script."""
    from datetime import date
    d = date.fromisoformat(day) if day else date.today()
    return TENSES[d.weekday() % len(TENSES)]


# ── Generators ───────────────────────────────────────────────────────────

OPTION_PREFIX = re.compile(r"^\s*[a-cA-C1-3]\s*[).:-]\s+")


def _clean_option(text: str) -> str:
    """Models like to prefix options with "a) " — the UI already draws the
    letter, so a stored prefix renders as "A a) …"."""
    return OPTION_PREFIX.sub("", text or "").strip()


def _ask_quiz(prompt: str, want: int, max_tokens: int) -> "list[dict]":
    """Local models occasionally answer with an empty question list. Silently
    dropping the activity would leave a hole in the day, so ask twice before
    giving up, and keep only well-formed 3-option questions."""
    provider = ai.get_provider("activities")
    for _ in range(2):
        result = provider.generate_json(QUIZ_SYSTEM, prompt, QUIZ_SCHEMA,
                                        max_tokens=max_tokens)
        questions = clean_questions(result.get("questions", []), want)
        if questions:
            return questions
    return []


def clean_questions(raw: "list[dict]", want: int) -> "list[dict]":
    """Las preguntas bien formadas, sin los prefijos "a) ". La usan el modelo
    local y la rutina de Claude Code: una sola definición de "esto sirve"."""
    questions = []
    for q in raw:
        if len(q.get("options", [])) != 3 or not 0 <= q.get("answer_index", -1) < 3:
            continue
        q["options"] = [_clean_option(o) for o in q["options"]]
        q["prompt"] = _clean_option(q.get("prompt", ""))
        if not q["prompt"] or not str(q.get("why", "")).strip():
            continue
        questions.append(q)
    return questions[:want]


def grammar_prompt(conn: sqlite3.Connection) -> dict:
    """El encargo del quiz de gramática de hoy. Lo usan el generador local y
    el `brief` de la rutina, para que pidan exactamente lo mismo."""
    focus = tense_focus()
    errs = model.errors(conn)["top_categories"]
    words = [w["word"] for w in model.learning_words(conn, 8)]
    return {
        "title": f"Grammar — {focus}",
        "focus": focus,
        "target_words": words,
        "error_categories": errs,
        "prompt": (
            f"Write 6 multiple-choice questions.\n"
            f"Grammar focus: {focus}.\n"
            + (f"Target his recurring errors: {', '.join(errs)}.\n" if errs else "")
            + f"Where natural, use these words he is learning: {', '.join(words)}."),
    }


def _grammar_quiz(conn: sqlite3.Connection) -> dict:
    spec = grammar_prompt(conn)
    return {"kind": "grammar_quiz", "title": spec["title"],
            "questions": _ask_quiz(spec["prompt"], 6, 4096)}


# Qué clase de palabra cabe en el hueco lo dice la palabra que lo precede: tras
# un artículo va un sustantivo; tras "to", un verbo; tras "was/very", un
# adjetivo. No hay categoría gramatical en la base ni etiquetador en el
# entorno, así que se usa esa pista y nada más.
_DET = {"the", "a", "an", "my", "your", "his", "her", "its", "our", "their",
        "this", "that", "these", "those", "some", "any"}
_BE = {"was", "is", "are", "were", "be", "been", "am", "very", "so", "too",
       "feel", "felt", "look", "looked", "seems", "seemed", "really", "quite"}


def _context_class(sentence: str, start: int) -> "str | None":
    prev = re.findall(r"[A-Za-z’']+", sentence[:start])
    p = prev[-1].lower() if prev else ""
    return "det" if p in _DET else "to" if p == "to" else "be" if p in _BE else None


def _cloze(conn: sqlite3.Connection, n: int = CLOZE_QUESTIONS) -> "list[dict]":
    """Huecos hechos con las oraciones de ejemplo del mazo — sin modelo.

    Las palabras salen de `model.learning_words`, o sea primero las que más
    falla (atascadas, las que vuelven): justo las que necesitan un contexto.
    Sólo sirven las oraciones donde la palabra aparece TAL CUAL, una vez: con
    una forma derivada ("forged") la opción base ("forge") delataría o
    desencajaría, y la respuesta correcta no sería una opción honesta.

    Los distractores son otras palabras que estudia, preferidas entre las que
    en SU oración van tras el mismo tipo de palabra (`_context_class`): así
    "I looked at the ___" no ofrece un adjetivo que se descarta sin pensar.
    Cuando no hay suficientes, se completa con cualquiera.
    """
    pool = model.learning_words(conn, CLOZE_POOL)
    if len(pool) < 3:
        return []
    rows = {r["normalized"]: r for r in conn.execute(
        f"SELECT normalized, word, meaning_es, example_en FROM words WHERE "
        f"normalized IN ({','.join('?' * len(pool))})",
        [w["normalized"] for w in pool])}
    usable = []
    for w in pool:
        row = rows.get(w["normalized"])
        sentence = (row["example_en"] or "").strip() if row else ""
        if not sentence or " " in row["word"] or not 4 <= len(sentence.split()) <= 30:
            continue
        hits = list(re.finditer(rf"(?<![\w'’-]){re.escape(row['word'])}(?![\w'’-])",
                                sentence, re.IGNORECASE))
        if len(hits) == 1:
            usable.append({"row": row, "sentence": sentence, "hit": hits[0],
                           "ctx": _context_class(sentence, hits[0].start())})
    ctx_of = {u["row"]["normalized"]: u["ctx"] for u in usable}
    questions = []
    for u in usable:
        row, sentence, hit = u["row"], u["sentence"], u["hit"]
        surface = hit.group(0)
        cap = surface[:1].isupper()      # al inicio de la oración: todas capitalizadas
        others = [p for p in pool if p["normalized"] != row["normalized"]
                  and " " not in p["word"] and p["word"].lower() != surface.lower()]
        if len(others) < 2:
            continue
        same = [p for p in others if u["ctx"] and ctx_of.get(p["normalized"]) == u["ctx"]]
        picks = random.sample(same, min(2, len(same)))
        rest = [p for p in others if p not in picks]
        picks += random.sample(rest, 2 - len(picks))
        options = [surface] + [p["word"].capitalize() if cap else p["word"].lower()
                               for p in picks]
        random.shuffle(options)
        questions.append({
            "prompt": sentence[:hit.start()] + "___" + sentence[hit.end():],
            "options": options,
            "answer_index": options.index(surface),
            "why": (f"“{surface}”"
                    + (f" — {row['meaning_es']}." if row["meaning_es"] else ".")
                    + f" {sentence}"),
            "category": "Vocabulario",
        })
        if len(questions) == n:
            break
    return questions


def _vocabulary_check(conn: sqlite3.Connection) -> dict:
    questions = _cloze(conn)
    if len(questions) >= CLOZE_MIN:
        return {"kind": "vocabulary_check", "title": "Vocabulary in context",
                "questions": questions}
    return _vocabulary_check_ai(conn)


def _vocabulary_check_ai(conn: sqlite3.Connection) -> dict:
    words = [w["word"] for w in model.learning_words(conn, 8)]
    prompt = (
        "Write 4 multiple-choice gap-fill questions. Each shows an ENGLISH "
        "sentence with one blank (use ___ for the blank) and three word "
        "options; only one fits the meaning. Use these words as the correct "
        f"answers: {', '.join(words[:4])}. Distractors should be plausible but "
        "wrong. Category for all four: Vocabulario."
    )
    return {"kind": "vocabulary_check", "title": "Vocabulary in context",
            "questions": _ask_quiz(prompt, 4, 3000)}


def _listening(conn: sqlite3.Connection, n: int = LISTENING_QUESTIONS) -> dict:
    """Deterministic — the deck's audio IS the question. No AI involved."""
    rows = conn.execute(
        "SELECT word, audio_word, meaning_es FROM words "
        "WHERE audio_word IS NOT NULL AND status IN ('LEARNING','FAMILIAR') "
        "ORDER BY COALESCE(last_reviewed_on,'') DESC LIMIT 40").fetchall()
    if len(rows) < 4:
        return {"kind": "listening", "title": "Listening", "questions": []}

    pool = [dict(r) for r in rows]
    random.shuffle(pool)
    questions = []
    for target in pool[:n]:
        others = [p for p in pool if p["word"] != target["word"]]
        distractors = random.sample(others, 2)
        options = [target["word"]] + [d["word"] for d in distractors]
        random.shuffle(options)
        questions.append({
            "prompt": "Which word did you hear?",
            "audio": target["audio_word"],
            "options": options,
            "answer_index": options.index(target["word"]),
            "why": (f"“{target['word']}”"
                    + (f" — {target['meaning_es']}." if target["meaning_es"] else ".")),
            "category": "Vocabulario",
        })
    return {"kind": "listening", "title": "Listening", "questions": questions}


# ── Daily set ────────────────────────────────────────────────────────────

def _row_to_activity(row) -> dict:
    payload = json.loads(row["payload"])
    return {
        "id": row["id"], "date": row["date"], "kind": row["kind"],
        "title": row["title"], "questions": payload["questions"],
        "score": row["score"], "total": row["total"],
        "answers": json.loads(row["answers"]) if row["answers"] else None,
        "completed_at": row["completed_at"],
    }


def today_set(conn: sqlite3.Connection, regenerate: bool = False) -> "list[dict]":
    """Today's activities, generating any that are missing. Idempotent: an
    activity already answered is never regenerated.

    While paused, existing sets are still served but nothing new is built:
    the pause stops the automatic pile-up, not his right to study (ADR-008 D3).
    """
    from app import pause
    today = db.study_day()
    if pause.is_paused(conn):
        return [_row_to_activity(r) for r in conn.execute(
            "SELECT * FROM activities WHERE date=? AND kind!='tip' ORDER BY id",
            (today,))]
    existing = {r["kind"]: r for r in conn.execute(
        "SELECT * FROM activities WHERE date=? ORDER BY id", (today,))}

    builders = {"grammar_quiz": _grammar_quiz,
                "vocabulary_check": _vocabulary_check,
                "listening": _listening}
    out = []
    for kind in KINDS:
        row = existing.get(kind)
        if row is not None and not (regenerate and row["completed_at"] is None):
            out.append(_row_to_activity(row))
            continue
        built = builders[kind](conn)
        if not built["questions"]:
            continue
        out.append(store(conn, kind, built["title"], built["questions"]))
    return out


def store(conn: sqlite3.Connection, kind: str, title: str,
          questions: "list[dict]") -> dict:
    """Guarda la actividad de hoy de ese tipo. Una ya contestada no se pisa."""
    if kind not in KINDS:
        raise ValueError(f"unknown activity kind: {kind}")
    if not questions:
        raise ValueError("questions is empty")
    today = db.study_day()
    row = conn.execute("SELECT * FROM activities WHERE date=? AND kind=?",
                       (today, kind)).fetchone()
    if row is not None and row["completed_at"] is not None:
        raise ValueError(f"today's {kind} is already answered")
    payload = json.dumps({"questions": questions}, ensure_ascii=False)
    if row is not None:
        conn.execute("UPDATE activities SET payload=?, title=?, total=?, "
                     "updated_at=? WHERE id=?",
                     (payload, title, len(questions), db.now_iso(), row["id"]))
        aid = row["id"]
    else:
        # ON CONFLICT: a concurrent request may have inserted this kind
        # while we were generating (a minute on a local model).
        conn.execute(
            "INSERT INTO activities (date, kind, title, payload, total, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(date, kind) DO NOTHING",
            (today, kind, title, payload, len(questions),
             db.now_iso(), db.now_iso()))
        aid = conn.execute("SELECT id FROM activities WHERE date=? AND kind=?",
                           (today, kind)).fetchone()["id"]
    conn.commit()
    return _row_to_activity(conn.execute(
        "SELECT * FROM activities WHERE id=?", (aid,)).fetchone())


def submit(conn: sqlite3.Connection, activity_id: int,
           answers: "list[int]", seconds: int = 0) -> dict:
    """Grade, persist, and send every miss to the shared error loop."""
    row = conn.execute("SELECT * FROM activities WHERE id=?",
                       (activity_id,)).fetchone()
    if row is None:
        raise ValueError(f"activity {activity_id} not found")
    questions = json.loads(row["payload"])["questions"]
    if len(answers) != len(questions):
        raise ValueError("answers do not match the number of questions")

    results, score = [], 0
    for q, given in zip(questions, answers):
        correct = given == q["answer_index"]
        score += 1 if correct else 0
        results.append({"correct": correct, "answer_index": q["answer_index"],
                        "why": q["why"]})
        if not correct:
            _record_miss(conn, q, given)

    conn.execute(
        "UPDATE activities SET answers=?, score=?, total=?, seconds=?, "
        "completed_at=?, updated_at=? WHERE id=?",
        (json.dumps(answers), score, len(questions), seconds,
         db.now_iso(), db.now_iso(), activity_id))
    conn.commit()
    return {"id": activity_id, "score": score, "total": len(questions),
            "results": results}


def _record_miss(conn: sqlite3.Connection, question: dict, given: int) -> None:
    """A wrong answer is an error like any other (same table, dedup by text)."""
    options = question.get("options", [])
    chosen = options[given] if 0 <= given < len(options) else "—"
    right = options[question["answer_index"]] if options else "—"
    original = f"{question['prompt']} → {chosen}"
    today = db.study_day()
    existing = conn.execute(
        "SELECT id, recurrences FROM errors WHERE category=? AND original=?",
        (question["category"], original)).fetchone()
    if existing:
        conn.execute("UPDATE errors SET recurrences=?, date=?, updated_at=? "
                     "WHERE id=?",
                     (existing["recurrences"] + 1, today, db.now_iso(),
                      existing["id"]))
    else:
        conn.execute(
            "INSERT INTO errors (date, category, error, original, correction, "
            "explanation, source, recurrences, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,1,?,?)",
            (today, question["category"], right, original, right,
             question["why"], "Activity", db.now_iso(), db.now_iso()))
