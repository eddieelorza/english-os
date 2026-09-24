"""Dual-write step: refresh data/english.db from Anki/Notion/profile (ADR-006).

Runs at the end of session-end. The importers are idempotent upserts, so a
full re-run is the incremental sync (878 vocab rows ≈ 9 Notion requests; the
Anki pass reads a local copy and takes seconds).

Exit code is 0 unless EVERY importer fails — the local mirror lagging a day
must never break the day's pipeline (ADR-006 risk table).
"""

from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from app.importers.__main__ import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
