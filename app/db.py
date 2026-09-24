"""SQLite system of record for the English Learning OS (ADR-006).

Single file at data/english.db (override with ENGLISH_DB_PATH). The SQL is
kept portable — no SQLite-only features beyond pragmas — so a future move to
Postgres/Supabase is a connection-string change, not a rewrite (ADR-006 D1).

Word status model (LingQ-style): NEW → LEARNING → FAMILIAR → MASTERED.
Derivation from Anki card state lives in `derive_status` and is documented in
ADR-006; FSRS (M4) will refine it with real retention data.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BASE / "data" / "english.db"

SCHEMA_VERSION = 1

STATUSES = ("NEW", "LEARNING", "FAMILIAR", "MASTERED")
KINDS = ("word", "phrasal_verb", "expression", "sentence")

DDL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS words (
    id              INTEGER PRIMARY KEY,
    word            TEXT NOT NULL,
    normalized      TEXT NOT NULL,
    kind            TEXT NOT NULL DEFAULT 'word',
    status          TEXT NOT NULL DEFAULT 'NEW',
    cefr            TEXT,
    meaning_en      TEXT,
    meaning_es      TEXT,
    pronunciation   TEXT,
    example_en      TEXT,
    example_es      TEXT,
    source          TEXT,
    deck            TEXT,
    anki_note_id    INTEGER UNIQUE,
    notion_page_id  TEXT UNIQUE,
    ease            REAL,
    interval_days   INTEGER,
    lapses          INTEGER,
    review_count    INTEGER,
    times_used      INTEGER NOT NULL DEFAULT 0,
    last_reviewed_on TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_words_normalized ON words(normalized);
CREATE INDEX IF NOT EXISTS idx_words_status     ON words(status);

CREATE TABLE IF NOT EXISTS review_history (
    id               INTEGER PRIMARY KEY,
    word_id          INTEGER NOT NULL REFERENCES words(id),
    reviewed_at      TEXT NOT NULL,
    rating           INTEGER,
    interval_days    REAL,
    last_interval_days REAL,
    ease             REAL,
    took_ms          INTEGER,
    review_kind      TEXT,
    source           TEXT NOT NULL DEFAULT 'anki',
    anki_revlog_id   INTEGER UNIQUE,
    anki_card_id     INTEGER
);
CREATE INDEX IF NOT EXISTS idx_review_word ON review_history(word_id);
CREATE INDEX IF NOT EXISTS idx_review_at   ON review_history(reviewed_at);

CREATE TABLE IF NOT EXISTS errors (
    id               INTEGER PRIMARY KEY,
    date             TEXT,
    category         TEXT,
    error            TEXT,
    original         TEXT,
    correction       TEXT,
    explanation      TEXT,
    source           TEXT,
    status           TEXT,
    priority         TEXT,
    recurrences      INTEGER NOT NULL DEFAULT 1,
    last_practiced_on TEXT,
    notion_page_id   TEXT UNIQUE,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    date            TEXT PRIMARY KEY,
    cards_reviewed  INTEGER,
    introduced      INTEGER,
    again           INTEGER,
    again_rate      REAL,
    words_produced  INTEGER,
    errors_total    INTEGER,
    reading_minutes REAL,
    speaking_minutes REAL,
    updated_at      TEXT NOT NULL
);

-- Persisted preferences (session length, daily caps). Key/value on purpose:
-- these are single-user knobs, not a domain model worth a column each.
CREATE TABLE IF NOT EXISTS settings (
    key             TEXT PRIMARY KEY,
    value           TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- One sitting at the Review deck (M16b). NOT the same as `sessions`, which is
-- the daily rollup: several study_sessions can happen in one day.
CREATE TABLE IF NOT EXISTS study_sessions (
    id               INTEGER PRIMARY KEY,
    started_at       TEXT NOT NULL,
    ended_at         TEXT,
    mode             TEXT NOT NULL,      -- 'time' | 'counts'
    minutes          INTEGER,            -- requested budget, time mode only
    planned_new      INTEGER NOT NULL,
    planned_reviews  INTEGER NOT NULL,
    -- Progreso se cuenta por id de review, no por reloj: now_iso() tiene
    -- resolución de segundo y un repaso hecho en el mismo segundo en que
    -- abres la sesión se contaría dentro de ella.
    from_review_id   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_study_sessions_open
    ON study_sessions(ended_at, started_at);

-- Cada vez que el rezago se reparte (M16c). Se registra para que el coste sea
-- auditable: repartir retrasa repasos, y eso hay que poder mirarlo.
CREATE TABLE IF NOT EXISTS backlog_spreads (
    id              INTEGER PRIMARY KEY,
    date            TEXT NOT NULL,
    cards           INTEGER NOT NULL,
    days            INTEGER NOT NULL,
    kept_today      INTEGER NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_backlog_spreads_date ON backlog_spreads(date);

CREATE TABLE IF NOT EXISTS jobs (
    id              INTEGER PRIMARY KEY,
    kind            TEXT NOT NULL,
    params          TEXT,
    status          TEXT NOT NULL,
    result          TEXT,
    error           TEXT,
    created_at      TEXT NOT NULL,
    started_at      TEXT,
    finished_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, id);

CREATE TABLE IF NOT EXISTS pauses (
    id              INTEGER PRIMARY KEY,
    start_date      TEXT NOT NULL,
    end_date        TEXT,
    reason          TEXT,
    days_paused     INTEGER,
    cards_spread    INTEGER,
    ramp_days       INTEGER,
    created_at      TEXT NOT NULL,
    resumed_at      TEXT
);

CREATE TABLE IF NOT EXISTS explanations (
    id              INTEGER PRIMARY KEY,
    sentence_hash   TEXT UNIQUE NOT NULL,
    sentence        TEXT NOT NULL,
    meaning         TEXT,
    grammar         TEXT,
    spanish         TEXT,
    watch_out       TEXT,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activities (
    id              INTEGER PRIMARY KEY,
    date            TEXT NOT NULL,
    kind            TEXT NOT NULL,
    title           TEXT,
    payload         TEXT NOT NULL,
    answers         TEXT,
    score           INTEGER,
    total           INTEGER,
    seconds         INTEGER,
    completed_at    TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_activities_date ON activities(date);
/* One set per kind per day. Generation takes ~a minute on a local model, so
   overlapping requests would otherwise each insert their own copy. */
CREATE UNIQUE INDEX IF NOT EXISTS idx_activities_day_kind
    ON activities(date, kind);

CREATE TABLE IF NOT EXISTS texts (
    id              INTEGER PRIMARY KEY,
    kind            TEXT NOT NULL,
    title           TEXT,
    date            TEXT,
    level           TEXT,
    topic           TEXT,
    body            TEXT,
    source          TEXT,
    words_produced  INTEGER,
    errors_count    INTEGER,
    corrected       INTEGER,
    notion_page_id  TEXT UNIQUE,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- Conversación hablada (M19). Los turnos van en su propia tabla y no como un
-- blob JSON: el resumen del final necesita recorrerlos, y las estadísticas
-- querrán contar minutos hablados por día sin parsear nada.
-- Shadowing sobre vídeo (M20). El audio se guarda en data/media/shadow/ y
-- aquí sólo la referencia: la base no debe engordar con binarios.
CREATE TABLE IF NOT EXISTS shadow_sessions (
    id           INTEGER PRIMARY KEY,
    url          TEXT NOT NULL,
    video_id     TEXT UNIQUE,
    title        TEXT,
    channel      TEXT,
    seconds      REAL,
    audio_path   TEXT,
    -- Confianza media de la transcripción; se enseña para no presentar una
    -- transcripción dudosa como si fuera cierta.
    confidence   REAL,
    date         TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS shadow_lines (
    id          INTEGER PRIMARY KEY,
    session_id  INTEGER NOT NULL REFERENCES shadow_sessions(id) ON DELETE CASCADE,
    idx         INTEGER NOT NULL,
    start_s     REAL NOT NULL,
    end_s       REAL NOT NULL,
    text        TEXT NOT NULL,
    confidence  REAL,
    done_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_shadow_lines ON shadow_lines(session_id, idx);

CREATE TABLE IF NOT EXISTS conversations (
    id          INTEGER PRIMARY KEY,
    date        TEXT NOT NULL,
    topic       TEXT,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    turns       INTEGER NOT NULL DEFAULT 0,
    summary     TEXT,          -- JSON: <=3 correcciones + 1 fortaleza
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_turns (
    id              INTEGER PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    idx             INTEGER NOT NULL,
    speaker         TEXT NOT NULL,   -- 'eddie' | 'partner'
    text            TEXT NOT NULL,
    audio_path      TEXT,
    seconds         REAL,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conv_turns
    ON conversation_turns(conversation_id, idx);
"""

