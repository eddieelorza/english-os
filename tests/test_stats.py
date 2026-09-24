"""M7 tests: stats series — growth from first reviews, honest retention."""

from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import db, model  # noqa: E402


def recent(days_ago: int, hour="10:00:00") -> str:
    return f"{(date.today() - timedelta(days=days_ago)).isoformat()}T{hour}"


class TestSeries(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")

    def test_daily_series_merges_anki_and_fsrs(self):
        db.upsert_session(self.conn, recent(1)[:10],
                          {"cards_reviewed": 40, "reading_minutes": 5})
        wid = db.upsert_word(self.conn, {"word": "forge"})
        db.insert_review(self.conn, {"word_id": wid, "reviewed_at": recent(1),
                                     "rating": 3, "source": "fsrs"})
        daily = model.daily_series(self.conn, days=7)
        self.assertEqual(len(daily), 7)
        yesterday = daily[-2]
        self.assertEqual(yesterday["reviews"], 41)
        self.assertEqual(yesterday["reading_minutes"], 5.0)

    def test_weekly_growth_counts_first_review_once(self):
        wid = db.upsert_word(self.conn, {"word": "forge"})
        for days_ago in (10, 8, 3):  # same word, several reviews
            db.insert_review(self.conn, {"word_id": wid,
                                         "reviewed_at": recent(days_ago),
                                         "rating": 3, "source": "anki",
                                         "anki_revlog_id": days_ago})
        weekly = model.weekly_series(self.conn, weeks=4)
        self.assertEqual(sum(w["introduced"] for w in weekly), 1)
        self.assertEqual(weekly[-1]["cumulative"], 1)

    def test_retention_none_without_reviews(self):
        weekly = model.weekly_series(self.conn, weeks=2)
        self.assertIsNone(weekly[-1]["retention"])

    def test_retention_computed_from_again(self):
        db.upsert_session(self.conn, recent(1)[:10],
                          {"cards_reviewed": 100, "again": 15})
        weekly = model.weekly_series(self.conn, weeks=2)
        rets = [w["retention"] for w in weekly if w["retention"] is not None]
        self.assertEqual(rets, [0.85])

    def test_stats_totals_shape(self):
        db.upsert_word(self.conn, {"word": "forge", "status": "MASTERED"})
        db.upsert_word(self.conn, {"word": "arise", "status": "LEARNING"})
        s = model.stats(self.conn)
        self.assertEqual(s["totals"]["words_known"], 2)
        self.assertEqual(s["totals"]["mastered"], 1)
        self.assertEqual(len(s["daily"]), 30)
        self.assertEqual(len(s["weekly"]), 12)


if __name__ == "__main__":
    unittest.main()
