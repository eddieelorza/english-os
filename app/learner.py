"""Quién es el alumno según lo que HACE, y cómo va en eso (ADR-015 D8).

El único indicador de éxito del producto era errores por cada 100 palabras
producidas. Pide ≥150 palabras por ventana, y Eddie produjo 250 en 28 días:
el indicador dice "no evidence yet" casi siempre. No es que no avance — es
que el sistema mide lo que él hace poco (writing, speaking) e ignora lo que
hace mucho (repasar, leer, shadowing, practice). De ahí "no mide mi objetivo".

Aquí no se inventa ningún nivel. Se juntan las señales que sus actividades
reales ya dejan en SQLite, cada una con su muestra; por debajo de la muestra
mínima el valor es None y la pantalla debe decir "not enough yet".

`context()` es la frase que los generadores pueden anteponer a su prompt. La
meta sólo aparece si él la declaró (ajuste `learner_goal`): una meta supuesta
es peor que ninguna.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from app import db  # noqa: E402

WINDOW_DAYS = 28
MIN_SAMPLE = 5            # por debajo, un porcentaje es ruido


def _since(days: int = WINDOW_DAYS) -> str:
    return (datetime.now() - timedelta(days=days)).isoformat()


def _rate(ok: "float | None", n: int) -> "float | None":
    return round(ok, 2) if (n >= MIN_SAMPLE and ok is not None) else None


def activity(conn: sqlite3.Connection, days: int = WINDOW_DAYS) -> dict:
    """Cuántas veces hizo cada cosa en la ventana. Sólo cuentas."""
    since = _since(days)

    def one(sql: str) -> int:
        return conn.execute(sql, (since,)).fetchone()[0] or 0

    from app import load
    return {
        "window_days": days,
        "review_days": load.rhythm(conn)["study_days"],
        "readings_finished": one("SELECT COUNT(*) FROM texts WHERE kind='reading' "
                                 "AND finished_at >= ?"),
        "podcasts_finished": one("SELECT COUNT(*) FROM texts WHERE kind='podcast' "
                                 "AND finished_at >= ?"),
        "practice_done": one("SELECT COUNT(*) FROM activities WHERE kind != 'tip' "
                             "AND completed_at >= ?"),
        "shadowing": one("SELECT COUNT(*) FROM shadow_sessions WHERE created_at >= ?"),
        "conversations": one("SELECT COUNT(*) FROM conversations WHERE started_at >= ?"),
        "writings": one("SELECT COUNT(*) FROM texts WHERE kind='writing' "
                        "AND created_at >= ?"),
        "speakings": one("SELECT COUNT(*) FROM texts WHERE kind='speaking' "
                         "AND created_at >= ?"),
        "words_produced": one("SELECT COALESCE(SUM(words_produced), 0) FROM texts "
                              "WHERE kind IN ('writing','speaking') AND created_at >= ?"),
    }


def signals(conn: sqlite3.Connection, days: int = WINDOW_DAYS) -> "list[dict]":
    """Lo medible de lo que sí hace. Cada señal: valor (o None), muestra, y
    qué mide — para que ninguna se lea como "nivel de inglés"."""
    from app import load
    since = _since(days)
    out = []

    row = conn.execute(
        "SELECT COUNT(*) AS n, AVG(1.0 * quiz_score / quiz_total) AS ok FROM texts "
        "WHERE kind='reading' AND quiz_total > 0 AND finished_at >= ?", (since,)).fetchone()
    out.append({"key": "comprehension", "label": "Reading comprehension",
                "value": _rate(row["ok"], row["n"]), "sample": row["n"],
                "unit": "quizzes", "measures": "questions right after a reading"})

    row = conn.execute(
        "SELECT COUNT(*) AS n, AVG(1.0 * score / total) AS ok FROM activities "
        "WHERE kind != 'tip' AND total > 0 AND completed_at >= ?", (since,)).fetchone()
    out.append({"key": "practice", "label": "Practice accuracy",
                "value": _rate(row["ok"], row["n"]), "sample": row["n"],
                "unit": "drills", "measures": "grammar and vocabulary drills"})

    row = conn.execute(
        "SELECT COUNT(*) AS n, AVG(CASE WHEN rating > 1 THEN 1.0 ELSE 0 END) AS ok "
        "FROM review_history WHERE source='fsrs' AND review_kind='review' "
        "AND stability_before >= ? AND reviewed_at >= ?",
        (load.CONSOLIDATED_DAYS, since)).fetchone()
    out.append({"key": "retention", "label": "Settled words still remembered",
                "value": _rate(row["ok"], row["n"]), "sample": row["n"],
                "unit": "reviews", "measures": "recall of words past one week"})

    g = load.group(conn)
    out.append({"key": "settled", "label": "Words settled",
                "value": g["settled"], "sample": g["settled"] + g["came_in"],
                "unit": f"in {g['window_days']} days",
                "measures": "words that crossed one week of stability and stayed"})

    a = activity(conn, days)
    out.append({"key": "production", "label": "Words produced",
                "value": a["words_produced"], "sample": a["writings"] + a["speakings"],
                "unit": "texts",
                "measures": "writing + speaking; errors/100 words needs 150+"})
    return out


def goal(conn: sqlite3.Connection) -> "str | None":
    row = conn.execute("SELECT value FROM settings WHERE key='learner_goal'").fetchone()
    return (row["value"].strip() or None) if row else None


def context(conn: sqlite3.Connection) -> str:
    """Dos o tres frases sobre él, sólo con lo que consta."""
    a = activity(conn)
    does = [(a["review_days"], "reviews vocabulary"), (a["readings_finished"], "reads"),
            (a["shadowing"] + a["podcasts_finished"], "shadows and listens to podcasts"),
            (a["practice_done"], "does practice drills")]
    rarely = [(a["writings"], "writing"), (a["speakings"] + a["conversations"], "speaking")]
    often = [name for n, name in sorted(does, reverse=True) if n >= 2]
    seldom = [name for n, name in rarely if n <= 2]
    parts = []
    if often:
        parts.append(f"In the last {a['window_days']} days he mostly {', '.join(often)}.")
    if seldom:
        parts.append(f"He rarely does free {' or '.join(seldom)} — he is not confident "
                     f"producing yet, so keep any production step short and safe.")
    declared = goal(conn)
    if declared:
        parts.append(f"His stated goal: {declared}")
    return " ".join(parts)


def profile(conn: sqlite3.Connection) -> dict:
    return {"goal": goal(conn), "activity": activity(conn),
            "signals": signals(conn), "context": context(conn),
            "min_sample": MIN_SAMPLE}
