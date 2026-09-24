"""M4 Speaking Engine — STUB (see REDESIGN.md §Motor 4).

Two sub-commands:
  shadow <url|file>   — N reps with timer, log to Shadowing Log DB
  record --topic ... --seconds N — record + Whisper transcribe + Claude evaluate
                                    + write to Speaking Log DB

Blocked on:
  B-SP-1  Install sox (`brew install sox`) or pick a different recorder
  B-SP-2  Create Shadowing Log + Speaking Log Notion DBs (IDs in .env)
  B-SP-3  Audio storage location: `audio/` (repo, gitignored) or ~/Documents/...?
  B-SP-4  Frequency list: NGSL 5K (recommended) or COCA top 5K
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from notion_client import NotionClient  # noqa: E402

SHADOWING_DB_ID = os.environ.get("SHADOWING_DB_ID", "").strip()
SPEAKING_DB_ID  = os.environ.get("SPEAKING_DB_ID", "").strip()


def cmd_shadow(args: argparse.Namespace) -> int:
    if not SHADOWING_DB_ID:
        print("M4 shadow: SHADOWING_DB_ID falta en .env (B-SP-2).")
        return 2
    # TODO: play audio (afplay on mac), countdown timer N reps
    # TODO: on completion, upsert Shadowing Log row by Title=source
    print(f"M4 shadow stub: would loop {args.reps}x on {args.source!r}")
    return 1


def cmd_record(args: argparse.Namespace) -> int:
    if not SPEAKING_DB_ID:
        print("M4 record: SPEAKING_DB_ID falta en .env (B-SP-2).")
        return 2
    # TODO(B-SP-1): `rec` via sox or AVFoundation capture
    # TODO: whisper transcribe → text + WPM
    # TODO: claude_review evaluate with rubric → WPM, errors/100w, lexical band
    # TODO: write Speaking Log row + optionally hand off errors to M3
    print(f"M4 record stub: would record {args.seconds}s about {args.topic!r}")
    return 1


def main() -> int:
    p = argparse.ArgumentParser(prog="speaking_engine")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("shadow")
    s.add_argument("source", help="URL or local file path")
    s.add_argument("--reps", type=int, default=10)
    s.set_defaults(func=cmd_shadow)

    r = sub.add_parser("record")
    r.add_argument("--topic", required=True)
    r.add_argument("--seconds", type=int, default=120)
    r.set_defaults(func=cmd_record)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
