"""Aggregate Error Library + Writing output into learner metrics (ADR-004).

Deterministic half of the trainer loop: the cloud routine categorises errors
(cognitive work), this module counts them (arithmetic) and turns them into
the two signals the planner needs:

  • top_categories  → what tomorrow's activities should target
  • errors_per_100  → the single most predictive accuracy metric available

Never invents precision: with fewer than MIN_SAMPLE words produced in the
window, errors_per_100 is None and callers must render "Sin datos suficientes"
(Vision §7 / Learner Profile rule).

Importable (`aggregate`) and runnable standalone for a quick report.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from notion_client import NotionClient  # noqa: E402
from notion_blocks import get_select, get_number  # noqa: E402

BASE = Path(__file__).resolve().parent.parent
PROFILE_FILE = BASE / "data" / "learner_profile.json"

ERRORS_DB = os.environ.get("ERRORS_DB_ID", "").strip()
WRITING_DB = os.environ.get("WRITING_DB_ID", "").strip()

WINDOW_DAYS = 14
MIN_SAMPLE_WORDS = 150  # below this, accuracy numbers are noise


def _since(days: int) -> str:
    return (dt.date.today() - dt.timedelta(days=days)).isoformat()


def aggregate(c: NotionClient, window_days: int = WINDOW_DAYS) -> dict:
    """Return {top_categories, errors_per_100, words_produced, errors_total,
    sample_days, enough_data}. Safe to call before Error Library has rows."""
    result = {
        "window_days": window_days,
        "top_categories": [],
        "errors_per_100": None,
        "words_produced": 0,
        "errors_total": 0,
        "sample_days": 0,
        "enough_data": False,
    }
    if not ERRORS_DB:
        return result

    since = _since(window_days)

    # 1. Error categories, weighted by recurrence.
    counter: Counter[str] = Counter()
    for row in c.query_database(ERRORS_DB,
                                {"property": "Date", "date": {"on_or_after": since}}):
        cat = get_select(row["properties"], "Category")
        if cat:
            counter[cat] += int(get_number(row["properties"], "Recurrences") or 1)
    result["top_categories"] = [c_ for c_, _ in counter.most_common(3)]

    # 2. Accuracy from corrected writing sessions.
    words = errors = days = 0
    for page in c.query_database(WRITING_DB, {"and": [
        {"property": "Date", "date": {"on_or_after": since}},
        {"property": "Corrected", "checkbox": {"equals": True}},
    ]}):
        w = get_number(page["properties"], "Words Produced")
        e = get_number(page["properties"], "Errors Count")
        if w:
            words += int(w)
            errors += int(e or 0)
            days += 1

    result.update(words_produced=words, errors_total=errors, sample_days=days)
    if words >= MIN_SAMPLE_WORDS:
        result["errors_per_100"] = round(errors * 100 / words, 1)
        result["enough_data"] = True
    return result


def save_to_profile(metrics: dict) -> None:
    """Store today's snapshot so trends survive without re-querying Notion."""
    try:
        profile = json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
    except Exception:
        profile = {"version": 1, "days": {}}
    profile.setdefault("errors", {})[dt.date.today().isoformat()] = metrics
    PROFILE_FILE.parent.mkdir(exist_ok=True)
    tmp = PROFILE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.rename(PROFILE_FILE)


def run() -> None:
    if not ERRORS_DB:
        print("⏭  error_metrics: falta ERRORS_DB_ID en .env — skip.")
        return
    m = aggregate(NotionClient())
    save_to_profile(m)
    acc = (f"{m['errors_per_100']} errores/100 palabras"
           if m["enough_data"] else "Sin datos suficientes")
    cats = ", ".join(m["top_categories"]) or "—"
    print(f"📊 Últimos {m['window_days']}d: {acc} "
          f"({m['words_produced']} palabras, {m['sample_days']} sesiones) · "
          f"top errores: {cats}")


if __name__ == "__main__":
    run()
