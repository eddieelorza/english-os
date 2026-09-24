"""M14 tests: the queue runs one job at a time, survives failures and
restarts, and never pre-generates while paused."""

from __future__ import annotations

import sys
import threading
import time
import threading as th_module
import os
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import db, jobs, pause  # noqa: E402


class TestQueueBasics(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")

    def test_enqueue_returns_a_queued_job(self):
        with mock.patch.object(jobs, "ensure_worker"):
            job = jobs.enqueue(self.conn, "reading", {"minutes": 5})
        self.assertEqual(job["status"], "queued")
        self.assertEqual(job["params"], {"minutes": 5})

    def test_unknown_kind_is_rejected(self):
        with self.assertRaises(ValueError):
            jobs.enqueue(self.conn, "nonsense")

    def test_identical_pending_jobs_are_deduped(self):
        with mock.patch.object(jobs, "ensure_worker"):
            a = jobs.enqueue(self.conn, "podcast", {"minutes": 3})
            b = jobs.enqueue(self.conn, "podcast", {"minutes": 3})
            c = jobs.enqueue(self.conn, "podcast", {"minutes": 8})
        self.assertEqual(a["id"], b["id"])   # asking twice generates once
        self.assertNotEqual(a["id"], c["id"])

    def test_run_one_executes_and_records_result(self):
        with mock.patch.object(jobs, "ensure_worker"):
            job = jobs.enqueue(self.conn, "tip")
        with mock.patch.dict(jobs.HANDLERS,
                             {"tip": lambda conn, p: {"tip": "ok"}}):
            done = jobs.run_one(self.conn)
        self.assertEqual(done["status"], "done")
        self.assertEqual(done["result"], {"tip": "ok"})
        self.assertEqual(done["id"], job["id"])

    def test_empty_queue_returns_none(self):
        self.assertIsNone(jobs.run_one(self.conn))

    def test_failure_is_recorded_without_killing_the_queue(self):
        with mock.patch.object(jobs, "ensure_worker"):
            jobs.enqueue(self.conn, "reading")
            jobs.enqueue(self.conn, "tip")

        def boom(conn, p):
            raise RuntimeError("model unavailable")

        with mock.patch.dict(jobs.HANDLERS,
                             {"reading": boom, "tip": lambda c, p: {"ok": True}}):
            first = jobs.run_one(self.conn)
            second = jobs.run_one(self.conn)
        self.assertEqual(first["status"], "failed")
        self.assertIn("model unavailable", first["error"])
        self.assertEqual(second["status"], "done")  # queue kept going


class TestSerialization(unittest.TestCase):
    """The point of the queue: never two inferences at once — and never the
    same job claimed twice, even from separate connections."""

    def test_jobs_never_overlap_and_are_claimed_once(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.dict(os.environ,
                             {"ENGLISH_JOBS_LOCK": str(Path(tmp) / "jobs.lock")}):
            path = str(Path(tmp) / "jobs.db")
            db.connect(path)  # create the schema
            overlap = {"max": 0, "now": 0}
            ran = []
            guard = threading.Lock()

            def slow(c, p):
                with guard:
                    overlap["now"] += 1
                    overlap["max"] = max(overlap["max"], overlap["now"])
                    ran.append(p["i"])
                time.sleep(0.05)
                with guard:
                    overlap["now"] -= 1
                return {"ok": True}

            conn = db.connect(path)
            with mock.patch.object(jobs, "ensure_worker"):
                for i in range(4):
                    jobs.enqueue(conn, "reading", {"i": i})

            def worker():
                # each thread gets its own connection to the same file
                c = db.connect(path)
                try:
                    while jobs.run_one(c) is not None:
                        pass
                finally:
                    c.close()

            with mock.patch.dict(jobs.HANDLERS, {"reading": slow}):
                threads = [threading.Thread(target=worker) for _ in range(4)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()

            self.assertEqual(overlap["max"], 1, "two jobs ran at the same time")
            self.assertEqual(sorted(ran), [0, 1, 2, 3], "a job ran twice or not at all")
            self.assertEqual(jobs.pending(conn), 0)


class TestRestartRecovery(unittest.TestCase):
    def test_orphaned_running_jobs_return_to_the_queue(self):
        conn = db.connect(":memory:")
        conn.execute("INSERT INTO jobs (kind, params, status, created_at, "
                     "started_at) VALUES ('reading','{}','running',?,?)",
                     (db.now_iso(), db.now_iso()))
        conn.commit()
        self.assertEqual(jobs.requeue_orphans(conn), 1)
        row = conn.execute("SELECT status, started_at FROM jobs").fetchone()
        self.assertEqual(row["status"], "queued")
        self.assertIsNone(row["started_at"])

    def test_nothing_to_recover_is_a_no_op(self):
        conn = db.connect(":memory:")
        self.assertEqual(jobs.requeue_orphans(conn), 0)


class TestPregenerate(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")

    def test_pregenerate_queues_and_drains(self):
        """Los handlers falsos se derivan de KINDS: si se añade un tipo nuevo
        y aquí se listan a mano, el handler REAL corre y el test llama al
        modelo — pasó con `writing_task` y la suite se fue de 2s a 12s."""
        calls = []
        fake = {k: (lambda c, p, k=k: calls.append(k) or {"ok": k})
                for k in jobs.KINDS}
        with mock.patch.object(jobs, "ensure_worker"), \
             mock.patch.dict(jobs.HANDLERS, fake):
            r = jobs.pregenerate(self.conn)
        # el podcast no entra en la pre-generación diaria: es a petición
        self.assertEqual(sorted(calls), ["activities", "reading", "tip",
                                         "writing_task"])
        self.assertEqual(r["processed"], len(calls))
        self.assertEqual(jobs.pending(self.conn), 0)

    def test_pregenerate_does_nothing_while_paused(self):
        pause.start(self.conn, "vacaciones")
        with mock.patch.object(jobs, "ensure_worker"):
            r = jobs.pregenerate(self.conn)
        self.assertEqual(r["skipped"], "paused")
        self.assertEqual(jobs.pending(self.conn), 0)


if __name__ == "__main__":
    unittest.main()


class TestExclusiveAcrossThreads(unittest.TestCase):
    """El fallo del 2026-09-03: dos hilos del mismo proceso entrando en
    `_exclusive` — el worker y el `while run_one(...)` de `pregenerate()`, que
    corre en el hilo de la petición. `flock` sólo serializa entre procesos; el
    segundo hilo no esperaba turno, sino que `open(path, "w")` truncaba un
    archivo ya bloqueado y macOS devolvía EDEADLK. Mataba el worker y los
    trabajos se apilaban en silencio durante días."""

    def setUp(self):
        import tempfile
        from app import jobs
        self.jobs = jobs
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._prev = os.environ.get("ENGLISH_JOBS_LOCK")
        os.environ["ENGLISH_JOBS_LOCK"] = str(Path(self.tmp.name) / "jobs.lock")
        self.addCleanup(self._restore)

    def _restore(self):
        if self._prev is None:
            os.environ.pop("ENGLISH_JOBS_LOCK", None)
        else:
            os.environ["ENGLISH_JOBS_LOCK"] = self._prev

    def test_two_threads_take_turns_instead_of_crashing(self):
        import threading as th
        errors, order, inside = [], [], []

        def worker(tag):
            try:
                with self.jobs._exclusive():
                    inside.append(tag)
                    order.append(len(inside))
                    time.sleep(0.15)
                    inside.remove(tag)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        ts = [th.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(timeout=10)

        self.assertEqual(errors, [], f"el candado reventó: {errors}")
        self.assertEqual(order, [1, 1, 1, 1],
                         "dos hilos estuvieron dentro a la vez")

    def test_the_lock_is_reentrant_for_one_thread(self):
        """Un handler que acabe llamando a `run_one` no puede bloquearse a sí
        mismo."""
        with self.jobs._exclusive():
            with self.jobs._exclusive():
                pass

    def test_the_worker_survives_a_failing_job(self):
        """Una excepción costaba la generación entera y en silencio: ni un job
        en 'failed', ni un aviso, sólo cosas encoladas para siempre.

        Se corre `_loop` en este mismo hilo y se sale con un `KeyboardInterrupt`
        —que `except Exception` no atrapa— en vez de lanzar un hilo de fondo:
        un `_loop` suelto sobrevive al test, agarra el candado con un trabajo
        real y cuelga la suite entera. Ya pasó."""
        calls = []

        def boom(_conn=None):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("revienta la primera vez")
            raise KeyboardInterrupt  # única salida del bucle

        fake_wake = mock.Mock()
        fake_wake.wait.return_value = True
        with mock.patch.object(self.jobs, "run_one", side_effect=boom), \
             mock.patch.object(self.jobs, "_wake", fake_wake), \
             mock.patch.object(self.jobs.db, "connect",
                               return_value=db.connect(":memory:")):
            with self.assertRaises(KeyboardInterrupt):
                self.jobs._loop()

        self.assertEqual(len(calls), 2, "el hilo se murió con el primer fallo")
