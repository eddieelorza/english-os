"""La sesión del día: un botón y una lista corta de bloques (ADR-018, MVP 3).

Determinista y sin estado propio: cada bloque se da por hecho mirando lo que
ya está en la base (sentadas, Recall, lecturas). Recargar o volver mañana no
pierde nada, y no hay un "flujo" que pueda quedarse a medias en memoria.
"""

from __future__ import annotations

import sqlite3

from app import db, gate, pause, recall, session, srs, writing


def _review(conn: sqlite3.Connection) -> "dict | None":
    q = srs.queue(conn, new_per_day=gate.allowed(conn)["new_per_day"])
    start = db.study_day_start()
    open_ = session.active(conn)
    prog = session.progress(conn, open_) if open_ else None
    ended = conn.execute(
        "SELECT 1 FROM study_sessions WHERE started_at >= ? AND ended_at IS NOT NULL",
        (start,)).fetchone() is not None
    left = q["due"] + q["new_available"] + q["learning_now"]
    if not left and not q["reviewed_today"]:
        return None                      # nada que repasar hoy: no hay bloque
    done = (not left or (prog is not None and prog["done"] >= prog["planned"])
            or (prog is None and ended))
    return {"key": "review", "title": "Review", "route": "/review", "done": done,
            "detail": (f"{q['reviewed_today']} reviewed today" if done
                       else f"{q['due']} due · {q['new_available']} new")}


def _recall(conn: sqlite3.Connection) -> "dict | None":
    nxt = recall.next_item(conn)
    left = nxt["due"] + nxt["new_left"] if nxt["item"] else 0
    answered = conn.execute(
        "SELECT COUNT(*) FROM recall_log WHERE reviewed_at >= ?",
        (db.study_day_start(),)).fetchone()[0]
    if not left and not answered:
        return None
    # Página propia: en /review una card todavía en sus pasos de aprendizaje
    # taparía la sección Recall y «Continue — Recall» llevaría a otra cosa.
    return {"key": "recall", "title": "Recall", "route": "/recall", "done": not left,
            "detail": f"{left} to recall" if left else f"{answered} recalled today"}


def _write(conn: sqlite3.Connection) -> "dict | None":
    wrote = conn.execute(
        "SELECT COUNT(*) FROM texts WHERE kind='writing' AND created_at >= ?",
        (db.study_day_start(),)).fetchone()[0]
    if wrote:
        return {"key": "write", "title": "Write", "route": "/write", "done": True,
                "detail": "Written today"}
    words = writing.micro_words(conn)
    if not words:
        return None
    return {"key": "write", "title": "Write", "route": "/write", "done": False,
            "detail": "Two sentences: " + ", ".join(w["word"] for w in words)}


def _reading(conn: sqlite3.Connection) -> "dict | None":
    start = db.study_day_start()
    read = conn.execute(
        "SELECT id, title FROM texts WHERE kind='reading' AND finished_at >= ? "
        "ORDER BY finished_at DESC LIMIT 1", (start,)).fetchone()
    if read:
        return {"key": "reading", "title": "Read", "route": f"/reading/{read['id']}",
                "done": True, "detail": read["title"]}
    # La más antigua sin terminar, no una nueva: primero se consume lo que hay.
    row = conn.execute(
        "SELECT id, title FROM texts WHERE kind='reading' AND body IS NOT NULL "
        "AND finished_at IS NULL ORDER BY created_at, id LIMIT 1").fetchone()
    if row is None:
        return None
    return {"key": "reading", "title": "Read", "route": f"/reading/{row['id']}",
            "done": False, "detail": row["title"]}


def plan(conn: sqlite3.Connection) -> dict:
    """Bloques en orden y el siguiente por hacer (None = sesión terminada)."""
    if pause.is_paused(conn):
        return {"paused": True, "blocks": [], "next": None}
    # Write va justo después de Recall: usa las palabras recién recuperadas
    # mientras siguen frescas; la lectura, más larga, cierra.
    blocks = [b for b in (_review(conn), _recall(conn), _write(conn), _reading(conn)) if b]
    nxt = next((b for b in blocks if not b["done"]), None)
    return {"paused": False, "blocks": blocks, "next": nxt}
