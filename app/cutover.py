"""El cut-over de Anki: la app pasa a ser la única verdad del scheduling.

Hasta aquí convivían dos sistemas. Anki era el mazo de verdad y la app leía
de él; desde M4 la app también programa, así que llevaban divergiendo en
silencio. El cut-over cierra esa puerta.

**Qué hace**: marca la fecha, guarda una foto del estado final de Anki y
enciende las guardas que impiden que el importador vuelva a pisar el estado
de la app.

**Qué NO hace**: tocar Anki. El mazo queda intacto, congelado como archivo.
Nadie escribe en él ni lee de él para programar. Es reversible: `revert()`
apaga la marca y el pipeline vuelve a leer de Anki tal como antes.

El peligro concreto que evita: `importers/anki.py` escribe con
`overwrite=("status", "ease", "interval_days", ...)`. No toca el scheduling
FSRS, pero sí `status`, así que una palabra que la app ya avanzó volvería a lo
que Anki cree — corrupción silenciosa y difícil de notar.

Coste asumido: Anki tiene app de móvil y esto no. Se pierde estudiar fuera del
escritorio a cambio de dejar de tener dos sistemas que se contradicen
(decisión de Eddie, ADR-011).
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from app import db  # noqa: E402

ANKI_URL = "http://localhost:8765"
KEY_DATE = "cutover_date"
KEY_SNAPSHOT = "cutover_anki_snapshot"
KEY_NOTION_DATE = "notion_off_date"
KEY_NOTION_SNAPSHOT = "notion_off_snapshot"


# ── Estado ───────────────────────────────────────────────────────────────

def _get(conn: sqlite3.Connection, key: str) -> "str | None":
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def _set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings (key, value, updated_at) VALUES (?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
        "updated_at=excluded.updated_at", (key, value, db.now_iso()))


def done(conn: sqlite3.Connection) -> bool:
    """¿Ya se cortó? Lo consultan las guardas del pipeline."""
    return _get(conn, KEY_DATE) is not None


# El vigilante de Anki: un `launchd` que sondea cada 10 s y, al cerrar Anki,
# lanza `run_all.py morning`. El corte de ADR-011 congeló Anki y ADR-012 apagó
# Notion, pero **nadie lo descargó**: siguió vivo dos semanas. Si Eddie abría
# Anki por curiosidad, disparaba un pipeline condenado a `NotionOff` y le
# enseñaba una alerta de fallo que no significaba nada.
#
# Vive aquí y no en un `rm` suelto porque `revert()` promete devolver el
# pipeline legacy, y un revert que no reactiva su disparador es media promesa.
WATCHER_LABEL = "com.english.anki-watcher"
WATCHER_PLIST = Path.home() / "Library/LaunchAgents" / f"{WATCHER_LABEL}.plist"
WATCHER_ARCHIVE = BASE / "scripts/legacy" / f"{WATCHER_LABEL}.plist"


def watcher_loaded() -> bool:
    """Si `launchd` lo tiene cargado ahora mismo."""
    try:
        r = subprocess.run(["launchctl", "print",
                            f"gui/{os.getuid()}/{WATCHER_LABEL}"],
                           capture_output=True, timeout=10)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def watcher_stop() -> dict:
    """Descarga el vigilante y guarda su plist en el repo."""
    if not watcher_loaded() and not WATCHER_PLIST.exists():
        return {"stopped": False, "reason": "no estaba"}
    WATCHER_ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    if WATCHER_PLIST.exists():
        WATCHER_ARCHIVE.write_bytes(WATCHER_PLIST.read_bytes())
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{WATCHER_LABEL}"],
                   capture_output=True, timeout=20)
    WATCHER_PLIST.unlink(missing_ok=True)
    return {"stopped": True, "archived": str(WATCHER_ARCHIVE)}


def watcher_start() -> dict:
    """Lo devuelve desde el archivo. Lo usa `revert()`."""
    if not WATCHER_ARCHIVE.exists():
        return {"started": False, "reason": "no hay plist archivado"}
    WATCHER_PLIST.parent.mkdir(parents=True, exist_ok=True)
    WATCHER_PLIST.write_bytes(WATCHER_ARCHIVE.read_bytes())
    r = subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}",
                        str(WATCHER_PLIST)], capture_output=True, timeout=20)
    return {"started": r.returncode == 0,
            "error": r.stderr.decode()[:200] or None}


def state(conn: sqlite3.Connection) -> dict:
    raw = _get(conn, KEY_SNAPSHOT)
    return {
        "cut_over": done(conn),
        "date": _get(conn, KEY_DATE),
        "anki_snapshot": json.loads(raw) if raw else None,
        # Se reporta siempre: un corte "hecho" con el vigilante encendido no
        # está hecho, y durante dos semanas nada lo dijo.
        "anki_watcher_loaded": watcher_loaded(),
    }


# ── Anki (solo lectura) ──────────────────────────────────────────────────

def _anki(action: str, **params) -> "object | None":
    payload = json.dumps({"action": action, "version": 6,
                          "params": params}).encode()
    req = urllib.request.Request(ANKI_URL, data=payload,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        return None if data.get("error") else data.get("result")
    except Exception:
        return None


def _anki_snapshot() -> "dict | None":
    """Foto del estado final de Anki, para el registro.

    No se usa para nada funcional: existe para que dentro de un año se pueda
    responder "¿qué había en Anki el día que corté?" sin adivinar.
    """
    ids = _anki("findCards", query="deck:*")
    if ids is None:
        return None
    info = _anki("cardsInfo", cards=ids) or []
    by_type = {}
    for card in info:
        name = {0: "new", 1: "learning", 2: "review",
                3: "relearning"}.get(card["type"], str(card["type"]))
        by_type[name] = by_type.get(name, 0) + 1
    return {
        "taken_at": db.now_iso(),
        "cards": len(ids),
        "by_type": by_type,
        "notes_studied": sorted({c["note"] for c in info if c["type"] != 0}),
    }


# ── Comprobaciones previas ───────────────────────────────────────────────

def preflight(conn: sqlite3.Connection) -> dict:
    """¿Es seguro cortar?

    La única condición que de verdad importa: que Anki no sepa nada que la app
    no sepa. Si hay tarjetas estudiadas en Anki sin card en la app, cortar
    perdería ese progreso.
    """
    checks = []

    snapshot = _anki_snapshot()
    if snapshot is None:
        checks.append({"name": "anki_reachable", "ok": False,
                       "detail": "AnkiConnect no responde — abre Anki para "
                                 "poder comprobar y fotografiar el estado final"})
        return {"ok": False, "checks": checks, "snapshot": None}
    checks.append({"name": "anki_reachable", "ok": True,
                   "detail": f"{snapshot['cards']} cards, {snapshot['by_type']}"})

    app_notes = {r["anki_note_id"] for r in conn.execute(
        "SELECT anki_note_id FROM words WHERE anki_note_id IS NOT NULL "
        "AND card_state IS NOT NULL AND card_state != 'NEW'")}
    orphans = [n for n in snapshot["notes_studied"] if n not in app_notes]
    checks.append({
        "name": "nothing_only_in_anki",
        "ok": not orphans,
        "detail": ("Anki no sabe nada que la app no sepa"
                   if not orphans else
                   f"{len(orphans)} tarjeta(s) estudiadas solo en Anki: "
                   f"se perdería su progreso"),
        "note_ids": orphans[:20],
    })

    backups = sorted((BASE / "data" / "backups").glob("*.db")) \
        if (BASE / "data" / "backups").exists() else []
    checks.append({"name": "backup_exists", "ok": bool(backups),
                   "detail": (f"último: {backups[-1].name}" if backups
                              else "no hay copia en data/backups/")})

    return {"ok": all(c["ok"] for c in checks), "checks": checks,
            "snapshot": snapshot}


# ── Cortar y deshacer ────────────────────────────────────────────────────

def run(conn: sqlite3.Connection, force: bool = False) -> dict:
    """Marca el cut-over. No toca Anki."""
    if done(conn):
        return {"cut_over": True, "already": True, **state(conn)}

    pre = preflight(conn)
    if not pre["ok"] and not force:
        return {"cut_over": False, "blocked": True, "preflight": pre}

    _set(conn, KEY_DATE, db.study_day())
    if pre["snapshot"]:
        _set(conn, KEY_SNAPSHOT, json.dumps(pre["snapshot"]))
    conn.commit()
    return {"cut_over": True, "already": False, "preflight": pre, **state(conn)}


# ── Notion (ADR-012) ─────────────────────────────────────────────────────
#
# Notion es más delicado que Anki. Anki solo tenía scheduling, que la app ya
# replicaba; Notion tiene **contenido escrito**: el inglés de Eddie, las
# correcciones y las historias. El importador viejo solo leía propiedades, así
# que ese contenido no estaba en la app. Apagar Notion sin rescatarlo primero
# lo habría dejado inalcanzable sin que nadie lo notara hasta ir a buscarlo.

def notion_done(conn: sqlite3.Connection) -> bool:
    return _get(conn, KEY_NOTION_DATE) is not None


def notion_state(conn: sqlite3.Connection) -> dict:
    raw = _get(conn, KEY_NOTION_SNAPSHOT)
    return {
        "notion_off": notion_done(conn),
        "date": _get(conn, KEY_NOTION_DATE),
        "snapshot": json.loads(raw) if raw else None,
    }


def notion_preflight(conn: sqlite3.Connection) -> dict:
    """¿Está a salvo todo lo que hay en Notion?

    La condición que importa: ninguna página con cuerpo vacío en la app. Un
    cascarón significa contenido que solo existe en Notion.
    """
    checks = []
    empty = conn.execute(
        "SELECT kind, COUNT(*) n FROM texts WHERE notion_page_id IS NOT NULL "
        "AND (body IS NULL OR TRIM(body) = '') GROUP BY kind").fetchall()
    missing = {r["kind"]: r["n"] for r in empty}
    checks.append({
        "name": "content_rescued",
        "ok": not missing,
        "detail": ("todas las páginas tienen su contenido en la app"
                   if not missing else
                   f"páginas sin cuerpo: {missing} — corre "
                   f"`python3 -m app.importers.notion_content` primero"),
    })

    counts = {r["kind"]: r["n"] for r in conn.execute(
        "SELECT kind, COUNT(*) n FROM texts GROUP BY kind")}
    checks.append({"name": "archive_counts", "ok": True,
                   "detail": f"{counts} · errors="
                             f"{conn.execute('SELECT COUNT(*) FROM errors').fetchone()[0]}"})

    backups = sorted((BASE / "data" / "backups").glob("*.db")) \
        if (BASE / "data" / "backups").exists() else []
    checks.append({"name": "backup_exists", "ok": bool(backups),
                   "detail": (f"último: {backups[-1].name}" if backups
                              else "no hay copia en data/backups/")})

    return {"ok": all(c["ok"] for c in checks), "checks": checks,
            "counts": counts}


def notion_off(conn: sqlite3.Connection, force: bool = False) -> dict:
    """Apaga Notion. No borra nada allí: las páginas quedan como archivo."""
    if notion_done(conn):
        return {"notion_off": True, "already": True, **notion_state(conn)}
    pre = notion_preflight(conn)
    if not pre["ok"] and not force:
        return {"notion_off": False, "blocked": True, "preflight": pre}

    _set(conn, KEY_NOTION_DATE, db.study_day())
    _set(conn, KEY_NOTION_SNAPSHOT, json.dumps(
        {"taken_at": db.now_iso(), "texts": pre["counts"]}, ensure_ascii=False))
    conn.commit()
    return {"notion_off": True, "already": False, "preflight": pre,
            **notion_state(conn)}


def notion_on(conn: sqlite3.Connection) -> dict:
    if not notion_done(conn):
        return {"reverted": False, "reason": "Notion no estaba apagado"}
    conn.execute("DELETE FROM settings WHERE key=?", (KEY_NOTION_DATE,))
    conn.commit()
    return {"reverted": True}


def revert(conn: sqlite3.Connection) -> dict:
    """Vuelve al modo anterior: el pipeline lee de Anki otra vez.

    La foto del estado final se conserva — borrarla no ayudaría a nadie.
    """
    if not done(conn):
        return {"reverted": False, "reason": "no estaba cortado"}
    conn.execute("DELETE FROM settings WHERE key=?", (KEY_DATE,))
    conn.commit()
    return {"reverted": True, "watcher": watcher_start()}
