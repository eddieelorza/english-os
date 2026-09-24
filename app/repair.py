"""Reparar el scheduling que falsificó el bucle de learn-ahead (ADR-009 D2 rev.3).

Entre el 2026-08-21 y el 2026-08-24, con la cola vacía, la app volvía a
servir una card **segundos** después de contestarla. FSRS puntúa tiempo
transcurrido: acertar al instante apenas suma y fallar al instante hunde la
estabilidad, así que esas respuestas no midieron memoria — midieron el bug.

Qué hace: recalcula la card replicando el historial **sin** esas respuestas.
Qué NO hace: borrar historial. Esas respuestas ocurrieron y el registro es
cierto; lo que estaba mal era la lectura que el scheduler hacía de ellas.
Dejarlas permite volver a ejecutar esto y auditar qué se descartó.

Alcance deliberadamente estrecho: sólo respuestas `source='fsrs'`. Anki
repetía cards a los pocos segundos en sus pasos de aprendizaje y eso era su
funcionamiento normal, no un fallo. Un primer prototipo sin esta distinción
"reparaba" 42 palabras reescribiendo años de historial sano.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from fsrs import Card, State  # noqa: E402
from app import db, srs  # noqa: E402

# El paso más corto del mazo. Por debajo de esto no hay repaso que valga.
MIN_GAP_SECONDS = 60.0


def _rows(conn: sqlite3.Connection, word_id: int) -> list:
    return conn.execute(
        "SELECT id, reviewed_at, rating, source FROM review_history "
        "WHERE word_id=? AND rating BETWEEN 1 AND 4 ORDER BY reviewed_at, id",
        (word_id,)).fetchall()


def split(rows: list, min_gap: float = MIN_GAP_SECONDS) -> "tuple[list, list]":
    """Separa el historial en (creíble, descartado).

    Se conserva la PRIMERA respuesta de cada ráfaga: es la única que llegó
    tras una espera real. Las siguientes se miden contra la última conservada,
    no contra la inmediatamente anterior, para que una ráfaga de seis no se
    cuele en pares.
    """
    kept, dropped, last = [], [], None
    for r in rows:
        t = datetime.fromisoformat(r["reviewed_at"])
        if (r["source"] == "fsrs" and last is not None
                and (t - last).total_seconds() < min_gap):
            dropped.append(r)
            continue
        kept.append(r)
        last = t
    return kept, dropped


def _replay(conn: sqlite3.Connection, kept: list,
            card_id: "int | None" = None) -> "tuple[Card, int]":
    """Reconstruye la card y cuenta los lapses que el replay implica.

    Se conserva el `card_id` original: `Card()` genera uno nuevo cada vez, y
    sin esto reparar dos veces escribía un JSON distinto con el mismo
    scheduling — idempotente de hecho pero no de forma, que es justo lo que
    hace dudar de si una reparación se aplicó dos veces.
    """
    scheduler = srs._scheduler(conn)
    card, lapses = Card(), 0
    if card_id is not None:
        card.card_id = card_id
    for r in kept:
        was_review = card.state == State.Review
        card, _ = scheduler.review_card(
            card, srs.RATINGS[r["rating"]], srs._utc(r["reviewed_at"]))
        if was_review and r["rating"] == 1:
            lapses += 1
    return card, lapses


def plan(conn: sqlite3.Connection, min_gap: float = MIN_GAP_SECONDS) -> list[dict]:
    """Qué cambiaría, sin tocar nada."""
    out = []
    words = conn.execute(
        "SELECT DISTINCT w.id, w.word FROM words w "
        "JOIN review_history r ON r.word_id=w.id "
        "WHERE r.source='fsrs' ORDER BY w.word").fetchall()
    for w in words:
        rows = _rows(conn, w["id"])
        kept, dropped = split(rows, min_gap)
        if not dropped:
            continue
        card, lapses = _replay(conn, kept)
        before = conn.execute(
            "SELECT stability, difficulty, interval_days, lapses, card_state, "
            "       fsrs_due FROM words WHERE id=?", (w["id"],)).fetchone()
        out.append({
            "word_id": w["id"], "word": w["word"],
            "dropped": len(dropped), "kept": len(kept),
            "before": {"stability": before["stability"],
                       "difficulty": before["difficulty"],
                       "interval_days": before["interval_days"],
                       "lapses": before["lapses"],
                       "state": before["card_state"],
                       "due": before["fsrs_due"]},
            "after": {"stability": card.stability,
                      "difficulty": card.difficulty,
                      "interval_days": max(0.0, round(
                          (card.due - srs._utc(kept[-1]["reviewed_at"])
                           ).total_seconds() / 86400, 4)),
                      "lapses": lapses,
                      "state": srs.STATE_NAMES.get(int(card.state)),
                      "due": card.due.isoformat()},
        })
    return out


def apply(conn: sqlite3.Connection, min_gap: float = MIN_GAP_SECONDS,
          words: "list[str] | None" = None) -> dict:
    """Aplica el replay. Idempotente: correrlo dos veces da lo mismo, porque
    la entrada (el historial) no cambia."""
    done = []
    for item in plan(conn, min_gap):
        if words is not None and item["word"] not in words:
            continue
        rows = _rows(conn, item["word_id"])
        kept, _ = split(rows, min_gap)
        existing = conn.execute(
            "SELECT fsrs_card FROM words WHERE id=?", (item["word_id"],)).fetchone()[0]
        card_id = json.loads(existing).get("card_id") if existing else None
        card, lapses = _replay(conn, kept, card_id)
        srs._save_card(conn, item["word_id"], card)
        interval = int(item["after"]["interval_days"])
        # `lapses` se recalcula porque lo deriva el scheduler; `review_count`
        # NO: cuenta lo que Eddie hizo de verdad, y eso no lo cambia un bug.
        status = (db.derive_status(2, interval, lapses)
                  if card.state == State.Review else "LEARNING")
        conn.execute(
            "UPDATE words SET status=?, lapses=?, interval_days=?, updated_at=? "
            "WHERE id=?", (status, lapses, interval, db.now_iso(), item["word_id"]))
        done.append(item["word"])
    conn.commit()
    return {"repaired": done, "count": len(done)}


if __name__ == "__main__":
    conn = db.connect()
    items = plan(conn)
    if not items:
        print("nada que reparar")
        raise SystemExit(0)
    print(f"{'palabra':12} {'stab':>8} {'dific':>6} {'iv':>5}  →  "
          f"{'stab':>8} {'dific':>6} {'iv':>5}   desc")
    for i in items:
        b, a = i["before"], i["after"]
        print(f"{i['word']:12} {b['stability']:8.3f} {b['difficulty']:6.2f} "
              f"{b['interval_days']:4}d  →  {a['stability']:8.3f} "
              f"{a['difficulty']:6.2f} {a['interval_days']:5.1f}d   {i['dropped']}")
    if "--apply" in sys.argv:
        print(apply(conn))
    else:
        print("\n(sólo simulación — añade --apply para escribir)")
