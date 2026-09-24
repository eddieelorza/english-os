"""Anki collection → SQLite (ADR-006 M0).

Reads a *copy* of collection.anki2 (Anki may hold the original locked) and
imports every note plus the full revlog. This is richer than what ever reached
Notion: the revlog carries each review's rating, interval and duration — the
raw material FSRS (M4) needs.

Idempotent: words upsert by anki_note_id, reviews by anki_revlog_id.
"""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from app import db  # noqa: E402

DEFAULT_COLLECTION = (
    Path.home() / "Library" / "Application Support" / "Anki2" / "User 1"
    / "collection.anki2"
)

# Candidate Anki field names per target column, in priority order — same
# philosophy as anki_notion_sync.FIELD_MAP (the deck's own fields carry the
# right sense; an empty column beats a wrong one). Matches Eddie's AJ-Basic
# model: Word, Meaning (=ES gloss), Example_en, Example_es, IPA.
FIELD_MAP = {
    "meaning_en": ("Definition", "Meaning_en", "Meaning (EN)", "English", "Sense"),
    "meaning_es": ("Meaning", "Meaning_es", "Spanish", "Español", "Espanol",
                   "Traducción", "Traduccion", "Example_es_gloss"),
    "example_en": ("Example_en", "Example", "Sentence", "Usage"),
    "example_es": ("Example_es",),
    "pronunciation": ("IPA", "Pronunciation", "Phonetic", "Fonética"),
}

REVLOG_KINDS = {0: "learn", 1: "review", 2: "relearn", 3: "filtered", 4: "manual"}


def strip_html(s: str) -> str:
    s = (s or "").replace("<br>", " ").replace("<div>", " ").replace("</div>", " ")
    s = re.sub(r"\[sound:[^\]]+\]", "", s)
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _open_copy(collection_path: Path, tmp_dir: str) -> sqlite3.Connection:
    copy = Path(tmp_dir) / "collection_copy.anki2"
    shutil.copy2(collection_path, copy)
    conn = sqlite3.connect(str(copy))
    # Anki uses a custom 'unicase' collation; register a lowercase stand-in so
    # any indexed text column is readable.
    conn.create_collation(
        "unicase", lambda a, b: (a.lower() > b.lower()) - (a.lower() < b.lower())
    )
    conn.row_factory = sqlite3.Row
    return conn


def _field_names(anki: sqlite3.Connection) -> "dict[int, list[str]]":
    out: "dict[int, list[str]]" = {}
    for row in anki.execute("SELECT ntid, ord, name FROM fields ORDER BY ntid, ord"):
        out.setdefault(row["ntid"], []).append(row["name"])
    return out


def _pick(named: "dict[str, str]", target: str) -> "str | None":
    lookup = {k.lower(): v for k, v in named.items()}
    for candidate in FIELD_MAP[target]:
        val = strip_html(lookup.get(candidate.lower(), ""))
        if val:
            return val
    return None


def _ivl_days(ivl: int) -> float:
    """Anki interval: positive = days, negative = seconds."""
    return float(ivl) if ivl >= 0 else round(-ivl / 86400.0, 4)


