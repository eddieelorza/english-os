"""ADR-014 tests: presupuesto en cards, triage por recuperabilidad, las
palabras que vuelven y la compuerta de nuevas."""

from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from fsrs import Card, State
    from app import backlog, gate, session, srs  # noqa: E402
except ImportError:
    raise unittest.SkipTest("fsrs not installed in this interpreter")
from app import db  # noqa: E402


def aged_word(conn, word, stability, days_since):
    """Una card en REVIEW con esta estabilidad, vista por última vez hace
    `days_since` días y vencida desde que pasó su intervalo. A diferencia de
    `overdue_word` de test_backlog, aquí la recuperabilidad es real."""
    wid = db.upsert_word(conn, {"word": word, "meaning_es": "x"})
    seen = datetime.now(timezone.utc) - timedelta(days=days_since)
    card = Card(state=State.Review, step=None, stability=stability,
                difficulty=5.0, due=seen + timedelta(days=stability),
                last_review=seen)
    srs._save_card(conn, wid, card, since="2026-01-01")
    conn.execute(
        "UPDATE words SET status='LEARNING', last_reviewed_on=? WHERE id=?",
        (seen.astimezone().replace(tzinfo=None).isoformat(timespec="seconds"),
         wid))
    conn.commit()
    return wid


def fresh(conn, word):
    """Vencida por poco: se recuerda casi seguro."""
    return aged_word(conn, word, stability=20, days_since=22)


def lost(conn, word):
    """Estabilidad de horas y dos semanas fuera: olvidada."""
    return aged_word(conn, word, stability=0.05, days_since=14)


def fake_pace(conn, seconds=5, n=40):
    wid = db.upsert_word(conn, {"word": "pacer", "meaning_es": "x"})
    start = datetime.fromisoformat(db.now_iso()) - timedelta(days=3)
    for i in range(n):
        db.insert_review(conn, {
            "word_id": wid, "rating": 3, "review_kind": "review",
            "source": "fsrs", "stability_before": 50.0,
            "reviewed_at": (start + timedelta(seconds=i * seconds)).isoformat()})


class TestCardBudget(unittest.TestCase):
    """D1 — "20 minutos" eran 240 cards a su ritmo real de 5 s."""

    def setUp(self):
        self.conn = db.connect(":memory:")
        fake_pace(self.conn, seconds=5)

    def test_a_fast_pace_no_longer_buys_a_wall_of_cards(self):
        self.assertEqual(session.pace(self.conn)["seconds_per_card"], 5.0)
        self.assertEqual(session.card_budget(self.conn, 10), 25)
        self.assertEqual(session.card_budget(self.conn, 20), 50)
        self.assertEqual(session.card_budget(self.conn, 30), 75)

    def test_a_slow_pace_is_still_bounded_by_the_clock(self):
        conn = db.connect(":memory:")
        fake_pace(conn, seconds=60)
        self.assertEqual(session.card_budget(conn, 10), 10)

    def test_the_plan_total_respects_the_budget(self):
        for i in range(120):
            fresh(self.conn, f"w{i}")
        for minutes, cap in ((10, 25), (20, 50), (30, 75)):
            p = session.plan(self.conn, mode="time", minutes=minutes)
            self.assertLessEqual(p["total"], cap)
        self.assertEqual(p["reviews"], 75)

    def test_the_plan_says_how_much_waits_for_later(self):
        for i in range(120):
            fresh(self.conn, f"w{i}")
        p = session.plan(self.conn, mode="time", minutes=20)
        self.assertEqual(p["triage"]["due"], 120)
        self.assertEqual(p["triage"]["today"], 50)
        self.assertEqual(p["triage"]["later"], 70)


