"""In-app spaced repetition with FSRS (ADR-006 D4, M4).

The same algorithm modern Anki uses, via the official `fsrs` package. Seeding
replays each word's real Anki review history (imported in M0) through the
scheduler, so the app starts with honest memory states instead of guesses.

Anki keeps running in parallel until Eddie cuts over — in-app reviews are
logged to review_history with source='fsrs' and never touch Anki.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fsrs import Card, Rating, Scheduler, State

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from app import db  # noqa: E402

NEW_PER_DAY = 5  # matches Eddie's real Anki cadence (learner_profile history)

# A card rated Again comes back in 1 minute, then 10 (FSRS learning steps).
# Waiting out a literal minute with an empty screen is absurd, so once nothing
# else is left we show those cards early — Anki calls this the learn-ahead
# limit. Without it the session ends on "deck is clear" while the word you
# just failed is still unlearned (ADR-009 D2).
#
# DOS ventanas, y la diferencia entre ellas es el punto (ADR-009 D2 rev.2):
#
# - Mientras QUEDE otra cosa que hacer (vencidas o nuevas), la ventana es
#   corta: 3 minutos. Con la ventana ancha de Anki (20 min) una card que
#   acababas de ACERTAR volvía enseguida, la sentada se alimentaba sola y un
#   plan de 9 cards se iba a 16.
# - Cuando ya NO queda nada más, la ventana se abre hasta cubrir la escalera
#   de aprendizaje entera (`deck.longest_step_minutes`). Con 3 minutos fijos,
#   una card en el paso de 10 min era invisible: la app decía "nothing to
#   study" con trabajo pendiente y la palabra reaparecía un rato después.
#   Esperar mirando una pantalla vacía no enseña nada.
#
# La regla se lee sola: el reloj manda mientras haya alternativa; cuando no
# la hay, no hay nada que esperar.
LEARN_AHEAD_MINUTES = 3

# fsrs serialises Card.state as an int; 1 = Learning, 3 = Relearning.
_UNLEARNED_STATES = (int(State.Learning), int(State.Relearning))

RATINGS = {1: Rating.Again, 2: Rating.Hard, 3: Rating.Good, 4: Rating.Easy}
KIND_BY_STATE = {State.Learning: "learn", State.Review: "review",
                 State.Relearning: "relearn"}

# NEW no es un estado de FSRS: la librería sólo conoce Learning/Review/
# Relearning. "Nueva" es la ausencia de card (fsrs_card IS NULL).
STATE_NAMES = {int(State.Learning): "LEARNING", int(State.Review): "REVIEW",
               int(State.Relearning): "RELEARNING"}


def _scheduler(conn: "sqlite3.Connection | None" = None) -> Scheduler:
    """El scheduler de la app, uno solo, con los parámetros del mazo.

    El fuzz (activado por defecto en FSRS) reparte los vencimientos al azar
    para que no se apelmacen. Se apaga a propósito: con fuzz, seis llamadas
    idénticas devuelven 9, 9, 7, 11, 8, 9 días — y entonces el intervalo que
    la UI promete encima de un botón no es el que se aplica al pulsarlo. En
    intervalos largos la diferencia llega a ±25 días.

    Lo que se pierde (evitar que las cartas vuelvan en bloque) ya lo cubre el
    reparto del rezago de M16c. Decisión de Eddie, ADR-010.

    Efecto lateral bueno: el sembrado desde Anki ya usaba fuzz apagado, así
    que sembrar y contestar dejan de usar schedulers distintos.

    Los pasos, la retención y el fuzz salen de `deck.config` (M17b). Sin
    conexión se usan los defaults, para que importar el módulo no exija base.
    """
    from app import deck  # local: deck importa db, no srs
    return Scheduler(**deck.scheduler_kwargs(conn))


def _utc(ts: str) -> datetime:
    """Local naive ISO (how review_history stores it) → aware UTC."""
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.astimezone(timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _save_card(conn: sqlite3.Connection, word_id: int, card: Card,
               since: "str | None" = None) -> None:
    """Guarda la card y su espejo consultable.

    El JSON sigue siendo la fuente de verdad para FSRS; las cuatro columnas
    existen porque no se puede filtrar ni agrupar dentro de un blob (M17a).
    """
    sets = ("fsrs_card=?, fsrs_due=?, card_state=?, learning_step=?, "
            "stability=?, difficulty=?, updated_at=?")
    args = [json.dumps(card.to_dict()), card.due.isoformat(),
            STATE_NAMES.get(int(card.state), "LEARNING"), card.step,
            card.stability, card.difficulty, db.now_iso()]
    if since:
        sets += ", fsrs_since=?"
        args.append(since)
    conn.execute(f"UPDATE words SET {sets} WHERE id=?", args + [word_id])


def _load_card(row) -> "Card | None":
    return Card.from_dict(json.loads(row["fsrs_card"])) if row["fsrs_card"] else None


# ── Seeding from Anki history ────────────────────────────────────────────

def seed_from_history(conn: sqlite3.Connection) -> dict:
    """Replay every word's Anki revlog through FSRS. Idempotent: words that
    already carry a card are skipped, so live in-app progress is never
    overwritten by a re-seed."""
    scheduler = _scheduler(conn)  # el mismo que contesta: replay determinista
    stats = {"seeded": 0, "skipped": 0}
    words = conn.execute(
        "SELECT DISTINCT w.id FROM words w JOIN review_history r ON r.word_id=w.id "
        "WHERE w.fsrs_card IS NULL").fetchall()
    for (word_id,) in words:
        reviews = conn.execute(
            "SELECT reviewed_at, rating FROM review_history "
            "WHERE word_id=? AND rating BETWEEN 1 AND 4 ORDER BY reviewed_at",
            (word_id,)).fetchall()
        if not reviews:
            stats["skipped"] += 1
            continue
        card = Card()
        first = reviews[0]["reviewed_at"]
        for r in reviews:
            card, _ = scheduler.review_card(card, RATINGS[r["rating"]],
                                            _utc(r["reviewed_at"]))
        _save_card(conn, word_id, card, since=first[:10])
        stats["seeded"] += 1
    conn.commit()
    return stats


def backfill(conn: sqlite3.Connection) -> dict:
    """Rellena el espejo (`card_state`/`learning_step`/`stability`/
    `difficulty`) desde el JSON que ya existe.

    No inventa nada: los cuatro valores llevan guardados dentro de
    `fsrs_card` desde M4, sólo que no se podían consultar. Idempotente — sólo
    toca las filas a las que les falta el espejo.

    Las palabras sin card quedan en NEW, que es lo que son.
    """
    stats = {"cards": 0, "new": 0}
    for row in conn.execute(
            "SELECT id, fsrs_card FROM words WHERE card_state IS NULL"):
        if not row["fsrs_card"]:
            conn.execute("UPDATE words SET card_state='NEW' WHERE id=?", (row["id"],))
            stats["new"] += 1
            continue
        card = json.loads(row["fsrs_card"])
        conn.execute(
            "UPDATE words SET card_state=?, learning_step=?, stability=?, "
            "difficulty=? WHERE id=?",
            (STATE_NAMES.get(card.get("state"), "LEARNING"), card.get("step"),
             card.get("stability"), card.get("difficulty"), row["id"]))
        stats["cards"] += 1
    conn.commit()
    return stats


# ── Queue ────────────────────────────────────────────────────────────────

def mark_seen(conn: sqlite3.Connection, text_id: "int | None" = None) -> int:
    """Anota qué palabras NEW aparecen en lecturas terminadas.

    Con `text_id`, sólo esa lectura. La primera vez (nada marcado todavía)
    recorre todas las terminadas, para que no haga falta un backfill a mano.
    """
    from app import lemma
    first_time = conn.execute(
        "SELECT 1 FROM words WHERE seen_in_text IS NOT NULL LIMIT 1").fetchone() is None
    sql = ("SELECT id, body, finished_at FROM texts WHERE kind='reading' "
           "AND body IS NOT NULL AND finished_at IS NOT NULL")
    args: tuple = ()
    if text_id is not None and not first_time:
        sql += " AND id=?"
        args = (text_id,)
    marked = 0
    for text in conn.execute(sql, args).fetchall():
        ids = {w["id"] for w in lemma.build_lexicon(text["body"], conn).values()
               if w["status"] == "NEW"}
        if not ids:
            continue
        cur = conn.execute(
            f"UPDATE words SET seen_in_text=? WHERE seen_in_text IS NULL "
            f"AND fsrs_card IS NULL AND id IN ({','.join('?' * len(ids))})",
            [text["finished_at"][:10]] + sorted(ids))
        marked += cur.rowcount
    conn.commit()
    return marked


def _next_study_day() -> datetime:
    """El instante (UTC) en que empieza el próximo día de estudio."""
    local = datetime.now()
    start = local.replace(hour=db.rollover_hour(), minute=0, second=0,
                          microsecond=0)
    if start <= local:
        start += timedelta(days=1)
    return start.astimezone(timezone.utc)


def _introduced_today(conn: sqlite3.Connection) -> int:
    today = db.study_day()
    return conn.execute(
        "SELECT COUNT(*) FROM words WHERE fsrs_since=?", (today,)).fetchone()[0]




# Las tres consultas de la cola, en un solo sitio. Usan `card_state` en vez de
# json_extract: para eso se promovió la columna en M17a, y así entra el índice.
# WHERE y ORDER BY van separados para poder contar sin ordenar.
_WHERE_DUE = "FROM words WHERE fsrs_due IS NOT NULL AND fsrs_due <= ?"
_WHERE_LEARNING = ("FROM words WHERE fsrs_due > ? AND fsrs_due <= ? "
                   "AND card_state IN ('LEARNING','RELEARNING') "
                   # El suelo de enfriamiento: una card contestada hace
                   # menos del paso más corto no se adelanta. Sin esto
                   # "vuelve en 1 minuto" se cumplía en 2 segundos.
                   "AND (last_reviewed_on IS NULL OR last_reviewed_on <= ?)")
# La escalera entera, sin el suelo: lo que sigue sin aprenderse, se pueda
# servir ahora o no. Es lo que cuentan los contadores y lo que lista la
# muestra de ids — si la muestra usara el suelo, diría "1 pendiente" y
# devolvería una lista vacía.
_WHERE_LADDER = ("FROM words WHERE fsrs_due > ? AND fsrs_due <= ? "
                 "AND card_state IN ('LEARNING','RELEARNING')")
_SQL_LADDER = f"{_WHERE_LADDER} ORDER BY fsrs_due"

_WHERE_NEW = ("FROM words WHERE fsrs_card IS NULL AND status='NEW' "
              "AND meaning_es IS NOT NULL")

# El orden de lo vencido (ADR-014 D4): recuperabilidad descendente, con las
# que vuelven (`comeback_on`) al final. R es monótona en tiempo/estabilidad,
# así que basta ordenar por ese cociente — sin pow() en SQL, que el sqlite3 de
# Python no garantiza. El `?` extra es la hora LOCAL ingenua, el marco de
# `last_reviewed_on`. Antes era `ORDER BY fsrs_due`: lo más olvidado primero.
_ORDER_BY_RECALL = ("ORDER BY (comeback_on IS NOT NULL), "
                    "COALESCE((julianday(?) - julianday(last_reviewed_on)) "
                    "/ MAX(COALESCE(stability, 0.01), 0.01), 1e9), fsrs_due")
_SQL_DUE = f"{_WHERE_DUE} {_ORDER_BY_RECALL}"
_SQL_COMEBACK = f"{_WHERE_DUE} AND comeback_on IS NOT NULL {_ORDER_BY_RECALL}"
# Vencidas que siguen a medio aprender (ADR-015): lo único que se sirve cuando
# el presupuesto ya sólo alcanza para terminar lo empezado.
_WHERE_DUE_LADDER = f"{_WHERE_DUE} AND card_state IN ('LEARNING','RELEARNING')"
_SQL_DUE_LADDER = f"{_WHERE_DUE_LADDER} {_ORDER_BY_RECALL}"

# Una palabra que vuelve se sirve tras unos aciertos y espaciada, nunca de
# entrada ni en racha: abrir la sentada con lo que ya olvidaste es la forma
# más rápida de cerrarla.
COMEBACK_AFTER = 5
COMEBACK_EVERY = 4
_SQL_LEARNING = f"{_WHERE_LEARNING} ORDER BY fsrs_due"
# Primero las que ya encontró leyendo (ADR-014 Fase 3): una palabra vista en
# una historia entra con contexto; una suelta del mazo de Anki, a 5 s la card,
# es la que luego acierta el 45% en los pasos de aprendizaje.
_SQL_NEW = f"{_WHERE_NEW} ORDER BY (seen_in_text IS NULL), anki_note_id, id"

# Agains a la misma palabra en un día antes de dejarla descansar. Hubo cards
# con 9 repeticiones en una sentada: a partir de la tercera ya no es repaso,
# es noria — y el 44% de todos los repasos eran eso. La palabra no se esconde
# ni se suspende: vuelve mañana, y mientras tanto `model.stuck_words` la mete
# en la lectura y los ejercicios.
MAX_AGAIN_PER_DAY = 3

SAMPLE = 25   # cuántos ids se devuelven por grupo: para inspección, no scroll


def _buckets(conn: sqlite3.Connection, new_per_day: int,
             limits: "dict | None", sample: int = SAMPLE) -> dict:
    """Los tres grupos con sus cuentas y una muestra de ids.

    Separar NEW / LEARNING / REVIEW es lo que pedía la petición (§10-11): sin
    esto la pantalla sólo sabe decir "quedan N", que mezcla cosas que no se
    comportan igual — las de aprendizaje reaparecen en la misma sentada, las
    de repaso desaparecen hasta su fecha.
    """
    now_dt = _now()
    now = now_dt.isoformat()
    ahead_until = (now_dt + timedelta(minutes=LEARN_AHEAD_MINUTES)).isoformat()
    from app import deck
    # El suelo se compara contra `last_reviewed_on`, que es hora LOCAL ingenua.
    # Mezclarlo con `now` (UTC con offset) daría un suelo desplazado por la
    # zona horaria — seis horas de enfriamiento en vez de uno.
    cool_minutes = deck.shortest_step_minutes(conn)
    cool_since = (now_dt.astimezone().replace(tzinfo=None)
                  - timedelta(minutes=cool_minutes)).isoformat(timespec="seconds")

    # COUNT, not len(rows): el LIMIT viejo hacía mentir al contador pasadas
    # las 500 vencidas.
    due = conn.execute(f"SELECT COUNT(*) {_WHERE_DUE}", (now,)).fetchone()[0]
    comeback_due = conn.execute(
        f"SELECT COUNT(*) {_WHERE_DUE} AND comeback_on IS NOT NULL",
        (now,)).fetchone()[0]
    local_now = now_dt.astimezone().replace(tzinfo=None).isoformat(
        timespec="seconds")
    learning = conn.execute(f"SELECT COUNT(*) {_WHERE_LEARNING}",
                            (now, ahead_until, cool_since)).fetchone()[0]
    # La ventana ancha: toda la escalera de aprendizaje. Sólo se usa cuando no
    # queda nada más, pero se cuenta siempre para poder decir la verdad en la
    # pantalla de "no queda nada".
    wide_until = (now_dt + timedelta(
        minutes=max(LEARN_AHEAD_MINUTES, deck.longest_step_minutes(conn))
    )).isoformat()
    wide_args = (now, wide_until, cool_since)
    learning_wide = conn.execute(f"SELECT COUNT(*) {_WHERE_LEARNING}",
                                 wide_args).fetchone()[0]
    # Las que están enfriándose: siguen pendientes, sólo que todavía no. La
    # pantalla las necesita para decir "vuelve en 0:38" en vez de "no queda
    # nada", que es mentira y expulsa de la sentada.
    cooling = conn.execute(
        "SELECT COUNT(*) AS n, MIN(last_reviewed_on) AS oldest FROM words "
        "WHERE card_state IN ('LEARNING','RELEARNING') AND fsrs_due > ? "
        "  AND fsrs_due <= ? AND last_reviewed_on > ?",
        (now, wide_until, cool_since)).fetchone()
    resume_at = None
    if cooling["n"] and cooling["oldest"]:
        resume_at = (datetime.fromisoformat(cooling["oldest"])
                     + timedelta(minutes=cool_minutes)).isoformat(
                         timespec="seconds")

    new_budget = max(0, new_per_day - _introduced_today(conn))
    if limits is not None:
        new_budget = min(new_budget, max(0, limits.get("new", 0)))
    new_ids = [r[0] for r in conn.execute(
        f"SELECT id {_SQL_NEW} LIMIT ?", (new_budget,))] if new_budget else []

    # El tope de la sentada esconde repasos de HOY; no finge que dejaron de
    # estar vencidos. `due_total` guarda el número honesto.
    due_total = due
    ladder_only = bool(limits and limits.get("ladder_only"))
    if ladder_only:
        due = conn.execute(f"SELECT COUNT(*) {_WHERE_DUE_LADDER}", (now,)).fetchone()[0]
        comeback_due = 0
    if limits is not None:
        due = min(due, max(0, limits.get("reviews", 0)))
        # ADR-015: presupuesto agotado — tampoco la escalera. Las palabras a
        # medias siguen vencidas y abren la siguiente sentada.
        if limits.get("ladder") == 0:
            learning = learning_wide = 0
            cooling = {"n": 0, "oldest": None}
            resume_at = None

    return {
        "due": due, "due_total": due_total,
        "comeback_due": comeback_due,
        "ladder_only": ladder_only,
        "local_now": local_now,
        "learning": learning,
        "learning_wide": learning_wide,
        "wide_until": wide_until,
        "cool_since": cool_since,
        "cooling": cooling["n"],
        "resume_at": resume_at,
        "new_available": len(new_ids),
        "now": now, "ahead_until": ahead_until,
        "ids": {
            "reviews": [r[0] for r in conn.execute(
                f"SELECT id {_SQL_DUE_LADDER if ladder_only else _SQL_DUE} LIMIT ?",
                (now, local_now, min(due, sample)))],
            "learning": [r[0] for r in conn.execute(
                f"SELECT id {_SQL_LADDER} LIMIT ?",
                (now, wide_until, sample))],
            "new": new_ids[:sample],
        },
    }


def _mix(conn: sqlite3.Connection) -> str:
    from app import deck
    return deck.config(conn).get("queue_mix", "due_first")


def _position(conn: sqlite3.Connection) -> int:
    """Cuántas cards llevas en esta sentada. Sólo la usa el modo `mixed`."""
    try:
        from app import session
        return session.progress(conn).get("done", 0) or 0
    except Exception:  # noqa: BLE001 — sin sentada, la posición es 0
        return 0


def _pick(conn: sqlite3.Connection, b: dict, mix: str,
          position: int) -> "tuple":
    """Qué card toca ahora, según la estrategia de mezcla.

    `learn-ahead` va SIEMPRE al final: mostrar antes de tiempo una palabra que
    fallaste sólo tiene sentido cuando no queda nada más que hacer.
    """
    def fetch(sql, args):
        return conn.execute(f"SELECT * {sql} LIMIT 1", args).fetchone()

    due_args = (b["now"], b["local_now"])
    learn_args = (b["now"], b["ahead_until"], b["cool_since"])

    want_new = False
    if b["new_available"] and b["due"]:
        if mix == "new_first":
            want_new = True
        elif mix == "mixed":
            # Una nueva cada `spacing` cards, repartidas entre los repasos en
            # vez de todas juntas al principio o al final.
            spacing = max(2, round((b["due"] + b["new_available"])
                                   / max(1, b["new_available"])))
            want_new = position % spacing == 0
    elif b["new_available"]:
        want_new = True

    if want_new:
        return fetch(_SQL_NEW, ()), False
    if b["due"]:
        if (b["comeback_due"] and position >= COMEBACK_AFTER
                and position % COMEBACK_EVERY == 0):
            return fetch(_SQL_COMEBACK, due_args), False
        # Las que vuelven van al final del orden: si no queda otra cosa
        # vencida, salen aquí sin esperar turno.
        return fetch(_SQL_DUE_LADDER if b["ladder_only"] else _SQL_DUE,
                     due_args), False
    if b["learning"]:
        return fetch(_SQL_LEARNING, learn_args), True
    # Nada más que hacer: se abre la ventana a la escalera entera antes de
    # rendirse. Decir "no queda nada" y que la palabra reaparezca diez minutos
    # después es lo peor de los dos mundos.
    if b["learning_wide"]:
        return fetch(_SQL_LEARNING,
                     (b["now"], b["wide_until"], b["cool_since"])), True
    return None, False


def study_queue(conn: sqlite3.Connection, new_per_day: int = NEW_PER_DAY,
                limits: "dict | None" = None) -> dict:
    """La cola del día, separada por grupo (§10-11 de la petición).

    Devuelve cuentas y una muestra de ids por grupo. No devuelve la lista
    entera a propósito: con miles de palabras nuevas eso serían megabytes que
    nadie mira, y el contador ya dice la verdad.
    """
    from app import pause
    if pause.is_paused(conn):
        return {"paused": True, "mix": _mix(conn),
                "counts": {"new": 0, "learning": 0, "reviews": 0, "total": 0},
                "ids": {"new": [], "learning": [], "reviews": []}}
    b = _buckets(conn, new_per_day, limits)
    return {
        "paused": False,
        "mix": _mix(conn),
        "counts": {
            "new": b["new_available"],
            # Las que se enfrían CUENTAN: siguen sin aprenderse. Dejarlas
            # fuera haría que la cola del día encogiera sola cada vez que
            # contestas, que es exactamente la mentira que se quiere evitar.
            "learning": b["learning"] + b["cooling"],
            "cooling": b["cooling"],
            "reviews": b["due"],
            "reviews_total": b["due_total"],
            "total": (b["new_available"] + b["learning"] + b["cooling"]
                      + b["due"]),
        },
        "ids": b["ids"],
    }


def _as_card(row) -> dict:
    return {
        "id": row["id"], "word": row["word"],
        "pronunciation": row["pronunciation"],
        "meaning_en": row["meaning_en"], "meaning_es": row["meaning_es"],
        "example_en": row["example_en"], "example_es": row["example_es"],
        "status": row["status"],
        "is_new": row["fsrs_card"] is None,
        # La UI la presenta como reencuentro, no como examen (ADR-014 D4).
        "comeback": row["comeback_on"] is not None,
        "audio_word": row["audio_word"],
        "audio_example": row["audio_example"],
        "image_path": row["image_path"],
    }


def queue(conn: sqlite3.Connection, new_per_day: int = NEW_PER_DAY,
          limits: "dict | None" = None) -> dict:
    """What to show next.

    Order: cards due now → a new word within the daily budget → a card still
    being learned, shown ahead of its minute. New words go before learn-ahead
    on purpose: it spaces the failed word out by a card or two instead of
    showing it again immediately, which is the whole point of the step.

    `limits` is the open study session's remaining budget (M16b). It caps the
    new words and the due cards offered — but **never** the learning ones:
    capping those would strand a word you already failed in a half-learned
    state, which is the opposite of "repeat it until it's clear" (ADR-009).

    While paused nothing is due and nothing new is introduced (ADR-008 D3).
    """
    from app import pause  # local import: pause imports db, not srs
    if pause.is_paused(conn):
        return {"due": 0, "due_total": 0, "new_available": 0, "learning": 0,
                "learning_now": 0, "cooling": 0, "resume_at": None,
                "introduced_today": _introduced_today(conn),
                "reviewed_today": reviewed_today(conn),
                "next": None, "preview": None, "ahead": False, "paused": True}

    b = _buckets(conn, new_per_day, limits)
    row, ahead = _pick(conn, b, _mix(conn), _position(conn))

    return {
        "due": b["due"],
        "due_total": b["due_total"],
        "new_available": b["new_available"],
        # `learning` es todo lo que sigue en la escalera de aprendizaje;
        # `learning_now` sólo lo que vence ya. La UI necesita el primero para
        # no decir "no queda nada" cuando sí queda (ADR-009 D2 rev.2).
        "learning": b["learning_wide"] + b["cooling"],
        "learning_now": b["learning"],
        # Cuántas esperan su turno y cuándo vuelve la primera (ISO local).
        "cooling": b["cooling"],
        "resume_at": b["resume_at"],
        "introduced_today": _introduced_today(conn),
        "reviewed_today": reviewed_today(conn),
        "next": _as_card(row) if row is not None else None,
        # Los cuatro intervalos viajan con la card: la UI los necesita para
        # pintar los botones y una segunda petición sólo añadiría parpadeo.
        # Si el preview falla NO se cae la cola: los botones se quedan sin
        # número, pero se puede seguir estudiando. El error viaja en el
        # payload en vez de tragarse en silencio.
        **_safe_preview(conn, row),
        "ahead": ahead,
        "paused": False,
    }


def reviewed_today(conn: sqlite3.Connection) -> int:
    today = db.study_day()
    return conn.execute(
        "SELECT COUNT(*) FROM review_history WHERE source='fsrs' "
        "AND reviewed_at >= ?", (today,)).fetchone()[0]


# ── Preview: qué pasa con cada botón ─────────────────────────────────────

RATING_NAMES = {1: "again", 2: "hard", 3: "good", 4: "easy"}


def _safe_preview(conn: sqlite3.Connection, row) -> dict:
    """El preview no puede tumbar la cola.

    Un `fsrs_card` corrupto o de un formato viejo haría reventar la pantalla
    entera de Review, y estudiar importa más que ver los intervalos. El fallo
    se reporta, no se esconde.
    """
    if row is None:
        return {"preview": None}
    try:
        return {"preview": preview(conn, row["id"])}
    except Exception as exc:  # noqa: BLE001 — degradar, nunca caer
        return {"preview": None,
                "preview_error": f"{type(exc).__name__}: {exc}"[:200]}


def preview(conn: sqlite3.Connection, word_id: int) -> dict:
    """Los cuatro intervalos, para pintarlos encima de los botones.

    El número NO dice cuánto llevas estudiando la palabra: dice cuándo
    volverá si pulsas ese botón. Se calcula pasando una **copia** de la card
    por el scheduler una vez por rating.

    Es exacto, no aproximado, porque el fuzz está apagado (ADR-010 D1). Si
    alguien lo enciende desde la configuración, esto pasa a ser una
    estimación y `exact` lo advierte — un número que promete y no cumple es
    peor que no ponerlo.
    """
    from copy import deepcopy
    from app import deck

    row = conn.execute("SELECT * FROM words WHERE id=?", (word_id,)).fetchone()
    if row is None:
        raise ValueError(f"word {word_id} not found")

    card = _load_card(row) or Card()
    is_new = row["fsrs_card"] is None
    scheduler = _scheduler(conn)
    now = _now()

    out = {}
    for value, rating in RATINGS.items():
        # deepcopy por seguridad: hoy `review_card` no muta la card de
        # entrada (verificado), pero el preview no puede depender de eso.
        after, _ = scheduler.review_card(deepcopy(card), rating, now)
        seconds = max(0.0, (after.due - now).total_seconds())
        out[RATING_NAMES[value]] = {
            "rating": value,
            "seconds": round(seconds),
            "interval": deck.human_delta(seconds),
            "due": after.due.isoformat(),
            "state_after": STATE_NAMES.get(int(after.state)),
            "step_after": after.step,
            # Graduarse es entrar en REVIEW desde fuera. Una card nueva
            # arranca en Learning, así que la misma condición la cubre.
            "graduates": (int(after.state) == int(State.Review)
                          and int(card.state) != int(State.Review)),
        }
    return {
        "word_id": word_id,
        "state": "NEW" if is_new else STATE_NAMES.get(int(card.state)),
        "step": None if is_new else card.step,
        "exact": not deck.config(conn)["enable_fuzzing"],
        "ratings": out,
    }


# ── Answering ────────────────────────────────────────────────────────────

def answer(conn: sqlite3.Connection, word_id: int, rating: int,
           now: "datetime | None" = None) -> dict:
    """Apply one review. Creates the FSRS card on first sight (introduction).

    `now` (aware, UTC) permite fechar la respuesta en otro instante. La app
    nunca lo pasa; existe para replay y para poder probar la progresión de
    intervalos, que depende del tiempo transcurrido: cuatro respuestas en el
    mismo milisegundo dejan el intervalo plano porque para FSRS no ha pasado
    nada entre ellas. Refleja `Scheduler.review_card(..., review_datetime)`.
    """
    if rating not in RATINGS:
        raise ValueError("rating must be 1 (again), 2 (hard), 3 (good) or 4 (easy)")
    row = conn.execute("SELECT * FROM words WHERE id=?", (word_id,)).fetchone()
    if row is None:
        raise ValueError(f"word {word_id} not found")

    scheduler = _scheduler(conn)
    card = _load_card(row)
    introduced = card is None
    if introduced:
        card = Card()

    # El "antes", capturado antes de tocar nada. FSRS devuelve un ReviewLog
    # pero sólo trae card_id/rating/fecha: la estabilidad y la dificultad
    # previas hay que guardarlas aquí o se pierden para siempre (M17a).
    before = {
        "state": None if introduced else STATE_NAMES.get(int(card.state)),
        "step": None if introduced else card.step,
        "stability": None if introduced else card.stability,
        "difficulty": None if introduced else card.difficulty,
        "due": row["fsrs_due"],
    }
    prior_state = card.state
    now = now or _now()
    reviewed_at = now.astimezone().replace(tzinfo=None).isoformat(
        timespec="seconds")
    card, _log = scheduler.review_card(card, RATINGS[rating], now)
    _save_card(conn, word_id, card,
               since=db.study_day(datetime.fromisoformat(reviewed_at))
               if introduced else None)

    interval_days = max(0.0, round((card.due - now).total_seconds() / 86400, 4))
    lapsed = (not introduced and prior_state == State.Review and rating == 1)
    # Cuánto se contestó DESPUÉS de tocar, y cuánto pasó desde el repaso
    # anterior. El primero es la factura del reparto del rezago (M16c); el
    # segundo es lo que FSRS llama elapsed_days.
    # `_utc()` normaliza los dos marcos: `fsrs_due` llega con offset y
    # `last_reviewed_on` es hora local ingenua. Mezclarlos a mano es justo el
    # error que este helper existe para impedir.
    days_late = None
    if not introduced and before["due"]:
        days_late = max(0.0, round(
            (now - _utc(before["due"])).total_seconds() / 86400, 3))
    elapsed_days = None
    if row["last_reviewed_on"]:
        try:
            elapsed_days = max(0.0, round(
                (now - _utc(row["last_reviewed_on"])).total_seconds() / 86400, 3))
        except ValueError:
            elapsed_days = None

    db.insert_review(conn, {
        "word_id": word_id,
        "reviewed_at": reviewed_at,
        "rating": rating,
        "interval_days": interval_days,
        "last_interval_days": row["interval_days"],
        "days_late": days_late,
        "elapsed_days": elapsed_days,
        # 'new' = primera vez que se ve la palabra; 'learn' = repaso en paso de
        # aprendizaje. Eran lo mismo ('learn') y la sesión contaba como
        # "palabras nuevas" cada repaso de una card en LEARNING (M16b).
        "review_kind": "new" if introduced else KIND_BY_STATE.get(prior_state, "review"),
        "state_before": before["state"] or "NEW",
        "state_after": STATE_NAMES.get(int(card.state)),
        "step_before": before["step"],
        "step_after": card.step,
        "stability_before": before["stability"],
        "stability_after": card.stability,
        "difficulty_before": before["difficulty"],
        "difficulty_after": card.difficulty,
        "previous_due": before["due"],
        "comeback": 1 if row["comeback_on"] is not None else None,
        "source": "fsrs",
    })

    # Tercer Again del día a la misma palabra: descansa hasta mañana. Sólo se
    # mueve `fsrs_due` (cuándo llega); la card y su estado FSRS quedan como
    # FSRS los dejó.
    rested = False
    if rating == 1 and now >= _now() - timedelta(minutes=5):
        agains = conn.execute(
            "SELECT COUNT(*) FROM review_history WHERE word_id=? AND rating=1 "
            "AND source='fsrs' AND reviewed_at >= ?",
            (word_id, db.study_day_start())).fetchone()[0]
        if agains >= MAX_AGAIN_PER_DAY:
            conn.execute("UPDATE words SET fsrs_due=? WHERE id=?",
                         (_next_study_day().isoformat(), word_id))
            rested = True

    lapses = int(row["lapses"] or 0) + (1 if lapsed else 0)
    if card.state == State.Review:
        status = db.derive_status(2, int(interval_days), lapses)
    else:
        status = "LEARNING"
    conn.execute(
        # `comeback_on` se borra: contestada, la palabra vuelve a ser una card
        # como las demás y FSRS decide con lo que de verdad pasó.
        "UPDATE words SET status=?, review_count=COALESCE(review_count,0)+1, "
        "lapses=?, interval_days=?, last_reviewed_on=?, comeback_on=NULL, "
        "updated_at=? WHERE id=?",
        (status, lapses, int(interval_days), reviewed_at, db.now_iso(), word_id))
    conn.commit()
    return {"word_id": word_id, "status": status,
            "interval_days": interval_days, "due": card.due.isoformat(),
            "introduced": introduced, "rested": rested}
