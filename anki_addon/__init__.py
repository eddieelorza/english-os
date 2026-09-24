"""
English Automation – Anki Add-on (canonical).

This file is the single source of truth. The installed add-on directory
at ~/Library/Application Support/Anki2/addons21/english_automation should
be a symlink to the anki_addon/ directory of this repo, so any edit here
is picked up by Anki on next restart.

Trigger model (ADR-001, revisado 2026-07-30):
  El disparo NO ocurre al volver al deck browser — eso pasaba a mitad de
  sesión. Ocurre cuando dejas de contestar cards por DEBOUNCE_MS (señal real
  de "terminé"), o cuando cierras el perfil. Cada card contestada reinicia el
  temporizador, así que estudiar en tandas cortas no dispara nada de más.

  El umbral de "sesión real" (mínimo de reviews) y el gate de una sola
  generación de material por día viven en run_all.py, que lee .env — el
  add-on se mantiene tonto y sin secretos a propósito.
"""

import json
import subprocess
import traceback
from datetime import datetime
from pathlib import Path

import aqt
from aqt import gui_hooks
from aqt.qt import QTimer
from aqt.utils import tooltip

ADDON_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = ADDON_DIR.parent
PIPELINE_SCRIPT = PROJECT_ROOT / "run_all.py"
SNAPSHOT = PROJECT_ROOT / "data" / "anki_session.json"
ADDON_LOG = PROJECT_ROOT / "logs" / "addon.log"


def log(msg: str) -> None:
    """Errors here used to go to Anki's invisible stdout — a silent failure
    is worse than a loud one, so everything lands in a file we can read."""
    try:
        ADDON_LOG.parent.mkdir(exist_ok=True)
        with open(ADDON_LOG, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}\n")
    except Exception:
        pass

DEBOUNCE_MS = 120_000  # 2 min sin contestar cards = sesión terminada

_timer = None
_answered = 0


def _dump_snapshot() -> None:
    """Freeze today's studied notes to disk using Anki's in-process API.

    This is what makes the "closed Anki right after studying" path work:
    AnkiConnect dies with Anki (and can die *mid-run*), but this hook still
    has a live collection. The pipeline falls back to this file whenever
    AnkiConnect is unreachable.
    """
    try:
        # aqt.mw is assigned during startup: binding it at import time can
        # capture None. Always read it from the module at call time.
        col = getattr(aqt.mw, "col", None) if aqt.mw else None
        if col is None:
            log("snapshot: no hay colección abierta (mw.col = None)")
            return
        find_notes = getattr(col, "find_notes", None) or col.findNotes
        get_note = getattr(col, "get_note", None) or col.getNote
        find_cards = getattr(col, "find_cards", None) or col.findCards

        notes = []
        for nid in find_notes("rated:1"):
            note = get_note(nid)
            cards = [{
                "reps": c.reps,
                "lapses": c.lapses,
                "factor": c.factor,
                "queue": c.queue,
                "deckName": col.decks.name(c.did),
            } for c in note.cards()]
            notes.append({
                "noteId": int(nid),
                "fields": {name: {"value": value} for name, value in note.items()},
                "cards": cards,
            })

        SNAPSHOT.parent.mkdir(exist_ok=True)
        tmp = SNAPSHOT.with_suffix(".tmp")
        tmp.write_text(json.dumps({
            "date": __import__("datetime").date.today().isoformat(),
            "reviews_today": _reviews_today(col),
            "introduced": len(find_cards("introduced:1")),
            "again": len(find_cards("rated:1:1")),
            "notes": notes,
        }, ensure_ascii=False), encoding="utf-8")
        tmp.rename(SNAPSHOT)
        log(f"snapshot OK: {len(notes)} notas")
    except Exception:  # snapshot is best-effort, never break Anki
        log("snapshot FALLÓ:\n" + traceback.format_exc())


def _reviews_today(col) -> int:
    try:
        return col.db.scalar(
            "select count() from revlog where id > ?",
            (col.sched.day_cutoff - 86400) * 1000) or 0
    except Exception:
        return 0


def _spawn_pipeline(reason: str) -> None:
    global _answered
    if not _answered:
        return
    n, _answered = _answered, 0
    _dump_snapshot()  # always fresh, and it's the only source once Anki closes

    if not PIPELINE_SCRIPT.exists():
        tooltip(f"English coach: no encontré {PIPELINE_SCRIPT}", period=6000)
        return
    try:
        subprocess.Popen(
            [
                "/bin/zsh", "-lc",
                f'cd "{PROJECT_ROOT}" && exec python3 run_all.py session-end',
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        tooltip(f"English coach: procesando sesión ({n} cards)…", period=2500)
    except Exception as exc:  # never break Anki over this
        tooltip(f"English coach error: {exc}", period=6000)


def _restart_debounce() -> None:
    global _timer
    if _timer is not None:
        _timer.stop()
    _timer = QTimer()
    _timer.setSingleShot(True)
    _timer.timeout.connect(lambda: _spawn_pipeline("idle"))
    _timer.start(DEBOUNCE_MS)


def _on_card_answered(reviewer, card, ease) -> None:
    global _answered
    _answered += 1
    _restart_debounce()


def _on_profile_will_close() -> None:
    global _timer
    if _timer is not None:
        _timer.stop()
        _timer = None
    _spawn_pipeline("profile_close")


gui_hooks.reviewer_did_answer_card.append(_on_card_answered)
gui_hooks.profile_will_close.append(_on_profile_will_close)