def run(conn: sqlite3.Connection,
        collection_path: "Path | None" = None,
        force: bool = False) -> dict:
    """Importa palabras y revlog de la colección de Anki.

    **Se detiene si ya se hizo el cut-over** (ADR-011). Este importador
    escribe con `overwrite=("status", "ease", "interval_days", ...)`: tras el
    corte, Anki tiene datos viejos y esa escritura devolvería palabras que la
    app ya avanzó al estado que Anki recuerda. Es corrupción silenciosa, del
    tipo que se descubre semanas después.
    """
    from app import cutover
    if cutover.done(conn) and not force:
        return {"skipped": "cut-over", "since": cutover.state(conn)["date"],
                "words_new": 0, "words_seen": 0,
                "reviews_new": 0, "reviews_seen": 0}

    src = Path(collection_path
               or os.environ.get("ANKI_COLLECTION_PATH")
               or DEFAULT_COLLECTION)
    stats = {"words_new": 0, "words_seen": 0, "reviews_new": 0, "reviews_seen": 0}
    if not src.exists():
        raise FileNotFoundError(f"Anki collection not found: {src}")

    with tempfile.TemporaryDirectory() as tmp:
        anki = _open_copy(src, tmp)
        try:
            fields_by_nt = _field_names(anki)
            decks = {row["id"]: row["name"].replace("\x1f", "::")
                     for row in anki.execute("SELECT id, name FROM decks")}

            # cards aggregated per note — the most advanced card represents
            # the note (same convention as anki_notion_sync).
            cards_by_note: "dict[int, dict]" = {}
            card_note: "dict[int, int]" = {}
            for c in anki.execute(
                    "SELECT id, nid, did, queue, ivl, factor, reps, lapses FROM cards"):
                card_note[c["id"]] = c["nid"]
                agg = cards_by_note.setdefault(c["nid"], {
                    "queue": c["queue"], "ivl": 0, "factor": 0,
                    "reps": 0, "lapses": 0, "did": c["did"],
                })
                agg["queue"] = max(agg["queue"], c["queue"])
                agg["ivl"] = max(agg["ivl"], c["ivl"])
                agg["factor"] = max(agg["factor"], c["factor"])
                agg["reps"] = max(agg["reps"], c["reps"])
                agg["lapses"] = max(agg["lapses"], c["lapses"])

            # last review timestamp per note, straight from the revlog.
            last_review: "dict[int, str]" = {}
            for r in anki.execute(
                    "SELECT cid, MAX(id) AS ts FROM revlog GROUP BY cid"):
                nid = card_note.get(r["cid"])
                if nid is None:
                    continue
                iso = datetime.fromtimestamp(r["ts"] / 1000).isoformat(
                    timespec="seconds")
                if nid not in last_review or iso > last_review[nid]:
                    last_review[nid] = iso

            word_ids: "dict[int, int]" = {}  # anki nid → words.id
            for note in anki.execute("SELECT id, mid, flds FROM notes"):
                values = note["flds"].split("\x1f")
                names = fields_by_nt.get(note["mid"], [])
                named = dict(zip(names, values))
                word = strip_html(values[0] if values else "")
                if not word:
                    continue
                agg = cards_by_note.get(note["id"], {
                    "queue": 0, "ivl": 0, "factor": 0, "reps": 0,
                    "lapses": 0, "did": None,
                })
                existing = conn.execute(
                    "SELECT 1 FROM words WHERE anki_note_id=?",
                    (note["id"],)).fetchone()
                wid = db.upsert_word(conn, {
                    "word": word,
                    "anki_note_id": note["id"],
                    "source": "Anki",
                    "deck": decks.get(agg["did"]),
                    "meaning_en": _pick(named, "meaning_en"),
                    "meaning_es": _pick(named, "meaning_es"),
                    "example_en": _pick(named, "example_en"),
                    "example_es": _pick(named, "example_es"),
                    "pronunciation": _pick(named, "pronunciation"),
                    "status": db.derive_status(
                        agg["queue"], agg["ivl"], agg["lapses"]),
                    "ease": (agg["factor"] / 1000.0) if agg["factor"] else None,
                    "interval_days": agg["ivl"] or None,
                    "lapses": agg["lapses"],
                    "review_count": agg["reps"],
                    "last_reviewed_on": last_review.get(note["id"]),
                }, overwrite=("status", "ease", "interval_days", "lapses",
                              "review_count", "last_reviewed_on", "deck"))
                word_ids[note["id"]] = wid
                stats["words_seen" if existing else "words_new"] += 1

            for r in anki.execute(
                    "SELECT id, cid, ease, ivl, lastIvl, factor, time, type "
                    "FROM revlog ORDER BY id"):
                nid = card_note.get(r["cid"])
                wid = word_ids.get(nid) if nid else None
                if wid is None:
                    continue  # review of a deleted/foreign note
                inserted = db.insert_review(conn, {
                    "word_id": wid,
                    "reviewed_at": datetime.fromtimestamp(
                        r["id"] / 1000).isoformat(timespec="seconds"),
                    "rating": r["ease"],
                    "interval_days": _ivl_days(r["ivl"]),
                    "last_interval_days": _ivl_days(r["lastIvl"]),
                    "ease": (r["factor"] / 1000.0) if r["factor"] else None,
                    "took_ms": r["time"],
                    "review_kind": REVLOG_KINDS.get(r["type"], "review"),
                    "source": "anki",
                    "anki_revlog_id": r["id"],
                    "anki_card_id": r["cid"],
                })
                stats["reviews_new" if inserted else "reviews_seen"] += 1
        finally:
            anki.close()

    conn.commit()
    return stats


if __name__ == "__main__":
    c = db.connect()
    print("anki →", run(c))