# English phrasal-verb particles, for `derive_kind`.
_PARTICLES = {
    "up", "down", "in", "out", "on", "off", "over", "under", "away", "back",
    "through", "along", "around", "about", "across", "by", "forward", "after",
    "into", "for", "with", "to",
}


# ── Tiempo: dos marcos, a propósito ──────────────────────────────────────
#
# `now_iso()`   reloj de pared local, ingenuo. Es lo que lleva TODO el
#               historial (1,088 filas) y todo lo que se archiva por día.
# `now_utc()`   aware en UTC. Es el marco de FSRS: `words.fsrs_due` viene de
#               la librería y siempre trae offset.
#
# Los dos conviven y **no deben compararse entre sí**. Cada comparación del
# código vive dentro de un solo marco; estos helpers existen para que siga
# siendo así por decisión y no por casualidad. No se migra el historial a UTC:
# el beneficio es teórico para un usuario en una sola zona horaria y reescribir
# 1,088 filas es un riesgo real (ADR-010).

def now_iso() -> str:
    """Reloj de pared local, sin zona. Para historial y archivo por día."""
    return datetime.now().isoformat(timespec="seconds")


def now_utc() -> datetime:
    """Instante aware en UTC. Para todo lo que toque scheduling FSRS."""
    return datetime.now(timezone.utc)


