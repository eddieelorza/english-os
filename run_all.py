#!/usr/bin/env python3
"""
run_all.py – English Automation pipeline orchestrator.

Modes:
  python3 run_all.py morning       # anki sync + writing + reading (NO auto-reset)
  python3 run_all.py session-end   # automated post-Anki run (ADR-001): waits for
                                   # AnkiConnect, skips if today's reviews were
                                   # already processed, runs morning steps +
                                   # learner profile, notifies via macOS.
                                   # Add --force to ignore the idempotency state.
  python3 run_all.py sync-used     # mark Used Today / Times Used after exercises
  python3 run_all.py reset         # manually wipe Used Today (run before a new day)

A non-blocking file lock prevents two pipelines from running at the same time
(e.g. Anki add-on firing while anki_watcher.sh also fires). The second caller
exits cleanly without touching Notion.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import subprocess
import sys
import time
import urllib.request
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
LOGS_DIR = BASE / "logs"
LOGS_DIR.mkdir(exist_ok=True)

LOG_FILE = LOGS_DIR / f"{datetime.now():%Y-%m-%d}.log"
LOCK_FILE = LOGS_DIR / ".pipeline.lock"
ENV_FILE = BASE / ".env"


def load_env_into_environ(env_path: Path) -> None:
    """Read .env and apply it to os.environ with priority over the inherited
    shell environment. This makes .env the single source of truth for secrets
    regardless of who launches the pipeline (add-on, watcher, or terminal)."""
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ[key.strip()] = val.strip().strip('"').strip("'")


load_env_into_environ(ENV_FILE)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

SCRIPTS = {
    "reset":   BASE / "scripts" / "reset_used_today.py",
    "anki":    BASE / "scripts" / "anki_notion_sync.py",
    "session": BASE / "scripts" / "writing_session_daily.py",
    "reading": BASE / "scripts" / "reading_page_daily.py",
    "used":    BASE / "scripts" / "sync_used_words.py",
    "profile": BASE / "scripts" / "learner_profile_update.py",
    "today":   BASE / "scripts" / "daily_plan_update.py",
    "localdb": BASE / "scripts" / "local_db_sync.py",
    "pregen":  BASE / "scripts" / "pregenerate.py",
}

STATE_FILE = LOGS_DIR / ".session_state.json"
ANKI_URL = "http://localhost:8765"
ANKICONNECT_WAIT_S = 60

# Gates against accidental/duplicate runs (ADR-001 rev. 2026-07-30):
# below this many reviews today, the day doesn't count as a study session.
MIN_SESSION_REVIEWS = int(os.environ.get("MIN_SESSION_REVIEWS", "10"))


@contextmanager
def pipeline_lock():
    """Single-writer guard. If the lock is held, the caller exits 0 silently
    (after logging) — concurrent triggers are expected and benign."""
    fd = open(LOCK_FILE, "w")
    try:
        try:
            fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log.info("Otro pipeline ya está corriendo; saliendo sin hacer nada.")
            fd.close()
            raise SystemExit(0)

        fd.write(str(datetime.now()))
        fd.flush()
        try:
            yield
        finally:
            fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
    finally:
        fd.close()


def run_script(name: str) -> None:
    path = SCRIPTS[name]
    if not path.exists():
        log.error("No existe: %s  (ruta: %s)", path.name, path)
        raise SystemExit(1)

    log.info("▶  %s", path.name)
    result = subprocess.run([sys.executable, str(path)], capture_output=False)
    if result.returncode != 0:
        log.error("✗  %s terminó con código %d", path.name, result.returncode)
        raise SystemExit(result.returncode)
    log.info("✓  %s", path.name)


def morning() -> None:
    """Daily pipeline. Reset is NOT included on purpose — run it manually."""
    log.info("═══ Morning pipeline ═══")
    run_script("anki")
    run_script("session")
    run_script("reading")
    log.info("═══ Morning pipeline listo ═══")
    log.info("👉 Cuando termines los ejercicios: python3 run_all.py sync-used")


def sync_used() -> None:
    log.info("═══ Sync used words ═══")
    run_script("used")
    log.info("═══ Sync listo ═══")


def reset_only() -> None:
    log.info("═══ Reset Used Today (manual) ═══")
    run_script("reset")


# ── session-end automation (ADR-001) ─────────────────────────────────────

def notify(message: str, title: str = "English Coach") -> None:
    """macOS notification; never fatal."""
    try:
        script = f'display notification "{message}" with title "{title}"'
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)
    except Exception as exc:
        log.warning("No pude notificar: %s", exc)


def anki_reviews_today() -> int | None:
    """getNumCardsReviewedToday via AnkiConnect, or None if unreachable."""
    payload = json.dumps(
        {"action": "getNumCardsReviewedToday", "version": 6}
    ).encode()
    req = urllib.request.Request(
        ANKI_URL, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        if data.get("error"):
            return None
        return int(data["result"])
    except Exception:
        return None


def wait_for_ankiconnect(max_wait_s: int = ANKICONNECT_WAIT_S) -> int | None:
    deadline = time.monotonic() + max_wait_s
    while True:
        reviews = anki_reviews_today()
        if reviews is not None:
            return reviews
        if time.monotonic() >= deadline:
            return None
        time.sleep(5)


def snapshot_reviews() -> int | None:
    """Today's review count from the add-on snapshot, or None if stale/absent."""
    try:
        data = json.loads((BASE / "data" / "anki_session.json").read_text("utf-8"))
    except Exception:
        return None
    if data.get("date") != datetime.now().date().isoformat():
        return None
    return int(data.get("reviews_today") or 0)


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(status: str, reviews: int | None,
               routine_fired_on: str | None = None) -> None:
    state = {
        "date": datetime.now().date().isoformat(),
        "reviews_processed": reviews,
        "status": status,
        "ts": datetime.now().isoformat(timespec="seconds"),
        # Material generation is once per day: keep the last date we fired the
        # cloud routine so a second study burst doesn't regenerate the day.
        "routine_fired_on": routine_fired_on or load_state().get("routine_fired_on"),
    }
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.rename(STATE_FILE)


