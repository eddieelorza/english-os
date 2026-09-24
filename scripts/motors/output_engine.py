"""M3 Output Engine — STUB (see REDESIGN.md §Motor 3).

Pipeline: today's Writing Session "Free Writing" block → Claude rubric →
errors back into the Writing page + Anki "English::Errors" deck +
"Error Categories" Notion DB counters.

Blocked on:
  B-OUT-1  ANTHROPIC_API_KEY in .env
  B-OUT-2  Anki deck name (default: English::Errors)
  B-OUT-3  ERRORS_DB_ID (new Notion DB for category counters)
  B-OUT-4  Claude model choice (recommended: claude-sonnet-4-6)

This motor is the recommended first one to build (highest ROI, lowest setup).
"""

from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from notion_client import NotionClient  # noqa: E402

ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
ERRORS_DB_ID = os.environ.get("ERRORS_DB_ID", "").strip()
WRITING_DB_ID = os.environ.get("WRITING_DB_ID", "").strip()
ANKI_ERRORS_DECK = os.environ.get("ANKI_ERRORS_DECK", "English::Errors")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")


def main() -> int:
    missing = []
    if not ANTHROPIC_KEY:  missing.append("ANTHROPIC_API_KEY (B-OUT-1)")
    if not ERRORS_DB_ID:   missing.append("ERRORS_DB_ID (B-OUT-3)")
    if not WRITING_DB_ID:  missing.append("WRITING_DB_ID")

    if missing:
        print("M3: faltan en .env:")
        for m in missing:
            print(f"   • {m}")
        print("Ver BLOCKERS.md para resolver.")
        return 2

    # TODO: notion.find_first(WRITING_DB_ID, title=today)
    # TODO: extract Free Writing paragraph(s) from the page's blocks
    # TODO: Claude API call with structured rubric (see REDESIGN.md §Motor 3)
    # TODO: parse JSON response → categorized errors + C1 rewrite + lex score
    # TODO: append blocks to the Writing page (errors callout, C1 quote, gap exercise)
    # TODO: per error → AnkiConnect addNote into ANKI_ERRORS_DECK (idempotent by sentence hash)
    # TODO: bump counters in ERRORS_DB_ID (this week, all time, last example)
    print(f"M3: scaffolding only. Will use {CLAUDE_MODEL}, deck={ANKI_ERRORS_DECK}.")
    print("Bloqueado en implementación; ver REDESIGN.md §Motor 3.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