def rollover_hour() -> int:
    """Hora a la que empieza el día de estudio. Anki usa las 4:00 y la razón
    es buena: estudiar a las 00:30 es seguir con el día anterior, no empezar
    uno nuevo. Sin esto se rompen la racha y el cupo de palabras nuevas justo
    cuando alguien estudia de madrugada."""
    try:
        return max(0, min(23, int(os.environ.get("STUDY_DAY_ROLLOVER_HOUR", 4))))
    except ValueError:
        return 4


def study_day(now: "datetime | None" = None) -> str:
    """El día de estudio al que pertenece este instante (YYYY-MM-DD)."""
    now = now or datetime.now()
    if now.hour < rollover_hour():
        now = now - timedelta(days=1)
    return now.date().isoformat()


def study_day_start(day: "str | None" = None) -> str:
    """Instante local en que empezó (o empieza) un día de estudio."""
    d = date.fromisoformat(day or study_day())
    return datetime(d.year, d.month, d.day, rollover_hour()).isoformat(
        timespec="seconds")


def normalize(word: str) -> str:
    return " ".join((word or "").lower().split())


def derive_kind(word: str) -> str:
    """word | phrasal_verb | expression | sentence — cheap heuristic (ADR-006)."""
    tokens = normalize(word).split()
    if len(tokens) <= 1:
        return "word"
    if len(tokens) in (2, 3) and any(t in _PARTICLES for t in tokens[1:]):
        return "phrasal_verb"
    if len(tokens) >= 6 or word.rstrip().endswith((".", "?", "!")):
        return "sentence"
    return "expression"


