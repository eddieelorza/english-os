"""Update data/learner_profile.json with today's Anki session metrics.

Seed of the Learner Profile (see docs/01_PRODUCT_VISION.md P2: metrics are a
byproduct, never a task). Pulls everything from AnkiConnect — requires Anki
open. Idempotent: re-running simply overwrites today's entry with fresher
numbers.

Metrics per day:
  cards_reviewed  – total review answers today (getNumCardsReviewedToday)
  introduced      – cards seen for the first time today (query introduced:1)
  again           – review answers rated Again today (query rated:1:1)
  again_rate      – again / cards_reviewed (0 when no reviews)
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import requests

ANKI_URL = "http://localhost:8765"
BASE = Path(__file__).resolve().parent.parent
DATA_DIR = BASE / "data"
PROFILE_FILE = DATA_DIR / "learner_profile.json"


SNAPSHOT_FILE = BASE / "data" / "anki_session.json"


def anki(action: str, params: dict | None = None):
    r = requests.post(
        ANKI_URL,
        json={"action": action, "version": 6, "params": params or {}},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("error"):
        raise RuntimeError(f"AnkiConnect error: {data['error']}")
    return data["result"]


def snapshot_metrics() -> dict | None:
    """Same numbers from the add-on's snapshot when AnkiConnect is gone."""
    try:
        data = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None
    if data.get("date") != dt.date.today().isoformat():
        return None
    return {
        "cards_reviewed": data.get("reviews_today", 0),
        "introduced": data.get("introduced", 0),
        "again": data.get("again", 0),
    }


def load_profile() -> dict:
    if PROFILE_FILE.exists():
        try:
            return json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # Never lose history silently: keep the corrupt file aside.
            backup = PROFILE_FILE.with_suffix(".corrupt.json")
            PROFILE_FILE.rename(backup)
            print(f"⚠️  learner_profile.json corrupto; respaldado en {backup.name}")
    return {"version": 1, "days": {}}


def save_profile(profile: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    tmp = PROFILE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.rename(PROFILE_FILE)


def run() -> None:
    today = dt.date.today().isoformat()

    try:
        cards_reviewed = anki("getNumCardsReviewedToday")
        introduced = len(anki("findCards", {"query": "introduced:1"}))
        again = len(anki("findCards", {"query": "rated:1:1"}))
    except Exception:
        snap = snapshot_metrics()
        if snap is None:
            raise
        print("📸 AnkiConnect no disponible; uso el snapshot de la sesión.")
        cards_reviewed = snap["cards_reviewed"]
        introduced = snap["introduced"]
        again = snap["again"]

    again_rate = round(again / cards_reviewed, 3) if cards_reviewed else 0.0

    profile = load_profile()
    profile["days"][today] = {
        "cards_reviewed": cards_reviewed,
        "introduced": introduced,
        "again": again,
        "again_rate": again_rate,
        "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    save_profile(profile)

    print(
        f"🧠 Learner profile {today}: {cards_reviewed} reviews, "
        f"{introduced} nuevas, again_rate={again_rate:.0%}"
    )


if __name__ == "__main__":
    run()
