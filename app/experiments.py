"""Experimentos por ítem con un solo sujeto (ADR-018, MVP 5).

E1 — ¿Reparar la glosa mejora el recuerdo? Palabras en estudio con la glosa
     desalineada: «repair» entra a la cola de propuestas, «control» conserva
     su glosa mientras dure el experimento.
E2 — ¿Recordar escribiendo supera a auto-calificarse? Al introducir una
     palabra en Recall: «recall» recibe su tarjeta productiva, «control» se
     queda sólo con Review.

Las dos se miden con una prueba sorpresa a 7 y 30 días de la asignación: la
oración del ejemplo con hueco, sin glosa (no favorece a ningún grupo de E1),
sin tocar FSRS y sin mostrar la respuesta (no contamina la de 30 días).

La asignación alterna entre grupos (empate al azar): con ~30 palabras por
experimento, una moneda podría dejar 20 contra 10.

ponytail: sin fecha de cierre; se añade un interruptor cuando haya datos
suficientes para decidir.
"""

from __future__ import annotations

import random
import sqlite3
from datetime import datetime, timedelta

from app import db

ARMS = {"E1": ("repair", "control"), "E2": ("recall", "control")}
PROBE_DAYS = (7, 30)
QUIZ_PER_DAY = 10


def arm(conn: sqlite3.Connection, experiment: str, word_id: int) -> str:
    """El grupo de la palabra; lo asigna (y programa sus pruebas) la primera vez."""
    row = conn.execute(
        "SELECT arm FROM experiment_arms WHERE experiment=? AND word_id=?",
        (experiment, word_id)).fetchone()
    if row:
        return row["arm"]
    word = conn.execute("SELECT word, example_en FROM words WHERE id=?", (word_id,)).fetchone()
    if word is None or _cue(word) is None:
        # Sin hueco no hay prueba diferida: no se mide, así que no se le
        # niega nada. Sigue el camino normal, fuera del experimento.
        return ARMS[experiment][0]
    counts = dict(conn.execute(
        "SELECT arm, COUNT(*) FROM experiment_arms WHERE experiment=? GROUP BY arm",
        (experiment,)).fetchall())
    a, b = ARMS[experiment]
    na, nb = counts.get(a, 0), counts.get(b, 0)
    chosen = a if na < nb else b if nb < na else random.choice((a, b))
    now = db.now_iso()
    conn.execute(
        "INSERT INTO experiment_arms (experiment, word_id, arm, assigned_at) "
        "VALUES (?, ?, ?, ?)", (experiment, word_id, chosen, now))
    for days in PROBE_DAYS:
        due = (datetime.fromisoformat(now) + timedelta(days=days)).isoformat(timespec="seconds")
        conn.execute(
            "INSERT INTO probes (experiment, word_id, arm, after_days, due_at) "
            "VALUES (?, ?, ?, ?, ?)", (experiment, word_id, chosen, days, due))
    return chosen


# ── La prueba sorpresa ───────────────────────────────────────────────────

def _cue(word) -> "dict | None":
    from app import recall
    matches = recall._matches(word["word"], word["example_en"] or "")
    if not matches:
        return None
    expected = matches[0].group()
    sentence = word["example_en"]
    for m in reversed(matches):
        sentence = sentence[:m.start()] + "____" + sentence[m.end():]
    return {"sentence": sentence, "expected": expected,
            "hint": f"{expected[0].lower()}·{sum(c.isalpha() for c in expected)}"}


def _answered_today(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM probes WHERE answered_at >= ?",
                        (db.study_day_start(),)).fetchone()[0]


def quiz(conn: sqlite3.Connection) -> dict:
    """La siguiente prueba vencida, dentro del cupo del día."""
    left = max(0, QUIZ_PER_DAY - _answered_today(conn))
    due = conn.execute(
        "SELECT p.id, w.word, w.example_en FROM probes p JOIN words w ON w.id = p.word_id "
        "WHERE p.answered_at IS NULL AND p.due_at <= ? ORDER BY p.due_at, p.id",
        (db.now_iso(),)).fetchall()
    for p in due if left else []:
        cue = _cue(p)
        if cue is None:          # sin ejemplo utilizable: no se puede medir, se descarta
            conn.execute("UPDATE probes SET answered_at=?, verdict='skipped' WHERE id=?",
                         (db.now_iso(), p["id"]))
            conn.commit()
            continue
        return {"item": {"probe_id": p["id"], "sentence": cue["sentence"], "hint": cue["hint"]},
                "left": min(left, len(due))}
    return {"item": None, "left": 0}


def answer(conn: sqlite3.Connection, probe_id: int, given: str) -> dict:
    from app import recall
    row = conn.execute(
        "SELECT p.*, w.word, w.example_en FROM probes p JOIN words w ON w.id = p.word_id "
        "WHERE p.id=?", (probe_id,)).fetchone()
    if row is None:
        raise ValueError("Prueba no encontrada")
    if row["answered_at"]:
        raise ValueError("Esa prueba ya se respondió")
    cue = _cue(row)
    if cue is None:
        raise ValueError("La palabra ya no tiene ejemplo")
    verdict, _ = recall.grade(cue["expected"], given)
    conn.execute(
        "UPDATE probes SET answered_at=?, expected=?, answer=?, verdict=? WHERE id=?",
        (db.now_iso(), cue["expected"], given.strip()[:80], verdict, probe_id))
    conn.commit()
    return {"saved": True, **quiz(conn)}


# ── Lo que va saliendo ───────────────────────────────────────────────────

def summary(conn: sqlite3.Connection) -> dict:
    out = {}
    for experiment, arms in ARMS.items():
        groups = {}
        for a in arms:
            n = conn.execute(
                "SELECT COUNT(*) FROM experiment_arms WHERE experiment=? AND arm=?",
                (experiment, a)).fetchone()[0]
            probes = {}
            for days in PROBE_DAYS:
                done, right = conn.execute(
                    "SELECT COUNT(*), COALESCE(SUM(verdict IN ('correct','close')), 0) "
                    "FROM probes WHERE experiment=? AND arm=? AND after_days=? "
                    "AND verdict IN ('correct','close','wrong')",
                    (experiment, a, days)).fetchone()
                probes[str(days)] = {"answered": done, "right": right}
            groups[a] = {"words": n, "probes": probes}
        if experiment == "E1":
            for a in arms:
                groups[a]["lapses_after"] = conn.execute(
                    "SELECT COUNT(*) FROM review_history h JOIN experiment_arms e "
                    "ON e.word_id = h.word_id AND e.experiment='E1' AND e.arm=? "
                    "WHERE h.rating = 1 AND h.reviewed_at >= e.assigned_at", (a,)).fetchone()[0]
        out[experiment] = groups
    return out
