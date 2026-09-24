"""The Personal English Model (ADR-006 M5) — one brain, many arms.

Every module that generates, recommends or reports consults THIS layer
(Vision P3: a single component makes the pedagogical decisions). It reads
only SQLite and returns plain dicts; generators never query learner state
on their own.

Honesty rules carried over from the legacy pipeline (Vision P4 / ADR-004):
- Accuracy metrics with < MIN_SAMPLE_WORDS produced in the window are None
  ("not enough data") — never an invented number.
- The level recommendation states its reason.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from app import db  # noqa: E402

ERROR_WINDOW_DAYS = 14
MIN_SAMPLE_WORDS = 150   # below this, errors/100 words is noise (ADR-004)
TARGET_WORD_COUNT = 12
NEW_PER_DAY = 5


def _one(conn, sql, *args):
    row = conn.execute(sql, args).fetchone()
    return row[0] if row else None


# ── Building blocks ──────────────────────────────────────────────────────

def vocabulary(conn: sqlite3.Connection) -> dict:
    counts = dict(conn.execute(
        "SELECT status, COUNT(*) FROM words GROUP BY status").fetchall())
    return {
        "counts": {s: counts.get(s, 0) for s in db.STATUSES},
        "total": sum(counts.values()),
    }


# ── Palabras atascadas ───────────────────────────────────────────────────
#
# 11 palabras (6% de las cards) se llevaban el 16% de todos los repasos, y
# seguían sin despegar: `rear` con 22 repasos y un intervalo de 1 día. Repetir
# la misma card no las estaba moviendo.
#
# La señal no es el número de fallos sino la **dificultad de FSRS**, que va de
# 1 a 10 y en estas está en 9.5+. Contar fallos las coge DESPUÉS de fallar
# tres veces; la dificultad las coge antes — `mill` y `needle` ya estaban ahí
# antes de acumular un solo lapse.
#
# Los otros dos filtros evitan falsos positivos: una palabra recién
# introducida puede tener dificultad alta sin ser un problema todavía.
STUCK_DIFFICULTY = 9.5
STUCK_MIN_REVIEWS = 6     # ya la has visto bastantes veces
STUCK_MAX_INTERVAL = 10   # y aun así no despega

# Cuánto del material puede ocupar una palabra atascada. Llenar una lectura
# sólo con las difíciles produce un texto raro y sin contexto donde agarrarse:
# se aprende de material mayormente conocido con algo nuevo dentro.
STUCK_SHARE = 0.5
# Las palabras que vuelven (ADR-014 D4) también entran al material: "continuar
# donde me quedé" es reencontrarlas en una historia, no sólo en una card.
COMEBACK_SHARE = 0.25


def stuck_words(conn: sqlite3.Connection,
                limit: "int | None" = None) -> "list[dict]":
    """Las que llevas repasando sin que avancen, peor primero."""
    sql = ("SELECT word, normalized, meaning_es, lapses, review_count, "
           "       interval_days, ROUND(difficulty, 1) AS difficulty "
           "FROM words WHERE difficulty >= ? AND review_count >= ? "
           "  AND interval_days <= ? "
           "ORDER BY difficulty DESC, review_count DESC")
    args = [STUCK_DIFFICULTY, STUCK_MIN_REVIEWS, STUCK_MAX_INTERVAL]
    if limit:
        sql += " LIMIT ?"
        args.append(limit)
    return [dict(r) for r in conn.execute(sql, args)]


def learning_words(conn: sqlite3.Connection,
                   n: int = TARGET_WORD_COUNT) -> "list[dict]":
    """The words every generator must reuse.

    Order: **stuck words first** (up to half the slots), then LEARNING most
    recently studied, topped up with FAMILIAR needing reinforcement.

    Why stuck words lead: this function is the single choke point for every
    generator — readings, activities, podcast, speaking and writing all call
    it. Putting them here is what turns "repeat the failing card" into "meet
    the word in a story, then in an exercise, then in a conversation". They
    are NOT suspended the way Anki does it: hiding a word you want to learn
    solves the metric, not the problem.
    """
    out: "list[dict]" = []
    seen: "set[str]" = set()

    def add(rows) -> None:
        for r in rows:
            d = dict(r)
            if d["normalized"] in seen or len(out) >= n:
                continue
            seen.add(d["normalized"])
            out.append(d)

    add(stuck_words(conn, limit=max(1, int(n * STUCK_SHARE))))
    add(conn.execute(
        "SELECT word, normalized, meaning_es FROM words "
        "WHERE comeback_on IS NOT NULL ORDER BY fsrs_due LIMIT ?",
        (max(1, int(n * COMEBACK_SHARE)),)))
    for status in ("LEARNING", "FAMILIAR"):
        if len(out) >= n:
            break
        add(conn.execute(
            "SELECT word, normalized, meaning_es FROM words WHERE status=? "
            "ORDER BY COALESCE(last_reviewed_on,'') DESC LIMIT ?",
            (status, n - len(out))))
    # los generadores esperan estas tres claves; las de stuck traen más
    return [{k: w.get(k) for k in ("word", "normalized", "meaning_es")}
            for w in out]


def errors(conn: sqlite3.Connection,
           window_days: int = ERROR_WINDOW_DAYS) -> dict:
    since = (date.today() - timedelta(days=window_days)).isoformat()
    cats = [r[0] for r in conn.execute(
        "SELECT category FROM errors WHERE category IS NOT NULL AND date >= ? "
        "GROUP BY category ORDER BY SUM(recurrences) DESC LIMIT 3", (since,))]
    # Free production is writing AND speaking (ADR-008 D1): a day he spoke
    # instead of writing is still a day he produced English.
    words_produced = _one(conn,
        "SELECT COALESCE(SUM(words_produced),0) FROM texts "
        "WHERE kind IN ('writing','speaking') AND corrected=1 AND date >= ?",
        (since)) or 0
    errors_total = _one(conn,
        "SELECT COALESCE(SUM(errors_count),0) FROM texts "
        "WHERE kind IN ('writing','speaking') AND corrected=1 AND date >= ?",
        (since)) or 0
    enough = words_produced >= MIN_SAMPLE_WORDS
    return {
        "window_days": window_days,
        "top_categories": cats,
        "words_produced": int(words_produced),
        "errors_total": int(errors_total),
        "errors_per_100": (round(errors_total * 100 / words_produced, 1)
                           if enough else None),
        "enough_data": enough,
    }


def review_performance(conn: sqlite3.Connection, window_days: int = 7) -> dict:
    since = (date.today() - timedelta(days=window_days)).isoformat()
    # Anki sessions (imported) + in-app FSRS reviews, one honest blend.
    srow = conn.execute(
        "SELECT COALESCE(SUM(cards_reviewed),0), COALESCE(SUM(again),0) "
        "FROM sessions WHERE date >= ?", (since,)).fetchone()
    anki_reviews, anki_again = int(srow[0]), int(srow[1])
    frow = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(rating=1),0) FROM review_history "
        "WHERE source='fsrs' AND reviewed_at >= ?", (since,)).fetchone()
    fsrs_reviews, fsrs_again = int(frow[0]), int(frow[1])
    total = anki_reviews + fsrs_reviews
    again = anki_again + fsrs_again
    return {
        "window_days": window_days,
        "reviews": total,
        "again_rate": (round(again / total, 3) if total else None),
        "fsrs_reviews": fsrs_reviews,
    }


def reading_activity(conn: sqlite3.Connection, window_days: int = 7) -> dict:
    since = (date.today() - timedelta(days=window_days)).isoformat()
    minutes = _one(conn,
        "SELECT COALESCE(SUM(reading_minutes),0) FROM sessions WHERE date >= ?",
        (since)) or 0
    finished = _one(conn,
        "SELECT COUNT(*) FROM texts WHERE kind='reading' "
        "AND finished_at >= ?", (since)) or 0
    return {"window_days": window_days,
            "minutes": round(float(minutes), 1),
            "texts_finished": int(finished)}


def streak(conn: sqlite3.Connection) -> int:
    """Consecutive days with study evidence. **Paused days are neutral**: they
    neither count nor break the run (ADR-008 D3) — telling the system you're
    away should never be punished."""
    from app import pause  # local import: pause imports db, not model
    active = {r[0] for r in conn.execute("SELECT date FROM sessions")}
    # Un repaso a las 00:30 pertenece al día de estudio anterior, no a uno
    # nuevo: sin restar la hora de corte, trasnochar parte la racha en dos
    # (M17a). El desplazamiento se hace en SQL sobre el sello local guardado.
    active |= {r[0] for r in conn.execute(
        "SELECT DISTINCT substr(datetime(reviewed_at, ?), 1, 10) "
        "FROM review_history WHERE source='fsrs'",
        (f"-{db.rollover_hour()} hours",))}
    skip = pause.paused_days(conn)

    today = date.fromisoformat(db.study_day())
    n, day = 0, today
    while True:
        key = day.isoformat()
        if key in active:
            n += 1
        elif key in skip:
            pass                       # neutral: keep walking back
        elif day == today:
            pass                       # today may simply not have started yet
        else:
            break
        day -= timedelta(days=1)
    return n


# ── Evidence: what the last fortnight actually shows (ADR-008 D1) ────────
#
# Four independent sources, each with its own honest minimum. The level is
# read from whatever is available — a fortnight without writing is still
# assessable, because recall, comprehension and controlled practice are all
# real evidence. Before M12 only writing could unlock B2, which meant a
# learner who never typed had a permanent ceiling.

MIN_REVIEWS = 50        # recall
MIN_COMPREHENSION = 12  # questions answered across readings + podcasts
MIN_CONTROLLED = 20     # activity questions
# free production keeps the ADR-004 rule: MIN_SAMPLE_WORDS


def _signal(value: "float | None", consolidate_below: float,
            stretch_at: float, higher_is_better: bool = True) -> "str | None":
    """Turn a measurement into one of: consolidate / hold / stretch."""
    if value is None:
        return None
    if higher_is_better:
        if value < consolidate_below:
            return "consolidate"
        return "stretch" if value >= stretch_at else "hold"
    if value > consolidate_below:
        return "consolidate"
    return "stretch" if value <= stretch_at else "hold"


def evidence(conn: sqlite3.Connection, window_days: int = ERROR_WINDOW_DAYS) -> dict:
    """The four sources, each with its measurement, sample size and verdict."""
    since = (date.today() - timedelta(days=window_days)).isoformat()

    perf = review_performance(conn, window_days=7)
    retention = (1 - perf["again_rate"]) if perf["again_rate"] is not None else None
    recall_enough = perf["reviews"] >= MIN_REVIEWS

    row = conn.execute(
        "SELECT COALESCE(SUM(quiz_score),0), COALESCE(SUM(quiz_total),0) "
        "FROM texts WHERE quiz_total IS NOT NULL AND date >= ?", (since,)).fetchone()
    comp_score, comp_total = int(row[0]), int(row[1])
    comp_rate = (comp_score / comp_total) if comp_total else None

    row = conn.execute(
        "SELECT COALESCE(SUM(score),0), COALESCE(SUM(total),0) FROM activities "
        "WHERE score IS NOT NULL AND date >= ?", (since,)).fetchone()
    act_score, act_total = int(row[0]), int(row[1])
    act_rate = (act_score / act_total) if act_total else None

    err = errors(conn, window_days)

    return {
        "window_days": window_days,
        "recall": {
            "label": "recall", "value": round(retention, 3) if retention else None,
            "display": f"{round(retention * 100)}% retention" if retention else None,
            "n": perf["reviews"], "unit": "reviews",
            "enough": recall_enough and retention is not None,
            "signal": _signal(retention, 0.80, 0.88) if recall_enough else None,
        },
        "comprehension": {
            "label": "comprehension",
            "value": round(comp_rate, 3) if comp_rate is not None else None,
            "display": f"{round(comp_rate * 100)}% comprehension" if comp_rate is not None else None,
            "n": comp_total, "unit": "questions",
            "enough": comp_total >= MIN_COMPREHENSION,
            "signal": (_signal(comp_rate, 0.60, 0.80)
                       if comp_total >= MIN_COMPREHENSION else None),
        },
        "controlled": {
            "label": "practice accuracy",
            "value": round(act_rate, 3) if act_rate is not None else None,
            "display": f"{round(act_rate * 100)}% in practice" if act_rate is not None else None,
            "n": act_total, "unit": "questions",
            "enough": act_total >= MIN_CONTROLLED,
            "signal": (_signal(act_rate, 0.60, 0.80)
                       if act_total >= MIN_CONTROLLED else None),
        },
        "production": {
            "label": "free production",
            "value": err["errors_per_100"],
            "display": (f"{err['errors_per_100']} errors/100 words"
                        if err["errors_per_100"] is not None else None),
            "n": err["words_produced"], "unit": "words spoken or written",
            "enough": err["enough_data"],
            "signal": (_signal(err["errors_per_100"], 10, 6, higher_is_better=False)
                       if err["enough_data"] else None),
        },
    }


def recommend_level(conn: sqlite3.Connection) -> dict:
    """B1 base, B1+ when the evidence supports it, B2 when several sources
    insist. Rules, not vibes (Vision P4) — and the answer names the evidence
    it used, so a verdict can always be argued with."""
    ev = evidence(conn)
    sources = [s for s in (ev["recall"], ev["comprehension"],
                           ev["controlled"], ev["production"]) if s["signal"]]

    if not sources:
        return {"level": "B1", "evidence": [],
                "reason": "no evidence yet this fortnight — hold the base level"}

    weak = [s for s in sources if s["signal"] == "consolidate"]
    strong = [s for s in sources if s["signal"] == "stretch"]
    used = ", ".join(s["display"] for s in sources if s["display"])

    # The weakest link governs: a gap anywhere means consolidate, however
    # good the rest looks. Stretching on a cracked foundation is how people
    # plateau.
    if weak:
        names = ", ".join(s["display"] for s in weak if s["display"])
        return {"level": "B1", "evidence": [s["label"] for s in sources],
                "reason": f"{names} — consolidate before stretching"}

    if len(strong) >= 2:
        return {"level": "B2", "evidence": [s["label"] for s in sources],
                "reason": f"{used} — several sources agree, stretch"}
    if strong:
        return {"level": "B1+", "evidence": [s["label"] for s in sources],
                "reason": f"{used} — a step up is earned"}
    if len(sources) >= 2:
        return {"level": "B1+", "evidence": [s["label"] for s in sources],
                "reason": f"{used} — comfortable at level, stretch gently"}
    return {"level": "B1", "evidence": [s["label"] for s in sources],
            "reason": f"{used} — one source only, hold until more evidence"}


# ── Stats series (M7) — evidence over sensation, drawn ───────────────────

def daily_series(conn: sqlite3.Connection, days: int = 30) -> "list[dict]":
    """One row per day: reviews (Anki sessions + in-app FSRS), minutes."""
    since = (date.today() - timedelta(days=days - 1)).isoformat()
    sess = {r["date"]: dict(r) for r in conn.execute(
        "SELECT date, cards_reviewed, reading_minutes, speaking_minutes "
        "FROM sessions WHERE date >= ?", (since,))}
    fsrs = dict(conn.execute(
        "SELECT substr(reviewed_at,1,10) AS d, COUNT(*) FROM review_history "
        "WHERE source='fsrs' AND reviewed_at >= ? GROUP BY d", (since,)))
    out = []
    for i in range(days):
        d = (date.today() - timedelta(days=days - 1 - i)).isoformat()
        s = sess.get(d, {})
        out.append({
            "date": d,
            "reviews": int(s.get("cards_reviewed") or 0) + int(fsrs.get(d, 0)),
            "reading_minutes": round(float(s.get("reading_minutes") or 0), 1),
            "speaking_minutes": round(float(s.get("speaking_minutes") or 0), 1),
        })
    return out


def weekly_series(conn: sqlite3.Connection, weeks: int = 12) -> "list[dict]":
    """Vocabulary growth (first-ever review per word) + weekly retention.
    Retention is None on weeks without reviews — never invented."""
    firsts = [r[0][:10] for r in conn.execute(
        "SELECT MIN(reviewed_at) FROM review_history GROUP BY word_id")]
    monday = date.today() - timedelta(days=date.today().weekday())
    starts = [monday - timedelta(weeks=w) for w in range(weeks - 1, -1, -1)]
    base = sum(1 for f in firsts if date.fromisoformat(f) < starts[0])

    sess = conn.execute(
        "SELECT date, cards_reviewed, again FROM sessions").fetchall()
    fsrs = conn.execute(
        "SELECT substr(reviewed_at,1,10) AS d, COUNT(*) AS n, "
        "COALESCE(SUM(rating=1),0) AS again FROM review_history "
        "WHERE source='fsrs' GROUP BY d").fetchall()

    out, cumulative = [], base
    for start in starts:
        end = start + timedelta(days=7)
        in_week = lambda ds: start <= date.fromisoformat(ds) < end  # noqa: E731
        introduced = sum(1 for f in firsts if in_week(f))
        cumulative += introduced
        reviews = sum(int(s["cards_reviewed"] or 0) for s in sess if in_week(s["date"]))
        again = sum(int(s["again"] or 0) for s in sess if in_week(s["date"]))
        reviews += sum(int(f["n"]) for f in fsrs if in_week(f["d"]))
        again += sum(int(f["again"]) for f in fsrs if in_week(f["d"]))
        out.append({
            "week_start": start.isoformat(),
            "introduced": introduced,
            "cumulative": cumulative,
            "reviews": reviews,
            "retention": (round(1 - again / reviews, 3) if reviews else None),
        })
    return out


def stats(conn: sqlite3.Connection) -> dict:
    vocab = vocabulary(conn)
    total_reviews = _one(conn, "SELECT COUNT(*) FROM review_history") or 0
    texts_read = _one(conn,
        "SELECT COUNT(*) FROM texts WHERE kind='reading' AND finished_at IS NOT NULL") or 0
    speaking_sessions = _one(conn,
        "SELECT COUNT(*) FROM texts WHERE kind='speaking'") or 0
    return {
        "totals": {
            "words_known": (vocab["counts"]["LEARNING"]
                            + vocab["counts"]["FAMILIAR"]
                            + vocab["counts"]["MASTERED"]),
            "mastered": vocab["counts"]["MASTERED"],
            "vocabulary": vocab["counts"],
            "reviews_all_time": int(total_reviews),
            "texts_read": int(texts_read),
            "speaking_sessions": int(speaking_sessions),
            "streak_days": streak(conn),
        },
        "recommendation": recommend_level(conn),
        "evidence": evidence(conn),
        "review_7d": review_performance(conn),
        "errors_14d": errors(conn),
        "daily": daily_series(conn),
        "weekly": weekly_series(conn),
        # El precio del reparto del rezago (ADR-009 D4): no basta con
        # repartir, hay que poder mirar lo que cuesta.
        "lateness": _lateness_block(conn),
    }


def _lateness_block(conn: sqlite3.Connection) -> dict:
    from app import backlog
    return {
        "summary": backlog.lateness(conn),
        "by_bucket": backlog.recall_by_lateness(conn),
        "weekly": backlog.lateness_series(conn),
        "spreads": backlog.spreads_in(conn),
        "min_sample": backlog.MIN_BUCKET_REVIEWS,
    }


# ── The snapshot every module consumes ───────────────────────────────────

def snapshot(conn: sqlite3.Connection) -> dict:
    return {
        "date": db.study_day(),
        "vocabulary": vocabulary(conn),
        "learning_words": [w["word"] for w in learning_words(conn)],
        "errors": errors(conn),
        "review": review_performance(conn),
        "reading": reading_activity(conn),
        "streak_days": streak(conn),
        "evidence": evidence(conn),
        "recommendation": recommend_level(conn),
    }
