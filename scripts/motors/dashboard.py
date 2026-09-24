"""M5 Dashboard — STUB (see REDESIGN.md §Motor 5).

Weekly aggregator. Reads from every other engine's Notion DB + Vocab Master +
Writing Sessions, builds a "Weekly Dashboard" page with metrics + deltas.

Blocked on:
  B-DA-1  Schedule (Sunday 21:00 via launchd, or manual?)
  B-DA-2  Create "Weekly Dashboards" Notion DB (ID in .env as DASHBOARD_DB_ID)

This is the cheapest engine to ship after M3 — pure read+aggregate, no APIs
beyond Notion itself.
"""

from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from notion_client import NotionClient  # noqa: E402

DASHBOARD_DB_ID = os.environ.get("DASHBOARD_DB_ID", "").strip()


def main() -> int:
    if not DASHBOARD_DB_ID:
        print("M5: DASHBOARD_DB_ID falta en .env (B-DA-2).")
        return 2

    # TODO: gather Vocab Master stats (added, retained at 7d, productive %)
    # TODO: gather Listening minutes (sum Input Inbox.Duration where Processed in week)
    # TODO: gather Speaking minutes (sum Speaking Log.Duration)
    # TODO: gather WPM (latest probe)
    # TODO: gather Writing words (sum chars/5 of Writing Sessions in week)
    # TODO: top-5 errors from ERRORS_DB_ID with delta vs last week
    # TODO: optional weekly probe (20-word ES→EN CLI quiz)
    # TODO: upsert page in DASHBOARD_DB_ID titled "Week YYYY-WXX"
    iso_year, iso_week, _ = dt.date.today().isocalendar()
    title = f"Week {iso_year}-W{iso_week:02d}"
    print(f"M5: would write/update '{title}' in dashboard DB.")
    print("Bloqueado en implementación; depende de que los motores upstream emitan datos.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