class TestTriage(unittest.TestCase):
    """D4 — recuperabilidad descendente; las perdidas, aparte y a goteo."""

    def setUp(self):
        self.conn = db.connect(":memory:")
        session.save_settings(self.conn, {"mode": "counts", "reviews": 10})

    def test_order_is_most_retrievable_first(self):
        shaky = aged_word(self.conn, "shaky", stability=3, days_since=12)
        solid = aged_word(self.conn, "solid", stability=60, days_since=62)
        gone = lost(self.conn, "gone")
        order = [c["id"] for c in backlog.triaged(self.conn)]
        self.assertEqual(order, [solid, shaky, gone])

    def test_what_stays_today_is_what_can_still_be_saved(self):
        """Antes se quedaban las más atrasadas — las ya olvidadas."""
        keep = [fresh(self.conn, f"keep{i}") for i in range(10)]
        for i in range(25):
            aged_word(self.conn, f"fading{i}", stability=3, days_since=10 + i)
        r = backlog.spread(self.conn)
        self.assertTrue(r["spread"])
        now = datetime.now(timezone.utc).isoformat()
        still_due = {row["id"] for row in self.conn.execute(
            "SELECT id FROM words WHERE fsrs_due <= ?", (now,))}
        self.assertEqual(still_due, set(keep))

    def test_lost_words_are_marked_and_trickle_back(self):
        ids = [lost(self.conn, f"gone{i}") for i in range(8)]
        r = backlog.spread(self.conn)
        self.assertTrue(r["spread"])
        self.assertEqual(r["comeback"], 8)
        self.assertEqual(r["comeback_today"], backlog.COMEBACK_PER_DAY)
        marked = self.conn.execute(
            "SELECT COUNT(*) FROM words WHERE comeback_on IS NOT NULL").fetchone()[0]
        self.assertEqual(marked, 8)
        self.assertEqual(backlog.due_total(self.conn), backlog.COMEBACK_PER_DAY)
        # de tres en tres: ningún día siguiente recibe más
        per_day = {}
        for row in self.conn.execute(
                "SELECT substr(fsrs_due, 1, 10) AS d FROM words WHERE id IN "
                f"({','.join('?' * len(ids))})", ids):
            per_day[row["d"]] = per_day.get(row["d"], 0) + 1
        self.assertLessEqual(max(per_day.values()), backlog.COMEBACK_PER_DAY)

    def test_lost_words_do_not_take_the_room_of_live_ones(self):
        for i in range(8):
            lost(self.conn, f"gone{i}")
        for i in range(30):
            fresh(self.conn, f"live{i}")
        backlog.spread(self.conn)
        now = datetime.now(timezone.utc).isoformat()
        rows = self.conn.execute(
            "SELECT comeback_on FROM words WHERE fsrs_due <= ?", (now,)).fetchall()
        self.assertEqual(len(rows), 10)
        self.assertEqual(sum(1 for r in rows if r["comeback_on"]), 3)

    def test_the_fsrs_memory_state_is_never_rewritten(self):
        """El triage cambia CUÁNDO llega la card, nunca lo que FSRS sabe."""
        wid = lost(self.conn, "gone")
        for i in range(6):
            lost(self.conn, f"other{i}")
        before = json.loads(self.conn.execute(
            "SELECT fsrs_card FROM words WHERE id=?", (wid,)).fetchone()[0])
        backlog.spread(self.conn)
        after = json.loads(self.conn.execute(
            "SELECT fsrs_card FROM words WHERE id=?", (wid,)).fetchone()[0])
        self.assertEqual(before, after)

    def test_a_few_lost_words_alone_are_marked_without_a_spread(self):
        lost(self.conn, "gone")
        r = backlog.spread(self.conn)
        self.assertFalse(r["spread"])
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM words WHERE comeback_on IS NOT NULL"
        ).fetchone()[0], 1)

    def test_a_second_pass_the_same_day_moves_nothing(self):
        for i in range(8):
            lost(self.conn, f"gone{i}")
        for i in range(30):
            fresh(self.conn, f"live{i}")
        backlog.spread(self.conn)
        self.assertFalse(backlog.spread(self.conn)["spread"])

    def test_answering_clears_the_mark_and_fsrs_sees_the_truth(self):
        wid = lost(self.conn, "gone")
        backlog.spread(self.conn)
        srs.answer(self.conn, wid, 1)
        row = self.conn.execute(
            "SELECT comeback_on, card_state FROM words WHERE id=?", (wid,)).fetchone()
        self.assertIsNone(row["comeback_on"])
        self.assertEqual(row["card_state"], "RELEARNING")   # un lapso honesto