def derive_status(queue: int, interval_days: int, lapses: int) -> str:
    """Anki card state → LingQ-style status (rule documented in ADR-006).

    queue: 0=new, 1/3=learning-relearn, 2=review, negatives=suspended/buried
    (suspended/buried keep whatever the interval says — being hidden from the
    scheduler doesn't change how well the word is known).
    """
    if queue == 0:
        return "NEW"
    if queue in (1, 3):
        return "LEARNING"
    if interval_days >= 90 and lapses <= 1:
        return "MASTERED"
    if interval_days >= 21:
        return "FAMILIAR"
    return "LEARNING"


# Guarded column additions (portable, idempotent). (table, column, type)
MIGRATIONS = (
    ("texts", "reading_seconds", "INTEGER"),  # M2: time spent reading
    ("texts", "finished_at", "TEXT"),         # M2: reading completed stamp
    ("texts", "questions", "TEXT"),           # M3: comprehension questions (JSON)
    ("texts", "words_target", "TEXT"),        # M3: vocabulary the AI had to use (JSON)
    ("words", "fsrs_card", "TEXT"),           # M4: serialized FSRS card (JSON)
    ("words", "fsrs_due", "TEXT"),            # M4: denormalized due date (UTC ISO)
    ("words", "fsrs_since", "TEXT"),          # M4: date the card was introduced
    ("texts", "correction", "TEXT"),          # M6: speaking correction (JSON)
    ("texts", "audio_path", "TEXT"),          # M6: recorded audio file
    ("words", "audio_word", "TEXT"),          # M8: deck MP3 of the word
    ("words", "audio_example", "TEXT"),       # M8: deck MP3 of the example
    ("words", "image_path", "TEXT"),          # M8: deck illustration
    ("texts", "tts_path", "TEXT"),            # M8: generated narration
    ("texts", "tts_marks", "TEXT"),           # M8: sentence timings (JSON)
    ("sessions", "listening_minutes", "REAL"),  # M11: podcast time
    ("texts", "quiz_score", "INTEGER"),       # M12: comprehension result
    ("texts", "quiz_total", "INTEGER"),
    ("texts", "quiz_answers", "TEXT"),
    # M16b: el DDL de study_sessions nació sin esta columna y CREATE TABLE IF
    # NOT EXISTS no toca una tabla ya creada — hace falta la migración.
    ("study_sessions", "from_review_id", "INTEGER NOT NULL DEFAULT 0"),
    # M16c: días de retraso con que se contestó la carta — la factura del
    # reparto del rezago.
    ("review_history", "days_late", "REAL"),

    # M17a — espejo consultable del estado FSRS. La verdad sigue siendo el
    # JSON de `fsrs_card`; estas columnas existen porque no se puede hacer
    # WHERE ni GROUP BY dentro de un blob, y la cola diaria necesita separar
    # LEARNING de REVIEW en SQL. Se rellenan en cada answer y con `backfill`.
    ("words", "card_state", "TEXT"),        # NEW|LEARNING|REVIEW|RELEARNING
    ("words", "learning_step", "INTEGER"),  # NULL en REVIEW
    ("words", "stability", "REAL"),
    ("words", "difficulty", "REAL"),

    # M17a — ReviewLog completo. Una fila por respuesta, nunca se sobreescribe.
    # Sin el antes/después no se puede reconstruir por qué una carta acabó
    # donde acabó, ni mostrar estadísticas por palabra.
    ("review_history", "state_before", "TEXT"),
    ("review_history", "state_after", "TEXT"),
    ("review_history", "step_before", "INTEGER"),
    ("review_history", "step_after", "INTEGER"),
    ("review_history", "stability_before", "REAL"),
    ("review_history", "stability_after", "REAL"),
    ("review_history", "difficulty_before", "REAL"),
    ("review_history", "difficulty_after", "REAL"),
    ("review_history", "previous_due", "TEXT"),
    ("review_history", "elapsed_days", "REAL"),

    # ADR-014 — el día de estudio en que el triage dio la palabra por perdida
    # (recuperabilidad < 50%). Mientras esté puesto, la palabra vuelve a goteo
    # en el cupo de nuevas. Se borra al contestarla. No toca el estado FSRS.
    ("words", "comeback_on", "TEXT"),
    ("backlog_spreads", "comeback", "INTEGER"),
    # ADR-014 Fase 3 — 1 si el repaso fue un reencuentro: sin esto no se puede
    # medir si el goteo funciona.
    ("review_history", "comeback", "INTEGER"),
    # La fecha en que una palabra todavía NEW apareció en una lectura que
    # terminó. Esas entran antes al mazo: ya tienen un contexto donde agarrarse.
    ("words", "seen_in_text", "TEXT"),
    # ADR-015 — presupuesto de la sentada en RESPUESTAS (repeticiones
    # incluidas). NULL en las sentadas por tiempo o por números.
    ("study_sessions", "budget", "INTEGER"),
)

