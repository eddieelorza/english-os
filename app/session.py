"""La sesión de repaso: cuánto tiempo tienes y qué cabe (ADR-009 D3).

Tres piezas:

1. **Ajustes** — key/value en SQLite: modo, minutos, topes manuales.
2. **Ritmo** — segundos por card *medidos*, no inventados. Se calculan de los
   huecos entre repasos in-app consecutivos. Con poca muestra devuelve el
   default conservador y lo dice (`measured: False`); nunca finge precisión.
3. **Plan** — cuántas nuevas y cuántos repasos caben, y la sesión abierta
   contra la que la cola se recorta.

Por qué no se usan los 5 s/card del revlog de Anki: vienen del mazo viejo,
donde una card era una palabra suelta. Aquí la card trae significado, ejemplo
y audio. Se arranca en 10 s y se corrige sola con datos de esta app.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from app import db  # noqa: E402

DEFAULTS = {
    "session_mode": "time",      # 'time' | 'counts' | 'auto' (ADR-015)
    "session_minutes": "20",
    "session_new": "6",          # modo manual: nuevas por sesión
    "session_reviews": "25",     # modo manual: repasos por sesión
    "new_per_day": "5",          # tope diario de introducciones
    "new_gate": "auto",          # 'auto' | 'off' — la compuerta de ADR-014 D3
    "fail_brake": "auto",        # 'auto' | 'off' — el freno de ADR-014 D5
}

DEFAULT_SECONDS_PER_CARD = 10.0
MIN_GAPS = 30          # por debajo de esto no hay muestra: no se calibra
MAX_GAP_SECONDS = 120  # un hueco mayor es que te levantaste, no una card
# En una sesión corta, no dejar que las nuevas se coman todo el tiempo: son
# las caras y las que generan carga futura.
NEW_SHARE_OF_SESSION = 0.5
# El tope en CARDS de una sentada por tiempo (ADR-014 D1). El ritmo medido de
# Eddie es 5 s por card, así que "20 minutos" daba 240 cards: el presupuesto
# por tiempo nunca llegó a limitar nada. Lo que cansa no son los segundos, son
# las cards y los fallos. 2.5 por minuto → 25 / 50 / 75 para 10 / 20 / 30 min.
MAX_CARDS_PER_MINUTE = 2.5
# El freno por fallos (ADR-014 D5). La cola va de más a menos recordable, así
# que cuando los fallos se disparan lo que queda por delante es peor todavía:
# seguir sólo fabrica más Again y más escalera. Cuenta sólo repasos de cards
# vencidas — fallar un paso de aprendizaje es parte de aprender la palabra.
BRAKE_MIN_REVIEWS = 15
BRAKE_AGAIN_RATE = 0.35


# ── Ajustes ──────────────────────────────────────────────────────────────

def settings(conn: sqlite3.Connection) -> dict:
    stored = {r["key"]: r["value"] for r in conn.execute("SELECT * FROM settings")}
    merged = {**DEFAULTS, **stored}
    return {
        "mode": merged["session_mode"],
        "minutes": int(merged["session_minutes"]),
        "new": int(merged["session_new"]),
        "reviews": int(merged["session_reviews"]),
        "new_per_day": int(merged["new_per_day"]),
        "new_gate": merged["new_gate"],
        "fail_brake": merged["fail_brake"],
    }


_KEYS = {"mode": "session_mode", "minutes": "session_minutes",
         "new": "session_new", "reviews": "session_reviews",
         "new_per_day": "new_per_day", "new_gate": "new_gate",
         "fail_brake": "fail_brake"}


def save_settings(conn: sqlite3.Connection, patch: dict) -> dict:
    for field, value in patch.items():
        key = _KEYS.get(field)
        if key is None or value is None:
            continue
        if field == "mode":
            if value not in ("time", "counts", "auto"):
                raise ValueError("mode must be 'time', 'counts' or 'auto'")
        elif field in ("new_gate", "fail_brake"):
            if value not in ("auto", "off"):
                raise ValueError(f"{field} must be 'auto' or 'off'")
        else:
            value = max(0, int(value))
        conn.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
            "updated_at=excluded.updated_at",
            (key, str(value), db.now_iso()))
    conn.commit()
    return settings(conn)


# ── Ritmo ────────────────────────────────────────────────────────────────

def _median(values: "list[float]") -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def pace(conn: sqlite3.Connection) -> dict:
    """Segundos por card, medidos de los huecos entre repasos in-app.

    Se separan nuevas y repasos sólo si ambos tienen muestra: una card nueva
    se lee entera la primera vez y tarda más, pero inventar un multiplicador
    sería peor que usar un único ritmo.
    """
    rows = conn.execute(
        "SELECT reviewed_at, review_kind FROM review_history "
        "WHERE source='fsrs' ORDER BY reviewed_at").fetchall()

    gaps: "list[float]" = []
    learn_gaps: "list[float]" = []
    prev = None
    for row in rows:
        stamp = datetime.fromisoformat(row["reviewed_at"])
        if prev is not None:
            delta = (stamp - prev).total_seconds()
            if 0 < delta <= MAX_GAP_SECONDS:
                gaps.append(delta)
                # el hueco termina EN esta card, así que la clasifica ella
                if row["review_kind"] == "new":
                    learn_gaps.append(delta)
        prev = stamp

    measured = len(gaps) >= MIN_GAPS
    per_card = _median(gaps) if measured else DEFAULT_SECONDS_PER_CARD
    per_new = (_median(learn_gaps) if len(learn_gaps) >= MIN_GAPS else per_card)
    return {
        "seconds_per_card": round(per_card, 1),
        "seconds_per_new": round(per_new, 1),
        "samples": len(gaps),
        "measured": measured,
        # UI copy is English (DESIGN.md); Spanish is for learning content only.
        "note": (None if measured else
                 f"pace not measured yet ({len(gaps)}/{MIN_GAPS} cards) — "
                 f"estimating {DEFAULT_SECONDS_PER_CARD:.0f}s per card"),
    }


# ── Plan ─────────────────────────────────────────────────────────────────

def card_budget(conn: sqlite3.Connection, minutes: "int | None" = None) -> int:
    """Cuántas cards caben en una sentada por tiempo: lo que dé el reloj,
    nunca más que el tope de cards (ADR-014 D1)."""
    minutes = settings(conn)["minutes"] if minutes is None else max(1, int(minutes))
    by_clock = int(minutes * 60 // max(1.0, pace(conn)["seconds_per_card"]))
    return min(by_clock, int(minutes * MAX_CARDS_PER_MINUTE))


def _auto_plan(conn: sqlite3.Connection, less: "bool | None") -> "dict | None":
    """El plan en modo auto, o None si aún no hay historia para proponer
    nada (entonces se cae al plan por tiempo, diciéndolo)."""
    from app import backlog, load, srs
    prop = load.proposal(conn, less=less)
    if not prop["measured"]:
        return None
    speed = pace(conn)
    remaining = prop["remaining"]
    q = srs.queue(conn, new_per_day=prop["new"])
    new = min(prop["new"], q["new_available"])
    new_cost = 1 + prop["effort"]["ladder_cost"]
    new = max(0, min(new, remaining // new_cost))
    # Cards que caben: el resto del presupuesto, descontadas sus repeticiones.
    cards = int((remaining - new * new_cost) // max(1.0, prop["effort"]["repeat_factor"]))
    reviews = max(0, min(cards, q["due"]))
    triage = backlog.outlook(conn, cap=max(prop["cards"], 1),
                             rate=prop["rhythm"]["rate"])
    return {
        "gate": prop["gate"], "triage": triage, "mode": "auto", "minutes": None,
        "new": new, "reviews": reviews, "total": new + reviews,
        # El número que importa: respuestas, repeticiones incluidas.
        "budget": remaining, "day_budget": prop["budget"],
        "answered_today": prop["answered"],
        "estimated_minutes": round(remaining * speed["seconds_per_card"] / 60, 1),
        "pace": speed,
        "available": {"new": q["new_available"], "reviews": q["due"]},
        "short": [], "why": prop["why"], "less": prop["less"],
        "load": prop, "paused": False,
    }


def plan(conn: sqlite3.Connection, mode: "str | None" = None,
         minutes: "int | None" = None, new: "int | None" = None,
         reviews: "int | None" = None, less: "bool | None" = None) -> dict:
    """Qué cabe hoy. No promete lo que no hay: recorta contra lo realmente
    vencido y contra el tope diario de palabras nuevas."""
    from app import backlog, gate, srs

    cfg = settings(conn)
    mode = mode or cfg["mode"]
    fallback_why = None
    if mode == "auto":
        from app import load, pause
        auto = None if pause.is_paused(conn) else _auto_plan(conn, less)
        if auto is not None:
            return auto
        # Sin historia suficiente: plan por tiempo, y se dice por qué.
        fallback_why = load.proposal(conn, less=less)["why"]
        mode = "time"
    speed = pace(conn)
    if mode == "counts":
        minutes = None
        cap = cfg["reviews"] if reviews is None else max(0, int(reviews))
    else:
        minutes = cfg["minutes"] if minutes is None else max(1, int(minutes))
        cap = card_budget(conn, minutes)
    # La compuerta decide cuántas nuevas admite HOY (ADR-014 D3); el ajuste
    # `new_per_day` pasa a ser el techo, no la cifra.
    door = gate.allowed(conn, capacity=cap, mode=mode)
    q = srs.queue(conn, new_per_day=door["new_per_day"])

    available_new = q["new_available"]     # ya descuenta lo introducido hoy
    available_reviews = q["due"]

    if mode == "counts":
        want_new = cfg["new"] if new is None else max(0, int(new))
        want_reviews = cap
    else:
        budget = minutes * 60
        # las nuevas primero, pero sin quedarse con más de la mitad del rato
        want_new = min(int((budget * NEW_SHARE_OF_SESSION) // speed["seconds_per_new"]),
                       int(cap * NEW_SHARE_OF_SESSION))
        taken = min(want_new, available_new)
        spent = taken * speed["seconds_per_new"]
        want_reviews = min(int(max(0, budget - spent) // speed["seconds_per_card"]),
                           cap - taken)

    plan_new = min(want_new, available_new)
    plan_reviews = min(want_reviews, available_reviews)
    estimate = (plan_new * speed["seconds_per_new"]
                + plan_reviews * speed["seconds_per_card"])

    short = []
    if plan_new < want_new:
        if door["reason"]:
            # La compuerta es la que manda: decir "no quedan" sería mentira.
            short.append(door["reason"])
        else:
            short.append("no new words left for today" if available_new == 0 else
                         f"only {available_new} new word"
                         f"{'' if available_new == 1 else 's'} left for today")
    if plan_reviews < want_reviews:
        short.append("nothing due right now" if available_reviews == 0 else
                     f"only {available_reviews} review"
                     f"{'' if available_reviews == 1 else 's'} due")

    # Lo que no cabe hoy no desaparece: se agenda. La pantalla lo dice en vez
    # de enseñar un "102 due" que nadie va a hacer de una sentada.
    triage = ({"due": 0, "later": 0, "comeback": 0, "days": 0}
              if q.get("paused") else backlog.outlook(conn, cap=cap))

    return {
        "gate": door,
        "triage": triage,
        "mode": mode,
        "minutes": minutes,
        "new": plan_new,
        "reviews": plan_reviews,
        "total": plan_new + plan_reviews,
        "estimated_minutes": round(estimate / 60, 1),
        "pace": speed,
        "available": {"new": available_new, "reviews": available_reviews},
        "short": short,
        "why": fallback_why,
        "paused": q.get("paused", False),
    }


# ── Ciclo de vida ────────────────────────────────────────────────────────

def _row(r) -> "dict | None":
    return dict(r) if r is not None else None


def active(conn: sqlite3.Connection) -> "dict | None":
    """La sesión abierta de HOY, si la hay.

    Una sesión es una sentada, no un estado permanente: si te levantaste sin
    cerrarla, mañana no sigues dentro de ella. Las de días anteriores se
    cierran solas al preguntar — si no, el contador arrastra los repasos de
    días pasados y dice cosas como "38 de 10".
    """
    today = db.study_day()
    stale = conn.execute(
        "SELECT COUNT(*) FROM study_sessions WHERE ended_at IS NULL "
        "AND substr(started_at, 1, 10) < ?", (today,)).fetchone()[0]
    if stale:
        conn.execute(
            "UPDATE study_sessions SET ended_at=? WHERE ended_at IS NULL "
            "AND substr(started_at, 1, 10) < ?", (db.now_iso(), today))
        conn.commit()
    return _row(conn.execute(
        "SELECT * FROM study_sessions WHERE ended_at IS NULL "
        "ORDER BY started_at DESC LIMIT 1").fetchone())


def start(conn: sqlite3.Connection, mode: "str | None" = None,
          minutes: "int | None" = None, new: "int | None" = None,
          reviews: "int | None" = None, less: "bool | None" = None) -> dict:
    """Abre una sesión con el plan calculado. Si ya había una abierta la
    cierra: dos sesiones a la vez no significan nada.

    Antes de planear se ordena el día (ADR-014 D2). El reparto vivía sólo en
    `end()`, y casi ninguna sentada se cierra a mano: en un mes no corrió ni
    una vez. Sentarse sí ocurre siempre.
    """
    from app import backlog, pause
    tidy = {"spread": False}
    budget = None
    cfg = settings(conn)
    auto = (mode or cfg["mode"]) == "auto"
    if auto and not pause.is_paused(conn):
        from app import load
        if less is not None:
            load.set_less(conn, less)
        prop = load.proposal(conn)
        if prop["measured"]:
            # El reparto usa las cards de UNA sentada y el ritmo real: los días
            # que no vas a estudiar no reciben cartas (ADR-015 D3).
            tidy = backlog.spread(conn, cap=max(prop["cards"], 1),
                                  rate=prop["rhythm"]["rate"])
            load.begin_day(conn, prop["computed"])
            budget = load.proposal(conn)["remaining"]
        else:
            auto = False
    if not auto and not pause.is_paused(conn):
        if (mode or cfg["mode"]) == "counts":
            cap = cfg["reviews"] if reviews is None else max(0, int(reviews))
        else:
            cap = card_budget(conn, minutes)
        tidy = backlog.spread(conn, cap=cap)
    p = plan(conn, mode=mode, minutes=minutes, new=new, reviews=reviews, less=less)
    conn.execute("UPDATE study_sessions SET ended_at=? WHERE ended_at IS NULL",
                 (db.now_iso(),))
    high_water = conn.execute(
        "SELECT COALESCE(MAX(id), 0) FROM review_history").fetchone()[0]
    cur = conn.execute(
        "INSERT INTO study_sessions (started_at, mode, minutes, planned_new, "
        "planned_reviews, from_review_id, budget) VALUES (?,?,?,?,?,?,?)",
        (db.now_iso(), p["mode"], p["minutes"], p["new"], p["reviews"],
         high_water, budget if p["mode"] == "auto" else None))
    conn.commit()
    return {**progress(conn, active(conn)), "plan": p, "id": cur.lastrowid,
            "backlog": tidy}


def end(conn: sqlite3.Connection) -> dict:
    """Cierra la sentada y, si lo que queda vencido no cabe en un día,
    reparte el excedente (ADR-009 D4). Es el momento natural: hiciste tu
    parte de hoy, el resto se ordena para que mañana no sea un muro."""
    sess = active(conn)
    if sess is None:
        return {"ended": False}
    done = progress(conn, sess)
    conn.execute("UPDATE study_sessions SET ended_at=? WHERE id=?",
                 (db.now_iso(), sess["id"]))
    conn.commit()

    from app import backlog, pause
    spread = ({"spread": False} if pause.is_paused(conn)
              else backlog.spread(conn))

    # Cerrar la sentada es ahora el disparador del material del día (ADR-011).
    # Antes lo lanzaba el add-on de Anki al terminar de estudiar ahí; tras el
    # cut-over nadie abre Anki y el material dejaría de generarse solo.
    # Se encola y se sigue: generar tarda minutos y nadie va a esperarlos
    # mirando la tarjeta de cierre.
    material = None
    if not pause.is_paused(conn):
        try:
            from app import jobs
            material = jobs.enqueue_daily(conn)
        except Exception as exc:  # noqa: BLE001 — cerrar nunca debe fallar
            material = {"error": f"{type(exc).__name__}: {exc}"[:200]}

    return {"ended": True, **done, "backlog": spread, "material": material}


def progress(conn: sqlite3.Connection, sess: "dict | None" = None) -> dict:
    """Cuánto llevas de lo planeado. Se cuenta del review_history, no de un
    contador en memoria, para que recargar la página no reinicie la sesión."""
    sess = sess if sess is not None else active(conn)
    if sess is None:
        return {"active": False}
    rows = conn.execute(
        "SELECT review_kind FROM review_history WHERE source='fsrs' AND id > ?",
        (sess["from_review_id"],)).fetchall()
    # Sólo las introducciones cuentan contra el cupo de palabras nuevas; un
    # repaso en paso de aprendizaje ('learn') es un repaso.
    done_new = sum(1 for r in rows if r["review_kind"] == "new")
    done_reviews = len(rows) - done_new
    return {
        "active": True,
        "id": sess["id"],
        "started_at": sess["started_at"],
        "mode": sess["mode"],
        "minutes": sess["minutes"],
        "planned_new": sess["planned_new"],
        "planned_reviews": sess["planned_reviews"],
        "done_new": done_new,
        "done_reviews": done_reviews,
        "remaining_new": max(0, sess["planned_new"] - done_new),
        "remaining_reviews": max(0, sess["planned_reviews"] - done_reviews),
        "done": done_new + done_reviews,
        "planned": (sess["budget"] if sess.get("budget") is not None
                    else sess["planned_new"] + sess["planned_reviews"]),
        # ADR-015: en modo auto el límite es de respuestas, con repeticiones.
        "budget": sess.get("budget"),
    }


def brake(conn: sqlite3.Connection, sess: "dict | None" = None) -> "dict | None":
    """¿Se está yendo la sentada en fallos? None si no, o si no aplica."""
    sess = sess if sess is not None else active(conn)
    if sess is None or settings(conn)["fail_brake"] == "off":
        return None
    released = conn.execute(
        "SELECT value FROM settings WHERE key='brake_released_session'").fetchone()
    if released and released["value"] == str(sess["id"]):
        return None
    # En modo auto cuentan también los fallos en pasos de aprendizaje: ahí es
    # donde se iban sus sentadas (45% de acierto), y el freno de ADR-014 no
    # los veía. La primera vista de una palabra nueva no cuenta: no saberla
    # no es olvidarla. El listón es SU línea base, no un número fijo.
    auto = sess.get("mode") == "auto"
    kinds = "review_kind != 'new'" if auto else "review_kind='review'"
    row = conn.execute(
        "SELECT COUNT(*) AS n, SUM(CASE WHEN rating = 1 THEN 1 ELSE 0 END) AS again "
        f"FROM review_history WHERE source='fsrs' AND {kinds} "
        "AND id > ?", (sess["from_review_id"],)).fetchone()
    n, again = row["n"] or 0, row["again"] or 0
    bar = baseline_again(conn) if auto else {"rate": BRAKE_AGAIN_RATE, "measured": False}
    if n < BRAKE_MIN_REVIEWS or again / n <= bar["rate"]:
        return None
    return {"on": True, "reviews": n, "again": again,
            "rate": round(again / n, 2),
            "bar": bar,
            "note": f"{again} of the last {n} slipped — stopping here keeps the "
                    f"rest for a day they can stick. Finish the words in "
                    f"progress and you are done."}


BASELINE_MIN_DAYS = 8


def baseline_again(conn: sqlite3.Connection) -> dict:
    """Su tasa de fallo habitual: el cuartil alto de sus días de estudio.

    "Esta sentada va peor que tres de cada cuatro de las tuyas" es una frase
    que se puede comprobar; "35%" no es una medición de nadie. Sin días
    suficientes se usa el 35% de ADR-014 y se marca como no medido.
    """
    days: "dict[str, list]" = {}
    since = (datetime.now().date().toordinal() - 56)
    for r in conn.execute(
            "SELECT reviewed_at, rating FROM review_history WHERE source='fsrs' "
            "AND review_kind != 'new' AND reviewed_at < ?", (db.study_day_start(),)):
        stamp = datetime.fromisoformat(r["reviewed_at"])
        if stamp.date().toordinal() >= since:
            days.setdefault(db.study_day(stamp), []).append(r["rating"])
    rates = sorted(sum(1 for x in v if x == 1) / len(v)
                   for v in days.values() if len(v) >= BRAKE_MIN_REVIEWS)
    if len(rates) < BASELINE_MIN_DAYS:
        return {"rate": BRAKE_AGAIN_RATE, "measured": False, "days": len(rates)}
    return {"rate": round(rates[int(len(rates) * 0.75)], 2), "measured": True,
            "days": len(rates)}


def release_brake(conn: sqlite3.Connection) -> dict:
    """"Sigo": el freno es un consejo, no un candado. Vale para esta sentada."""
    sess = active(conn)
    if sess is None:
        return {"released": False}
    conn.execute(
        "INSERT INTO settings (key, value, updated_at) VALUES "
        "('brake_released_session', ?, ?) ON CONFLICT(key) DO UPDATE SET "
        "value=excluded.value, updated_at=excluded.updated_at",
        (str(sess["id"]), db.now_iso()))
    conn.commit()
    return {"released": True}


def limits(conn: sqlite3.Connection) -> "dict | None":
    """Los topes que la cola debe respetar, o None si no hay sesión abierta."""
    p = progress(conn)
    if not p.get("active"):
        return None
    if p.get("budget") is not None:
        return _budget_limits(conn, p)
    if brake(conn) is not None:
        # Ni vencidas ni nuevas. La escalera no se corta nunca: dejar a medias
        # una palabra que acabas de fallar es lo contrario del objetivo.
        return {"new": 0, "reviews": 0}
    return {"new": p["remaining_new"], "reviews": p["remaining_reviews"]}


def _budget_limits(conn: sqlite3.Connection, p: dict) -> dict:
    """Los topes en modo auto: TODA respuesta cuenta, repeticiones incluidas.

    ADR-009 no cortaba nunca la escalera, y por eso una sentada "de 50" se
    iba a 80-100 respuestas: la cola eran repeticiones, con el fallo subiendo
    de 28% a 57%. Aquí el presupuesto es un límite de verdad. Para no dejar
    palabras a medias, antes de agotarlo se deja de servir material nuevo y
    se reserva lo que cuesta terminar la escalera abierta.

    Lo que aun así quede a medias NO se esconde ni se reinicia: sigue vencido
    con su estado FSRS real y es lo primero de la siguiente sentada.
    """
    from app import load
    left = p["budget"] - p["done"]
    if left <= 0:
        return {"new": 0, "reviews": 0, "ladder": 0}
    ladder = conn.execute(
        "SELECT COUNT(*) FROM words WHERE card_state IN ('LEARNING','RELEARNING') "
        "AND fsrs_due <= ?", ((datetime.now(timezone.utc)
                               + _ladder_window(conn)).isoformat(),)).fetchone()[0]
    reserve = ladder * load.effort(conn)["ladder_cost"]
    if brake(conn) is not None or left <= reserve:
        # Sólo la escalera — incluida la que YA venció. Una palabra fallada
        # hace una hora sale por la cola de vencidas, no por la de
        # aprendizaje: con `reviews: 0` a secas la reserva bloqueaba justo lo
        # que existe para proteger, y la sentada se cerraba sin servir nada
        # (pasó el 2026-09-20: 3 vencidas, las 3 en escalera, 0 servidas).
        return {"new": 0, "reviews": left, "ladder": left, "ladder_only": True}
    return {"new": min(p["remaining_new"], left - reserve),
            "reviews": left - reserve, "ladder": left}


def _ladder_window(conn: sqlite3.Connection):
    from datetime import timedelta
    from app import deck
    return timedelta(minutes=deck.longest_step_minutes(conn))
