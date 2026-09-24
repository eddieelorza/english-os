"""M1 Input Engine — STUB (see REDESIGN.md §Motor 1).

Pipeline: Notion Input Inbox → yt-dlp → Whisper transcript →
extract new vocab → cloze Anki cards with audio clips.

This file is intentionally a scaffold. The body is gated on user decisions:
  B-IN-1  Whisper backend (faster-whisper / openai-whisper / OpenAI API)
  B-IN-2  Target Anki deck name for mined cards
  B-IN-3  Notion Input Inbox database (creation + ID in .env as INPUT_DB_ID)

Run: python3 -m scripts.motors.input_engine    # currently exits with TODO message
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from notion_client import NotionClient  # noqa: E402


def main() -> int:
    inbox_db = os.environ.get("INPUT_DB_ID", "").strip()
    if not inbox_db:
        print("M1: INPUT_DB_ID no está en .env. Crea la base 'Input Inbox' en")
        print("    Notion (ver REDESIGN.md §Motor 1) y agrega INPUT_DB_ID al .env.")
        print("    Bloqueado por: B-IN-3 (ver BLOCKERS.md).")
        return 2

    # TODO(B-IN-1): import whisper backend
    # TODO(B-IN-1): download_audio(url) via yt-dlp
    # TODO(B-IN-1): transcribe(audio_path) -> segments
    # TODO(extractor): tokens = tokenize(transcript); new = dedup(tokens, known)
    # TODO(extractor): for w in new: pick sentence + audio_clip; build cloze; addNote
    # TODO(B-IN-2): use target deck from env or constant
    print("M1: scaffolding only. Blocked on B-IN-1 and B-IN-2.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
