"""ADR-015 tests: la carga propuesta a partir del ritmo real, con historiales
ficticios. Nada de esto toca `data/english.db`: todo vive en memoria o en un
fichero temporal."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from fsrs import Card, State
    from app import backlog, gate, load, session, srs  # noqa: E402
except ImportError:
    raise unittest.SkipTest("fsrs not installed in this interpreter")
from app import db  # noqa: E402

IRREGULAR = [27, 25, 22, 20, 18, 15, 13, 11, 8, 6, 4, 1]      # 2-3 días/semana


def at(days_ago: int, minute: int = 0) -> datetime:
    # Anclado al DÍA DE ESTUDIO (empieza a las 4:00), no al calendario: entre
    # las 00:00 y las 04:00 "ayer" del calendario es el mismo día de estudio
    # que "hoy" y las pruebas contaban un día de menos.
    day = datetime.fromisoformat(db.study_day()) - timedelta(days=days_ago)
    return (day.replace(hour=10) + timedelta(minutes=minute)).astimezone(timezone.utc)


def study_day(conn, days_ago, new=5, fail_every=4, cap=40):
    """Un día de estudio ficticio: repasa lo vencido a esa fecha, falla una de
    cada `fail_every` (y la repite), e introduce `new` palabras."""
    now = at(days_ago)
    minute = 0
    due = [r["id"] for r in conn.execute(
        "SELECT id FROM words WHERE fsrs_due IS NOT NULL AND fsrs_due <= ? "
        "ORDER BY fsrs_due LIMIT ?", (now.isoformat(), cap))]
    for i, wid in enumerate(due):
        minute += 1
        failed = fail_every and i % fail_every == 0
        srs.answer(conn, wid, 1 if failed else 3, now=at(days_ago, minute))
        if failed:
            srs.answer(conn, wid, 3, now=at(days_ago, minute + 12))
    fresh = [r["id"] for r in conn.execute(
        "SELECT id FROM words WHERE fsrs_card IS NULL ORDER BY id LIMIT ?", (new,))]
    for wid in fresh:
        minute += 1
        srs.answer(conn, wid, 3, now=at(days_ago, minute))
        srs.answer(conn, wid, 3, now=at(days_ago, minute + 15))


def learner(conn, offsets, words=200, **kw):
    for i in range(words):
        db.upsert_word(conn, {"word": f"w{i}", "meaning_es": "x"})
    for d in sorted(offsets, reverse=True):
        study_day(conn, d, **kw)


def aged(conn, word, stability, days_since):
    wid = db.upsert_word(conn, {"word": word, "meaning_es": "x"})
    seen = datetime.now(timezone.utc) - timedelta(days=days_since)
    card = Card(state=State.Review, step=None, stability=stability, difficulty=5.0,
                due=seen + timedelta(days=stability), last_review=seen)
    srs._save_card(conn, wid, card, since="2026-01-01")
    conn.execute("UPDATE words SET status='LEARNING', last_reviewed_on=? WHERE id=?",
                 (seen.astimezone().replace(tzinfo=None).isoformat(timespec="seconds"),
                  wid))
    conn.commit()
    return wid


class TestIrregularStudy(unittest.TestCase):
    """Dos o tres días por semana."""

    @classmethod
    def setUpClass(cls):
        cls.conn = db.connect(":memory:")
        session.save_settings(cls.conn, {"mode": "auto", "new_per_day": 10})
        learner(cls.conn, IRREGULAR)

    def test_it_reads_the_real_rhythm(self):
        r = load.rhythm(self.conn)
        self.assertTrue(r["measured"])
        self.assertEqual(r["study_days"], 12)
        self.assertGreater(r["per_week"], 2)
        self.assertLess(r["per_week"], 4)
        self.assertEqual(r["days_away"], 1)

    def test_the_load_is_small_and_never_above_what_he_usually_does(self):
        p = load.proposal(self.conn)
        self.assertTrue(p["measured"])
        self.assertLessEqual(p["budget"], p["effort"]["typical_answers"])
        self.assertGreater(p["budget"], 0)

    def test_it_explains_itself_with_his_own_numbers(self):
        why = " ".join(load.proposal(self.conn)["why"])
        self.assertIn("days a week", why)
        self.assertIn("12 of the last", why)
        self.assertIn("answers", why)

    def test_a_growing_group_holds_new_words(self):
        """Entraron 5 por día de estudio y casi ninguna se ha asentado."""
        g = load.group(self.conn)
        self.assertGreater(g["came_in"], g["settled"])
        door = gate.allowed(self.conn, mode="auto")
        self.assertEqual((door["new_per_day"], door["code"]), (0, "group"))
        self.assertIn("not settled", door["reason"])

    def test_the_other_modes_are_untouched(self):
        self.assertNotEqual(gate.allowed(self.conn, mode="time")["code"], "group")


class TestComingBack(unittest.TestCase):
    def _after(self, away):
        conn = db.connect(":memory:")
        session.save_settings(conn, {"mode": "auto", "new_per_day": 10})
        learner(conn, [d + away for d in IRREGULAR if d + away <= 27] or [27, 25, 22, 20])
        return conn

    def test_after_7_and_14_days_nothing_new_and_it_says_why(self):
        for away in (7, 14):
            conn = self._after(away - 1)
            p = load.proposal(conn)
            self.assertTrue(p["measured"], away)
            self.assertEqual(p["rhythm"]["days_away"], away)
            self.assertEqual(p["new"], 0)
            self.assertTrue(any(f"{away} days away" in w for w in p["why"]))
            self.assertLessEqual(p["budget"], p["effort"]["typical_answers"])

    def test_the_return_sitting_opens_with_what_is_still_alive(self):
        conn = self._after(13)
        s = session.start(conn, mode="auto")
        first = srs.queue(conn, new_per_day=0, limits=session.limits(conn))["next"]
        self.assertIsNotNone(first)
        self.assertFalse(first["comeback"])
        self.assertEqual(s["plan"]["new"], 0)


class TestManyAccumulated(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        session.save_settings(self.conn, {"mode": "auto"})
        learner(self.conn, IRREGULAR, new=2)
        for i in range(160):
            aged(self.conn, f"old{i}", stability=5 + i % 40, days_since=30 + i % 25)

    def test_the_cap_is_what_he_usually_does_and_it_admits_the_cost(self):
        p = load.proposal(self.conn)
        self.assertEqual(p["budget"], p["effort"]["typical_answers"])
        self.assertTrue(any("catching up will take longer" in w for w in p["why"]))

    def test_nothing_is_hidden_or_lost(self):
        before = self.conn.execute(
            "SELECT COUNT(*) FROM words WHERE fsrs_card IS NOT NULL").fetchone()[0]
        cards = {r["id"]: r["fsrs_card"] for r in self.conn.execute(
            "SELECT id, fsrs_card FROM words WHERE fsrs_card IS NOT NULL")}
        session.start(self.conn, mode="auto")
        after = {r["id"]: r["fsrs_card"] for r in self.conn.execute(
            "SELECT id, fsrs_card FROM words WHERE fsrs_card IS NOT NULL")}
        self.assertEqual(len(after), before)
        self.assertEqual(cards, after, "el estado de memoria no se reescribe")

    def test_the_spread_follows_the_real_rhythm_and_builds_no_new_peak(self):
        """Con reparto diario, volver a los 3 días es encontrarse 3 sentadas
        apiladas. Con su ritmo, lo que espera es lo que cabe en las sentadas
        que de verdad habrá habido."""
        conn = db.connect(":memory:")
        for i in range(50):
            aged(conn, f"c{i}", stability=10, days_since=12)
        cap, rate = 10, 0.4                       # 10 cards por sentada, 2.8 días/semana
        now = datetime.now(timezone.utc)
        move = backlog._split(conn, cap, now)["move_alive"]
        self.assertEqual(len(move), 40)
        daily, _ = backlog._placement(conn, [], move, cap, now, 1.0)
        paced, per_day = backlog._placement(conn, [], move, cap, now, rate)

        def by_day(placed, d):
            return sum(1 for _, day in placed if day <= d)

        self.assertEqual(by_day(daily, 3), 30, "tres sentadas esperando a la vuelta")
        self.assertLessEqual(by_day(paced, 3), 12, "poco más de una")
        for d in range(1, backlog.MAX_SPREAD_DAYS + 1):
            self.assertLessEqual(by_day(paced, d), -(-per_day * rate * d // 1))
            self.assertLessEqual(sum(1 for _, day in paced if day == d), per_day)
        self.assertEqual(len(paced), len(move), "todo queda agendado, nada se pierde")

    def test_a_backlog_beyond_the_horizon_is_spread_evenly_and_says_so(self):
        """Cuando no cabe en 14 días a su ritmo, no hay reparto que lo arregle:
        los días salen parejos y la propuesta admite que tardará más."""
        p = load.proposal(self.conn)
        self.assertGreater(p["cards_needed"], p["cards"])
        self.assertTrue(any("take longer" in w for w in p["why"]))


class TestRepeatedFailures(unittest.TestCase):
    """Las repeticiones cuentan dentro del límite."""

    def setUp(self):
        self.conn = db.connect(":memory:")
        session.save_settings(self.conn, {"mode": "auto", "fail_brake": "off"})
        learner(self.conn, IRREGULAR, new=3)
        for i in range(60):
            aged(self.conn, f"due{i}", stability=10, days_since=12)

    def test_every_answer_counts_and_the_sitting_never_outgrows_its_budget(self):
        s = session.start(self.conn, mode="auto")
        budget = s["budget"]
        self.assertGreater(budget, 0)
        answers = 0
        while answers < budget + 30:
            nxt = srs.queue(self.conn, new_per_day=0,
                            limits=session.limits(self.conn))["next"]
            if nxt is None:
                break
            srs.answer(self.conn, nxt["id"], 1)        # falla todo, siempre
            answers += 1
        self.assertLessEqual(answers, budget, "ADR-009 dejaba seguir la escalera")

    def test_a_spent_budget_stops_even_the_ladder(self):
        s = session.start(self.conn, mode="auto")
        for _ in range(3):
            nxt = srs.queue(self.conn, new_per_day=0,
                            limits=session.limits(self.conn))["next"]
            srs.answer(self.conn, nxt["id"], 1)
        # las tres falladas ya "tocan": su minuto pasó
        past = (datetime.now() - timedelta(minutes=30)).isoformat(timespec="seconds")
        self.conn.execute(
            "UPDATE words SET fsrs_due=?, last_reviewed_on=? "
            "WHERE card_state IN ('LEARNING','RELEARNING')",
            ((datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(), past))
        self.conn.execute("UPDATE study_sessions SET budget=3 WHERE id=?", (s["id"],))
        self.conn.commit()
        self.assertEqual(session.limits(self.conn),
                         {"new": 0, "reviews": 0, "ladder": 0})
        q = srs.queue(self.conn, new_per_day=0, limits=session.limits(self.conn))
        self.assertIsNone(q["next"])
        # …pero no desaparecen: sin el tope de la sentada, ahí siguen
        self.assertIsNotNone(srs.queue(self.conn, new_per_day=0)["next"])

    def test_fresh_material_stops_early_to_leave_room_for_the_repeats(self):
        session.start(self.conn, mode="auto")
        served_fresh_after_reserve = False
        for _ in range(200):
            lim = session.limits(self.conn)
            nxt = srs.queue(self.conn, new_per_day=0, limits=lim)["next"]
            if nxt is None:
                break
            state = self.conn.execute("SELECT card_state FROM words WHERE id=?",
                                      (nxt["id"],)).fetchone()[0]
            if lim["reviews"] == 0 and state == "REVIEW":
                served_fresh_after_reserve = True
            srs.answer(self.conn, nxt["id"], 1)
        self.assertFalse(served_fresh_after_reserve)

    def test_overdue_half_learned_words_are_served_not_locked_out(self):
        """Regresión del 2026-09-20: 3 vencidas, las 3 falladas una hora
        antes. La reserva (3 x 2 = 6) superaba el presupuesto (5) y la sentada
        se cerró sin servir ninguna."""
        conn = db.connect(":memory:")
        session.save_settings(conn, {"mode": "auto", "fail_brake": "off"})
        learner(conn, IRREGULAR, new=3)
        conn.execute("UPDATE words SET fsrs_due=? WHERE fsrs_due <= ?",
                     ((datetime.now(timezone.utc) + timedelta(days=9)).isoformat(),
                      datetime.now(timezone.utc).isoformat()))
        hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        failed = []
        for i in range(3):
            wid = aged(conn, f"failed{i}", stability=10, days_since=12)
            srs.answer(conn, wid, 1, now=hour_ago)      # queda en RELEARNING, vencida
            failed.append(wid)
        s = session.start(conn, mode="auto")
        # un presupuesto que la reserva de esas tres ya agota
        tight = 3 * load.effort(conn)["ladder_cost"]
        conn.execute("UPDATE study_sessions SET budget=? WHERE id=?", (tight, s["id"]))
        conn.commit()
        lim = session.limits(conn)
        self.assertTrue(lim.get("ladder_only"))
        q = srs.queue(conn, new_per_day=0, limits=lim)
        self.assertIn(q["next"]["id"], failed, "debía servir lo que quedó a medias")

    def test_in_ladder_only_mode_fresh_due_cards_wait(self):
        conn = db.connect(":memory:")
        session.save_settings(conn, {"mode": "auto", "fail_brake": "off"})
        learner(conn, IRREGULAR, new=3)
        for i in range(10):
            aged(conn, f"fresh{i}", stability=30, days_since=31)
        wid = aged(conn, "failed", stability=10, days_since=12)
        srs.answer(conn, wid, 1, now=datetime.now(timezone.utc) - timedelta(hours=1))
        s = session.start(conn, mode="auto")
        conn.execute("UPDATE study_sessions SET budget=2 WHERE id=?", (s["id"],))
        conn.commit()
        q = srs.queue(conn, new_per_day=0, limits=session.limits(conn))
        self.assertEqual(q["next"]["id"], wid)
        self.assertEqual(q["due"], 1)
        self.assertGreater(q["due_total"], 1, "las demás siguen vencidas, a la vista")

    def test_words_left_half_learned_keep_their_real_state(self):
        session.start(self.conn, mode="auto")
        while True:
            nxt = srs.queue(self.conn, new_per_day=0,
                            limits=session.limits(self.conn))["next"]
            if nxt is None:
                break
            srs.answer(self.conn, nxt["id"], 1)
        session.end(self.conn)
        half = self.conn.execute(
            "SELECT COUNT(*) FROM words WHERE card_state IN ('LEARNING','RELEARNING')"
        ).fetchone()[0]
        self.assertGreater(half, 0)
        # no se esconden: sin sentada abierta, la cola las sigue viendo
        q = srs.queue(self.conn, new_per_day=0)
        self.assertGreater(q["learning"] + q["due"], 0)

    def test_the_brake_sees_learning_failures_and_uses_his_own_baseline(self):
        session.save_settings(self.conn, {"fail_brake": "auto"})
        wid = db.upsert_word(self.conn, {"word": "past", "meaning_es": "x"})
        for day in range(2, 12):                       # diez días, 25% de fallo
            for i in range(20):
                db.insert_review(self.conn, {
                    "word_id": wid, "rating": 1 if i % 4 == 0 else 3,
                    "review_kind": "review", "source": "fsrs",
                    "reviewed_at": (datetime.now() - timedelta(days=day, minutes=i)
                                    ).replace(hour=11).isoformat(timespec="seconds")})
        bar = session.baseline_again(self.conn)
        self.assertTrue(bar["measured"])
        self.assertLess(bar["rate"], 0.5)

        def sitting_of_learning_failures(mode):
            session.start(self.conn, mode=mode, **({} if mode == "auto"
                                                   else {"new": 0, "reviews": 30}))
            for i in range(16):                        # todo fallos de escalera
                db.insert_review(self.conn, {
                    "word_id": wid, "rating": 1, "review_kind": "relearn",
                    "source": "fsrs", "reviewed_at": db.now_iso()})
            return session.brake(self.conn)

        self.assertIsNone(sitting_of_learning_failures("counts"),
                          "el freno de ADR-014 no ve los fallos de aprendizaje")
        b = sitting_of_learning_failures("auto")
        self.assertTrue(b and b["on"])
        self.assertTrue(b["bar"]["measured"])


class TestLessToday(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        session.save_settings(self.conn, {"mode": "auto", "new_per_day": 7})
        learner(self.conn, IRREGULAR, new=1)
        for i in range(60):
            aged(self.conn, f"due{i}", stability=10, days_since=12)

    def test_it_halves_today_and_holds_new_words(self):
        full = load.proposal(self.conn)
        less = load.proposal(self.conn, less=True)
        self.assertEqual(less["budget"], -(-full["budget"] // 2))
        self.assertEqual(less["new"], 0)
        self.assertTrue(any("less today" in w for w in less["why"]))

    def test_it_never_touches_the_saved_preferences(self):
        before = session.settings(self.conn)
        session.start(self.conn, mode="auto", less=True)
        self.assertEqual(session.settings(self.conn), before)

    def test_it_expires_with_the_day(self):
        load.set_less(self.conn, True)
        self.assertTrue(load.proposal(self.conn)["less"])
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key='load_day'").fetchone()
        stale = {**json.loads(row["value"]), "date": "2026-01-01"}
        self.conn.execute("UPDATE settings SET value=? WHERE key='load_day'",
                          (json.dumps(stale),))
        self.assertFalse(load.proposal(self.conn)["less"])


class TestStopAndContinue(unittest.TestCase):
    def test_reload_and_a_second_sitting_pick_up_where_it_stopped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "fake.db")
            conn = db.connect(path)
            session.save_settings(conn, {"mode": "auto", "fail_brake": "off"})
            learner(conn, IRREGULAR, new=6)
            for i in range(80):
                aged(conn, f"due{i}", stability=10, days_since=12)
            s = session.start(conn, mode="auto")
            day_budget = s["budget"]
            for _ in range(5):
                nxt = srs.queue(conn, new_per_day=0, limits=session.limits(conn))["next"]
                srs.answer(conn, nxt["id"], 3)
            conn.close()

            conn = db.connect(path)                     # "recargar la página"
            prog = session.progress(conn)
            self.assertTrue(prog["active"])
            self.assertEqual((prog["done"], prog["budget"]), (5, day_budget))

            session.end(conn)                           # "termino cuando quiera"
            p = session.plan(conn, mode="auto")
            self.assertEqual(p["budget"], day_budget - 5)
            self.assertEqual(p["answered_today"], 5)
            again = session.start(conn, mode="auto")
            self.assertEqual(again["budget"], day_budget - 5)
            reviews = conn.execute(
                "SELECT COUNT(*) FROM review_history WHERE source='fsrs' "
                "AND reviewed_at >= ?", (db.study_day_start(),)).fetchone()[0]
            self.assertEqual(reviews, 5, "el progreso es el historial, no un contador")
            conn.close()

    def test_studying_more_is_voluntary_and_only_for_today(self):
        conn = db.connect(":memory:")
        session.save_settings(conn, {"mode": "auto"})
        learner(conn, IRREGULAR, new=1)
        for i in range(80):
            aged(conn, f"due{i}", stability=10, days_since=12)
        base = load.proposal(conn)["budget"]
        load.add_more(conn, 20)
        self.assertEqual(load.proposal(conn)["budget"], base + 20)


class TestNotEnoughHistory(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        session.save_settings(self.conn, {"mode": "auto", "minutes": 10})
        learner(self.conn, [3, 1], words=40)

    def test_it_claims_no_routine(self):
        r = load.rhythm(self.conn)
        self.assertFalse(r["measured"])
        p = load.proposal(self.conn)
        self.assertFalse(p["measured"])
        self.assertIsNone(p["budget"])
        self.assertIn("not enough history", p["why"][0])

    def test_the_plan_falls_back_to_the_time_he_picks_and_says_so(self):
        p = session.plan(self.conn, mode="auto")
        self.assertEqual(p["mode"], "time")
        self.assertEqual(p["minutes"], 10)
        self.assertIn("not enough history", p["why"][0])
        s = session.start(self.conn, mode="auto")
        self.assertIsNone(s["budget"])

    def test_the_brake_baseline_is_marked_as_a_default(self):
        self.assertFalse(session.baseline_again(self.conn)["measured"])

    def test_a_brand_new_learner_is_not_locked_out_of_new_words(self):
        conn = db.connect(":memory:")
        for i in range(10):
            db.upsert_word(conn, {"word": f"w{i}", "meaning_es": "x"})
        self.assertEqual(load.new_allowed(conn, 5)["new"], 5)

    def test_paused_days_are_not_counted_as_not_studying(self):
        conn = db.connect(":memory:")
        learner(conn, IRREGULAR, words=60)
        rate = load.rhythm(conn)["rate"]
        conn.execute(
            "INSERT INTO pauses (start_date, end_date, reason, created_at) "
            "VALUES (?,?,?,?)",
            (at(17).date().isoformat(), at(16).date().isoformat(), "trip",
             db.now_iso()))
        self.assertGreater(load.rhythm(conn)["rate"], rate)


if __name__ == "__main__":
    unittest.main()
