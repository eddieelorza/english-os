"""Configuración del mazo: los parámetros del scheduler (ADR-010 D2).

Los learning steps eran el default de la librería (1m/10m) y no se podían
tocar. Aquí se vuelven datos: se guardan en `settings` como texto legible
("1m,10m") y se parsean a `timedelta` para FSRS.

Qué NO vive aquí: la hora de corte del día. `db.study_day()` se llama desde
sitios que no tienen conexión abierta, así que leerla de la base obligaría a
un caché global con su propia invalidación. Se queda en `.env`
(`STUDY_DAY_ROLLOVER_HOUR`) y este módulo sólo la *reporta*, para que la UI
pueda enseñarla sin fingir que se edita desde ahí.
"""

from __future__ import annotations

import re
import sqlite3
import sys
from datetime import timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from app import db  # noqa: E402

DEFAULTS = {
    # 1m/10m es el default de Anki y lo que sus tarjetas ya usaban: elegirlo
    # significó que M17a no reprogramara nada (ADR-010 D2).
    "deck_learning_steps": "1m,10m",
    "deck_relearning_steps": "10m",
    "deck_desired_retention": "0.9",
    # Apagado a propósito: con fuzz el intervalo que la UI promete encima de
    # un botón no es el que se aplica al pulsarlo (ADR-010 D1).
    "deck_enable_fuzzing": "0",
    # Cómo se intercalan los tres grupos de la cola (M17c).
    "deck_queue_mix": "due_first",
}

QUEUE_MIXES = ("due_first", "new_first", "mixed")

_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_STEP_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhd])\s*$", re.I)

MIN_RETENTION, MAX_RETENTION = 0.7, 0.98
MAX_STEPS = 8


# ── Parseo de pasos ──────────────────────────────────────────────────────

def parse_steps(text: str) -> "tuple[timedelta, ...]":
    """'1m,10m,1d' → (60s, 600s, 1d). Vacío = sin pasos (graduación directa)."""
    out = []
    for chunk in (text or "").split(","):
        if not chunk.strip():
            continue
        m = _STEP_RE.match(chunk)
        if not m:
            raise ValueError(f"paso inválido: {chunk.strip()!r} — usa 1m, 10m, 1d")
        seconds = float(m.group(1)) * _UNITS[m.group(2).lower()]
        if seconds <= 0:
            raise ValueError(f"paso inválido: {chunk.strip()!r} — debe ser > 0")
        out.append(timedelta(seconds=seconds))
    if len(out) > MAX_STEPS:
        raise ValueError(f"demasiados pasos (máximo {MAX_STEPS})")
    return tuple(out)


def format_steps(steps: "tuple[timedelta, ...]") -> str:
    return ",".join(human_delta(s.total_seconds()) for s in steps)


def human_delta(seconds: float) -> str:
    """Intervalo legible al estilo Anki. Redondea hacia el grano que se lee
    mejor: nadie necesita '1440m' cuando quiere decir '1d'."""
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        return "<1m" if seconds > 0 else "now"
    if seconds < 3600:
        return f"{round(seconds / 60)}m"
    if seconds < 86400:
        return f"{round(seconds / 3600)}h"
    days = seconds / 86400
    if days < 30:
        return f"{round(days)}d"
    if days < 365:
        months = days / 30.44
        return f"{months:.1f}mo" if months < 10 else f"{round(months)}mo"
    years = days / 365.25
    return f"{years:.1f}y" if years < 10 else f"{round(years)}y"


# ── Configuración ────────────────────────────────────────────────────────

def config(conn: sqlite3.Connection) -> dict:
    stored = {r["key"]: r["value"] for r in conn.execute("SELECT * FROM settings")}
    merged = {**DEFAULTS, **{k: v for k, v in stored.items() if k in DEFAULTS}}
    return {
        "learning_steps": merged["deck_learning_steps"],
        "relearning_steps": merged["deck_relearning_steps"],
        "desired_retention": float(merged["deck_desired_retention"]),
        "enable_fuzzing": merged["deck_enable_fuzzing"] == "1",
        "queue_mix": merged["deck_queue_mix"],
        # Sólo lectura: se cambia en .env (ver el docstring del módulo).
        "rollover_hour": db.rollover_hour(),
        "rollover_hour_editable": False,
    }


