"""Notion (VOCAB + Error Library + Writing/Reading metadata) → SQLite (ADR-006 M0).

Merge policy for VOCAB: rows match local words by `Anki Note ID`; Notion only
fills gaps (its meanings were curated there first) except `Times Used`, where
Notion is authoritative — that counter never existed in Anki. Rows with no
Anki note (manually added words) are created as Notion-sourced words.

Requires NOTION_TOKEN + DB ids in the environment (load .env first, e.g. by
importing run_all). Idempotent by notion_page_id.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "scripts"))

from app import db  # noqa: E402
from notion_client import NotionClient  # noqa: E402
from notion_blocks import (  # noqa: E402
    get_title, get_rich_text, get_number, get_select, get_date, get_checkbox,
)


def _import_vocab(c: NotionClient, conn: sqlite3.Connection, stats: dict) -> None:
    vocab_db = os.environ.get("VOCAB_DB_ID", "").strip()
    if not vocab_db:
        print("⏭  notion: falta VOCAB_DB_ID — skip vocab.")
        return
    for page in c.query_database(vocab_db):
        p = page["properties"]
        word = get_title(p, "Word").strip()
        if not word:
            continue
        nid = get_number(p, "Anki Note ID")
        times_used = get_number(p, "Times Used")
        data = {
            "word": word,
            "notion_page_id": page["id"],
            "anki_note_id": int(nid) if nid else None,
            "meaning_en": get_rich_text(p, "Meaning (EN)") or None,
            "meaning_es": get_rich_text(p, "Meaning (ES)") or None,
            "pronunciation": get_rich_text(p, "Pronunciation") or None,
            "example_en": get_rich_text(p, "Example (EN)") or None,
            "deck": get_rich_text(p, "Deck") or None,
            "source": get_select(p, "Source") or "Notion",
            "times_used": int(times_used) if times_used else 0,
        }
        if not data["anki_note_id"]:
            # Manual word: no SRS evidence; been used in exercises → LEARNING.
            data["status"] = "LEARNING" if data["times_used"] else "NEW"
        db.upsert_word(conn, data, overwrite=("times_used",))
        stats["vocab"] += 1

    # Words from retired decks (stale Anki note id → no SRS row, review_count
    # NULL): the only evidence left is usage in exercises. Used → LEARNING.
    conn.execute(
        "UPDATE words SET status='LEARNING' WHERE status='NEW' "
        "AND times_used > 0 AND review_count IS NULL"
    )


def _import_errors(c: NotionClient, conn: sqlite3.Connection, stats: dict) -> None:
    errors_db = os.environ.get("ERRORS_DB_ID", "").strip()
    if not errors_db:
        print("⏭  notion: falta ERRORS_DB_ID — skip errors.")
        return
    for page in c.query_database(errors_db):
        p = page["properties"]
        db.upsert_error(conn, {
            "notion_page_id": page["id"],
            "date": get_date(p, "Date"),
            "category": get_select(p, "Category"),
            "error": get_title(p, "Error") or None,
            "original": get_rich_text(p, "Original") or None,
            "correction": get_rich_text(p, "Correction") or None,
            "explanation": get_rich_text(p, "Explanation") or None,
            "source": get_select(p, "Source"),
            "status": get_select(p, "Status"),
            "priority": get_select(p, "Priority"),
            "recurrences": int(get_number(p, "Recurrences") or 1),
            "last_practiced_on": get_date(p, "Last Practiced"),
        })
        stats["errors"] += 1


def _import_texts(c: NotionClient, conn: sqlite3.Connection, stats: dict) -> None:
    writing_db = os.environ.get("WRITING_DB_ID", "").strip()
    reading_db = os.environ.get("READING_DB_ID", "").strip()
    if writing_db:
        for page in c.query_database(writing_db):
            p = page["properties"]
            wp = get_number(p, "Words Produced")
            ec = get_number(p, "Errors Count")
            db.upsert_text(conn, {
                "notion_page_id": page["id"],
                "kind": "writing",
                "title": get_title(p, "Task") or None,
                "date": get_date(p, "Date"),
                "topic": get_select(p, "Tense Focus"),
                "corrected": 1 if get_checkbox(p, "Corrected") else 0,
                "words_produced": int(wp) if wp else None,
                "errors_count": int(ec) if ec else None,
                "source": "notion",
            })
            stats["texts"] += 1
    if reading_db:
        for page in c.query_database(reading_db):
            p = page["properties"]
            db.upsert_text(conn, {
                "notion_page_id": page["id"],
                "kind": "reading",
                "title": get_title(p, "Title") or None,
                "date": get_date(p, "Date"),
                "level": get_select(p, "Level"),
                "source": "notion",
            })
            stats["texts"] += 1


def run(conn: sqlite3.Connection, force: bool = False) -> dict:
    """Importa VOCAB, Error Library y páginas desde Notion.

    **Se detiene si Notion ya está apagado** (ADR-012). A diferencia de Anki,
    aquí el riesgo no es pisar el scheduling sino resucitar filas: Notion
    quedó congelado con menos contenido que la app (878 palabras contra 3,103,
    16 errores contra 35) y reimportarlo solo puede desordenar.
    """
    from app import cutover
    if cutover.notion_done(conn) and not force:
        return {"skipped": "notion-off",
                "since": cutover.notion_state(conn)["date"],
                "vocab": 0, "errors": 0, "texts": 0}

    stats = {"vocab": 0, "errors": 0, "texts": 0}
    c = NotionClient()
    _import_vocab(c, conn, stats)
    _import_errors(c, conn, stats)
    _import_texts(c, conn, stats)
    conn.commit()
    return stats


if __name__ == "__main__":
    import run_all  # noqa: F401  (loads .env)
    print("notion →", run(db.connect()))
