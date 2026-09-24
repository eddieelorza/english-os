"""learner_profile.json → sessions table (ADR-006 M0).

Only the per-day study entries move over; the `errors` snapshots in the
profile are 14-day *window* aggregates (not per-day facts), so they stay
derivable from the errors/texts tables instead of being copied.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE))
from app import db  # noqa: E402

PROFILE_FILE = BASE / "data" / "learner_profile.json"


def run(conn: sqlite3.Connection, profile_path: "Path | None" = None) -> dict:
    path = Path(profile_path or PROFILE_FILE)
    stats = {"sessions": 0}
    if not path.exists():
        print(f"⏭  profile: no existe {path} — skip.")
        return stats
    profile = json.loads(path.read_text(encoding="utf-8"))
    for date, day in sorted(profile.get("days", {}).items()):
        db.upsert_session(conn, date, {
            "cards_reviewed": day.get("cards_reviewed"),
            "introduced": day.get("introduced"),
            "again": day.get("again"),
            "again_rate": day.get("again_rate"),
        })
        stats["sessions"] += 1
    conn.commit()
    return stats


if __name__ == "__main__":
    print("profile →", run(db.connect()))
