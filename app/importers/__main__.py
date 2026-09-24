"""Run every importer: `python3 -m app.importers` (ADR-006 M0).

Order matters: Anki first (creates words with SRS truth), Notion second
(fills curated meanings + times_used + errors + texts), profile last.
Each importer is isolated — one failing does not stop the others.
"""

from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE))

import run_all  # noqa: F401  (loads .env into os.environ)
from app import db, obsidian  # noqa: E402
from app.importers import anki, apkg, notion, profile  # noqa: E402


def main() -> int:
    conn = db.connect()
    failures = 0
    # apkg after anki: words studied for the first time today get their deck
    # audio linked in the same run.
    for name, mod in (("anki", anki), ("apkg", apkg), ("notion", notion),
                      ("profile", profile), ("obsidian", obsidian)):
        try:
            stats = mod.run(conn)
            print(f"✅ {name}: {stats}")
        except Exception as exc:  # noqa: BLE001 — report and continue
            failures += 1
            print(f"❌ {name}: {type(exc).__name__}: {exc}")

    n_words = conn.execute("SELECT COUNT(*) FROM words").fetchone()[0]
    n_reviews = conn.execute("SELECT COUNT(*) FROM review_history").fetchone()[0]
    n_errors = conn.execute("SELECT COUNT(*) FROM errors").fetchone()[0]
    n_sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    n_texts = conn.execute("SELECT COUNT(*) FROM texts").fetchone()[0]
    by_status = dict(conn.execute(
        "SELECT status, COUNT(*) FROM words GROUP BY status").fetchall())
    print(f"━ english.db: {n_words} words {by_status} · {n_reviews} reviews · "
          f"{n_errors} errors · {n_sessions} sessions · {n_texts} texts")
    conn.close()
    return 1 if failures == 5 else 0


if __name__ == "__main__":
    raise SystemExit(main())
