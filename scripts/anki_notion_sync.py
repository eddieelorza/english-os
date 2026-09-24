"""Sync today's Anki review notes into the Notion Vocabulary Master database.

Pulls notes rated today via AnkiConnect (or the add-on's session snapshot when
Anki has closed) and upserts them into Notion using `Anki Note ID` as the
business key. Meanings and pronunciation come from the Anki note's own fields —
never from external dictionaries, which guessed the wrong sense (ADR-005).

A failure on one word never aborts the whole sync — each word is wrapped in
try/except, fails are counted, and a summary line is printed at the end.
All Notion calls go through NotionClient which retries on 429/5xx.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import time
import traceback
from pathlib import Path

import requests

# Local imports
sys.path.insert(0, str(Path(__file__).resolve().parent))
from notion_client import NotionClient, NotionError  # noqa: E402
from notion_blocks import (  # noqa: E402
    title_prop,
    rich_text_prop,
    number_prop,
    date_prop,
    select_prop,
)

ANKI_URL = "http://localhost:8765"
NOTION_DB_ID = os.environ.get("NOTION_DB_ID", "").strip()
if not NOTION_DB_ID:
    raise SystemExit("Falta NOTION_DB_ID en el entorno")

# ── Property names (ajusta si renombraste en Notion) ─────────────────────
P_TITLE         = "Word"
P_SOURCE        = "Source"
P_ANKI_NOTE_ID  = "Anki Note ID"
P_ANKI_STATE    = "Anki State"
P_EASE          = "Ease"
P_LAPSES        = "Lapses"
P_REVIEW_COUNT  = "Review Count"
P_LAST_REVIEWED = "Last Reviewed"
P_SYNCED_ON     = "Synced On"
P_DECK          = "Deck"
P_MEANING_EN    = "Meaning (EN)"
P_MEANING_ES    = "Meaning (ES)"
P_PRONUN        = "Pronunciation"
P_EXAMPLE_EN    = "Example (EN)"
SOURCE_VALUE    = "Anki"

# Side session for AnkiConnect.
# Notion calls go through `notion` (NotionClient) below.
external = requests.Session()
notion = NotionClient()


# ── AnkiConnect ──────────────────────────────────────────────────────────

SNAPSHOT_FILE = Path(__file__).resolve().parent.parent / "data" / "anki_session.json"
_snapshot: dict | None = None  # loaded lazily, only if AnkiConnect goes away


def _load_snapshot() -> dict | None:
    """Session snapshot written by the Anki add-on before the collection closes.

    Anki (and AnkiConnect with it) can die *while* this script runs — that is
    exactly what happens when Eddie closes Anki right after studying. Rather
    than fail the day, we serve the same four actions from the snapshot.
    """
    global _snapshot
    if _snapshot is None:
        try:
            data = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
            if data.get("date") != dt.date.today().isoformat():
                print(f"⚠️  Snapshot es de {data.get('date')}, no de hoy; lo ignoro.")
                return None
            _snapshot = data
            print(f"📸 Usando snapshot local ({len(data.get('notes', []))} notas) "
                  f"— AnkiConnect no está disponible.")
        except Exception:
            return None
    return _snapshot


def _anki_from_snapshot(action: str, params: dict):
    snap = _load_snapshot()
    if snap is None:
        raise RuntimeError(
            "AnkiConnect no responde y no hay snapshot de hoy. "
            "Abre Anki y corre: python3 run_all.py session-end --force")
    notes = snap["notes"]
    if action == "findNotes":
        return [n["noteId"] for n in notes]
    if action == "notesInfo":
        wanted = set(params.get("notes", []))
        return [n for n in notes if n["noteId"] in wanted]
    if action == "findCards":
        nid = int(params["query"].split("nid:")[1])
        return [nid]  # placeholder id; cardsInfo below keys off it
    if action == "cardsInfo":
        nid = params["cards"][0]
        for n in notes:
            if n["noteId"] == nid:
                return n["cards"]
        return []
    raise RuntimeError(f"Acción no soportada por el snapshot: {action}")


def anki(action: str, params: dict | None = None):
    if _snapshot is not None:  # already fell back; stay there
        return _anki_from_snapshot(action, params or {})
    payload = {"action": action, "version": 6, "params": params or {}}
    try:
        r = external.post(ANKI_URL, json=payload, timeout=30)
        r.raise_for_status()
    except Exception:
        # Any transport-level problem → snapshot.
        return _anki_from_snapshot(action, params or {})

    try:
        data = r.json()
    except ValueError:
        return _anki_from_snapshot(action, params or {})

    if data.get("error"):
        # A *shutting down* Anki answers HTTP 200 with an error payload
        # ("collection is not open"). That looked like a hard failure and
        # killed the run 2 s in; it is just another reason to use the
        # snapshot the add-on left behind.
        try:
            return _anki_from_snapshot(action, params or {})
        except RuntimeError:
            raise RuntimeError(f"AnkiConnect error: {data['error']}")
    return data["result"]


def map_state(queue: int) -> str:
    # 0=new, 1/3=learning, 2=review, -1=suspended, -2=buried
    if queue == 0:
        return "new"
    if queue in (1, 3):
        return "learning"
    if queue == -1:
        return "suspended"
    if queue == -2:
        return "buried"
    return "review"


# ── Notion helpers (thin wrappers over NotionClient) ─────────────────────

def notion_find_by_note_id(note_id: int) -> dict | None:
    filt = {"property": P_ANKI_NOTE_ID, "number": {"equals": float(note_id)}}
    return notion.find_first(NOTION_DB_ID, filt)


def notion_get_note_ids_synced_today() -> set[int]:
    today = dt.date.today().isoformat()
    filt = {
        "and": [
            {"property": P_SOURCE,    "select": {"equals": SOURCE_VALUE}},
            {"property": P_SYNCED_ON, "date":   {"equals": today}},
        ]
    }
    out: set[int] = set()
    for page in notion.query_database(NOTION_DB_ID, filt):
        prop = page.get("properties", {}).get(P_ANKI_NOTE_ID, {})
        val = prop.get("number")
        if val is not None:
            out.add(int(val))
    return out


def should_fill_rich_text(page: dict, prop_name: str) -> bool:
    """True if the property is missing or has an empty rich_text/title body."""
    if not page:
        return True
    p = page.get("properties", {}).get(prop_name)
    if not p:
        return True
    t = p.get("type")
    if t == "rich_text":
        return len(p.get("rich_text", [])) == 0
    if t == "title":
        return len(p.get("title", [])) == 0
    return True


# ── Text cleaning ────────────────────────────────────────────────────────

def strip_html(s: str) -> str:
    s = s.replace("<br>", " ").replace("<div>", " ").replace("</div>", " ")
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", s).strip()


def clean_spanish_translation(es: str) -> str | None:
    if not es:
        return None
    s = es.strip()
    if len(s) > 40:
        for sep in ["—", " - ", ". ", " (", "  "]:
            if sep in s:
                s = s.split(sep)[0].strip()
                break
    if ";" in s:
        parts = [p.strip() for p in s.split(";") if p.strip()]
        s = "; ".join(parts[:3])
    elif "," in s and len(s) > 25:
        parts = [p.strip() for p in s.split(",") if p.strip()]
        s = ", ".join(parts[:3])
    s = s.rstrip(" .;")
    if len(s) > 60:
        s = s[:60].rstrip(" ,;") + "…"
    return s or None


# ── External enrichment ─────────────────────────────────────────────────

def is_media_only(value: str) -> bool:
    """True for fields that only hold audio/image markup."""
    v = re.sub(r"\[sound:[^\]]+\]", "", value or "")
    v = re.sub(r"<img[^>]*>", "", v)
    return not strip_html(v)


# Explicit field mapping, in priority order per target column. Beats keyword
# guessing: Eddie's deck (model "AJ-Basic") names the SPANISH gloss "Meaning",
# so a heuristic looking for "meaning" filled the English column with Spanish.
FIELD_MAP = {
    "en_def":  ("Definition", "Meaning_en", "Meaning (EN)", "English", "Sense"),
    "es":      ("Meaning", "Meaning_es", "Spanish", "Español", "Espanol",
                "Traducción", "Traduccion"),
    "example": ("Example_en", "Example", "Sentence", "Usage"),
    "ipa":     ("IPA", "Pronunciation", "Phonetic", "Fonética"),
}


def pick_mapped(fields: dict, target: str) -> str | None:
    """First non-empty, non-media value among the candidate names for `target`.
    Matching is case-insensitive; unknown decks simply yield None (empty column
    beats a wrong one)."""
    lookup = {name.lower(): data for name, data in fields.items()}
    for candidate in FIELD_MAP[target]:
        data = lookup.get(candidate.lower())
        if not data:
            continue
        raw = data.get("value") or ""
        val = strip_html(raw)
        if val and not is_media_only(raw):
            return val
    return None


def extract_from_note(fields: dict, word_field: str) -> tuple[str | None, str | None,
                                                              str | None, str | None]:
    """(meaning_en, meaning_es, pronunciation, example_en) from the Anki note.

    Replaces dictionaryapi.dev + MyMemory (ADR-005): those guessed the sense out
    of context ("poor" → "the poor as a social group") and truncated Spanish to
    60 chars, so the columns were noise. The deck Eddie actually studies carries
    the right sense — use it, and leave a column empty rather than wrong.

    His deck has no English definition, but it does have an English example
    sentence, which is better input anyway: the word in real context.
    """
    en = pick_mapped(fields, "en_def")
    es = pick_mapped(fields, "es")
    pron = pick_mapped(fields, "ipa")
    example = pick_mapped(fields, "example")

    if en and len(en) > 220:
        en = en[:220] + "…"
    if example and len(example) > 300:
        example = example[:300] + "…"
    return en, es, pron, example


# ── Props builder ────────────────────────────────────────────────────────

def build_props(word, nid, state, ease, lapses, reps, deck,
                meaning_en=None, meaning_es=None, pron=None, example=None) -> dict:
    today = dt.date.today().isoformat()
    props = {
        P_TITLE:         title_prop(word),
        P_ANKI_NOTE_ID:  number_prop(nid),
        P_ANKI_STATE:    select_prop(state),
        P_EASE:          number_prop(ease),
        P_LAPSES:        number_prop(lapses),
        P_REVIEW_COUNT:  number_prop(reps),
        P_LAST_REVIEWED: date_prop(today),
        P_SYNCED_ON:     date_prop(today),
        P_DECK:          rich_text_prop(deck),
        P_SOURCE:        select_prop(SOURCE_VALUE),
    }
    if meaning_en:
        props[P_MEANING_EN] = rich_text_prop(meaning_en)
    if meaning_es:
        props[P_MEANING_ES] = rich_text_prop(meaning_es)
    if pron:
        props[P_PRONUN] = rich_text_prop(pron)
    if example:
        props[P_EXAMPLE_EN] = rich_text_prop(example)
    return props


# ── Per-word processing ──────────────────────────────────────────────────

def process_note(note: dict, fill_meanings: bool) -> tuple[str, str]:
    """Returns (status, label) where status is 'created'|'updated'."""
    nid = note["noteId"]
    fields = note["fields"]
    first_field_key = next(iter(fields.keys()))
    word = strip_html(fields[first_field_key]["value"] or "")
    if not word:
        return ("skip", f"nid={nid} (empty word field)")

    card_ids = anki("findCards", {"query": f"nid:{nid}"})
    cards = anki("cardsInfo", {"cards": card_ids}) if card_ids else []

    reps   = max((c.get("reps", 0)   for c in cards), default=0)
    lapses = max((c.get("lapses", 0) for c in cards), default=0)
    ease   = (max((c.get("factor", 0) for c in cards), default=0) / 1000) if cards else 0
    queue  = max((c.get("queue", 2)  for c in cards), default=2)
    state  = map_state(queue)
    deck   = cards[0].get("deckName", "") if cards else ""

    existing = notion_find_by_note_id(nid)

    meaning_en = meaning_es = pron = example = None
    if fill_meanings:
        # Everything comes from the note itself now — no network, no guessing,
        # no rate limiting. Only fill what's empty in Notion.
        en_tmp, es_tmp, pron_tmp, ex_tmp = extract_from_note(fields, first_field_key)
        if not existing or should_fill_rich_text(existing, P_MEANING_EN):
            meaning_en = en_tmp
        if not existing or should_fill_rich_text(existing, P_MEANING_ES):
            meaning_es = es_tmp
        if not existing or should_fill_rich_text(existing, P_PRONUN):
            pron = pron_tmp
        if not existing or should_fill_rich_text(existing, P_EXAMPLE_EN):
            example = ex_tmp

    props = build_props(word, nid, state, ease, lapses, reps, deck,
                        meaning_en, meaning_es, pron, example)

    if existing:
        notion.update_page(existing["id"], props)
        return ("updated", word)
    notion.create_page(NOTION_DB_ID, props)
    return ("created", word)


# ── Main ─────────────────────────────────────────────────────────────────

def run(
    deck_name: str | None = None,
    today_only: bool = True,
    limit: int | None = None,
    fill_meanings: bool = True,
    skip_if_already_synced_today: bool = True,
) -> None:
    query_parts: list[str] = []
    if deck_name:
        query_parts.append(f'deck:"{deck_name}"')
    if today_only:
        query_parts.append("rated:1")
    query = " ".join(query_parts)
    print(f"🔎 Anki query: {query!r}")

    note_ids = anki("findNotes", {"query": query})
    if limit:
        note_ids = note_ids[:limit]
    if not note_ids:
        print("No se encontraron notas.")
        return

    notes_info = anki("notesInfo", {"notes": note_ids})

    synced_today: set[int] = set()
    if today_only and skip_if_already_synced_today:
        print("⚡ Cargando palabras ya sincronizadas hoy desde Notion...")
        synced_today = notion_get_note_ids_synced_today()
        print(f"🧠 Total ya sincronizadas hoy: {len(synced_today)}")

    counters = {"created": 0, "updated": 0, "skipped": 0, "failed": 0}
    failures: list[tuple[int, str, str]] = []  # (nid, word_or_marker, error)

    for note in notes_info:
        nid = note.get("noteId")
        if today_only and skip_if_already_synced_today and int(nid) in synced_today:
            counters["skipped"] += 1
            continue
        try:
            status, label = process_note(note, fill_meanings=fill_meanings)
            if status == "skip":
                counters["skipped"] += 1
                print(f"⏭  Skip: {label}")
            else:
                counters[status] += 1
                icon = "🆕" if status == "created" else "✅"
                print(f"{icon} {status.title()}: {label}")
        except NotionError as exc:
            counters["failed"] += 1
            failures.append((nid, "?", f"NotionError: {exc}"))
            print(f"❌ Notion error on nid={nid}: {exc}")
        except Exception as exc:
            counters["failed"] += 1
            failures.append((nid, "?", f"{type(exc).__name__}: {exc}"))
            print(f"❌ Failed nid={nid}: {type(exc).__name__}: {exc}")
            print(traceback.format_exc(limit=3))

    # Final summary
    total = sum(counters.values())
    print()
    print(f"━ Resumen: {total} notas procesadas")
    print(f"   🆕 creadas:  {counters['created']}")
    print(f"   ✅ actualizadas: {counters['updated']}")
    print(f"   ⏭  saltadas: {counters['skipped']}")
    print(f"   ❌ fallidas: {counters['failed']}")

    if failures:
        print()
        print("Detalle de fallidas:")
        for nid, word, err in failures[:20]:
            print(f"   • nid={nid}: {err}")
        if len(failures) > 20:
            print(f"   … y {len(failures) - 20} más")
        # Non-zero exit so run_all.py logs the failure, but only if EVERYTHING
        # failed; partial failures are normal and shouldn't kill the pipeline.
        if counters["failed"] == total - counters["skipped"]:
            raise SystemExit(1)


if __name__ == "__main__":
    run(deck_name=None, today_only=True, limit=None, fill_meanings=True)