class TestQueueOrder(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")

    def test_the_sitting_opens_with_what_you_still_remember(self):
        gone = lost(self.conn, "gone")
        shaky = aged_word(self.conn, "shaky", stability=3, days_since=12)
        solid = aged_word(self.conn, "solid", stability=60, days_since=62)
        backlog.spread(self.conn)
        q = srs.queue(self.conn, new_per_day=0)
        self.assertEqual(q["next"]["id"], solid)
        self.assertFalse(q["next"]["comeback"])
        srs.answer(self.conn, solid, 3)
        self.assertEqual(srs.queue(self.conn, new_per_day=0)["next"]["id"], shaky)
        srs.answer(self.conn, shaky, 3)
        last = srs.queue(self.conn, new_per_day=0)["next"]
        self.assertEqual(last["id"], gone)
        self.assertTrue(last["comeback"])

    def test_a_returning_word_is_woven_in_after_a_few_wins(self):
        gone = lost(self.conn, "gone")
        live = [fresh(self.conn, f"live{i}") for i in range(12)]
        session.start(self.conn, mode="counts", new=0, reviews=20)
        limits = lambda: session.limits(self.conn)  # noqa: E731
        served = []
        for _ in range(9):
            nxt = srs.queue(self.conn, new_per_day=0, limits=limits())["next"]
            served.append(nxt["id"])
            srs.answer(self.conn, nxt["id"], 3)
        self.assertNotIn(gone, served[:srs.COMEBACK_AFTER])
        self.assertIn(gone, served)
        self.assertTrue(set(served) - {gone} <= set(live))


class TestGate(unittest.TestCase):
    """D3 — `new_per_day` es el techo; cuántas entran hoy lo dice la evidencia."""

    def setUp(self):
        self.conn = db.connect(":memory:")
        session.save_settings(self.conn, {"mode": "time", "minutes": 20,
                                          "new_per_day": 10})

    def _young(self, n, passed):
        wid = db.upsert_word(self.conn, {"word": f"y{n}{passed}", "meaning_es": "x"})
        for i in range(n):
            db.insert_review(self.conn, {
                "word_id": wid, "rating": 3 if i < passed else 1,
                "review_kind": "review", "source": "fsrs",
                "stability_before": 1.5,
                "reviewed_at": (datetime.now() - timedelta(days=2, seconds=i * 300)
                                ).isoformat(timespec="seconds")})

    def test_without_evidence_it_does_not_interfere(self):
        g = gate.allowed(self.conn)
        self.assertEqual(g["new_per_day"], 10)
        self.assertIsNone(g["reason"])

    def test_returning_words_take_the_place_of_new_ones(self):
        lost(self.conn, "gone")
        backlog.spread(self.conn)
        g = gate.allowed(self.conn)
        self.assertEqual((g["new_per_day"], g["code"]), (0, "comeback"))
        self.assertIn("coming back", g["reason"])

    def test_a_full_day_admits_nothing_new(self):
        for i in range(60):
            fresh(self.conn, f"w{i}")
        g = gate.allowed(self.conn)
        self.assertEqual((g["new_per_day"], g["code"]), (0, "full"))

    def test_new_words_only_get_the_room_reviews_leave(self):
        for i in range(47):
            fresh(self.conn, f"w{i}")
        g = gate.allowed(self.conn)
        self.assertEqual((g["new_per_day"], g["code"]), (3, "room"))

    def test_too_many_half_learned_words_close_it(self):
        for i in range(gate.LADDER_MAX):
            wid = db.upsert_word(self.conn, {"word": f"l{i}", "meaning_es": "x"})
            srs.answer(self.conn, wid, 1)
        self.assertEqual(gate.allowed(self.conn)["code"], "ladder")

    def test_recall_of_young_cards_sets_the_pace(self):
        for passed, expected in ((30, 10), (25, 5), (22, 3), (15, 0)):
            conn = db.connect(":memory:")
            session.save_settings(conn, {"new_per_day": 10})
            self.conn = conn
            self._young(30, passed)
            g = gate.allowed(conn)
            self.assertEqual(g["new_per_day"], expected, f"{passed}/30")
            self.assertEqual(g["reason"] is None, expected == 10)

    def test_learning_steps_do_not_count_as_forgetting(self):
        wid = db.upsert_word(self.conn, {"word": "stepper", "meaning_es": "x"})
        for i in range(40):
            db.insert_review(self.conn, {
                "word_id": wid, "rating": 1, "review_kind": "learn",
                "source": "fsrs", "stability_before": 0.1,
                "reviewed_at": db.now_iso()})
        self.assertFalse(gate.young_recall(self.conn)["enough"])

    def test_it_can_be_switched_off(self):
        lost(self.conn, "gone")
        backlog.spread(self.conn)
        session.save_settings(self.conn, {"new_gate": "off"})
        self.assertEqual(gate.allowed(self.conn)["new_per_day"], 10)

    def test_the_plan_explains_itself_instead_of_shrinking_quietly(self):
        db.upsert_word(self.conn, {"word": "brand-new", "meaning_es": "x"})
        lost(self.conn, "gone")
        backlog.spread(self.conn)
        p = session.plan(self.conn, mode="time", minutes=20)
        self.assertEqual(p["new"], 0)
        self.assertTrue(any("coming back" in s for s in p["short"]))


class TestComingBackAfterTwoWeeks(unittest.TestCase):
    """El caso que motivó el ADR, de punta a punta."""

    def test_the_return_sitting_is_calm(self):
        conn = db.connect(":memory:")
        session.save_settings(conn, {"mode": "time", "minutes": 20,
                                     "new_per_day": 10})
        for i in range(20):
            db.upsert_word(conn, {"word": f"new{i}", "meaning_es": "x"})
        for i in range(90):
            aged_word(conn, f"live{i}", stability=4 + i, days_since=18 + i)
        for i in range(12):
            lost(conn, f"gone{i}")

        s = session.start(conn, mode="time", minutes=20)
        self.assertTrue(s["backlog"]["spread"])
        self.assertEqual(s["plan"]["new"], 0, "nada nuevo mientras vuelven palabras")
        self.assertLessEqual(s["plan"]["reviews"], 50)
        self.assertEqual(backlog.due_total(conn), 50)
        first = srs.queue(conn, new_per_day=0, limits=session.limits(conn))["next"]
        self.assertFalse(first["comeback"])
        # nada se pierde: todo sigue agendado
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM words WHERE fsrs_due IS NOT NULL").fetchone()[0], 102)


class TestRestAfterRepeatedAgain(unittest.TestCase):
    """Fase 3 — a la tercera ya no es repaso, es noria."""

    def setUp(self):
        self.conn = db.connect(":memory:")
        self.wid = db.upsert_word(self.conn, {"word": "rear", "meaning_es": "x"})
        srs.answer(self.conn, self.wid, 3)

    def test_the_third_again_of_the_day_rests_the_word(self):
        results = [srs.answer(self.conn, self.wid, 1)
                   for _ in range(srs.MAX_AGAIN_PER_DAY)]
        self.assertEqual([r["rested"] for r in results], [False, False, True])
        q = srs.queue(self.conn, new_per_day=0)
        self.assertIsNone(q["next"], "no debía volver hoy")
        self.assertEqual(q["learning"], 0)

    def test_it_comes_back_the_next_study_day_with_its_fsrs_state_intact(self):
        for _ in range(srs.MAX_AGAIN_PER_DAY):
            srs.answer(self.conn, self.wid, 1)
        row = self.conn.execute(
            "SELECT fsrs_due, fsrs_card, card_state FROM words WHERE id=?",
            (self.wid,)).fetchone()
        due = datetime.fromisoformat(row["fsrs_due"])
        self.assertGreater(due, datetime.now(timezone.utc))
        self.assertLessEqual(due, datetime.now(timezone.utc) + timedelta(days=1))
        self.assertIn(row["card_state"], ("LEARNING", "RELEARNING"))
        # la card de FSRS conserva SU vencimiento: sólo se movió la cola
        self.assertNotEqual(json.loads(row["fsrs_card"])["due"], row["fsrs_due"])

    def test_passing_answers_never_rest_a_word(self):
        for _ in range(5):
            self.assertFalse(srs.answer(self.conn, self.wid, 3)["rested"])


class TestFailBrake(unittest.TestCase):
    """Fase 3 — cuando los fallos se disparan, lo que queda es peor aún."""

    def setUp(self):
        self.conn = db.connect(":memory:")
        self.ids = [fresh(self.conn, f"w{i}") for i in range(40)]
        session.start(self.conn, mode="counts", new=0, reviews=40)

    def _answer(self, ratings):
        for wid, rating in zip(self.ids, ratings):
            srs.answer(self.conn, wid, rating)

    def test_a_normal_sitting_is_left_alone(self):
        self._answer([3] * 16 + [1] * 4)               # 20% Again
        self.assertIsNone(session.brake(self.conn))
        self.assertGreater(session.limits(self.conn)["reviews"], 0)

    def test_it_waits_for_enough_cards_before_judging(self):
        self._answer([1] * 10)                         # 100%, pero son 10
        self.assertIsNone(session.brake(self.conn))

    def test_a_sitting_going_badly_stops_serving_due_cards(self):
        self._answer([3] * 9 + [1] * 7)                # 44% de 16
        b = session.brake(self.conn)
        self.assertTrue(b["on"])
        self.assertEqual((b["again"], b["reviews"]), (7, 16))
        self.assertEqual(session.limits(self.conn), {"new": 0, "reviews": 0})

    def test_the_failed_words_are_still_finished(self):
        self._answer([3] * 9 + [1] * 7)
        q = srs.queue(self.conn, new_per_day=5, limits=session.limits(self.conn))
        self.assertEqual(q["due"], 0)
        self.assertGreater(q["learning"], 0, "la escalera no se corta nunca")

    def test_failing_learning_steps_does_not_trip_it(self):
        self._answer([3] * 16)
        for _ in range(2):                             # < MAX_AGAIN_PER_DAY
            for wid in self.ids[:8]:
                srs.answer(self.conn, wid, 1)
        # 8 lapsos de repaso sobre 24 = 33%; los 8 Again en `relearn` no cuentan
        self.assertIsNone(session.brake(self.conn))

    def test_it_is_advice_not_a_lock(self):
        self._answer([3] * 9 + [1] * 7)
        self.assertTrue(session.release_brake(self.conn)["released"])
        self.assertIsNone(session.brake(self.conn))
        self.assertGreater(session.limits(self.conn)["reviews"], 0)

    def test_releasing_it_does_not_carry_over_to_the_next_sitting(self):
        self._answer([3] * 9 + [1] * 7)
        session.release_brake(self.conn)
        session.start(self.conn, mode="counts", new=0, reviews=40)
        self._answer([1] * 16)   # mismas cards, ya en relearn: no cuentan
        more = [fresh(self.conn, f"x{i}") for i in range(16)]
        for wid in more:
            srs.answer(self.conn, wid, 1)
        self.assertTrue(session.brake(self.conn)["on"])

    def test_it_can_be_switched_off(self):
        session.save_settings(self.conn, {"fail_brake": "off"})
        self._answer([1] * 16)
        self.assertIsNone(session.brake(self.conn))


class TestStudyMore(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        session.save_settings(self.conn, {"mode": "counts", "reviews": 10})
        for i in range(40):
            fresh(self.conn, f"w{i}")
        for i in range(5):
            lost(self.conn, f"gone{i}")
        backlog.spread(self.conn)

    def test_it_brings_the_nearest_scheduled_cards_to_today(self):
        before = backlog.due_total(self.conn)
        r = backlog.pull_forward(self.conn, 15)
        self.assertEqual(r["pulled"], 15)
        self.assertEqual(backlog.due_total(self.conn), before + 15)

    def test_returning_words_keep_their_trickle(self):
        backlog.pull_forward(self.conn, 50)
        now = datetime.now(timezone.utc).isoformat()
        due_comeback = self.conn.execute(
            "SELECT COUNT(*) FROM words WHERE comeback_on IS NOT NULL "
            "AND fsrs_due <= ?", (now,)).fetchone()[0]
        self.assertEqual(due_comeback, backlog.COMEBACK_PER_DAY)

    def test_it_is_bounded(self):
        self.assertLessEqual(backlog.pull_forward(self.conn, 999)["pulled"],
                             backlog.PULL_MAX)


class TestSeenWhileReading(unittest.TestCase):
    """Fase 3 — una palabra vista en una historia entra con contexto."""

    def setUp(self):
        self.conn = db.connect(":memory:")
        self.plain = db.upsert_word(self.conn, {"word": "anvil", "meaning_es": "x",
                                                "anki_note_id": 1})
        self.read = db.upsert_word(self.conn, {"word": "forge", "meaning_es": "x",
                                               "anki_note_id": 2})
        self.conn.execute(
            "INSERT INTO texts (kind, title, body, finished_at, created_at, updated_at) "
            "VALUES ('reading', 't', 'She forged a new key that night.', ?, ?, ?)",
            (db.now_iso(), db.now_iso(), db.now_iso()))
        self.conn.commit()

    def test_new_words_met_in_a_finished_reading_go_first(self):
        self.assertEqual(srs.queue(self.conn)["next"]["id"], self.plain)
        self.assertEqual(srs.mark_seen(self.conn), 1)
        self.assertEqual(srs.queue(self.conn)["next"]["id"], self.read)

    def test_unfinished_readings_do_not_count(self):
        self.conn.execute("UPDATE texts SET finished_at=NULL")
        self.assertEqual(srs.mark_seen(self.conn), 0)


class TestComebackIsMeasured(unittest.TestCase):
    def test_a_reunion_is_logged_as_such(self):
        conn = db.connect(":memory:")
        wid = lost(conn, "gone")
        other = fresh(conn, "live")
        backlog.spread(conn)
        srs.answer(conn, wid, 3)
        srs.answer(conn, other, 3)
        rows = dict(conn.execute(
            "SELECT word_id, comeback FROM review_history WHERE source='fsrs'"))
        self.assertEqual(rows[wid], 1)
        self.assertIsNone(rows[other])
        stat = backlog.comeback_recall(conn)
        self.assertEqual((stat["reviews"], stat["pending"]), (1, 0))
        self.assertIsNone(stat["recall"], "una muestra de 1 no es un porcentaje")

    def test_returning_words_reach_the_generators(self):
        from app import model
        conn = db.connect(":memory:")
        lost(conn, "gone")
        backlog.spread(conn)
        self.assertIn("gone", [w["word"] for w in model.learning_words(conn)])


if __name__ == "__main__":
    unittest.main()
