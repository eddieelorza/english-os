"""Material del día escrito por Claude Code, al momento (ADR-016 D4, D5).

El texto lo escribe la sesión de Claude Code que Eddie ya tiene abierta: usa
su plan, no la API, y no enciende Ollama. La app no pierde el control de la
pedagogía — entrega el mismo encargo que recibiría el generador local
(`brief`) y valida lo que vuelve con las MISMAS reglas (`submit`).

    GET  /api/routine/brief/{reading|podcast|practice}
    POST /api/routine/submit/{kind}

`brief` trae `skip`: si el día ya tiene ese material, o hay uno sin terminar
de los últimos 3 días, la respuesta correcta es no escribir nada.

Lo único que sigue costando CPU es el audio del podcast (Kokoro, local), y
por eso corre dentro del candado de la cola: nunca dos inferencias a la vez.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from app import activities, db, generator, jobs, podcast  # noqa: E402

KINDS = ("reading", "podcast", "practice")

PODCAST_MINUTES = 5
MIN_TURNS = 14
PRACTICE_QUESTIONS = 6


class AlreadyExists(Exception):
    """Ese material del día ya existe: duplicarlo está prohibido."""


def _recent_titles(conn: sqlite3.Connection, kind: str) -> "list[str]":
    return [r["title"] for r in conn.execute(
        "SELECT title FROM texts WHERE kind=? ORDER BY id DESC LIMIT 10", (kind,))]


def brief(conn: sqlite3.Connection, kind: str) -> dict:
    if kind == "reading":
        return generator.brief(conn)
    today = db.study_day()
    if kind == "podcast":
        spec = podcast.build_prompt(conn, PODCAST_MINUTES)
        return {
            "date": today,
            "skip": generator.skip_reason(conn, today, "podcast"),
            "level": spec["level"],
            "target_words": [w["word"] for w in spec["words"]],
            "system": podcast.SYSTEM,
            "prompt": spec["prompt"],
            "schema": podcast.SCHEMA,
            "recent_titles": _recent_titles(conn, "podcast"),
            "limits": {"min_turns": MIN_TURNS, "questions": 4},
        }
    if kind == "practice":
        spec = activities.grammar_prompt(conn)
        row = conn.execute("SELECT completed_at FROM activities WHERE date=? "
                           "AND kind='grammar_quiz'", (today,)).fetchone()
        # Misma regla que la lectura (D1): si el día ya tiene quiz, escribir
        # otro es cómputo tirado. `submit` sí lo reemplaza si se lo piden a
        # mano y nadie lo ha contestado.
        skip = None
        if row is not None:
            skip = ("today's grammar quiz is already answered"
                    if row["completed_at"] else "today already has a grammar quiz")
        return {
            "date": today,
            "skip": skip,
            "title": spec["title"],
            "focus": spec["focus"],
            "target_words": spec["target_words"],
            "error_categories": spec["error_categories"],
            "system": activities.QUIZ_SYSTEM,
            "prompt": spec["prompt"],
            "schema": activities.QUIZ_SCHEMA,
            "limits": {"questions": PRACTICE_QUESTIONS, "options": 3},
        }
    raise ValueError(f"kind must be one of {KINDS}")


def submit(conn: sqlite3.Connection, kind: str, data: dict) -> dict:
    if kind == "reading":
        try:
            return generator.submit_reading(conn, data)
        except generator.ReadingExists as exc:
            raise AlreadyExists(str(exc)) from exc
    today = db.study_day()
    if kind == "podcast":
        if conn.execute("SELECT 1 FROM texts WHERE kind='podcast' AND date=? "
                        "LIMIT 1", (today,)).fetchone():
            raise AlreadyExists("today already has a podcast")
        if not (data.get("title") or "").strip():
            raise ValueError("title is required")
        generator.check_questions(data.get("questions") or [])
        turns = [t for t in data.get("turns") or []
                 if t.get("speaker") in ("A", "B") and str(t.get("text", "")).strip()]
        if len(turns) < MIN_TURNS:
            raise ValueError(f"the dialogue has {len(turns)} usable turns "
                             f"(speaker A/B + text); it needs {MIN_TURNS}+")
        spec = podcast.build_prompt(conn, PODCAST_MINUTES,
                                    level=data.get("level"))
        # El audio es la única parte cara y va dentro del candado de la cola:
        # así no se solapa con el worker ni con otra generación.
        with jobs.exclusive():
            ep = podcast.store(conn, data, spec["words"], spec["level"],
                               spec["topic"], source=generator.ROUTINE_SOURCE)
        return {"id": ep["id"], "title": ep["title"], "turns": len(ep["turns"]),
                "audio": ep["audio"], "source": generator.ROUTINE_SOURCE}
    if kind == "practice":
        raw = data.get("questions") or []
        questions = activities.clean_questions(raw, PRACTICE_QUESTIONS)
        if len(questions) < 4:
            raise ValueError(
                f"{len(questions)} of {len(raw)} questions are usable; each "
                "needs a prompt, a why, exactly 3 options and answer_index 0-2")
        title = (data.get("title") or "").strip() or \
            activities.grammar_prompt(conn)["title"]
        act = activities.store(conn, "grammar_quiz", title, questions)
        return {"id": act["id"], "title": act["title"],
                "questions": len(act["questions"]), "source": generator.ROUTINE_SOURCE}
    raise ValueError(f"kind must be one of {KINDS}")
