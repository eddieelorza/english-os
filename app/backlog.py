"""El rezago: repartirlo en vez de esconderlo (ADR-009 D4, ADR-014).

ADR-014 cambió tres cosas aquí: la capacidad se mide en cards (antes nunca
había excedente y esto no corría), se queda hoy lo de mayor recuperabilidad
(antes lo más atrasado) y las palabras perdidas vuelven a goteo.

Eddie: *"jamás que se haga una cola gigante que me haga sentir que ya se me
juntó"*. Un tope de sesión por sí solo no consigue eso — oculta las cartas,
no las quita: al día siguiente siguen ahí y encima han llegado más.

Aquí se hace lo otro: cuando lo vencido pasa de lo que cabe en un día, el
excedente **se re-agenda repartido** en los días siguientes. La cola que ves
baja de verdad.

Lo que esto cuesta, dicho sin adornos: repartir **retrasa** repasos. Una carta
que FSRS quería hoy la ves en tres días, y en tres días se recuerda peor. Por
eso cada reparto se registra y cada repaso guarda su retraso real
(`review_history.days_late`), para que el precio se pueda mirar en Stats en
vez de suponerlo.

La palanca de verdad no es el tope de repasos: son las palabras nuevas. Cada
palabra introducida acaba consumiendo varios repasos, así que el ritmo diario
de nuevas fija la carga futura. `projection()` lo calcula con SU histórico,
no con una constante inventada.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from math import ceil
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from app import db  # noqa: E402

MAX_SPREAD_DAYS = 14
# Por debajo de esto no se toca nada: reprogramar por cuatro cartas es pelearse
# con FSRS sin motivo.
MIN_BACKLOG_TO_SPREAD = 10
# Muestra mínima para afirmar "cada palabra cuesta N repasos".
MIN_WORDS_FOR_PROJECTION = 30
# Sólo si no hay datos suficientes. FSRS a 90% de retención ronda esto en el
# primer año; se usa como último recurso y se marca como no medido.
DEFAULT_REVIEWS_PER_WORD = 8.0

# ── Triage (ADR-014 D4) ──
# Por debajo de esta recuperabilidad la palabra se da por perdida: servirla
# como un repaso más es fabricar un "Again". El 19-sep, tras 9 días fuera, la
# cola abrió con seis de estas: 5 fallos de 6 y la sentada duró 12 segundos.
# El umbral sale de su historial (2026-09-20): donde la librería predecía
# R < 50%, acertó el 39% (n=23); entre 80 y 90%, el 91% (n=181). La R de FSRS
# está bien calibrada para él, y por debajo de 0.5 es peor que una moneda.
LOST_BELOW = 0.50
# Las perdidas vuelven a goteo y ocupan el cupo de palabras nuevas: durante
# el regreso, tus "nuevas" son las que se te cayeron.
COMEBACK_PER_DAY = 3


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Capacidad ────────────────────────────────────────────────────────────

def capacity(conn: sqlite3.Connection) -> int:
    """Cuántas cards caben en un día con los ajustes actuales.

    En modo tiempo es el presupuesto de CARDS de la sentada (ADR-014 D1), no
    minutos entre ritmo: a 5 s por card eso daba 240 para "20 minutos", nunca
    había excedente y este módulo entero no llegó a ejecutarse.
    """
    from app import session
    cfg = session.settings(conn)
    if cfg["mode"] == "counts":
        return max(0, cfg["reviews"])
    return session.card_budget(conn)


def due_total(conn: sqlite3.Connection) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM words WHERE fsrs_due IS NOT NULL AND fsrs_due <= ?",
        (_now().isoformat(),)).fetchone()[0]


def triaged(conn: sqlite3.Connection, now: "datetime | None" = None) -> "list[dict]":
    """Lo vencido, ordenado por recuperabilidad descendente.

    Con un tope diario de repasos, *retrievability descending* es el orden
    que mejor conserva la memoria por card contestada, y *due date ascending*
    — el que había aquí — de los peores (simulaciones de los autores de
    FSRS): lo más atrasado es lo que ya se olvidó, y gastar ahí el cupo deja
    caer mientras tanto lo que aún se podía salvar.

    R sale de la propia librería, con la card real: nada de fórmulas a mano
    que se desincronicen de los parámetros del mazo. A igual R, lo más
    atrasado primero.
    """
    from app import srs
    now = now or _now()
    scheduler = srs._scheduler(conn)
    out = []
    for row in conn.execute(
            "SELECT id, fsrs_card, fsrs_due, comeback_on FROM words "
            "WHERE fsrs_due IS NOT NULL AND fsrs_due <= ?", (now.isoformat(),)):
        try:
            r = scheduler.get_card_retrievability(srs._load_card(row), now)
        except Exception:  # noqa: BLE001 — una card ilegible no tumba el día
            r = 1.0
        out.append({"id": row["id"], "due": row["fsrs_due"], "r": round(r, 3),
                    # Una vez dada por perdida lo sigue estando hasta que se
                    # conteste: si no, entraría y saldría del goteo cada día.
                    "lost": r < LOST_BELOW or row["comeback_on"] is not None})
    out.sort(key=lambda c: (-c["r"], c["due"]))
    return out


# ── Proyección: qué carga te compran las palabras nuevas ─────────────────

def reviews_per_word(conn: sqlite3.Connection) -> dict:
    """Repasos que consume una palabra, medidos de su propio historial.

    Es una **cota inferior**: sus palabras son jóvenes y todavía les quedan
    repasos por delante. Se dice, no se disimula.
    """
    row = conn.execute(
        "SELECT COUNT(*) AS reviews, COUNT(DISTINCT word_id) AS words "
        "FROM review_history").fetchone()
    words = row["words"] or 0
    if words < MIN_WORDS_FOR_PROJECTION:
        return {"value": DEFAULT_REVIEWS_PER_WORD, "words": words,
                "measured": False}
    return {"value": round(row["reviews"] / words, 1), "words": words,
            "measured": True}


def projection(conn: sqlite3.Connection, new_per_day: "int | None" = None) -> dict:
    """La carga diaria a la que tiende este ritmo de palabras nuevas.

    Conservación, no futurología: si cada palabra acaba costando R repasos y
    metes N palabras al día, en régimen tienes que hacer N x R repasos al día
    para no acumular.
    """
    from app import session
    cfg = session.settings(conn)
    n = cfg["new_per_day"] if new_per_day is None else max(0, int(new_per_day))
    per_word = reviews_per_word(conn)
    daily = round(n * per_word["value"])
    cap = capacity(conn)
    return {
        "new_per_day": n,
        "reviews_per_word": per_word,
        "steady_daily_reviews": daily,
        "capacity": cap,
        "sustainable": daily <= cap,
        "note": (None if daily <= cap else
                 f"{n} new words a day settles at about {daily} reviews a day, "
                 f"more than the {cap} your sitting holds"),
    }


# ── Reparto ──────────────────────────────────────────────────────────────

def _split(conn: sqlite3.Connection, cap: int,
           now: "datetime | None" = None) -> dict:
    """Qué se queda hoy y qué espera. No escribe nada."""
    cards = triaged(conn, now)
    lost = [c for c in cards if c["lost"]]
    alive = [c for c in cards if not c["lost"]]
    keep_lost = lost[:COMEBACK_PER_DAY]
    room = max(0, cap - len(keep_lost))
    move_alive = alive[room:]
    # Por cuatro cartas vivas no se reprograma nada; las perdidas sí gotean
    # siempre, que para eso se separan.
    if len(move_alive) < MIN_BACKLOG_TO_SPREAD:
        move_alive = []
    return {"cards": cards, "lost": lost, "keep_lost": keep_lost,
            "move_lost": lost[COMEBACK_PER_DAY:], "move_alive": move_alive}


def status(conn: sqlite3.Connection, cap: "int | None" = None,
           rate: float = 1.0) -> dict:
    cap = capacity(conn) if cap is None else max(0, cap)
    now = _now()
    parts = _split(conn, cap, now)
    due = len(parts["cards"])
    placed, _ = _placement(conn, parts["move_lost"], parts["move_alive"], cap, now,
                           rate)
    return {
        "due": due,
        "capacity": cap,
        "excess": len(placed),
        "lost": len(parts["lost"]),
        "overloaded": bool(placed),
        # los días que de verdad ocuparía, contando lo ya agendado
        "spread_days": max((day for _, day in placed), default=0),
    }


def outlook(conn: sqlite3.Connection, cap: "int | None" = None,
            rate: float = 1.0) -> dict:
    """Lo que la pantalla de plan necesita decir: cuánto es de hoy, cuánto se
    agenda para después y cuántas palabras están volviendo."""
    st = status(conn, cap, rate)
    pending = conn.execute(
        "SELECT COUNT(*) FROM words WHERE comeback_on IS NOT NULL").fetchone()[0]
    return {"due": st["due"], "today": st["due"] - st["excess"],
            "later": st["excess"], "days": st["spread_days"],
            # las ya marcadas más las que el triage marcaría al sentarte
            "comeback": max(pending, st["lost"])}


def _scheduled_by_day(conn: sqlite3.Connection, now: datetime) -> "dict[int, int]":
    """Cuántas cartas hay ya agendadas en cada uno de los próximos días."""
    counts: "dict[int, int]" = {}
    horizon = (now + timedelta(days=MAX_SPREAD_DAYS + 1)).isoformat()
    for row in conn.execute(
            "SELECT fsrs_due FROM words WHERE fsrs_due > ? AND fsrs_due <= ?",
            (now.isoformat(), horizon)):
        offset = (datetime.fromisoformat(row["fsrs_due"]) - now).days + 1
        counts[offset] = counts.get(offset, 0) + 1
    return counts


def _placement(conn: sqlite3.Connection, move_lost: list, move_alive: list,
               cap: int, now: datetime, rate: float = 1.0) -> "tuple[list, int]":
    """A qué día va cada carta. No escribe: lo usan `spread` para aplicar y
    `status` para anunciar, y así lo anunciado es lo que luego pasa.

    `rate` es la fracción de días que de verdad se estudia (ADR-015 D3). Con
    1.0 cada día recibe `cap`, como siempre. Con 0.45 lo agendado hasta el día
    d no pasa de `cap x 0.45 x d`: si estudia un día de cada dos, al volver
    le espera UNA sentada, no dos apiladas. Repartir a días en que no va a
    sentarse sólo fabricaba el siguiente pico.
    """
    rate = min(1.0, max(0.05, rate or 1.0))
    if cap <= 0 or not (move_lost or move_alive):
        return [], cap
    booked = _scheduled_by_day(conn, now)
    placed = []
    # Las perdidas primero y a su propio paso, para que el reparto de las
    # vivas cuente con ellas al buscar hueco.
    for i, card in enumerate(move_lost):
        day = 1 + i // COMEBACK_PER_DAY
        booked[day] = booked.get(day, 0) + 1
        placed.append((card["id"], day))

    already = sum(booked.get(d, 0) for d in range(1, MAX_SPREAD_DAYS + 1))
    # Si el rezago no cabe en el horizonte al ritmo deseado, los días salen
    # más cargados — pero PAREJOS. Antes el sobrante se apilaba en el último
    # día (126 cartas de golpe a 14 días vista): un muro nuevo, que es
    # justo lo que esto existe para evitar.
    per_day = max(cap, ceil((len(move_alive) + already)
                            / (MAX_SPREAD_DAYS * rate)))

    def fits(day: int) -> bool:
        if booked.get(day, 0) >= per_day:
            return False
        if rate >= 1.0:
            return True
        # acumulado: de aquí al final del horizonte nunca por encima de las
        # sentadas que cabe esperar
        running = sum(booked.get(d, 0) for d in range(1, day))
        for d in range(day, MAX_SPREAD_DAYS + 1):
            running += booked.get(d, 0)
            if running + 1 > ceil(per_day * rate * d):
                return False
        return True

    for card in move_alive:                   # ya viene en R descendente
        day = next((d for d in range(1, MAX_SPREAD_DAYS + 1) if fits(d)),
                   MAX_SPREAD_DAYS)
        booked[day] = booked.get(day, 0) + 1
        placed.append((card["id"], day))
    return placed, per_day


def spread(conn: sqlite3.Connection, force: bool = False,
           cap: "int | None" = None, rate: float = 1.0) -> dict:
    """Ordena el día: se queda lo que cabe, el resto se re-agenda.

    Cuatro reglas (la 1 y la 4 son de ADR-014; sustituyen a "se quedan hoy
    las más atrasadas" de ADR-009 D4):

    1. Se quedan hoy las de MAYOR recuperabilidad — ver `triaged`.
    2. Cada carta va al primer día que todavía tenga hueco **contando lo que
       ya estaba agendado ahí**. Sin esto el reparto amontona: repartir 112
       cartas de 8 en 8 dejaba 59 en un solo día porque ignoraba las 51 que
       ya vencían mañana — un muro nuevo tres días después, que es
       exactamente lo que esto existe para evitar.
    3. Si no cabe en el horizonte, los días salen más cargados pero PAREJOS.
    4. Las perdidas (R < 50%) no compiten por el cupo: se marcan
       (`comeback_on`) y vuelven de `COMEBACK_PER_DAY` en `COMEBACK_PER_DAY`.
       Su estado FSRS no se toca — al contestarlas, FSRS registra el lapso o
       el acierto tardío tal cual fue. Lo único que cambia es CUÁNDO llegan.
    """
    cap = capacity(conn) if cap is None else max(0, cap)
    now = _now()
    parts = _split(conn, cap, now)
    due = len(parts["cards"])
    base = {"due": due, "capacity": cap, "lost": len(parts["lost"])}
    if cap <= 0:
        return {"spread": False, **base}

    move_alive = parts["move_alive"]
    if force and not move_alive:
        room = max(0, cap - len(parts["keep_lost"]))
        move_alive = [c for c in parts["cards"] if not c["lost"]][room:]

    today = db.study_day()
    fresh = [c["id"] for c in parts["lost"]]
    if fresh:
        conn.execute(
            f"UPDATE words SET comeback_on=? WHERE comeback_on IS NULL "
            f"AND id IN ({','.join('?' * len(fresh))})", [today] + fresh)

    if not move_alive and not parts["move_lost"]:
        conn.commit()
        return {"spread": False, **base}

    placed, per_day = _placement(conn, parts["move_lost"], move_alive, cap, now,
                                 rate)
    for card_id, day in placed:
        conn.execute("UPDATE words SET fsrs_due=?, updated_at=? WHERE id=?",
                     ((now + timedelta(days=day)).isoformat(),
                      db.now_iso(), card_id))
    moved = len(placed)
    last_day = max((day for _, day in placed), default=0)
    over_capacity = per_day > cap

    kept = due - moved
    conn.execute(
        "INSERT INTO backlog_spreads (date, cards, days, kept_today, comeback, "
        "created_at) VALUES (?,?,?,?,?,?)",
        (today, moved, last_day, kept, len(parts["lost"]), db.now_iso()))
    conn.commit()
    return {"spread": True, "cards": moved, "days": last_day,
            "kept_today": kept, "capacity": cap, "per_day": per_day,
            "over_capacity": over_capacity, "comeback": len(parts["lost"]),
            "comeback_today": len(parts["keep_lost"])}


PULL_DEFAULT = 20
PULL_MAX = 50


def pull_forward(conn: sqlite3.Connection, cards: int = PULL_DEFAULT) -> dict:
    """"Estudiar más": trae a hoy las próximas cards agendadas.

    El reparto protege del muro; esto es la puerta de vuelta para el día que
    sobran ganas. Se traen las de vencimiento más cercano (las que más lo
    necesitan) dentro del horizonte del reparto. Las que vuelven no: su goteo
    es deliberado. Adelantar un repaso cuesta poco — FSRS da menos ganancia de
    estabilidad, no la quita.
    """
    n = max(1, min(PULL_MAX, int(cards)))
    now = _now()
    horizon = (now + timedelta(days=MAX_SPREAD_DAYS)).isoformat()
    ids = [r["id"] for r in conn.execute(
        "SELECT id FROM words WHERE fsrs_due > ? AND fsrs_due <= ? "
        "AND card_state='REVIEW' AND comeback_on IS NULL "
        "ORDER BY fsrs_due LIMIT ?", (now.isoformat(), horizon, n))]
    for card_id in ids:
        conn.execute("UPDATE words SET fsrs_due=?, updated_at=? WHERE id=?",
                     (now.isoformat(), db.now_iso(), card_id))
    conn.commit()
    return {"pulled": len(ids), "asked": n}


def comeback_recall(conn: sqlite3.Connection, window_days: int = 90) -> dict:
    """¿Funciona el goteo? Aciertos en los reencuentros, con su muestra."""
    since = (datetime.now() - timedelta(days=window_days)).isoformat()
    row = conn.execute(
        "SELECT COUNT(*) AS n, SUM(CASE WHEN rating > 1 THEN 1 ELSE 0 END) AS ok "
        "FROM review_history WHERE source='fsrs' AND comeback=1 "
        "AND reviewed_at >= ?", (since,)).fetchone()
    n = row["n"] or 0
    enough = n >= MIN_BUCKET_REVIEWS
    pending = conn.execute(
        "SELECT COUNT(*) FROM words WHERE comeback_on IS NOT NULL").fetchone()[0]
    return {"reviews": n, "pending": pending, "enough": enough,
            "recall": round((row["ok"] or 0) / n, 3) if enough else None}


def spread_today(conn: sqlite3.Connection) -> "dict | None":
    row = conn.execute(
        "SELECT * FROM backlog_spreads WHERE date=? ORDER BY id DESC LIMIT 1",
        (db.study_day(),)).fetchone()
    return dict(row) if row else None


# ── El precio: cuánto se retrasan los repasos ────────────────────────────

# Por debajo de esto un porcentaje de recuerdo es ruido, no una medición.
MIN_BUCKET_REVIEWS = 20

# (etiqueta, desde, hasta) en días de retraso. El primer tramo es "a tiempo":
# FSRS ya cuenta con unas horas de holgura.
LATENESS_BUCKETS = (
    ("on time", 0.0, 1.0),
    ("1-3 days late", 1.0, 4.0),
    ("4+ days late", 4.0, 10_000.0),
)


def recall_by_lateness(conn: sqlite3.Connection,
                       window_days: int = 90) -> "list[dict]":
    """¿Recordar una carta atrasada sale peor? Su propia respuesta.

    Esta es la factura del reparto, medida en vez de supuesta. Si los tramos
    tardíos aciertan claramente menos, el reparto está costando recuerdo. Cada
    tramo lleva su muestra: por debajo de MIN_BUCKET_REVIEWS no se afirma un
    porcentaje — un 100% sobre tres cartas no dice nada.

    Sólo repasos in-app: el revlog de Anki no trae retraso.
    """
    since = (datetime.now() - timedelta(days=window_days)).isoformat()
    out = []
    for label, lo, hi in LATENESS_BUCKETS:
        row = conn.execute(
            "SELECT COUNT(*) AS n, SUM(CASE WHEN rating > 1 THEN 1 ELSE 0 END) AS ok "
            "FROM review_history WHERE source='fsrs' AND days_late IS NOT NULL "
            "AND reviewed_at >= ? AND days_late >= ? AND days_late < ? "
            # una introducción no puede llegar tarde, y no se pregunta
            "AND review_kind != 'new'",
            (since, lo, hi)).fetchone()
        n = row["n"] or 0
        enough = n >= MIN_BUCKET_REVIEWS
        out.append({
            "label": label,
            "reviews": n,
            "recall": round((row["ok"] or 0) / n, 3) if enough else None,
            "enough": enough,
        })
    return out


def lateness_series(conn: sqlite3.Connection, weeks: int = 12) -> "list[dict]":
    """Retraso medio por semana. `None` en las semanas sin repasos in-app —
    un hueco honesto, nunca un cero que parezca puntualidad perfecta."""
    today = datetime.now().date()
    monday = today - timedelta(days=today.weekday())
    out = []
    for i in range(weeks - 1, -1, -1):
        start = monday - timedelta(weeks=i)
        end = start + timedelta(days=7)
        row = conn.execute(
            "SELECT COUNT(*) AS n, AVG(days_late) AS avg_late FROM review_history "
            "WHERE source='fsrs' AND days_late IS NOT NULL "
            "AND reviewed_at >= ? AND reviewed_at < ?",
            (start.isoformat(), end.isoformat())).fetchone()
        n = row["n"] or 0
        out.append({
            "week_start": start.isoformat(),
            "reviews": n,
            "avg_days_late": round(row["avg_late"], 2) if n else None,
        })
    return out


def spreads_in(conn: sqlite3.Connection, window_days: int = 30) -> dict:
    """Cuántas veces se repartió y cuántas cartas se movieron.

    Sin esto no se puede leer el retraso: una carta puede llegar tarde porque
    el sistema la aplazó, o simplemente porque ese día no estudiaste. Son
    cosas distintas y la pantalla no debe confundirlas.
    """
    since = (datetime.now().date() - timedelta(days=window_days)).isoformat()
    row = conn.execute(
        "SELECT COUNT(*) AS times, COALESCE(SUM(cards), 0) AS cards "
        "FROM backlog_spreads WHERE date >= ?", (since,)).fetchone()
    return {"window_days": window_days, "times": row["times"] or 0,
            "cards": row["cards"] or 0}


def lateness(conn: sqlite3.Connection, window_days: int = 30) -> dict:
    """Retraso medio con el que se contestan las cartas.

    Es la factura del reparto. Si sube mucho, la retención va a bajar: no hay
    forma de repartir sin pagar algo, y esto es lo que se paga.
    """
    since = (datetime.now() - timedelta(days=window_days)).isoformat()
    row = conn.execute(
        "SELECT COUNT(*) AS n, AVG(days_late) AS avg_late, MAX(days_late) AS worst "
        "FROM review_history WHERE source='fsrs' AND days_late IS NOT NULL "
        "AND reviewed_at >= ?", (since,)).fetchone()
    n = row["n"] or 0
    return {
        "window_days": window_days,
        "reviews": n,
        "avg_days_late": round(row["avg_late"], 1) if n else None,
        "worst_days_late": row["worst"] if n else None,
        "enough": n >= 20,
    }
