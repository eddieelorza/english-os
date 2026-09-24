"""La carga propuesta: cuánto hoy, a partir de cómo estudias de verdad (ADR-015).

ADR-014 quitó el muro, pero seguía preguntando "¿cuánto tiempo tienes?" y
repartía el rezago como si se estudiara todos los días. Medido el 2026-09-20:
14 días estudiados de 31 (2-4 por semana), y dentro de una sentada el fallo
sube con la posición — 28% en las primeras 20 respuestas, 57% pasada la 80 —
porque la cola de la sentada son repeticiones de lo que se acaba de fallar.

Aquí no se mide "capacidad": eso no se puede medir. Se mide lo que sí consta
en `review_history` y se separa de lo que es **política** (decisiones de
diseño, con nombre y en un solo sitio, abajo). Ningún número de política se
presenta en pantalla como si fuera una medición de Eddie.

Lo medido:
  · ritmo      — qué fracción de los días estudia, y cuánto lleva fuera
  · repetición — cuántas respuestas cuesta cada card en una sentada
  · lo típico  — cuántas respuestas hace en un día de estudio
  · el grupo   — palabras sin consolidar, cuántas entran y cuántas salen

Lo propuesto sale de una cuenta de conservación: el trabajo que vence en el
horizonte, entre las sentadas que de verdad va a haber. Es la carga más
pequeña que no deja crecer el rezago — y nunca más de lo que suele hacer.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from math import ceil
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from app import db  # noqa: E402

# ── Política (decisiones, no mediciones) ─────────────────────────────────
WINDOW_DAYS = 28          # cuánto historial se mira para leer el ritmo
MIN_OBSERVED_DAYS = 14    # por debajo no se afirma ningún ritmo
MIN_STUDY_DAYS = 4
HORIZON_DAYS = 14         # "estar al día en dos semanas"
LESS_FACTOR = 0.5         # "Less today" es la mitad
CONSOLIDATED_DAYS = 7.0   # estabilidad a partir de la cual una palabra sale del grupo
GROUP_WINDOW_DAYS = 14
DEFAULT_LADDER_COST = 2   # respuestas extra por card fallada, si no hay muestra
MIN_LADDER_SAMPLE = 20
MORE_STEP = 20            # "Study more" suma esto, voluntario


def _today() -> date:
    return date.fromisoformat(db.study_day())


def _median(values: list) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def _study_log(conn: sqlite3.Connection, since: date) -> "dict[str, list]":
    """Respuestas in-app por día de estudio, desde `since`."""
    out: "dict[str, list]" = {}
    for row in conn.execute(
            "SELECT reviewed_at, word_id, rating, review_kind FROM review_history "
            "WHERE source='fsrs' AND reviewed_at >= ? ORDER BY reviewed_at, id",
            (since.isoformat(),)):
        day = db.study_day(datetime.fromisoformat(row["reviewed_at"]))
        out.setdefault(day, []).append(row)
    return out


# ── Lo medido ────────────────────────────────────────────────────────────

def rhythm(conn: sqlite3.Connection) -> dict:
    """Qué fracción de los días estudia. Hoy no cuenta: está a medias.

    Los días en pausa se descuentan — unas vacaciones declaradas no son
    "estudiar poco". Con poca historia no se afirma nada (`measured: False`):
    inventar una rutina es peor que decir que aún no se conoce.
    """
    from app import pause
    today = _today()
    first = conn.execute(
        "SELECT MIN(reviewed_at) FROM review_history WHERE source='fsrs'").fetchone()[0]
    if first is None:
        return {"measured": False, "study_days": 0, "observed_days": 0,
                "rate": None, "days_away": None, "per_week": None}
    first_day = date.fromisoformat(db.study_day(datetime.fromisoformat(first)))
    start = max(first_day, today - timedelta(days=WINDOW_DAYS))
    paused = pause.paused_days(conn)
    log = _study_log(conn, start)
    observed = [start + timedelta(days=i) for i in range((today - start).days)]
    observed = [d for d in observed if d.isoformat() not in paused]
    studied = [d for d in observed if d.isoformat() in log]
    before_today = sorted(d for d in log if d < today.isoformat())
    days_away = ((today - date.fromisoformat(before_today[-1])).days
                 if before_today else None)
    measured = len(observed) >= MIN_OBSERVED_DAYS and len(studied) >= MIN_STUDY_DAYS
    rate = len(studied) / len(observed) if observed else None
    return {"measured": measured, "study_days": len(studied),
            "observed_days": len(observed),
            "rate": round(rate, 3) if rate is not None else None,
            "per_week": round(rate * 7, 1) if rate is not None else None,
            "days_away": days_away}


def effort(conn: sqlite3.Connection) -> dict:
    """Cuánto hace en un día de estudio y cuánto de eso son repeticiones."""
    today = _today()
    log = _study_log(conn, today - timedelta(days=WINDOW_DAYS))
    days = [rows for day, rows in log.items() if day < today.isoformat()]
    if len(days) < MIN_STUDY_DAYS:
        return {"measured": False, "typical_answers": None, "repeat_factor": None,
                "ladder_cost": DEFAULT_LADDER_COST, "ladder_measured": False,
                "days": len(days)}
    factors = [len(rows) / max(1, len({r["word_id"] for r in rows})) for rows in days]
    # Lo que cuesta una card fallada: respuestas a esa palabra DESPUÉS de su
    # primer Again del día.
    extra = []
    for rows in days:
        seen_fail: "dict[int, int]" = {}
        for r in rows:
            if r["word_id"] in seen_fail:
                seen_fail[r["word_id"]] += 1
            elif r["rating"] == 1:
                seen_fail[r["word_id"]] = 0
        extra += list(seen_fail.values())
    ladder_measured = len(extra) >= MIN_LADDER_SAMPLE
    return {"measured": True,
            "typical_answers": int(_median([len(rows) for rows in days])),
            "repeat_factor": round(_median(factors), 2),
            "ladder_cost": (max(1, round(_median(extra))) if ladder_measured
                            else DEFAULT_LADDER_COST),
            "ladder_measured": ladder_measured, "days": len(days)}


def group(conn: sqlite3.Connection) -> dict:
    """El grupo de palabras sin consolidar, y su balance de entradas y salidas.

    Conservación, no un umbral: si en dos semanas entraron 30 y se asentaron
    9, el grupo crece 21 y cada palabra recibe menos repasos. Meter otra más
    sólo lo agranda.
    """
    since = (datetime.now() - timedelta(days=GROUP_WINDOW_DAYS)).isoformat()
    size = conn.execute(
        "SELECT COUNT(*) FROM words WHERE fsrs_card IS NOT NULL AND ("
        "card_state IN ('LEARNING','RELEARNING') OR stability IS NULL "
        "OR stability < ?)", (CONSOLIDATED_DAYS,)).fetchone()[0]
    came_in = conn.execute(
        "SELECT COUNT(*) FROM review_history WHERE source='fsrs' "
        "AND review_kind='new' AND reviewed_at >= ?", (since,)).fetchone()[0]
    # Salió = cruzó el umbral en la ventana Y sigue por encima ahora.
    settled = conn.execute(
        "SELECT COUNT(DISTINCT r.word_id) FROM review_history r "
        "JOIN words w ON w.id = r.word_id "
        "WHERE r.source='fsrs' AND r.reviewed_at >= ? "
        "AND r.stability_after >= ? "
        "AND (r.stability_before IS NULL OR r.stability_before < ?) "
        "AND w.stability >= ? AND w.card_state='REVIEW'",
        (since, CONSOLIDATED_DAYS, CONSOLIDATED_DAYS, CONSOLIDATED_DAYS)).fetchone()[0]
    return {"size": size, "came_in": came_in, "settled": settled,
            "window_days": GROUP_WINDOW_DAYS}


def new_allowed(conn: sqlite3.Connection, ceiling: int) -> dict:
    """Cuántas palabras nuevas admite el grupo hoy.

    Una entra por cada una que se asentó; y si el grupo es menor que el techo
    que Eddie eligió, se rellena hasta ahí (si no, un grupo vacío no podría
    arrancar nunca). `ceiling` es su preferencia, no una capacidad medida.
    """
    g = group(conn)
    n = max(g["settled"] - g["came_in"], ceiling - g["size"])
    n = max(0, min(ceiling, n))
    reason = None
    if n < ceiling:
        reason = (f"new words wait — {g['size']} words are not settled yet; in "
                  f"{g['window_days']} days {g['came_in']} came in and "
                  f"{g['settled']} settled")
    return {"new": n, "group": g, "reason": reason}


def workload(conn: sqlite3.Connection) -> dict:
    """El trabajo real del horizonte: lo vencido que aún se puede salvar, lo
    que vence en las próximas dos semanas, y lo perdido (que va a goteo)."""
    from app import backlog
    now = datetime.now(timezone.utc)
    cards = backlog.triaged(conn, now)
    alive = sum(1 for c in cards if not c["lost"])
    lost = sum(1 for c in cards if c["lost"])
    upcoming = conn.execute(
        "SELECT COUNT(*) FROM words WHERE fsrs_due > ? AND fsrs_due <= ?",
        (now.isoformat(), (now + timedelta(days=HORIZON_DAYS)).isoformat())
    ).fetchone()[0]
    return {"alive": alive, "lost": lost, "upcoming": upcoming}


# ── El día: una propuesta que se mantiene aunque te levantes ─────────────

def _day_state(conn: sqlite3.Connection) -> dict:
    row = conn.execute("SELECT value FROM settings WHERE key='load_day'").fetchone()
    if row:
        try:
            state = json.loads(row["value"])
            if state.get("date") == db.study_day():
                return state
        except ValueError:
            pass
    return {"date": db.study_day(), "budget": None, "less": False, "extra": 0,
            "answered_before": 0}


def _save_day(conn: sqlite3.Connection, state: dict) -> None:
    conn.execute(
        "INSERT INTO settings (key, value, updated_at) VALUES ('load_day', ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
        "updated_at=excluded.updated_at", (json.dumps(state), db.now_iso()))
    conn.commit()


def answered_today(conn: sqlite3.Connection) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM review_history WHERE source='fsrs' "
        "AND reviewed_at >= ?", (db.study_day_start(),)).fetchone()[0]


def proposal(conn: sqlite3.Connection, less: "bool | None" = None) -> dict:
    """La carga de hoy y su porqué. No escribe nada.

    `less=None` respeta lo que ya se eligió hoy; True/False lo previsualiza.
    """
    from app import backlog, gate, pause, session
    if pause.is_paused(conn):
        return {"measured": False, "paused": True, "budget": 0, "remaining": 0,
                "why": ["the course is paused"]}

    r, e = rhythm(conn), effort(conn)
    state = _day_state(conn)
    less = state["less"] if less is None else bool(less)
    base = {"rhythm": r, "effort": e, "less": less, "paused": False,
            "policy": {"horizon_days": HORIZON_DAYS, "less_factor": LESS_FACTOR,
                       "consolidated_days": CONSOLIDATED_DAYS}}
    if not (r["measured"] and e["measured"]):
        need = max(0, MIN_STUDY_DAYS - r["study_days"])
        return {**base, "measured": False, "budget": None, "remaining": None,
                "why": [f"not enough history to read your rhythm yet "
                        f"({r['study_days']} study days in {r['observed_days']}; "
                        f"{need} more to go) — using the time you pick instead"]}

    w = workload(conn)
    sittings = max(1.0, r["rate"] * HORIZON_DAYS)
    coming_back = min(w["lost"], backlog.COMEBACK_PER_DAY)
    cards = ceil((w["alive"] + w["upcoming"]) / sittings) + coming_back
    # no más cards de las que hoy hay sobre la mesa
    on_the_table = w["alive"] + coming_back
    needed = cards
    cards = min(cards, on_the_table)
    answers = ceil(cards * e["repeat_factor"])

    ceiling = session.settings(conn)["new_per_day"]
    door = gate.allowed(conn, capacity=max(cards, 1) + ceiling, mode="auto")
    new = 0 if less else door["new_per_day"]
    # Una palabra nueva cuesta lo que cuesta una card más sus repeticiones.
    new_cost = 1 + e["ladder_cost"]
    wanted = answers + new * new_cost
    computed = min(wanted, e["typical_answers"])
    if computed < wanted:                     # lo primero que cede son las nuevas
        new = max(0, min(new, (computed - answers) // new_cost))

    # Las cards que de verdad caben en ese presupuesto. El reparto usa ESTE
    # número: dejar "para hoy" 29 cards con presupuesto para 10 era volver a
    # tener cada día un resto vencido que no se iba a hacer.
    fit = max(1, int((computed - new * new_cost) // e["repeat_factor"]))
    cards_today = min(cards, fit)

    # Fijada al sentarte por primera vez; "less" y "more" se aplican encima.
    fixed = state["budget"] if state["budget"] is not None else computed
    budget = (ceil(fixed * LESS_FACTOR) if less else fixed) + state.get("extra", 0)
    done = (max(0, answered_today(conn) - state.get("answered_before", 0))
            if state["budget"] is not None else 0)

    # Breve: ritmo, cuenta, y lo que se recortó. El detalle completo viaja en
    # el payload (`rhythm`, `effort`, `workload`) para quien quiera mirarlo.
    first = (f"you study about {r['per_week']:g} days a week "
             f"({r['study_days']} of the last {r['observed_days']})")
    if r["days_away"] and r["days_away"] >= 3:
        first += (f"; {r['days_away']} days away, so settling what you have "
                  f"comes before anything new")
    why = [first,
           f"{w['alive'] + w['upcoming']} cards fall due in the next "
           f"{HORIZON_DAYS} days, over about {sittings:.0f} sittings — about "
           f"{ceil(needed * e['repeat_factor'])} answers each, repeats included"]
    if less:
        why.append("less today: half, and no new words — nothing is lost, it "
                   "is rescheduled")
    elif computed < wanted:
        why.append(f"capped at {e['typical_answers']}, what you usually do in a "
                   f"day — catching up will take longer than {HORIZON_DAYS} days")
    if door["reason"]:
        why.append(door["reason"])

    return {**base, "measured": True, "budget": budget, "computed": computed,
            "answered": done, "remaining": max(0, budget - done),
            "cards": cards_today, "cards_needed": cards, "new": new,
            "workload": w, "gate": door,
            "sittings_in_horizon": round(sittings, 1), "why": why}


def begin_day(conn: sqlite3.Connection, budget: int) -> dict:
    """Fija la propuesta del día la primera vez que te sientas: si te levantas
    y vuelves, sigues con lo que quedaba, no con una propuesta nueva."""
    state = _day_state(conn)
    if state["budget"] is None:
        state["budget"] = budget
        state["answered_before"] = answered_today(conn)
        _save_day(conn, state)
    return state


def set_less(conn: sqlite3.Connection, less: bool) -> dict:
    """"Less today": vale hoy y caduca solo. No toca ninguna preferencia."""
    state = _day_state(conn)
    state["less"] = bool(less)
    _save_day(conn, state)
    return state


def add_more(conn: sqlite3.Connection, answers: int = MORE_STEP) -> dict:
    """Estudiar más, porque quieres: suma al día de hoy y nada más."""
    state = _day_state(conn)
    state["extra"] = state.get("extra", 0) + max(1, int(answers))
    _save_day(conn, state)
    return state