def fire_routine(session_id: str, routine_env: str = "ROUTINE_ID",
                 token_env: str = "ROUTINE_FIRE_TOKEN") -> bool:
    """POST to a Claude Code Routine API trigger (ADR-003/004). Never fatal:
    returns True if the cloud routine was fired, False → local-only mode.

    Trigger tokens are scoped per routine — each routine needs its own token
    generated in the claude.ai UI; a token from another routine returns 401."""
    rid = os.environ.get(routine_env, "").strip()
    token = os.environ.get(token_env, "").strip()
    if not (rid and token):
        log.info("(routine: skip — falta %s/%s en .env)", routine_env, token_env)
        return False

    url = f"https://api.anthropic.com/v1/claude_code/routines/{rid}/fire"
    payload = json.dumps({"session_id": session_id}).encode()
    req = urllib.request.Request(url, data=payload, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "experimental-cc-routine-2026-04-01",
    })
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                log.info("Routine disparada (HTTP %s, session %s)",
                         resp.status, session_id)
                return True
        except Exception as exc:
            log.warning("Routine intento %d/3 falló: %s", attempt, exc)
            if attempt < 3:
                time.sleep(5 * attempt)
    log.warning("Routine no disparada; el día queda en modo local (fallback).")
    return False


def _cut_over() -> bool:
    """¿Ya se cortó con Anki? (ADR-011)"""
    try:
        sys.path.insert(0, str(BASE))
        from app import cutover, db as appdb
        conn = appdb.connect()
        try:
            return cutover.done(conn)
        finally:
            conn.close()
    except Exception:       # sin english.db no hay corte que respetar
        return False


