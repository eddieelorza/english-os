"""Background job queue (ADR-008 D4/D5) — una tarea a la vez.

Dos problemas que resuelve, y conviene no confundirlos:

1. **La espera.** Generar un podcast local toma ~2 min. Bloquear la petición
   HTTP deja a Eddie mirando un spinner con los ventiladores a tope.
2. **El sobrecalentamiento de verdad.** Pedir una lectura y un podcast a la
   vez lanzaba **dos inferencias en paralelo** peleándose el CPU. Esta cola
   ejecuta estrictamente una tarea a la vez, y ese es el arreglo real.

Lo que NO hace: reducir el cómputo total. La misma generación cuesta lo
mismo; solo deja de ocurrir mientras esperas y deja de solaparse.

El estado vive en SQLite, así que un reinicio del servidor no pierde la cola:
los trabajos que quedaron 'running' se vuelven a encolar al arrancar.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import sqlite3
import sys
import threading
import traceback
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from app import db  # noqa: E402

_worker: "threading.Thread | None" = None
_wake = threading.Event()
_lock = threading.Lock()

KINDS = ("reading", "podcast", "activities", "tip", "writing_task",
         "shadow")


# ── Handlers ─────────────────────────────────────────────────────────────

def _run_reading(conn: sqlite3.Connection, params: dict) -> dict:
    from app import generator
    r = generator.generate_reading(conn, params.get("level"),
                                   int(params.get("minutes", 5)),
                                   params.get("topic", "Random"))
    return {"text_id": r["id"], "title": r["title"],
            "missing_words": r["missing_words"]}


def _run_shadow(conn: sqlite3.Connection, params: dict) -> dict:
    """Bajar + transcribir un vídeo.

    Vive en la cola y no en la petición HTTP por dos razones medidas: un
    vídeo de 3.4 min tardó **309 s** dentro del servidor (Whisper y Kokoro
    peleándose por los hilos del mismo proceso), y una petición de cinco
    minutos se cae sola en cuanto algo la interrumpe. Aquí, además, el worker
    serializa: transcribir deja de competir con una conversación en curso.
    """
    from app import shadowing
    r = shadowing.create(conn, params["url"])
    return {"session_id": r["id"], "title": r["title"],
            "lines": len(r["lines"]), "confidence": r["confidence"]}


def _run_podcast(conn: sqlite3.Connection, params: dict) -> dict:
    from app import podcast
    ep = podcast.generate(conn, int(params.get("minutes", 5)),
                          params.get("topic", "Random"), params.get("level"))
    return {"text_id": ep["id"], "title": ep["title"],
            "turns": len(ep["turns"])}


def _run_activities(conn: sqlite3.Connection, params: dict) -> dict:
    from app import activities
    acts = activities.today_set(conn)
    return {"activities": [{"id": a["id"], "kind": a["kind"],
                            "questions": len(a["questions"])} for a in acts]}


def _run_tip(conn: sqlite3.Connection, params: dict) -> dict:
    from app import coach
    tip = coach.grammar_tip(conn)
    return {"tip": tip}


def _run_writing_task(conn: sqlite3.Connection, params: dict) -> dict:
    """El encargo de writing del día, listo antes de que abra la pestaña.

    Generarlo tarda ~10 s. Diez segundos de esqueleto cada vez que abres
    Writing son fricción, y reducir fricción es justamente el punto de este
    modo (M20).
    """
    from app import writing
    task = writing.steps(conn)
    _cache_writing_task(conn, task)
    return {"steps": len(task.get("steps", [])), "from": task.get("from_name")}


HANDLERS = {"reading": _run_reading, "podcast": _run_podcast,
            "shadow": _run_shadow,
            "activities": _run_activities, "tip": _run_tip,
            "writing_task": _run_writing_task}


def _cache_writing_task(conn: sqlite3.Connection, task: dict) -> None:
    conn.execute(
        "INSERT INTO settings (key, value, updated_at) VALUES (?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
        "updated_at=excluded.updated_at",
        (f"writing_task_{db.study_day()}",
         json.dumps(task, ensure_ascii=False), db.now_iso()))
    conn.commit()


def cached_writing_task(conn: sqlite3.Connection) -> "dict | None":
    row = conn.execute("SELECT value FROM settings WHERE key=?",
                       (f"writing_task_{db.study_day()}",)).fetchone()
    return json.loads(row["value"]) if row else None


# ── Queue API ────────────────────────────────────────────────────────────

def _row(r) -> dict:
    d = dict(r)
    d["params"] = json.loads(d["params"]) if d["params"] else {}
    d["result"] = json.loads(d["result"]) if d["result"] else None
    return d


def enqueue(conn: sqlite3.Connection, kind: str, params: "dict | None" = None,
            dedupe: bool = True) -> dict:
    """Encola un trabajo. Con `dedupe`, si ya hay uno igual esperando o
    corriendo devuelve ese — pedir dos veces el mismo podcast no debe
    generar dos."""
    if kind not in KINDS:
        raise ValueError(f"unknown job kind: {kind}")
    payload = json.dumps(params or {}, sort_keys=True)
    if dedupe:
        existing = conn.execute(
            "SELECT * FROM jobs WHERE kind=? AND params=? "
            "AND status IN ('queued','running') ORDER BY id LIMIT 1",
            (kind, payload)).fetchone()
        if existing:
            return _row(existing)
    cur = conn.execute(
        "INSERT INTO jobs (kind, params, status, created_at) "
        "VALUES (?,?, 'queued', ?)", (kind, payload, db.now_iso()))
    conn.commit()
    job = conn.execute("SELECT * FROM jobs WHERE id=?", (cur.lastrowid,)).fetchone()
    # NO se arranca el worker aquí. Encolar es una escritura en una tabla; que
    # además levante un hilo de fondo convierte cualquier llamada —incluida la
    # de un test— en un proceso que se pone a generar por su cuenta. Siete
    # archivos de test tenían que parchear `ensure_worker` para evitarlo, y
    # bastó que uno se olvidara para dejar un worker suelto que bloqueaba la
    # suite entera. Lo arranca el servidor al iniciar (`_start_worker`), que
    # es quien tiene un ciclo de vida donde eso significa algo.
    _wake.set()
    return _row(job)


def get(conn: sqlite3.Connection, job_id: int) -> "dict | None":
    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return _row(row) if row else None


def recent(conn: sqlite3.Connection, limit: int = 20) -> "list[dict]":
    return [_row(r) for r in conn.execute(
        "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,))]


def pending(conn: sqlite3.Connection) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')"
    ).fetchone()[0]


# ── Worker ───────────────────────────────────────────────────────────────

def _lock_path() -> Path:
    return Path(os.environ.get("ENGLISH_JOBS_LOCK", BASE / "logs" / ".jobs.lock"))


# Candado DENTRO del proceso. `flock` sólo sirve entre procesos: la versión
# anterior afirmaba que "también serializa hilos del mismo proceso" y es falso
# en macOS. Con dos hilos —el worker y el `while run_one(...)` de
# `pregenerate()`, que corre en el hilo de la petición— el segundo no esperaba
# turno: `open(path, "w")` trunca, y truncar un archivo que este mismo proceso
# tiene bloqueado devuelve EDEADLK. Eso mataba el hilo del worker y los
# trabajos se apilaban en silencio durante días (2026-09-03).
_process_lock = threading.RLock()

# Profundidad de reentrada. El RLock deja volver a entrar al mismo hilo, pero
# `flock` NO: una llamada anidada abriría un segundo descriptor y se quedaría
# esperando un candado que ella misma tiene. Sólo la entrada más externa toca
# el archivo. Se lee y escribe con `_process_lock` en la mano, así que no
# necesita protección propia.
_lock_depth = 0


@contextlib.contextmanager
def _exclusive():
    """Un candado alrededor de claim + ejecución, en dos capas.

    - `_process_lock` serializa los hilos de ESTE proceso. Es reentrante para
      que un handler que acabe llamando a `run_one` no se bloquee solo.
    - `flock` serializa contra OTROS procesos (`session-end`, un script
      manual): sin él, la pre-generación y una petición desde la app lanzarían
      dos inferencias en paralelo, que es el sobrecalentamiento que la cola
      existe para evitar.

    Se espera el turno en vez de rendirse: el trabajo no se pierde, sólo se
    hace después.
    """
    global _lock_depth
    path = _lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _process_lock:
        if _lock_depth:
            _lock_depth += 1
            try:
                yield
            finally:
                _lock_depth -= 1
            return
        # O_RDWR|O_CREAT y NO modo "w": "w" trunca, y truncar un archivo con
        # un lock advisory encima es justo lo que dispara EDEADLK en macOS.
        # El contenido del archivo no importa; sólo que exista.
        fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            _lock_depth = 1
            try:
                yield
            finally:
                _lock_depth = 0
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


# Nombre público: lo usa quien genera fuera de la cola (la rutina de Claude
# Code produce el audio del podcast) y necesita el mismo turno.
exclusive = _exclusive


def _claim_next(conn: sqlite3.Connection) -> "dict | None":
    """Claim the next job **atomically**.

    A SELECT-then-UPDATE would let two claimants take the same job: the
    server's worker thread and the `session-end` pipeline run in different
    processes against the same file. A single conditional UPDATE ... RETURNING
    can only succeed once, because SQLite serializes writers and the second
    attempt no longer sees `status='queued'` on that row.
    """
    cur = conn.execute(
        "UPDATE jobs SET status='running', started_at=? "
        "WHERE id = (SELECT id FROM jobs WHERE status='queued' ORDER BY id LIMIT 1) "
        "AND status='queued' RETURNING id", (db.now_iso(),))
    row = cur.fetchone()
    conn.commit()
    return get(conn, row[0]) if row else None


def run_one(conn: "sqlite3.Connection | None" = None) -> "dict | None":
    """Ejecuta el siguiente trabajo. Síncrono a propósito: también lo usa el
    pipeline de `session-end`, donde no hay servidor corriendo."""
    own = conn is None
    conn = conn or db.connect()
    try:
        with _exclusive():
            job = _claim_next(conn)
            if job is None:
                return None
            try:
                result = HANDLERS[job["kind"]](conn, job["params"])
                conn.execute(
                    "UPDATE jobs SET status='done', result=?, finished_at=? WHERE id=?",
                    (json.dumps(result, ensure_ascii=False), db.now_iso(), job["id"]))
            except Exception as exc:  # noqa: BLE001 — a failure must not kill the queue
                conn.execute(
                    "UPDATE jobs SET status='failed', error=?, finished_at=? WHERE id=?",
                    (f"{type(exc).__name__}: {exc}"[:500], db.now_iso(), job["id"]))
                print(f"job {job['id']} ({job['kind']}) falló:\n"
                      f"{traceback.format_exc(limit=3)}")
            conn.commit()
            return get(conn, job["id"])
    finally:
        if own:
            conn.close()


def _loop() -> None:
    """El hilo trabajador. Sobrevive a sus propios fallos.

    Antes, una excepción cualquiera mataba el hilo y la app dejaba de generar
    **en silencio**: ni un job en 'failed', ni un aviso, sólo cosas encoladas
    para siempre. Un fallo tiene que costar un trabajo, no la generación
    entera. Se espera antes de reintentar para no quemar la CPU con un error
    que se repite.
    """
    conn = db.connect()
    try:
        while True:
            try:
                worked = run_one(conn) is not None
            except Exception:  # noqa: BLE001 — el hilo no se puede morir
                traceback.print_exc()
                worked = False
                _wake.wait(timeout=5)
            if not worked:
                _wake.clear()
                _wake.wait(timeout=30)
    finally:
        conn.close()


def ensure_worker() -> None:
    """Arranca el hilo trabajador una sola vez. Un hilo = una inferencia."""
    global _worker
    with _lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_loop, name="english-os-jobs",
                                       daemon=True)
            _worker.start()


def requeue_orphans(conn: sqlite3.Connection) -> int:
    """Un reinicio a media generación deja trabajos en 'running' que nadie
    está ejecutando. Vuelven a la cola en vez de quedarse colgados."""
    n = conn.execute("SELECT COUNT(*) FROM jobs WHERE status='running'").fetchone()[0]
    if n:
        conn.execute("UPDATE jobs SET status='queued', started_at=NULL "
                     "WHERE status='running'")
        conn.commit()
    return n


# ── Pre-generación (session-end) ─────────────────────────────────────────

def enqueue_daily(conn: sqlite3.Connection) -> dict:
    """Pide el material del día SIN esperarlo.

    Lo usan los dos disparadores — el cierre de sentada en la app y
    `session-end` desde Anki — así que la guarda contra duplicar vive aquí y
    no en cada uno.
    """
    from app import generator
    reason = generator.skip_reason(conn, db.study_day())
    queued = [enqueue(conn, "activities")["id"], enqueue(conn, "tip")["id"],
              enqueue(conn, "writing_task")["id"]]
    if reason is None:
        queued.append(
            enqueue(conn, "reading", {"minutes": 5, "topic": "Random"})["id"])
    return {"queued": queued, "reading_skipped": reason is not None,
            "reading_skip_reason": reason}


def pregenerate(conn: "sqlite3.Connection | None" = None) -> dict:
    """Deja listo el material del día.

    Se dispara al cerrar una sentada en la app y, mientras Anki siga en uso,
    también desde `session-end`. Por eso **no puede duplicar**: si la lectura
    de hoy ya existe no se pide otra. Las actividades ya son idempotentes por
    `UNIQUE(date, kind)`; la lectura no lo era y se generaba una segunda.
    """
    own = conn is None
    conn = conn or db.connect()
    try:
        from app import pause
        if pause.is_paused(conn):
            return {"skipped": "paused"}

        asked = enqueue_daily(conn)
        queued, has_reading = asked["queued"], asked["reading_skipped"]
        done = []
        while run_one(conn) is not None:
            done.append(True)
        return {"queued": queued, "processed": len(done),
                "reading_skipped": has_reading,
                "failed": [j["id"] for j in recent(conn, 10)
                           if j["status"] == "failed" and j["id"] in queued]}
    finally:
        if own:
            conn.close()


if __name__ == "__main__":
    print("pregenerate →", pregenerate())
