"""Backfill Meaning (ES), Pronunciation and Example (EN) for every VOCAB row.

One-off repair after ADR-005: the old external-dictionary values were wiped
(they were wrong), which left ~800 rows empty until each word came up for
review again. This pulls the real values straight from the Anki notes by
`Anki Note ID`, in bulk.

Safe to re-run: only writes fields that are currently empty in Notion, and
skips notes that no longer exist in Anki. Requires Anki open (AnkiConnect).

    python3 -c "import run_all" && python3 scripts/backfill_meanings.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from notion_client import NotionClient  # noqa: E402
from notion_blocks import get_rich_text, get_number, get_title, rich_text_prop  # noqa: E402
import anki_notion_sync as ans  # reuse the field mapping + AnkiConnect wrapper

CHUNK = 100


def run() -> None:
    notion = NotionClient()
    db = os.environ["VOCAB_DB_ID"]

    rows = list(notion.query_database(db))
    print(f"📚 {len(rows)} filas en Vocabulary Master")

    # A LIST per note id, not a single row: VOCAB has duplicate rows sharing a
    # note id, and a dict silently dropped all but the last — leaving the twin
    # empty forever.
    by_nid: dict[int, list[dict]] = {}
    for r in rows:
        nid = get_number(r["properties"], "Anki Note ID")
        if nid:
            by_nid.setdefault(int(nid), []).append(r)
    dupes = sum(len(v) - 1 for v in by_nid.values() if len(v) > 1)
    print(f"🔗 {len(by_nid)} note IDs distintos"
          + (f" ({dupes} filas duplicadas)" if dupes else ""))

    nids = list(by_nid)
    notes: dict[int, dict] = {}
    for i in range(0, len(nids), CHUNK):
        for n in ans.anki("notesInfo", {"notes": nids[i:i + CHUNK]}):
            if n and n.get("noteId"):
                notes[int(n["noteId"])] = n
    print(f"🃏 {len(notes)} notas encontradas en Anki "
          f"({len(nids) - len(notes)} ya no existen; se saltan)")

    filled = skipped = failed = 0
    for nid, note in notes.items():
        fields = note["fields"]
        _, es, pron, example = ans.extract_from_note(fields, next(iter(fields)))

        for page in by_nid[nid]:
            props = page["properties"]
            update = {}
            if es and not get_rich_text(props, "Meaning (ES)"):
                update["Meaning (ES)"] = rich_text_prop(es)
            if pron and not get_rich_text(props, "Pronunciation"):
                update["Pronunciation"] = rich_text_prop(pron)
            if example and not get_rich_text(props, "Example (EN)"):
                update["Example (EN)"] = rich_text_prop(example)

            if not update:
                skipped += 1
                continue
            try:
                notion.update_page(page["id"], update)
                filled += 1
                if filled % 100 == 0:
                    print(f"   … {filled} rellenadas")
            except Exception as exc:
                failed += 1
                print(f"   ❌ {get_title(props, 'Word')}: {exc}")

    print(f"\n✅ pase 1 (por Note ID) — rellenadas: {filled} | "
          f"sin cambios: {skipped} | fallos: {failed}")

    # ── Pase 2: filas huérfanas ──────────────────────────────────────────
    # Reimportar el mazo cambia los note IDs, así que cientos de filas quedaron
    # apuntando a notas inexistentes: sin datos y, peor, sin volver a
    # sincronizar nunca. Las reconectamos buscando por la palabra exacta.
    orphans = [r for nid, r in by_nid.items() if nid not in notes]
    print(f"\n🔍 {len(orphans)} filas huérfanas; buscándolas por palabra…")

    relinked = notfound = 0
    for page in orphans:
        props = page["properties"]
        word = get_title(props, "Word").strip()
        if not word:
            continue
        try:
            found = ans.anki("findNotes", {"query": f'"Word:{word}"'})
            if not found:
                notfound += 1
                continue
            info = ans.anki("notesInfo", {"notes": found[:1]})
            if not info:
                notfound += 1
                continue
            note = info[0]
            fields = note["fields"]
            _, es, pron, example = ans.extract_from_note(fields, next(iter(fields)))

            update = {"Anki Note ID": {"number": float(note["noteId"])}}
            if es and not get_rich_text(props, "Meaning (ES)"):
                update["Meaning (ES)"] = rich_text_prop(es)
            if pron and not get_rich_text(props, "Pronunciation"):
                update["Pronunciation"] = rich_text_prop(pron)
            if example and not get_rich_text(props, "Example (EN)"):
                update["Example (EN)"] = rich_text_prop(example)

            notion.update_page(page["id"], update)
            relinked += 1
            if relinked % 100 == 0:
                print(f"   … {relinked} reconectadas")
        except Exception as exc:
            failed += 1
            print(f"   ❌ {word}: {exc}")

    print(f"\n✅ pase 2 — reconectadas: {relinked} | "
          f"ya no existen en Anki: {notfound} | fallos: {failed}")


if __name__ == "__main__":
    run()
