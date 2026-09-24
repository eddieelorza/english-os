"""Upsert today's Daily Plan row and rebuild the 🎯 TODAY section (ADR-002, F1).

Runs as the last step of `run_all.py session-end`. Reads what the pipeline
already produced today (VOCAB sync, Writing/Reading pages, learner profile)
and turns it into: one Daily Plan row (idempotent by Date) plus a single
callout block at the top of the ENGLISH SYSTEM page with everything Eddie
needs for the session — links included.

Recommendation is rules-only (v0, ADR-002). When ANTHROPIC_API_KEY exists a
later phase may refine it via Claude; the rules remain the fallback.

Requires in .env: DAILY_PLAN_DB_ID, ENGLISH_SYSTEM_PAGE_ID (plus the usual).
Exits 0 with a notice if they're missing so the legacy pipeline never breaks.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from notion_client import NotionClient  # noqa: E402
from notion_blocks import (  # noqa: E402
    title_prop, rich_text_prop, number_prop, date_prop, select_prop,
    get_checkbox, get_select, get_rich_text, block_plain_text,
)
import error_metrics  # noqa: E402

BASE = Path(__file__).resolve().parent.parent
PROFILE_FILE = BASE / "data" / "learner_profile.json"

DAILY_PLAN_DB = os.environ.get("DAILY_PLAN_DB_ID", "").strip()
MAIN_PAGE = os.environ.get("ENGLISH_SYSTEM_PAGE_ID", "").strip()
VOCAB_DB = os.environ.get("VOCAB_DB_ID", "").strip()
WRITING_DB = os.environ.get("WRITING_DB_ID", "").strip()
READING_DB = os.environ.get("READING_DB_ID", "").strip()

TODAY_MARKER = "🎯 TODAY"
FORMATS = ["Story", "Dialogue", "Spot & Fix", "Free Writing",
           "Role Play", "Email", "Opinion"]
# Fallback only: used until Error Library has real data. Taken from Eddie's
# own list in the PROMPT page.
SEED_TARGET_ERRORS = "I mayúscula · verbos irregulares · preposiciones (in/on/at)"


def today_iso() -> str:
    return dt.date.today().isoformat()


def load_profile_entry(day: str) -> dict:
    try:
        profile = json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
        return profile.get("days", {}).get(day, {})
    except Exception:
        return {}


def profile_streak_last7() -> int:
    try:
        profile = json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
        days = profile.get("days", {})
    except Exception:
        return 0
    cutoff = dt.date.today() - dt.timedelta(days=7)
    return sum(1 for d in days if dt.date.fromisoformat(d) > cutoff)


# ── Recommendation rules v0 (ADR-002) ────────────────────────────────────

def recommend(entry: dict, yesterday_format: str | None,
              backlog: tuple[int, int], streak7: int, err: dict) -> dict:
    stuck, unproduced = backlog
    tips: list[str] = []

    again_rate = entry.get("again_rate", 0)
    if again_rate > 0.20:
        tips.append(f"Again rate alto ({again_rate:.0%}): mañana menos palabras "
                    "nuevas y sesión de repaso.")
    if err.get("top_categories"):
        tips.append(f"Foco de hoy: {err['top_categories'][0]} "
                    f"(tu error más recurrente de las últimas 2 semanas).")
    if err.get("enough_data"):
        tips.append(f"Vas en {err['errors_per_100']} errores/100 palabras.")
    if stuck:
        tips.append(f"Hay {stuck} writing(s) marcados esperando corrección; "
                    "si no llega hoy, corre «run_all.py review».")
    elif unproduced >= 3:
        tips.append("Llevas varias sesiones sin escribir: 5 líneas hoy valen "
                    "más que 50 palabras nuevas de Anki.")
    if streak7 < 3:
        tips.append("Racha baja esta semana: sesión ligera hoy, lo importante "
                    "es no romper el hábito.")
    if not tips:
        tips.append("Buen ritmo. Prioriza la producción libre: escribe sin "
                    "diccionario y marca «Ready for Review» al terminar.")

    target = " · ".join(err.get("top_categories") or []) or SEED_TARGET_ERRORS

    if yesterday_format in FORMATS:
        fmt = FORMATS[(FORMATS.index(yesterday_format) + 1) % len(FORMATS)]
    else:
        fmt = FORMATS[dt.date.today().toordinal() % len(FORMATS)]

    # Nivel de la lectura (la routine lo lee de la fila Daily Plan). Regla
    # v0, conservadora y basada en datos (Vision P4): B1 es la base declarada
    # por Eddie; sube a B1+ solo cuando hay muestra suficiente de producción
    # corregida Y la precisión lo respalda. Sin datos, nunca sube.
    difficulty = "B1"
    if err.get("enough_data") and err.get("errors_per_100", 99) < 5:
        difficulty = "B1+"

    return {
        "format": fmt,
        "skill": "Writing",
        "difficulty": difficulty,
        "target_errors": target,
        "recommendation": " ".join(tips),
    }


# ── Notion lookups ───────────────────────────────────────────────────────

def find_by_title(c: NotionClient, db_id: str, prop: str, value: str) -> dict | None:
    return c.find_first(db_id, {"property": prop, "title": {"equals": value}})


def count_words_synced_today(c: NotionClient) -> int:
    filt = {"property": "Synced On", "date": {"equals": today_iso()}}
    return len(list(c.query_database(VOCAB_DB, filt)))


def writing_backlog(c: NotionClient) -> tuple[int, int]:
    """(stuck, unproduced) over the last 7 days.

    stuck      = marked Ready for Review but still uncorrected → the pipeline
                 owes Eddie a correction (actionable by the system).
    unproduced = sessions created but never corrected → Eddie didn't write
                 (actionable by Eddie). Counting these as "pending correction"
                 would nag him about pages he is never going back to.
    """
    since = (dt.date.today() - dt.timedelta(days=7)).isoformat()
    base = [{"property": "Date", "date": {"on_or_after": since}},
            {"property": "Corrected", "checkbox": {"equals": False}}]
    unproduced = len(list(c.query_database(WRITING_DB, {"and": base})))
    stuck = len(list(c.query_database(WRITING_DB, {"and": base + [
        {"property": "Ready for Review", "checkbox": {"equals": True}}]})))
    return stuck, unproduced - stuck


def yesterday_plan_format(c: NotionClient) -> str | None:
    y = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    page = c.find_first(DAILY_PLAN_DB, {"property": "Date", "date": {"equals": y}})
    return get_select(page["properties"], "Format") if page else None


# ── Daily Plan upsert ────────────────────────────────────────────────────

def upsert_plan_row(c: NotionClient, rec: dict, entry: dict, words: int,
                    reading: dict | None, writing: dict | None) -> dict:
    day = today_iso()
    props = {
        "Session":      title_prop(f"Session – {day}"),
        "Date":         date_prop(day),
        "Skill":        select_prop(rec["skill"]),
        "Difficulty":   select_prop(rec["difficulty"]),
        "Format":       select_prop(rec["format"]),
        "Words Today":  number_prop(words),
        "Anki Reviews": number_prop(entry.get("cards_reviewed")),
        "Again Rate":   number_prop(entry.get("again_rate")),
        "Target Errors":  rich_text_prop(rec["target_errors"]),
        "Recommendation": rich_text_prop(rec["recommendation"]),
    }
    if reading:
        props["Reading"] = {"relation": [{"id": reading["id"]}]}
    if writing:
        props["Writing"] = {"relation": [{"id": writing["id"]}]}

    # session_id keys the cloud routine's idempotency (ADR-003). Deliberately
    # the DATE alone: a second study burst must NOT reset AI Status and make
    # the routine regenerate material on top of what Eddie is already working
    # on (ADR-001 rev. 2026-07-30). Regenerating is an explicit --force action.
    session_id = day

    existing = c.find_first(DAILY_PLAN_DB, {"property": "Date", "date": {"equals": day}})
    if existing:
        if get_rich_text(existing["properties"], "AI Session") != session_id:
            props["AI Session"] = rich_text_prop(session_id)
            props["AI Status"] = select_prop("Pending")
        # Never touch Status or Results on update: those belong to Eddie/review.
        c.update_page(existing["id"], props)
        print(f"✅ Daily Plan actualizado: Session – {day}")
        return c._request("GET", f"/pages/{existing['id']}")
    props["Status"] = select_prop("Pendiente")
    props["AI Session"] = rich_text_prop(session_id)
    props["AI Status"] = select_prop("Pending")
    page = c.create_page(DAILY_PLAN_DB, props)
    print(f"🆕 Daily Plan creado: Session – {day}")
    return page


# ── TODAY section on the main page ───────────────────────────────────────

def link_paragraph(label: str, url: str) -> dict:
    return {
        "object": "block", "type": "paragraph",
        "paragraph": {"rich_text": [
            {"type": "text", "text": {"content": label, "link": {"url": url}}}
        ]},
    }


def plain_paragraph(text: str) -> dict:
    return {
        "object": "block", "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }


def build_today_callout(entry: dict, words: int, rec: dict, session_done: bool,
                        reading: dict | None, writing: dict | None,
                        plan: dict | None, err: dict) -> dict:
    day = today_iso()
    state = ("Sesión completada 🎉" if session_done
             else "Anki procesado ✅ · Actividades pendientes")
    reviews = entry.get("cards_reviewed")
    again = entry.get("again_rate")
    anki_line = (f"Anki: {reviews} reviews · {entry.get('introduced', 0)} nuevas"
                 + (f" · again {again:.0%}" if again is not None else "")
                 ) if reviews is not None else "Anki: sin datos de hoy"
    est = 30 if words < 15 else 40

    children = [
        plain_paragraph(state),
        plain_paragraph(f"{anki_line} · {words} palabras del día · ~{est} min"),
    ]
    if reading:
        children.append(link_paragraph("📖 Lectura de hoy", reading["url"]))
    if writing:
        children.append(link_paragraph("✍️ Writing y actividades", writing["url"]))
    if plan:
        children.append(link_paragraph(f"🗓️ Plan de la sesión ({rec['format']})",
                                       plan["url"]))

    accuracy = (f"{err['errors_per_100']} errores/100 palabras"
                if err.get("enough_data") else "Sin datos suficientes")
    focus = err["top_categories"][0] if err.get("top_categories") else "—"
    children.append(plain_paragraph(
        f"📊 Precisión (14d): {accuracy} · Foco: {focus}"))
    children.append(plain_paragraph(f"💡 {rec['recommendation']}"))

    return {
        "object": "block", "type": "callout",
        "callout": {
            "rich_text": [{"type": "text",
                           "text": {"content": f"{TODAY_MARKER} — {day}"}}],
            "icon": {"type": "emoji", "emoji": "🎯"},
            "color": "blue_background",
            "children": children,
        },
    }


def find_today_callout(c: NotionClient, block_id: str,
                       depth: int = 0) -> tuple[str, str] | None:
    """(parent_id, block_id) of the existing TODAY callout, wherever it lives.

    Eddie rearranges his page freely (columns, toggles). Searching only the
    page's top level meant a moved callout was never found: the script would
    append a second one and his copy would silently go stale. So we look
    inside containers too, and rebuild the callout *in place*.
    """
    if depth > 3:
        return None
    for b in c.get_block_children(block_id):
        if b["type"] == "callout" and block_plain_text(b).startswith(TODAY_MARKER):
            return block_id, b["id"]
        if b.get("has_children") and b["type"] in ("column_list", "column", "toggle"):
            found = find_today_callout(c, b["id"], depth + 1)
            if found:
                return found
    return None


def rewrite_today_section(c: NotionClient, callout: dict) -> None:
    existing = find_today_callout(c, MAIN_PAGE)
    if existing:
        parent_id, old_id = existing
        # Insert the fresh one right after the old one, then remove the old:
        # this keeps Eddie's chosen position (column, toggle, wherever).
        c.append_block_children(parent_id, [callout], after=old_id)
        c.delete_block(old_id)
        print("✅ Sección 🎯 TODAY actualizada (en su posición actual)")
        return

    children = c.get_block_children(MAIN_PAGE)
    anchor = children[0]["id"] if children else None
    c.append_block_children(MAIN_PAGE, [callout], after=anchor)
    print("✅ Sección 🎯 TODAY creada en ENGLISH SYSTEM")


# ── Main ─────────────────────────────────────────────────────────────────

def run() -> None:
    missing = [k for k, v in (("DAILY_PLAN_DB_ID", DAILY_PLAN_DB),
                              ("ENGLISH_SYSTEM_PAGE_ID", MAIN_PAGE)) if not v]
    if missing:
        print(f"⏭  daily_plan_update: falta {', '.join(missing)} en .env — skip.")
        return

    c = NotionClient()
    day = today_iso()
    entry = load_profile_entry(day)
    words = count_words_synced_today(c)
    reading = find_by_title(c, READING_DB, "Title", f"Reading – {day}")
    writing = find_by_title(c, WRITING_DB, "Task", f"Writing Session – {day}")
    session_done = bool(writing) and get_checkbox(writing["properties"], "Corrected")

    err = error_metrics.aggregate(c)
    error_metrics.save_to_profile(err)

    rec = recommend(
        entry,
        yesterday_plan_format(c),
        writing_backlog(c),
        profile_streak_last7(),
        err,
    )

    plan = upsert_plan_row(c, rec, entry, words, reading, writing)
    callout = build_today_callout(entry, words, rec, session_done,
                                  reading, writing, plan, err)
    rewrite_today_section(c, callout)


if __name__ == "__main__":
    run()