def session_end(force: bool = False) -> None:
    log.info("═══ Session-end pipeline ═══")
    if _cut_over():
        # Tras el corte, la app es la única verdad y ella misma dispara el
        # material al cerrar una sentada. Que abrir Anki para mirar algo
        # relance este pipeline sería, en el mejor caso, ruido; en el peor,
        # reimportar estado viejo encima del nuevo.
        log.info("Cut-over hecho: el pipeline de Anki está retirado. "
                 "La app genera su material al cerrar la sentada.")
        return
    reviews = wait_for_ankiconnect()
    if reviews is None:
        # Anki is gone, but the add-on freezes the session to disk before the
        # collection closes — that snapshot is enough to finish the day.
        reviews = snapshot_reviews()
        if reviews is None:
            log.warning("AnkiConnect no respondió en %ss y no hay snapshot de hoy.",
                        ANKICONNECT_WAIT_S)
            save_state("pending", None)
            notify("Anki se cerró antes de sincronizar. Se procesará en tu "
                   "próxima sesión, o abre Anki y corre: run_all.py session-end")
            return
        log.info("AnkiConnect caído; sigo con el snapshot de la sesión (%s reviews).",
                 reviews)

    today = datetime.now().date().isoformat()
    state = load_state()
    if (
        not force
        and state.get("date") == today
        and state.get("status") == "ok"
        and state.get("reviews_processed") == reviews
    ):
        log.info("Sesión ya procesada hoy (%s reviews); nada que hacer.", reviews)
        return

    # Gate 1 — ¿fue una sesión de verdad? Contestar 2 cards por accidente no
    # debe mover Notion ni gastar cuota de Claude.
    if not force and reviews < MIN_SESSION_REVIEWS:
        log.info("Solo %s reviews hoy (mínimo %s); no cuenta como sesión. "
                 "Usa --force si quieres procesarla igual.",
                 reviews, MIN_SESSION_REVIEWS)
        return

    try:
        run_script("anki")
        run_script("session")
        run_script("reading")
        run_script("profile")
        run_script("today")

        # Dual-write to the local SQLite mirror (ADR-006 M0). Never fatal:
        # english.db lagging a day must not break the day's pipeline.
        try:
            run_script("localdb")
        except SystemExit:
            log.warning("local-db sync falló; english.db queda desactualizada "
                        "(corre: run_all.py local-db).")

        # Deja escrito el material de mañana ahora que ya cerraste Anki
        # (ADR-008 D5). Nunca fatal: si el modelo local no responde, el
        # material se pide a mano desde la app.
        try:
            run_script("pregen")
        except SystemExit:
            log.warning("pre-generación falló; el material se puede pedir "
                        "desde la app cuando quieras.")

        # Gate 2 — el material se genera UNA vez al día. Una segunda tanda de
        # estudio sincroniza palabras (barato, local) pero no vuelve a pedirle
        # material a la nube ni pisa lo que ya estás trabajando.
        already = state.get("routine_fired_on") == today
        if already and not force:
            log.info("Material de hoy ya solicitado; no re-disparo la routine.")
            fired = False
        else:
            fired = fire_routine(today)

        save_state("ok", reviews, routine_fired_on=today if fired else None)
        log.info("═══ Session-end listo (%s reviews) ═══", reviews)
        if fired:
            notify(f"Listo ✅ {reviews} reviews. Claude está generando tu "
                   f"material en la nube — llega a Notion en unos minutos. ☁️")
        elif already:
            notify(f"Listo ✅ {reviews} reviews sincronizadas. "
                   f"El material de hoy ya estaba generado.")
        else:
            notify(f"Listo ✅ {reviews} reviews (modo local). Pide a Claude "
                   f"la lectura del día cuando quieras.")
    except BaseException:
        # Distinguish "Anki went away mid-run" (recoverable, expected when you
        # close Anki right after studying) from a genuine failure. The former
        # is not something Eddie should have to act on.
        if anki_reviews_today() is None and snapshot_reviews() is None:
            save_state("pending", reviews)
            log.warning("Anki se cerró durante la corrida y no hay snapshot; "
                        "queda pendiente (nada se pierde).")
            notify("Anki se cerró antes de terminar. Nada se perdió: se "
                   "completa en tu próxima sesión. ⏳")
            return
        save_state("failed", reviews)
        notify(f"⚠️ El pipeline falló. Revisa logs/{today}.log y corre: "
               f"run_all.py session-end")
        raise


def review() -> None:
    """Manual backup for the correction routine (ADR-004). The routine also
    runs on its own cron; this just asks for it now."""
    log.info("═══ Review (corrección) ═══")
    stamp = datetime.now().strftime("%Y-%m-%dT%H:%M")
    if fire_routine(stamp, routine_env="ROUTINE_REVIEW_ID",
                    token_env="ROUTINE_REVIEW_TOKEN"):
        notify("Corrección en camino ☁️ — revisa Notion en unos minutos.")
    else:
        notify("No pude lanzar la corrección. Pídesela a Claude en el chat.")


def local_db() -> None:
    """Refresh data/english.db from Anki + Notion + profile (ADR-006)."""
    log.info("═══ Local DB sync ═══")
    run_script("localdb")


def pregenerate() -> None:
    """Prepara el material del día sin esperar a la próxima sesión."""
    log.info("═══ Pre-generación de material ═══")
    run_script("pregen")


MODES = {
    "morning":     morning,
    "local-db":    local_db,
    "localdb":     local_db,
    "pregenerate": pregenerate,
    "pregen":      pregenerate,
    "review":      review,
    "start":       morning,
    "daily":       morning,
    "session-end": session_end,
    "sync-used":   sync_used,
    "sync":        sync_used,
    "used":        sync_used,
    "reset":       reset_only,
}


if __name__ == "__main__":
    args = [a.lower() for a in sys.argv[1:]]
    force = "--force" in args
    positional = [a for a in args if not a.startswith("--")]
    mode = positional[0] if positional else "morning"
    handler = MODES.get(mode)
    if handler is None:
        print(__doc__)
        raise SystemExit(1)
    if mode == "session-end":
        handler = lambda: session_end(force=force)  # noqa: E731

    try:
        with pipeline_lock():
            handler()
    except SystemExit:
        raise
    except Exception as exc:
        log.exception("Error inesperado: %s", exc)
        raise SystemExit(1)
