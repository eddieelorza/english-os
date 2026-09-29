"""English OS — local API (M1, ADR-006).

FastAPI over data/english.db. Read path of the app: everything is served from
SQLite (never Notion — ADR-006 rule). Run with:

    .venv/bin/uvicorn app.server:app --reload --port 8770

The dev frontend (Vite, port 5173) proxies /api to this server.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path
from contextlib import contextmanager
from typing import Iterator, Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import (activities, ai, backlog, coach, conversation, db, deck, gate,
                 shadowing,
                 explain, generator,
                 jobs, lemma, library, model, pause, podcast, routine, session, speaking,
                 srs, tts, writing)

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env() -> None:
    """Carga `.env` al importar el servidor.

    Antes lo hacía sólo `run_all.py`, así que un uvicorn arrancado a mano —o
    por launchd, que no hereda tu shell— corría sin `AI_PROVIDER` ni
    `OLLAMA_MODEL` y elegía proveedor por su cuenta. Fallo silencioso: la app
    funciona y el material sale de otro sitio (o de ninguno).

    A diferencia de `run_all.py`, aquí `.env` **no pisa** lo que ya esté en el
    entorno. Bajo launchd da igual (no hereda nada, así que `.env` manda), y
    a cambio importar este módulo deja de poder secuestrar una variable que
    un test o una herramienta hayan puesto a propósito.
    """
    env = BASE_DIR / ".env"
    if not env.is_file():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()

app = FastAPI(title="English OS", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SORTS = {
    "recent": "COALESCE(last_reviewed_on, '') DESC, word COLLATE NOCASE",
    "alpha": "word COLLATE NOCASE",
    "status": ("CASE status WHEN 'LEARNING' THEN 0 WHEN 'FAMILIAR' THEN 1 "
               "WHEN 'MASTERED' THEN 2 ELSE 3 END, word COLLATE NOCASE"),
    "most_used": "times_used DESC, word COLLATE NOCASE",
}

WORD_COLS = (
    "id, word, kind, status, cefr, meaning_en, meaning_es, pronunciation, "
    "example_en, example_es, source, deck, ease, interval_days, lapses, "
    "review_count, times_used, last_reviewed_on, "
    "audio_word, audio_example, image_path"
)


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


class NewText(BaseModel):
    title: Optional[str] = None
    body: str


class FinishText(BaseModel):
    seconds: int
    words_added: int = 0


class NewWord(BaseModel):
    word: str
    meaning_en: Optional[str] = None
    meaning_es: Optional[str] = None
    example_en: Optional[str] = None
    status: str = "LEARNING"


class GenerateReading(BaseModel):
    level: Optional[str] = None  # None → the Personal English Model decides
    minutes: int = 5
    topic: str = "Random"


class WordPatch(BaseModel):
    status: Optional[str] = None
    cefr: Optional[str] = None
    meaning_en: Optional[str] = None
    meaning_es: Optional[str] = None
    example_en: Optional[str] = None
    pronunciation: Optional[str] = None


@app.get("/api/summary")
def summary() -> dict:
    with get_db() as conn:
        by_status = dict(conn.execute(
            "SELECT status, COUNT(*) FROM words GROUP BY status").fetchall())
        last_session = conn.execute(
            "SELECT * FROM sessions ORDER BY date DESC LIMIT 1").fetchone()
        reviews_14d = conn.execute(
            "SELECT COUNT(*) FROM review_history "
            "WHERE reviewed_at >= date('now', '-14 days')").fetchone()[0]
        top_errors = [r[0] for r in conn.execute(
            "SELECT category FROM errors WHERE date >= date('now', '-14 days') "
            "GROUP BY category ORDER BY SUM(recurrences) DESC LIMIT 3")]
        return {
            "words": {s: by_status.get(s, 0) for s in db.STATUSES},
            "words_total": sum(by_status.values()),
            "reviews_14d": reviews_14d,
            "top_error_categories": top_errors,
            "last_session": dict(last_session) if last_session else None,
        }


@app.get("/api/words")
def list_words(
    q: str = "",
    status: Optional[str] = None,
    kind: Optional[str] = None,
    sort: str = "recent",
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
) -> dict:
    where, params = ["1=1"], []
    if q.strip():
        where.append("(normalized LIKE ? OR meaning_es LIKE ? OR meaning_en LIKE ?)")
        like = f"%{q.strip().lower()}%"
        params += [like, like, like]
    if status:
        if status not in db.STATUSES:
            raise HTTPException(422, f"status must be one of {db.STATUSES}")
        where.append("status = ?")
        params.append(status)
    if kind:
        if kind not in db.KINDS:
            raise HTTPException(422, f"kind must be one of {db.KINDS}")
        where.append("kind = ?")
        params.append(kind)
    order = SORTS.get(sort, SORTS["recent"])

    with get_db() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM words WHERE {' AND '.join(where)}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT {WORD_COLS} FROM words WHERE {' AND '.join(where)} "
            f"ORDER BY {order} LIMIT ? OFFSET ?",
            params + [per_page, (page - 1) * per_page],
        ).fetchall()
        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "items": [dict(r) for r in rows],
        }


@app.get("/api/words/studied-today")
def words_studied_today() -> dict:
    """Las palabras que tocaste hoy, con lo que hiciste con ellas.

    El ledger completo (3,100 filas) no responde "¿qué hice hoy?": es un
    archivo, y un archivo es la forma equivocada para las últimas horas.

    Usa el **día de estudio** (corte a las 4:00), no la fecha de calendario:
    a las 00:30 sigues en la sesión de anoche (ADR-010 D6).
    """
    with get_db() as conn:
        today = db.study_day()
        # WORD_COLS va sin prefijo; en el JOIN con review_history `id` sería
        # ambiguo, así que se cualifica aquí.
        cols = ", ".join(f"w.{c.strip()}" for c in WORD_COLS.split(","))
        rows = conn.execute(
            f"SELECT {cols}, w.card_state, "
            "       MIN(r.rating) AS worst_rating, COUNT(r.id) AS times, "
            "       MAX(r.reviewed_at) AS last_at, "
            "       SUM(r.review_kind = 'new') AS introduced "
            "FROM review_history r JOIN words w ON w.id = r.word_id "
            "WHERE r.source='fsrs' "
            "  AND substr(datetime(r.reviewed_at, ?), 1, 10) = ? "
            "GROUP BY w.id ORDER BY last_at DESC",
            (f"-{db.rollover_hour()} hours", today)).fetchall()
        items = [dict(r) for r in rows]
        return {
            "date": today,
            "total": len(items),
            "introduced": sum(1 for i in items if i["introduced"]),
            "struggled": sum(1 for i in items if i["worst_rating"] == 1),
            "items": items,
        }


@app.get("/api/words/{word_id}")
def get_word(word_id: int) -> dict:
    with get_db() as conn:
        row = conn.execute(
            f"SELECT {WORD_COLS} FROM words WHERE id=?", (word_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "word not found")
        reviews = conn.execute(
            "SELECT reviewed_at, rating, interval_days, review_kind "
            "FROM review_history WHERE word_id=? ORDER BY reviewed_at DESC "
            "LIMIT 100",
            (word_id,),
        ).fetchall()
        return {**dict(row), "reviews": [dict(r) for r in reviews]}


@app.post("/api/words", status_code=201)
def create_word(w: NewWord) -> dict:
    """Add a word met while reading. Upserts (a known word gains nothing but
    the status change is NOT applied here — reading never demotes SRS truth)."""
    if w.status not in db.STATUSES:
        raise HTTPException(422, f"status must be one of {db.STATUSES}")
    if not w.word.strip():
        raise HTTPException(422, "empty word")
    with get_db() as conn:
        wid = db.upsert_word(conn, {
            "word": w.word.strip(),
            "status": w.status,
            "source": "Reading",
            "meaning_en": w.meaning_en,
            "meaning_es": w.meaning_es,
            "example_en": w.example_en,
        })
        conn.commit()
        row = conn.execute(f"SELECT {WORD_COLS} FROM words WHERE id=?", (wid,)).fetchone()
        return dict(row)


# ── Jobs (M14) ───────────────────────────────────────────────────────────

class JobRequest(BaseModel):
    kind: str
    params: dict = {}


@app.on_event("startup")
def _start_worker() -> None:
    """One worker thread — one inference at a time — and nothing left hanging
    from a restart mid-generation."""
    with get_db() as conn:
        orphans = jobs.requeue_orphans(conn)
        if orphans:
            print(f"jobs: {orphans} trabajo(s) huérfano(s) devueltos a la cola")
    jobs.ensure_worker()


@app.post("/api/jobs", status_code=202)
def create_job(body: JobRequest) -> dict:
    with get_db() as conn:
        try:
            job = jobs.enqueue(conn, body.kind, body.params)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
    # Red de seguridad: el hilo lo arranca `_start_worker` al iniciar, pero si
    # alguna vez no estuviera, encolar sin nadie que lo recoja es silencio.
    jobs.ensure_worker()
    return job


@app.get("/api/jobs")
def list_jobs() -> dict:
    with get_db() as conn:
        return {"jobs": jobs.recent(conn), "pending": jobs.pending(conn)}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: int) -> dict:
    with get_db() as conn:
        job = jobs.get(conn, job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        return {**job, "pending": jobs.pending(conn)}


# ── Pause (M13) ──────────────────────────────────────────────────────────

class PauseStart(BaseModel):
    reason: str = ""


@app.get("/api/pause")
def pause_state() -> dict:
    with get_db() as conn:
        return {**pause.state(conn), "history": pause.history(conn)}


@app.post("/api/pause")
def pause_start(body: PauseStart) -> dict:
    with get_db() as conn:
        return pause.start(conn, body.reason)


@app.post("/api/pause/resume")
def pause_resume() -> dict:
    with get_db() as conn:
        return pause.resume(conn)


# ── Review / FSRS (M4) ───────────────────────────────────────────────────

class ReviewAnswer(BaseModel):
    word_id: int
    rating: int  # 1 again · 2 hard · 3 good · 4 easy


def _queue(conn) -> dict:
    """The queue as the open session sees it: capped by what is left to do."""
    # La compuerta, no el ajuste: `new_per_day` es sólo el techo (ADR-014 D3).
    q = srs.queue(conn, new_per_day=gate.allowed(conn)["new_per_day"],
                  limits=session.limits(conn))
    q["brake"] = session.brake(conn)
    return q


@app.get("/api/review/queue")
def review_queue() -> dict:
    with get_db() as conn:
        return {**_queue(conn), "session": session.progress(conn)}


@app.post("/api/review/answer")
def review_answer(a: ReviewAnswer) -> dict:
    with get_db() as conn:
        try:
            result = srs.answer(conn, a.word_id, a.rating)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        return {**result, "queue": _queue(conn),
                "session": session.progress(conn)}


# ── Study session (M16b) ─────────────────────────────────────────────────

class SessionStart(BaseModel):
    mode: "str | None" = None
    minutes: "int | None" = None
    new: "int | None" = None
    reviews: "int | None" = None
    less: "bool | None" = None      # ADR-015: sólo hoy, no toca preferencias


@app.get("/api/session/plan")
def session_plan(mode: "str | None" = None, minutes: "int | None" = None,
                 new: "int | None" = None, reviews: "int | None" = None,
                 less: "bool | None" = None) -> dict:
    with get_db() as conn:
        try:
            return {"plan": session.plan(conn, mode, minutes, new, reviews, less),
                    "settings": session.settings(conn),
                    "session": session.progress(conn)}
        except ValueError as exc:
            raise HTTPException(422, str(exc))


@app.post("/api/session/start")
def session_start(body: SessionStart) -> dict:
    with get_db() as conn:
        try:
            return session.start(conn, body.mode, body.minutes,
                                 body.new, body.reviews, body.less)
        except ValueError as exc:
            raise HTTPException(422, str(exc))


@app.post("/api/session/end")
def session_end() -> dict:
    with get_db() as conn:
        return session.end(conn)


# ── Deck config y preview (M17b) ─────────────────────────────────────────

@app.get("/api/deck/config")
def get_deck_config() -> dict:
    with get_db() as conn:
        return deck.config(conn)


@app.patch("/api/deck/config")
def patch_deck_config(patch: dict) -> dict:
    with get_db() as conn:
        try:
            return deck.save_config(conn, patch)
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc))


@app.get("/api/review/study-queue")
def study_queue() -> dict:
    """La cola del día separada en NEW / LEARNING / REVIEW (§10-11)."""
    with get_db() as conn:
        return srs.study_queue(conn, new_per_day=gate.allowed(conn)["new_per_day"],
                               limits=session.limits(conn))


@app.get("/api/review/preview/{word_id}")
def review_preview(word_id: int) -> dict:
    with get_db() as conn:
        try:
            return srs.preview(conn, word_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc))


@app.get("/api/backlog")
def get_backlog(new_per_day: "int | None" = None) -> dict:
    with get_db() as conn:
        return {**backlog.status(conn),
                "projection": backlog.projection(conn, new_per_day),
                "lateness": backlog.lateness(conn),
                "comeback": backlog.comeback_recall(conn),
                "spread_today": backlog.spread_today(conn)}


class PullForward(BaseModel):
    cards: int = backlog.PULL_DEFAULT


@app.post("/api/backlog/pull")
def post_backlog_pull(body: PullForward) -> dict:
    """"Study more": trae a hoy las próximas cards agendadas."""
    with get_db() as conn:
        return backlog.pull_forward(conn, body.cards)


@app.get("/api/learner")
def get_learner() -> dict:
    """Lo que el alumno hace de verdad y cómo va en eso (ADR-015 D8)."""
    from app import learner
    with get_db() as conn:
        return learner.profile(conn)


class LearnerGoal(BaseModel):
    goal: str


@app.put("/api/learner/goal")
def put_learner_goal(body: LearnerGoal) -> dict:
    from app import learner
    with get_db() as conn:
        conn.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES ('learner_goal', ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
            "updated_at=excluded.updated_at", (body.goal.strip()[:400], db.now_iso()))
        conn.commit()
        return {"goal": learner.goal(conn)}


@app.get("/api/load")
def get_load() -> dict:
    """La carga propuesta para hoy con su evidencia y su porqué (ADR-015)."""
    from app import load
    with get_db() as conn:
        return load.proposal(conn)


class LoadMore(BaseModel):
    answers: int = 20


@app.post("/api/load/more")
def post_load_more(body: LoadMore) -> dict:
    """Estudiar más, porque quieres. Suma al día de hoy; si no queda nada
    vencido, adelanta las próximas agendadas."""
    from app import load
    with get_db() as conn:
        state = load.add_more(conn, body.answers)
        pulled = {"pulled": 0}
        if backlog.due_total(conn) == 0:
            pulled = backlog.pull_forward(conn, body.answers)
        return {"extra": state["extra"], **pulled}


@app.post("/api/session/keep-going")
def post_keep_going() -> dict:
    """Suelta el freno por fallos para la sentada abierta."""
    with get_db() as conn:
        return session.release_brake(conn)


@app.post("/api/backlog/spread")
def post_backlog_spread() -> dict:
    with get_db() as conn:
        return backlog.spread(conn)


@app.get("/api/settings")
def get_settings() -> dict:
    with get_db() as conn:
        return session.settings(conn)


@app.patch("/api/settings")
def patch_settings(patch: dict) -> dict:
    with get_db() as conn:
        try:
            return session.save_settings(conn, patch)
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc))


@app.get("/api/today")
def today() -> dict:
    with get_db() as conn:
        # Sin `limits`: Today muestra la carga real del día, no lo que queda
        # de la sesión abierta. El recorte es para la pantalla de Review.
        door = gate.allowed(conn)
        q = srs.queue(conn, new_per_day=door["new_per_day"])
        q.pop("next", None)
        # Lo que de verdad es de hoy frente a lo que se agenda al sentarse:
        # Today no debe enseñar un muro que Review ya no va a servir.
        q["gate"] = door
        q["triage"] = ({"due": 0, "today": 0, "later": 0, "days": 0, "comeback": 0}
                       if q.get("paused") else backlog.outlook(conn))
        last_session = conn.execute(
            "SELECT * FROM sessions ORDER BY date DESC LIMIT 1").fetchone()
        today_session = conn.execute(
            "SELECT * FROM sessions WHERE date=?", (db.study_day(),)).fetchone()
        unread = conn.execute(
            "SELECT id, title, level FROM texts WHERE kind='reading' AND body IS NOT NULL "
            "AND finished_at IS NULL ORDER BY created_at DESC LIMIT 1").fetchone()
        return {
            "date": db.study_day(),
            "pause": pause.state(conn),
            "recommendation": model.recommend_level(conn),
            "review": q,
            "last_session": dict(last_session) if last_session else None,
            "reading_minutes_today": (
                today_session["reading_minutes"] if today_session else 0) or 0,
            "unfinished_reading": dict(unread) if unread else None,
            "error_focus": model.errors(conn)["top_categories"],
            # Las que llevas repasando sin que avancen. Hasta ahora nada te
            # decía cuáles eran: sólo volvían.
            "stuck_words": model.stuck_words(conn, limit=8),
            "stuck_total": len(model.stuck_words(conn)),
            "streak_days": model.streak(conn),
        }


# ── Podcast (M11) ────────────────────────────────────────────────────────

class GeneratePodcast(BaseModel):
    minutes: int = 5
    topic: str = "Random"
    level: Optional[str] = None


class FinishPodcast(BaseModel):
    seconds: int = 0


@app.get("/api/podcasts")
def list_podcasts() -> dict:
    with get_db() as conn:
        return {"items": podcast.listed(conn)}


@app.get("/api/podcasts/{text_id}")
def get_podcast(text_id: int) -> dict:
    with get_db() as conn:
        try:
            return podcast.detail(conn, text_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc))


@app.post("/api/podcasts", status_code=201)
def create_podcast(body: GeneratePodcast) -> dict:
    with get_db() as conn:
        try:
            return podcast.generate(conn, body.minutes, body.topic, body.level)
        except ai.AIUnavailable as exc:
            raise HTTPException(503, str(exc))
        except tts.TTSUnavailable as exc:
            raise HTTPException(503, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))


@app.post("/api/podcasts/{text_id}/finish")
def finish_podcast(text_id: int, body: FinishPodcast) -> dict:
    with get_db() as conn:
        return podcast.finish(conn, text_id, body.seconds)


# ── Library & explanations (M10) ─────────────────────────────────────────

class ExplainRequest(BaseModel):
    sentence: str
    text_id: Optional[int] = None


@app.post("/api/explain")
def explain_sentence(body: ExplainRequest) -> dict:
    with get_db() as conn:
        context = None
        if body.text_id:
            row = conn.execute("SELECT body FROM texts WHERE id=?",
                               (body.text_id,)).fetchone()
            context = row["body"] if row else None
        try:
            return explain.explain(conn, body.sentence, context)
        except ai.AIUnavailable as exc:
            raise HTTPException(503, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))


@app.get("/api/library")
def library_by_day(kind: Optional[str] = None) -> dict:
    with get_db() as conn:
        return {"days": library.by_day(conn, kind)}


@app.get("/api/library/text/{text_id}")
def library_text(text_id: int) -> dict:
    with get_db() as conn:
        try:
            return library.text_detail(conn, text_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc))


@app.delete("/api/texts/{text_id}")
def delete_text(text_id: int) -> dict:
    with get_db() as conn:
        try:
            return library.delete_text(conn, text_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc))


@app.delete("/api/activities/{activity_id}")
def delete_activity(activity_id: int) -> dict:
    with get_db() as conn:
        try:
            return library.delete_activity(conn, activity_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc))


# ── Practice: activities, writing, tip (M9) ──────────────────────────────

class ActivitySubmit(BaseModel):
    answers: list[int]
    seconds: int = 0


class WritingSubmit(BaseModel):
    text: str
    prompt: str = ""
    seconds: int = 0


@app.get("/api/activities/today")
def activities_today(regenerate: bool = False) -> dict:
    with get_db() as conn:
        try:
            return {"activities": activities.today_set(conn, regenerate)}
        except ai.AIUnavailable as exc:
            raise HTTPException(503, str(exc))


@app.post("/api/activities/{activity_id}/submit")
def activities_submit(activity_id: int, body: ActivitySubmit) -> dict:
    with get_db() as conn:
        try:
            return activities.submit(conn, activity_id, body.answers, body.seconds)
        except ValueError as exc:
            raise HTTPException(422, str(exc))


@app.get("/api/writing/prompt")
def writing_prompt() -> dict:
    with get_db() as conn:
        try:
            return writing.writing_prompt(conn)
        except ai.AIUnavailable as exc:
            raise HTTPException(503, str(exc))


# ── Writing guiado, una oración a la vez (M20) ───────────────────────────

class SentenceCheck(BaseModel):
    sentence: str
    ask: Optional[str] = None


class GuidedFinish(BaseModel):
    sentences: list[dict]
    scenario: Optional[str] = None
    seconds: int = 0


@app.get("/api/writing/steps")
def writing_steps() -> dict:
    with get_db() as conn:
        try:
            return writing.steps(conn)
        except ai.AIUnavailable as exc:
            raise HTTPException(503, str(exc))


@app.post("/api/writing/check")
def writing_check(body: SentenceCheck) -> dict:
    with get_db() as conn:
        try:
            return writing.check(conn, body.sentence, body.ask)
        except ai.AIUnavailable as exc:
            raise HTTPException(503, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))


@app.post("/api/writing/finish", status_code=201)
def writing_finish(body: GuidedFinish) -> dict:
    with get_db() as conn:
        try:
            return writing.finish(conn, body.sentences, body.scenario,
                                  body.seconds)
        except ValueError as exc:
            raise HTTPException(422, str(exc))


@app.post("/api/writing/submit", status_code=201)
def writing_submit(body: WritingSubmit) -> dict:
    with get_db() as conn:
        try:
            return writing.submit(conn, body.text, body.prompt or None, body.seconds)
        except ai.AIUnavailable as exc:
            raise HTTPException(503, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))


@app.get("/api/coach/tip")
def coach_tip(refresh: bool = False) -> dict:
    with get_db() as conn:
        try:
            return {"tip": coach.grammar_tip(conn, refresh)}
        except ai.AIUnavailable as exc:
            raise HTTPException(503, str(exc))


# ── Media & narration (M8) ───────────────────────────────────────────────

@app.get("/api/media/{kind}/{filename}")
def media(kind: str, filename: str):
    """Serve deck audio/images and generated narration from data/media/."""
    if kind not in ("audio", "images", "tts", "shadow") or "/" in filename or ".." in filename:
        raise HTTPException(404, "not found")
    path = BASE_DIR / "data" / "media" / kind / filename
    if not path.exists():
        raise HTTPException(404, "not found")
    return FileResponse(path)


@app.get("/api/tts/status")
def tts_status() -> dict:
    return tts.status()


class QuizSubmit(BaseModel):
    answers: list[int]


@app.post("/api/texts/{text_id}/quiz")
def submit_quiz(text_id: int, body: QuizSubmit) -> dict:
    """Grade a comprehension quiz (reading or podcast) and keep the result.

    Comprehension misses are NOT errors in the grammar sense, so they never
    enter the errors table — but they are evidence, and until M12 they were
    thrown away (ADR-008 D2).
    """
    with get_db() as conn:
        row = conn.execute("SELECT questions FROM texts WHERE id=?",
                           (text_id,)).fetchone()
        if row is None or not row["questions"]:
            raise HTTPException(404, "no quiz for this text")
        questions = json.loads(row["questions"])
        if len(body.answers) != len(questions):
            raise HTTPException(422, "answers do not match the number of questions")
        score = sum(1 for q, a in zip(questions, body.answers)
                    if a == q["answer_index"])
        conn.execute(
            "UPDATE texts SET quiz_score=?, quiz_total=?, quiz_answers=?, "
            "updated_at=? WHERE id=?",
            (score, len(questions), json.dumps(body.answers), db.now_iso(), text_id))
        conn.commit()
        return {"score": score, "total": len(questions)}


@app.post("/api/texts/{text_id}/narrate")
def narrate_text(text_id: int) -> dict:
    """Synthesize the reading (cached) and store the sentence timings."""
    with get_db() as conn:
        row = conn.execute("SELECT body, tts_path, tts_marks FROM texts "
                           "WHERE id=?", (text_id,)).fetchone()
        if row is None or not row["body"]:
            raise HTTPException(404, "text not found")
        if row["tts_path"] and (BASE_DIR / "data" / "media" /
                                row["tts_path"]).exists():
            return {"path": row["tts_path"],
                    "marks": json.loads(row["tts_marks"] or "[]"), "cached": True}
        try:
            result = tts.narrate(row["body"])
        except tts.TTSUnavailable as exc:
            raise HTTPException(503, str(exc))
        conn.execute("UPDATE texts SET tts_path=?, tts_marks=?, updated_at=? "
                     "WHERE id=?",
                     (result["path"], json.dumps(result["marks"], ensure_ascii=False),
                      db.now_iso(), text_id))
        conn.commit()
        return result


# ── Speaking (M6) ────────────────────────────────────────────────────────

@app.get("/api/speaking/prompt")
def get_speaking_prompt() -> dict:
    with get_db() as conn:
        try:
            return speaking.speaking_prompt(conn)
        except ai.AIUnavailable as exc:
            raise HTTPException(503, str(exc))


# `def`, no `async def`: Whisper + modelo + voz son síncronos y dentro del
# event loop congelaban TODA la API durante el turno. Así van al threadpool.
@app.post("/api/speaking/submit", status_code=201)
def submit_speaking(audio: UploadFile = File(...),
                    prompt: str = Form(default="")) -> dict:
    speaking.RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(audio.filename or "rec.webm").suffix or ".webm"
    dest = speaking.RECORDINGS_DIR / f"{db.now_iso().replace(':', '-')}{suffix}"
    dest.write_bytes(audio.file.read())
    with get_db() as conn:
        try:
            return speaking.submit(conn, dest, prompt or None)
        except ai.AIUnavailable as exc:
            raise HTTPException(503, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))


# ── Conversación hablada (M19) ───────────────────────────────────────────

class ConversationStart(BaseModel):
    topic: "str | None" = None


@app.get("/api/conversation/active")
def conversation_active() -> dict:
    with get_db() as conn:
        return {"conversation": conversation.active(conn)}


@app.get("/api/conversation/{conv_id}/turns")
def conversation_turns(conv_id: int) -> dict:
    with get_db() as conn:
        return {"turns": conversation.turns(conn, conv_id)}


@app.post("/api/conversation/warm")
def conversation_warm() -> dict:
    """Precalienta modelo y voz. Se llama al abrir la pantalla."""
    return conversation.warm()


@app.post("/api/conversation/start", status_code=201)
def conversation_start(body: ConversationStart) -> dict:
    with get_db() as conn:
        try:
            return conversation.start(conn, body.topic)
        except ai.AIUnavailable as exc:
            raise HTTPException(503, str(exc))


@app.post("/api/conversation/{conv_id}/say", status_code=201)
def conversation_say(conv_id: int, audio: UploadFile = File(...)) -> dict:
    speaking.RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(audio.filename or "rec.webm").suffix or ".webm"
    dest = speaking.RECORDINGS_DIR / f"conv{conv_id}-{db.now_iso().replace(':', '-')}{suffix}"
    dest.write_bytes(audio.file.read())
    with get_db() as conn:
        try:
            return conversation.say(conn, conv_id, dest)
        except ai.AIUnavailable as exc:
            raise HTTPException(503, str(exc))
        except ValueError as exc:
            # Silencio o micrófono mudo: 422 y no 500, para que la pantalla
            # pueda decir "no se oyó nada" en vez de "algo falló".
            raise HTTPException(422, str(exc))


@app.post("/api/conversation/{conv_id}/finish")
def conversation_finish(conv_id: int) -> dict:
    with get_db() as conn:
        try:
            return conversation.finish(conn, conv_id)
        except ai.AIUnavailable as exc:
            raise HTTPException(503, str(exc))
        except ValueError as exc:
            raise HTTPException(404, str(exc))


# ── Shadowing sobre vídeo (M20) ──────────────────────────────────────────

class ShadowCreate(BaseModel):
    url: str


@app.get("/api/shadow")
def shadow_list() -> dict:
    with get_db() as conn:
        return {"sessions": shadowing.recent(conn)}


@app.get("/api/shadow/{session_id}")
def shadow_get(session_id: int) -> dict:
    with get_db() as conn:
        try:
            return shadowing.get(conn, session_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc))


@app.post("/api/shadow", status_code=202)
def shadow_create(body: ShadowCreate) -> dict:
    """Encola el trabajo y devuelve al momento.

    Se validan aquí la URL y la duración —negarse pronto y con motivo es
    mejor que un job que falla dos minutos después—, pero bajar y transcribir
    van a la cola: un vídeo de 3.4 min tardó 309 s dentro del servidor, y una
    petición HTTP de cinco minutos se cae sola.

    Si el vídeo ya está preparado se devuelve tal cual, sin cola.
    """
    with get_db() as conn:
        try:
            meta = shadowing.probe(body.url)
        except shadowing.DownloadError as exc:
            raise HTTPException(502, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        if meta["seconds"] > shadowing.MAX_SECONDS:
            raise HTTPException(
                422, f"Ese vídeo dura {meta['seconds'] / 60:.0f} min; el tope "
                     f"son {shadowing.MAX_SECONDS // 60}.")
        existing = conn.execute(
            "SELECT id FROM shadow_sessions WHERE video_id=?",
            (meta["video_id"],)).fetchone()
        if existing:
            return {"ready": True, "session": shadowing.get(conn, existing["id"])}
        job = jobs.enqueue(conn, "shadow", {"url": body.url})
    jobs.ensure_worker()
    return {"ready": False, "job_id": job["id"], "title": meta["title"],
            "seconds": meta["seconds"]}


@app.post("/api/shadow/line/{line_id}")
def shadow_mark(line_id: int, done: bool = Query(default=True)) -> dict:
    with get_db() as conn:
        try:
            return shadowing.mark(conn, line_id, done)
        except ValueError as exc:
            raise HTTPException(404, str(exc))


# ── AI (M3) ──────────────────────────────────────────────────────────────

@app.get("/api/stats")
def stats() -> dict:
    with get_db() as conn:
        return model.stats(conn)


@app.get("/api/model")
def personal_model() -> dict:
    """The Personal English Model snapshot — the one brain every module reads."""
    with get_db() as conn:
        return model.snapshot(conn)


@app.get("/api/ai/status")
def ai_status() -> dict:
    return ai.status()


@app.post("/api/generate/reading", status_code=201)
def generate_reading(req: GenerateReading) -> dict:
    with get_db() as conn:
        try:
            return generator.generate_reading(conn, req.level, req.minutes, req.topic)
        except ai.AIUnavailable as exc:
            raise HTTPException(503, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))


# ── Texts (Reading, M2) ──────────────────────────────────────────────────

@app.get("/api/texts")
def list_texts() -> dict:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, title, date, level, topic, source, reading_seconds, "
            "finished_at, LENGTH(body) AS body_len, body FROM texts "
            "WHERE kind='reading' AND body IS NOT NULL "
            "ORDER BY created_at DESC LIMIT 100").fetchall()
        items = []
        for r in rows:
            d = dict(r)
            d["word_count"] = len(lemma.tokens(d.pop("body") or ""))
            items.append(d)
        return {"items": items}


@app.get("/api/reading/brief")
def reading_brief() -> dict:
    """Lo que necesita una rutina para escribir la lectura del día (ADR-016)."""
    with get_db() as conn:
        return generator.brief(conn)


class RoutineReading(BaseModel):
    title: str
    body: str
    level: str
    questions: list
    words_target: list


@app.post("/api/reading/submit", status_code=201)
def reading_submit(r: RoutineReading) -> dict:
    """Recibe la lectura de la rutina, la valida con las reglas del generador
    y la guarda. 409 si el día ya tiene una; 422 con el motivo si no cumple."""
    with get_db() as conn:
        try:
            return generator.submit_reading(conn, r.model_dump())
        except generator.ReadingExists as exc:
            raise HTTPException(409, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))


@app.get("/api/routine/brief/{kind}")
def routine_brief(kind: str) -> dict:
    """El encargo del material de hoy para Claude Code (ADR-016 D5)."""
    with get_db() as conn:
        try:
            return routine.brief(conn, kind)
        except ValueError as exc:
            raise HTTPException(422, str(exc))


@app.post("/api/routine/submit/{kind}", status_code=201)
def routine_submit(kind: str, data: dict) -> dict:
    """Recibe el material escrito por Claude Code, lo valida con las reglas de
    la app y lo guarda. 409 si el día ya lo tiene; 422 con el motivo."""
    with get_db() as conn:
        try:
            return routine.submit(conn, kind, data)
        except routine.AlreadyExists as exc:
            raise HTTPException(409, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))


@app.post("/api/texts", status_code=201)
def create_text(t: NewText) -> dict:
    body = t.body.strip()
    # Pasted text often carries markdown emphasis (Notion exports mark target
    # vocabulary as **word**); strip it so the reader shows clean prose.
    body = re.sub(r"\*\*(.+?)\*\*", r"\1", body)
    body = re.sub(r"__(.+?)__", r"\1", body)
    body = re.sub(r"(?<!\w)[*_](\S[^*_]*?)[*_](?!\w)", r"\1", body)
    if not body:
        raise HTTPException(422, "empty body")
    words = lemma.tokens(body)
    title = (t.title or "").strip() or " ".join(words[:6]) + "…"
    with get_db() as conn:
        tid = db.upsert_text(conn, {
            "kind": "reading",
            "title": title,
            "date": db.study_day(),
            "body": body,
            "source": "pasted",
        })
        conn.commit()
        return {"id": tid, "title": title, "word_count": len(words)}


@app.get("/api/texts/{text_id}")
def get_text(text_id: int) -> dict:
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, title, date, level, topic, source, body, questions, "
            "words_target, reading_seconds, finished_at "
            "FROM texts WHERE id=? AND body IS NOT NULL",
            (text_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "text not found")
        d = dict(row)
        d["questions"] = json.loads(d["questions"]) if d["questions"] else None
        d["words_target"] = json.loads(d["words_target"]) if d["words_target"] else None
        return {**d, "lexicon": lemma.build_lexicon(row["body"], conn)}


@app.post("/api/texts/{text_id}/finish")
def finish_text(text_id: int, f: FinishText) -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT id FROM texts WHERE id=?", (text_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "text not found")
        conn.execute(
            "UPDATE texts SET reading_seconds=?, finished_at=?, updated_at=? WHERE id=?",
            (f.seconds, db.now_iso(), db.now_iso(), text_id))
        today = db.study_day()
        prev = conn.execute(
            "SELECT reading_minutes FROM sessions WHERE date=?", (today,)).fetchone()
        minutes = round((prev["reading_minutes"] or 0) if prev else 0, 2) + round(f.seconds / 60, 2)
        db.upsert_session(conn, today, {"reading_minutes": round(minutes, 2)})
        conn.commit()
        try:
            srs.mark_seen(conn, text_id)   # sus NEW entran antes al mazo
        except Exception:  # noqa: BLE001 — terminar de leer nunca debe fallar
            pass
        return {"ok": True, "reading_minutes_today": round(minutes, 2)}


@app.patch("/api/words/{word_id}")
def patch_word(word_id: int, patch: WordPatch) -> dict:
    updates = {k: v for k, v in patch.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(422, "empty patch")
    if "status" in updates and updates["status"] not in db.STATUSES:
        raise HTTPException(422, f"status must be one of {db.STATUSES}")
    with get_db() as conn:
        exists = conn.execute("SELECT 1 FROM words WHERE id=?", (word_id,)).fetchone()
        if not exists:
            raise HTTPException(404, "word not found")
        sets = ", ".join(f"{k}=?" for k in updates)
        conn.execute(
            f"UPDATE words SET {sets}, updated_at=? WHERE id=?",
            list(updates.values()) + [db.now_iso(), word_id],
        )
        conn.commit()
    return get_word(word_id)


# ── El frontend compilado (opción A) ─────────────────────────────────────
#
# Con esto la app se sirve entera desde aquí y `npm run dev` deja de hacer
# falta para USARLA (sigue haciendo falta para desarrollarla). Va al final
# del módulo a propósito: el comodín de abajo captura todo lo que no haya
# casado antes, así que cualquier ruta /api declarada después de este punto
# quedaría muerta.

DIST = BASE_DIR / "frontend" / "dist"


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str) -> FileResponse:
    """Sirve el build de Vite, con vuelta a `index.html` para las rutas del
    router (/review, /vocabulary…), que no existen como archivo."""
    # Un /api que no casó es un 404 de verdad. Sin esto, una ruta mal escrita
    # devolvería el HTML de la app con un 200 y el fallo aparecería como
    # "JSON inválido" muy lejos de su causa.
    if full_path.startswith("api/") or full_path == "api":
        raise HTTPException(404, "not found")
    if not DIST.is_dir():
        raise HTTPException(
            503, "frontend sin compilar — corre `npm run build --prefix frontend`")

    index = DIST / "index.html"
    if not full_path:
        return FileResponse(index)

    # `resolve()` antes de comparar: sin esta guarda, una ruta con .. serviría
    # cualquier archivo del disco. El comodín es exactamente donde eso entra.
    candidate = (DIST / full_path).resolve()
    if candidate.is_file() and candidate.is_relative_to(DIST.resolve()):
        return FileResponse(candidate)
    return FileResponse(index)
