"""Vacation mode (ADR-008 D3) — pausar sin castigo.

Todo SRS tiene el mismo defecto: si la vida se atraviesa, vuelves a un muro de
cartas vencidas y a una racha rota, justo cuando menos ganas tienes. Eso
empuja a abandonar. El Vision (§5) dice lo contrario: el sistema debe
sobrevivir los meses de poca motivación.

Mientras está pausado:
  · la cola de review no vence nada ni introduce palabras nuevas
  · el material diario no se auto-genera (pero sí puedes pedirlo a mano — la
    pausa detiene la acumulación automática, no tu derecho a estudiar)
  · los días pausados son neutrales para la racha: no suman, no rompen

Al reanudar, el rezago **no cae de golpe**: se reparte en una rampa de días,
in-app y también en Anki (vía AnkiConnect `setDueDate`, best-effort).
"""

from __future__ import annotations

import json
import sqlite3
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from math import ceil
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from app import db  # noqa: E402

ANKI_URL = "http://localhost:8765"
RESUME_TARGET_PER_DAY = 40   # cercano a su ritmo real de Anki (35-55/día)
MAX_RAMP_DAYS = 7


def state(conn: sqlite3.Connection) -> dict:
    """La pausa activa, si la hay."""
    row = conn.execute(
        "SELECT * FROM pauses WHERE end_date IS NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return {"paused": False, "since": None, "days": 0, "reason": None}
    days = (date.fromisoformat(db.study_day()) - date.fromisoformat(row["start_date"])).days
    return {"paused": True, "since": row["start_date"], "days": days,
            "reason": row["reason"], "id": row["id"]}


def is_paused(conn: sqlite3.Connection) -> bool:
    return state(conn)["paused"]


def paused_days(conn: sqlite3.Connection) -> "set[str]":
    """Todos los días cubiertos por alguna pausa — la racha los salta."""
    out: "set[str]" = set()
    for row in conn.execute("SELECT start_date, end_date FROM pauses"):
        start = date.fromisoformat(row["start_date"])
        end = date.fromisoformat(row["end_date"] or db.study_day())
        d = start
        while d <= end:
            out.add(d.isoformat())
            d += timedelta(days=1)
    return out


def start(conn: sqlite3.Connection, reason: "str | None" = None) -> dict:
    if is_paused(conn):
        return state(conn)
    conn.execute(
        "INSERT INTO pauses (start_date, reason, created_at) VALUES (?,?,?)",
        (db.study_day(), (reason or "").strip() or None, db.now_iso()))
    conn.commit()
    return state(conn)


# ── Reanudar: repartir el rezago ─────────────────────────────────────────

def _ramp_days(backlog: int) -> int:
    if backlog <= RESUME_TARGET_PER_DAY:
        return 1
    return min(MAX_RAMP_DAYS, ceil(backlog / RESUME_TARGET_PER_DAY))


def _spread_in_app(conn: sqlite3.Connection) -> "tuple[int, int]":
    """Reparte las cartas vencidas en una rampa. Devuelve (cartas, días)."""
    now = datetime.now(timezone.utc)
    overdue = conn.execute(
        "SELECT id FROM words WHERE fsrs_due IS NOT NULL AND fsrs_due <= ? "
        "ORDER BY fsrs_due", (now.isoformat(),)).fetchall()
    if not overdue:
        return 0, 0
    ramp = _ramp_days(len(overdue))
    if ramp <= 1:
        return len(overdue), 1

    per_day = ceil(len(overdue) / ramp)
    for i, row in enumerate(overdue):
        day_offset = i // per_day          # 0 = hoy, 1 = mañana, …
        if day_offset == 0:
            continue                        # los primeros se quedan para hoy
        new_due = now + timedelta(days=day_offset)
        conn.execute("UPDATE words SET fsrs_due=?, updated_at=? WHERE id=?",
                     (new_due.isoformat(), db.now_iso(), row["id"]))
    conn.commit()
    return len(overdue), ramp


def _anki(action: str, params: dict) -> "dict | None":
    """Llamada a AnkiConnect. Nunca fatal: si Anki está cerrado, la pausa
    in-app sigue valiendo y se reporta que Anki quedó sin tocar."""
    payload = json.dumps({"action": action, "version": 6,
                          "params": params}).encode()
    req = urllib.request.Request(ANKI_URL, data=payload,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        return None if data.get("error") else data
    except Exception:
        return None


def _spread_in_anki(ramp: int) -> dict:
    """`setDueDate` con un rango reparte las cartas al azar dentro de la rampa
    — el mismo mecanismo que usa Anki para 'reprogramar'."""
    found = _anki("findCards", {"query": "is:due -is:suspended"})
    if found is None:
        return {"reachable": False, "cards": 0}
    cards = found.get("result") or []
    if not cards:
        return {"reachable": True, "cards": 0}
    spec = "1" if ramp <= 1 else f"1-{ramp}"
    ok = _anki("setDueDate", {"cards": cards, "days": spec})
    return {"reachable": ok is not None, "cards": len(cards) if ok else 0}


def resume(conn: sqlite3.Connection, touch_anki: bool = True) -> dict:
    st = state(conn)
    if not st["paused"]:
        return {"resumed": False, "reason": "not paused"}

    cards, ramp = _spread_in_app(conn)
    anki = _spread_in_anki(ramp or 1) if touch_anki else {"reachable": False,
                                                          "cards": 0}
    conn.execute(
        "UPDATE pauses SET end_date=?, days_paused=?, cards_spread=?, "
        "ramp_days=?, resumed_at=? WHERE id=?",
        (db.study_day(), st["days"], cards, ramp, db.now_iso(), st["id"]))
    conn.commit()
    return {"resumed": True, "days_paused": st["days"],
            "cards_spread": cards, "ramp_days": ramp, "anki": anki}


def history(conn: sqlite3.Connection, limit: int = 10) -> "list[dict]":
    return [dict(r) for r in conn.execute(
        "SELECT start_date, end_date, reason, days_paused, cards_spread, "
        "ramp_days FROM pauses WHERE end_date IS NOT NULL "
        "ORDER BY id DESC LIMIT ?", (limit,))]