_FIELDS = {"learning_steps": "deck_learning_steps",
           "relearning_steps": "deck_relearning_steps",
           "desired_retention": "deck_desired_retention",
           "enable_fuzzing": "deck_enable_fuzzing",
           "queue_mix": "deck_queue_mix"}


def save_config(conn: sqlite3.Connection, patch: dict) -> dict:
    """Valida antes de guardar: unos pasos rotos dejarían el mazo sin poder
    programar nada, y el fallo aparecería al contestar, no al configurar."""
    updates = {}
    for field, value in patch.items():
        key = _FIELDS.get(field)
        if key is None or value is None:
            continue
        if field in ("learning_steps", "relearning_steps"):
            parse_steps(str(value))          # levanta ValueError si está mal
            updates[key] = str(value).strip()
        elif field == "desired_retention":
            r = float(value)
            if not MIN_RETENTION <= r <= MAX_RETENTION:
                raise ValueError(
                    f"desired_retention debe estar entre {MIN_RETENTION} "
                    f"y {MAX_RETENTION}")
            updates[key] = str(r)
        elif field == "enable_fuzzing":
            updates[key] = "1" if value in (True, 1, "1", "true", "True") else "0"
        elif field == "queue_mix":
            if value not in QUEUE_MIXES:
                raise ValueError(f"queue_mix debe ser uno de {QUEUE_MIXES}")
            updates[key] = value

    for key, value in updates.items():
        conn.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
            "updated_at=excluded.updated_at", (key, value, db.now_iso()))
    conn.commit()
    return config(conn)


def longest_step_minutes(conn: "sqlite3.Connection | None" = None) -> float:
    """El paso de aprendizaje más largo configurado, en minutos.

    Marca hasta dónde puede adelantarse una card cuando ya no queda nada más
    que estudiar: la escalera de aprendizaje entera, ni un minuto más. Sin
    este tope, "no queda nada" acabaría trayendo trabajo de mañana.
    """
    kw = scheduler_kwargs(conn)
    steps = list(kw["learning_steps"]) + list(kw["relearning_steps"])
    return max((s.total_seconds() / 60 for s in steps), default=0.0)


def shortest_step_minutes(conn: "sqlite3.Connection | None" = None) -> float:
    """El paso de aprendizaje más CORTO configurado, en minutos.

    Es el suelo del adelanto. Adelantar el paso de 10 minutos cuando no queda
    nada más es razonable; adelantarlo a dos segundos no: FSRS mide tiempo
    transcurrido, así que contestar al instante no prueba memoria — sube la
    dificultad y hunde la estabilidad. Sin este suelo la ventana ancha
    convertía "vuelve en 1 minuto" en "vuelve ya" y la misma palabra se
    contestaba seis veces en 55 segundos (ADR-009 D2 rev.3).
    """
    kw = scheduler_kwargs(conn)
    steps = list(kw["learning_steps"]) + list(kw["relearning_steps"])
    return min((s.total_seconds() / 60 for s in steps), default=0.0)


def scheduler_kwargs(conn: "sqlite3.Connection | None" = None) -> dict:
    """Los argumentos con los que se construye el Scheduler de FSRS."""
    if conn is None:
        cfg = {"learning_steps": DEFAULTS["deck_learning_steps"],
               "relearning_steps": DEFAULTS["deck_relearning_steps"],
               "desired_retention": float(DEFAULTS["deck_desired_retention"]),
               "enable_fuzzing": DEFAULTS["deck_enable_fuzzing"] == "1"}
    else:
        cfg = config(conn)
    return {
        "learning_steps": parse_steps(cfg["learning_steps"]),
        "relearning_steps": parse_steps(cfg["relearning_steps"]),
        "desired_retention": cfg["desired_retention"],
        "enable_fuzzing": cfg["enable_fuzzing"],
    }