POST_MIGRATION_INDEXES = (
    # La cola diaria separa LEARNING de REVIEW y ordena por vencimiento.
    "CREATE INDEX IF NOT EXISTS idx_words_state_due "
    "ON words(card_state, fsrs_due)",
)


def _migrate(conn: sqlite3.Connection) -> None:
    for table, col, coltype in MIGRATIONS:
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if col not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")

    # Índices que dependen de columnas añadidas arriba: no pueden vivir en el
    # DDL, que se ejecuta ANTES de las migraciones y no vería la columna.
    for stmt in POST_MIGRATION_INDEXES:
        conn.execute(stmt)


def connect(db_path: "str | Path | None" = None) -> sqlite3.Connection:
    """Open (creating if needed) the DB with the v1 schema applied."""
    path = Path(db_path or os.environ.get("ENGLISH_DB_PATH") or DEFAULT_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(DDL)
    _migrate(conn)
    conn.execute(
        "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO NOTHING",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
    return conn


# ── Upserts ──────────────────────────────────────────────────────────────
# Business keys: anki_note_id / notion_page_id on words, anki_revlog_id on
# review_history, notion_page_id on errors/texts, date on sessions. All
# upserts are idempotent so importers can re-run daily (dual-write step).

_WORD_FIELDS = (
    "word", "normalized", "kind", "status", "cefr", "meaning_en", "meaning_es",
    "pronunciation", "example_en", "example_es", "source", "deck",
    "anki_note_id", "notion_page_id", "ease", "interval_days", "lapses",
    "review_count", "times_used", "last_reviewed_on",
    "audio_word", "audio_example", "image_path",
)


def _find_word(conn: sqlite3.Connection, data: dict) -> "sqlite3.Row | None":
    if data.get("anki_note_id") is not None:
        row = conn.execute("SELECT * FROM words WHERE anki_note_id=?",
                           (data["anki_note_id"],)).fetchone()
        if row:
            return row
    if data.get("notion_page_id"):
        row = conn.execute("SELECT * FROM words WHERE notion_page_id=?",
                           (data["notion_page_id"],)).fetchone()
        if row:
            return row
    if data.get("normalized"):
        return conn.execute("SELECT * FROM words WHERE normalized=?",
                            (data["normalized"],)).fetchone()
    return None


def upsert_word(conn: sqlite3.Connection, data: dict,
                overwrite: "tuple[str, ...]" = ()) -> int:
    """Insert or merge a word; returns its id.

    Merge policy: existing non-empty values win, incoming values only fill
    gaps — except fields listed in `overwrite`, which always take the incoming
    value (used for SRS stats where the source is authoritative).
    """
    data = dict(data)
    data.setdefault("normalized", normalize(data.get("word", "")))
    data.setdefault("kind", derive_kind(data.get("word", "")))
    unknown = set(data) - set(_WORD_FIELDS)
    if unknown:
        raise ValueError(f"unknown word fields: {unknown}")

    existing = _find_word(conn, data)
    ts = now_iso()
    if existing is None:
        cols = [f for f in _WORD_FIELDS if data.get(f) is not None]
        sql = (f"INSERT INTO words ({', '.join(cols)}, created_at, updated_at) "
               f"VALUES ({', '.join('?' * len(cols))}, ?, ?)")
        cur = conn.execute(sql, [data[c] for c in cols] + [ts, ts])
        return cur.lastrowid

    updates: dict = {}
    for field in _WORD_FIELDS:
        incoming = data.get(field)
        if incoming is None:
            continue
        current = existing[field]
        if field in overwrite:
            if incoming != current:
                updates[field] = incoming
        elif current in (None, "", 0) and incoming != current:
            updates[field] = incoming
    if updates:
        updates["updated_at"] = ts
        sets = ", ".join(f"{k}=?" for k in updates)
        conn.execute(f"UPDATE words SET {sets} WHERE id=?",
                     list(updates.values()) + [existing["id"]])
    return existing["id"]


def insert_review(conn: sqlite3.Connection, data: dict) -> bool:
    """Insert one review; returns False if already imported (idempotent by
    anki_revlog_id)."""
    if data.get("anki_revlog_id") is not None:
        dup = conn.execute("SELECT 1 FROM review_history WHERE anki_revlog_id=?",
                           (data["anki_revlog_id"],)).fetchone()
        if dup:
            return False
    cols = list(data)
    conn.execute(
        f"INSERT INTO review_history ({', '.join(cols)}) "
        f"VALUES ({', '.join('?' * len(cols))})",
        [data[c] for c in cols],
    )
    return True


def upsert_error(conn: sqlite3.Connection, data: dict) -> int:
    """Upsert an Error Library row by notion_page_id (source is authoritative)."""
    ts = now_iso()
    page_id = data.get("notion_page_id")
    existing = None
    if page_id:
        existing = conn.execute("SELECT id FROM errors WHERE notion_page_id=?",
                                (page_id,)).fetchone()
    if existing:
        cols = [k for k in data if k != "notion_page_id"]
        sets = ", ".join(f"{k}=?" for k in cols)
        conn.execute(f"UPDATE errors SET {sets}, updated_at=? WHERE id=?",
                     [data[c] for c in cols] + [ts, existing["id"]])
        return existing["id"]
    cols = list(data)
    cur = conn.execute(
        f"INSERT INTO errors ({', '.join(cols)}, created_at, updated_at) "
        f"VALUES ({', '.join('?' * len(cols))}, ?, ?)",
        [data[c] for c in cols] + [ts, ts],
    )
    return cur.lastrowid


def upsert_session(conn: sqlite3.Connection, date: str, data: dict) -> None:
    cols = list(data)
    sets = ", ".join(f"{k}=excluded.{k}" for k in cols)
    conn.execute(
        f"INSERT INTO sessions (date, {', '.join(cols)}, updated_at) "
        f"VALUES (?, {', '.join('?' * len(cols))}, ?) "
        f"ON CONFLICT(date) DO UPDATE SET {sets}, updated_at=excluded.updated_at",
        [date] + [data[c] for c in cols] + [now_iso()],
    )


def upsert_text(conn: sqlite3.Connection, data: dict) -> int:
    """Upsert a writing/reading text by notion_page_id."""
    ts = now_iso()
    page_id = data.get("notion_page_id")
    existing = None
    if page_id:
        existing = conn.execute("SELECT id FROM texts WHERE notion_page_id=?",
                                (page_id,)).fetchone()
    if existing:
        cols = [k for k in data if k != "notion_page_id"]
        sets = ", ".join(f"{k}=?" for k in cols)
        conn.execute(f"UPDATE texts SET {sets}, updated_at=? WHERE id=?",
                     [data[c] for c in cols] + [ts, existing["id"]])
        return existing["id"]
    cols = list(data)
    cur = conn.execute(
        f"INSERT INTO texts ({', '.join(cols)}, created_at, updated_at) "
        f"VALUES ({', '.join('?' * len(cols))}, ?, ?)",
        [data[c] for c in cols] + [ts, ts],
    )
    return cur.lastrowid
