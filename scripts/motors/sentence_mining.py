"""M2 Sentence Mining — STUB (see REDESIGN.md §Motor 2).

Replaces premade decks past 3000 word families. Pulls candidate sentences from:
  (a) Motor 1's transcripts (auto)
  (b) Notion pages tagged #mine (manual highlight)
  (c) Existing Vocabulary Master entries with `Example Sentence` filled

Blocked on:
  B-SM-1  Definition of "known": all rows in Vocab Master, or only state=review & reps>=3?
  B-SM-2  Keep Meaning (ES) column or drop it for B2+?
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from notion_client import NotionClient  # noqa: E402

VOCAB_DB_ID = os.environ.get("VOCAB_DB_ID", "").strip()


def main() -> int:
    if not VOCAB_DB_ID:
        print("M2: VOCAB_DB_ID falta en .env.")
        return 2

    # TODO(B-SM-1): build known-vocab set per chosen rule
    # TODO: gather candidates from inbox / tagged Notion pages / vocab rows
    # TODO: per candidate: build cloze front+back, optional audio
    # TODO: AnkiConnect addNotes(batch) to ANKI_MINED_DECK (env)
    # TODO: insert/update Vocab Master row with Source=mined-*, Provenance=URL
    print("M2: scaffolding only. Bloqueado en B-SM-1, B-SM-2.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
