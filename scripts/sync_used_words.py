"""After completing Writing Session exercises, mark each checked to-do as
'Used Today' and increment Times Used on the corresponding Vocabulary page.

Fixed:
- get_block_children now paginates (the old version only read the first 100
  blocks, silently dropping any later todos).
- All Notion calls go through NotionClient (retries on 429/5xx).
- Per-word try/except so one bad lookup doesn't kill the whole sync.
"""

from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from notion_client import NotionClient, NotionError  # noqa: E402
from notion_blocks import get_title, get_number, checkbox_prop, number_prop  # noqa: E402

VOCAB_DB_ID   = os.environ.get("VOCAB_DB_ID", "").strip()
WRITING_DB_ID = os.environ.get("WRITING_DB_ID", "").strip()

if not VOCAB_DB_ID or not WRITING_DB_ID:
    raise SystemExit("Faltan VOCAB_DB_ID y/o WRITING_DB_ID en el entorno")

VOCAB_WORD_PROP       = "Word"
VOCAB_USED_PROP       = "Used Today"
VOCAB_TIMES_USED_PROP = "Times Used"
WRITING_TITLE_PROP    = "Task"

notion = NotionClient()


def get_today_writing_session() -> dict | None:
    today = dt.date.today().isoformat()
    title = f"Writing Session – {today}"
    filt = {"property": WRITING_TITLE_PROP, "title": {"equals": title}}
    return notion.find_first(WRITING_DB_ID, filt)


def get_checked_words(page_id: str) -> list[str]:
    """Walk every child block (auto-paginated) and collect text of checked todos."""
    out: list[str] = []
    for block in notion.get_block_children(page_id):
        if block.get("type") != "to_do":
            continue
        body = block.get("to_do", {})
        if not body.get("checked"):
            continue
        text = "".join(x.get("plain_text", "") for x in body.get("rich_text", [])).strip()
        if text:
            out.append(text)
    return out


def find_vocab_page(word: str) -> dict | None:
    filt = {"property": VOCAB_WORD_PROP, "title": {"equals": word}}
    return notion.find_first(VOCAB_DB_ID, filt)


def bump_vocab(page: dict, word: str) -> None:
    current = get_number(page.get("properties", {}), VOCAB_TIMES_USED_PROP) or 0
    notion.update_page(
        page["id"],
        {
            VOCAB_USED_PROP:       checkbox_prop(True),
            VOCAB_TIMES_USED_PROP: number_prop(current + 1),
        },
    )


def main() -> None:
    session = get_today_writing_session()
    if not session:
        print("No writing session found today.")
        return

    words = get_checked_words(session["id"])
    if not words:
        print("No words marked as used.")
        return

    print(f"📝 {len(words)} palabras marcadas en Writing Session de hoy")

    counters = {"updated": 0, "not_found": 0, "failed": 0}
    for word in words:
        try:
            page = find_vocab_page(word)
            if not page:
                counters["not_found"] += 1
                print(f"⚠  No encontrada en Vocab: {word}")
                continue
            bump_vocab(page, word)
            counters["updated"] += 1
            print(f"✅ Vocab+1: {word}")
        except NotionError as exc:
            counters["failed"] += 1
            print(f"❌ Notion error on '{word}': {exc}")
        except Exception as exc:
            counters["failed"] += 1
            print(f"❌ Failed '{word}': {type(exc).__name__}: {exc}")

    print()
    print(
        f"━ Resumen: {len(words)} marcadas · "
        f"{counters['updated']} actualizadas · "
        f"{counters['not_found']} no encontradas · "
        f"{counters['failed']} fallidas"
    )


if __name__ == "__main__":
    main()
