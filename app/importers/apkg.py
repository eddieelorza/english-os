"""Anki .apkg → local media library (ADR-007 M8).

Eddie's Essential English Words deck ships a recording of every word AND of
every example sentence (7,188 MP3s), plus an illustration per word. That is
the pronunciation audio his ear already knows from Anki — so the app imports
it instead of synthesizing it.

Mapping is by normalized word text (the deck he studies was built from this
one), not by note id: the .apkg carries the *shared* deck's ids, which differ
from the ids in his own collection.

Idempotent: files already extracted are skipped, and a word that already has
audio is left alone.
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE))
from app import db  # noqa: E402

MEDIA_DIR = BASE / "data" / "media"
AUDIO_DIR = MEDIA_DIR / "audio"
IMAGE_DIR = MEDIA_DIR / "images"
DEFAULT_APKG = BASE / "data" / "Essential_English_Words_en-es.apkg"

SOUND_RE = re.compile(r"\[sound:([^\]]+)\]")
IMG_RE = re.compile(r'<img[^>]+src="([^"]+)"')
AUDIO_EXT = {".mp3", ".ogg", ".wav", ".m4a"}


def _collation(conn: sqlite3.Connection) -> None:
    conn.create_collation(
        "unicase", lambda a, b: (a.lower() > b.lower()) - (a.lower() < b.lower()))


def _strip_html(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()


def _fields_of(flds: str) -> "list[str]":
    return flds.split("\x1f")


def run(conn: sqlite3.Connection, apkg_path: "Path | None" = None) -> dict:
    """Extract the deck's media and attach it to matching words."""
    src = Path(apkg_path or DEFAULT_APKG)
    stats = {"notes": 0, "audio": 0, "images": 0,
             "words_linked": 0, "unmatched": 0}
    if not src.exists():
        print(f"⏭  apkg: no existe {src} — skip.")
        return stats

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(src) as zf:
            zf.extractall(tmp)
        tmp_path = Path(tmp)

        # media maps numeric archive entries → original filenames
        try:
            media_map = json.loads((tmp_path / "media").read_text(encoding="utf-8"))
        except Exception:
            media_map = {}
        by_name = {name: tmp_path / key for key, name in media_map.items()}

        col_file = next((p for p in tmp_path.glob("collection.anki2*")
                         if p.suffix in (".anki2", ".anki21")), None)
        if col_file is None:
            print("⏭  apkg: no encontré la colección — skip.")
            return stats
        anki = sqlite3.connect(str(col_file))
        _collation(anki)
        anki.row_factory = sqlite3.Row

        # Words already in the local DB, by normalized text.
        local = {r["normalized"]: r["id"] for r in conn.execute(
            "SELECT id, normalized FROM words")}

        def copy_media(name: str, dest_dir: Path) -> "str | None":
            source = by_name.get(name)
            if source is None or not source.exists():
                return None
            dest = dest_dir / name
            if not dest.exists():
                shutil.copy2(source, dest)
            return f"{dest_dir.name}/{name}"

        for note in anki.execute("SELECT flds FROM notes"):
            fields = _fields_of(note["flds"])
            if not fields:
                continue
            word = _strip_html(fields[0])
            stats["notes"] += 1
            wid = local.get(db.normalize(word))
            if wid is None:
                stats["unmatched"] += 1
                continue

            sounds = SOUND_RE.findall(note["flds"])
            images = IMG_RE.findall(note["flds"])
            audio_files = [s for s in sounds if Path(s).suffix.lower() in AUDIO_EXT]
            # Convention in this deck: <id>.mp3 = word, <id>_example.mp3 = sentence
            word_audio = next((a for a in audio_files if "_example" not in a), None)
            example_audio = next((a for a in audio_files if "_example" in a), None)

            updates = {}
            if word_audio:
                rel = copy_media(word_audio, AUDIO_DIR)
                if rel:
                    updates["audio_word"] = rel
                    stats["audio"] += 1
            if example_audio:
                rel = copy_media(example_audio, AUDIO_DIR)
                if rel:
                    updates["audio_example"] = rel
                    stats["audio"] += 1
            if images:
                rel = copy_media(images[0], IMAGE_DIR)
                if rel:
                    updates["image_path"] = rel
                    stats["images"] += 1
            if not updates:
                continue

            sets = ", ".join(f"{k}=COALESCE({k}, ?)" for k in updates)
            conn.execute(f"UPDATE words SET {sets}, updated_at=? WHERE id=?",
                         list(updates.values()) + [db.now_iso(), wid])
            stats["words_linked"] += 1

        anki.close()
    conn.commit()
    return stats


if __name__ == "__main__":
    print("apkg →", run(db.connect()))
