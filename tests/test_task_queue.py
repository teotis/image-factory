import datetime as dt
import sqlite3
import tempfile
import unittest
from pathlib import Path

from image_factory.task_queue import (
    cancel_stale_tasks,
    claim_task,
    complete_task,
    enqueue_tasks,
    fail_task,
    init_db,
    is_in_cooldown,
    queue_summary,
    queued_paths,
    register_worker,
    reset_stale_claims,
    set_cooldown,
    set_worker_heartbeat,
)


def _tmp_db() -> Path:
    tmp = tempfile.mkdtemp()
    return Path(tmp) / "test_queue.db"


def _sample_plan(n: int = 3) -> list[dict]:
    return [
        {
            "prompt_text": f"prompt {i}",
            "prompt_sha256_16": f"hash{i:04d}",
            "prompt_title": f"title {i}",
            "prompt_source": "main",
            "prompt_index": i,
            "path": f"/tmp/output/img_{i:03d}.png",
        }
        for i in range(1, n + 1)
    ]


class InitDbTests(unittest.TestCase):
    def test_creates_tables(self):
        db = _tmp_db()
        result = init_db(db)
        self.assertEqual(result, db)
        conn = sqlite3.connect(str(db))
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        self.assertIn("image_tasks", tables)
        self.assertIn("workers", tables)
        self.assertIn("key_cooldowns", tables)

    def test_idempotent(self):
        db = _tmp_db()
        init_db(db)
        init_db(db)  # should not raise


class EnqueueTests(unittest.TestCase):
    def setUp(self):
        self.db = _tmp_db()
        init_db(self.db)

    def test_enqueue_returns_count(self):
        plan = _sample_plan(3)
        count = enqueue_tasks(
            self.db, plan, prompt_doc_path="/tmp/doc.html",
            model="gpt-image-2", provider="openai",
            size="1024x1024", quality="high", output_format="png",
        )
        self.assertEqual(count, 3)

    def test_enqueue_stores_correct_data(self):
        plan = _sample_plan(1)
        enqueue_tasks(
            self.db, plan, prompt_doc_path="/tmp/doc.html",
            theme="test_theme", character="test_char",
            model="m1", provider="p1", size="s1", quality="q1", output_format="png",
        )
        conn = sqlite3.connect(str(self.db))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM image_tasks").fetchone()
        conn.close()
        self.assertEqual(row["prompt_text"], "prompt 1")
        self.assertEqual(row["theme"], "test_theme")
        self.assertEqual(row["character"], "test_char")
        self.assertEqual(row["status"], "pending")


class ClaimTaskTests(unittest.TestCase):
    def setUp(self):
        self.db = _tmp_db()
        init_db(self.db)
        enqueue_tasks(
            self.db, _sample_plan(3), prompt_doc_path="/tmp/doc.html",
            model="m", provider="p", size="s", quality="q", output_format="png",
        )

    def test_claim_returns_task(self):
        task = claim_task(self.db, "worker_0")
        self.assertIsNotNone(task)
        self.assertEqual(task["prompt_text"], "prompt 1")

    def test_claim_increments_attempt(self):
        claim_task(self.db, "worker_0")
        conn = sqlite3.connect(str(self.db))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT attempt_count FROM image_tasks WHERE id = 1"
        ).fetchone()
        conn.close()
        self.assertEqual(row["attempt_count"], 1)

    def test_claim_returns_updated_state(self):
        task = claim_task(self.db, "worker_0")

        self.assertEqual(task["status"], "claimed")
        self.assertEqual(task["claimed_by"], "worker_0")
        self.assertIsNotNone(task["claimed_at"])
        self.assertEqual(task["attempt_count"], 1)

    def test_claim_sets_status_claimed(self):
        claim_task(self.db, "worker_0")
        conn = sqlite3.connect(str(self.db))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status, claimed_by FROM image_tasks WHERE id = 1"
        ).fetchone()
        conn.close()
        self.assertEqual(row["status"], "claimed")
        self.assertEqual(row["claimed_by"], "worker_0")

    def test_claim_fifo_order(self):
        t1 = claim_task(self.db, "w0")
        t2 = claim_task(self.db, "w0")
        self.assertEqual(t1["id"], 1)
        self.assertEqual(t2["id"], 2)

    def test_claim_respects_retry_after(self):
        fail_task(self.db, 1, "w0", "err", retry_delay=3600)
        task = claim_task(self.db, "w0")
        # task 1 has retry_after in the future, so should claim task 2
        self.assertEqual(task["id"], 2)

    def test_claim_returns_none_when_empty(self):
        claim_task(self.db, "w0")
        claim_task(self.db, "w0")
        claim_task(self.db, "w0")
        result = claim_task(self.db, "w0")
        self.assertIsNone(result)


class CompleteTaskTests(unittest.TestCase):
    def setUp(self):
        self.db = _tmp_db()
        init_db(self.db)
        enqueue_tasks(
            self.db, _sample_plan(1), prompt_doc_path="/tmp/doc.html",
            model="m", provider="p", size="s", quality="q", output_format="png",
        )
        register_worker(self.db, "worker_0", "***/worker_0")
        claim_task(self.db, "worker_0")

    def test_complete_sets_done(self):
        complete_task(self.db, 1, "worker_0")
        conn = sqlite3.connect(str(self.db))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status FROM image_tasks WHERE id = 1").fetchone()
        conn.close()
        self.assertEqual(row["status"], "done")

    def test_complete_bumps_worker(self):
        complete_task(self.db, 1, "worker_0")
        conn = sqlite3.connect(str(self.db))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT total_completed FROM workers WHERE id = 'worker_0'"
        ).fetchone()
        conn.close()
        self.assertEqual(row["total_completed"], 1)


class FailTaskTests(unittest.TestCase):
    def setUp(self):
        self.db = _tmp_db()
        init_db(self.db)
        enqueue_tasks(
            self.db, _sample_plan(1), prompt_doc_path="/tmp/doc.html",
            model="m", provider="p", size="s", quality="q", output_format="png",
            # use default max_attempts=5
        )
        register_worker(self.db, "worker_0", "***/worker_0")
        claim_task(self.db, "worker_0")

    def test_fail_exhausts_with_single_attempt(self):
        fail_task(self.db, 1, "worker_0", "transient error", retry_delay=10)
        conn = sqlite3.connect(str(self.db))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status FROM image_tasks WHERE id = 1").fetchone()
        conn.close()
        self.assertEqual(row["status"], "failed")

    def test_fail_sets_failed_when_exhausted(self):
        # max_attempts=1: single claim+fail cycle exhausts retries
        claim_task(self.db, "worker_0")
        fail_task(self.db, 1, "worker_0", "err")
        conn = sqlite3.connect(str(self.db))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status, attempt_count FROM image_tasks WHERE id = 1"
        ).fetchone()
        conn.close()
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["attempt_count"], 1)

    def test_fail_nonexistent_task_bumps_worker(self):
        fail_task(self.db, 9999, "worker_0", "phantom")
        conn = sqlite3.connect(str(self.db))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT total_failed FROM workers WHERE id = 'worker_0'"
        ).fetchone()
        conn.close()
        self.assertEqual(row["total_failed"], 1)


class ResetStaleClaimsTests(unittest.TestCase):
    def setUp(self):
        self.db = _tmp_db()
        init_db(self.db)
        enqueue_tasks(
            self.db, _sample_plan(1), prompt_doc_path="/tmp/doc.html",
            model="m", provider="p", size="s", quality="q", output_format="png",
        )

    def test_reset_stale_by_heartbeat(self):
        register_worker(self.db, "worker_old", "***/old")
        claim_task(self.db, "worker_old")
        # Manually set stale heartbeat
        conn = sqlite3.connect(str(self.db))
        stale_time = (
            dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=600)
        ).isoformat()
        conn.execute(
            "UPDATE workers SET last_heartbeat = ? WHERE id = 'worker_old'",
            (stale_time,),
        )
        conn.commit()
        conn.close()

        reset = reset_stale_claims(self.db, stale_heartbeat_seconds=120)
        self.assertEqual(reset, 1)
        conn = sqlite3.connect(str(self.db))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status FROM image_tasks WHERE id = 1").fetchone()
        conn.close()
        self.assertEqual(row["status"], "pending")

    def test_no_reset_for_fresh_worker(self):
        register_worker(self.db, "worker_fresh", "***/fresh")
        claim_task(self.db, "worker_fresh")
        set_worker_heartbeat(self.db, "worker_fresh", task_id=1)

        reset = reset_stale_claims(self.db, stale_heartbeat_seconds=120)
        self.assertEqual(reset, 0)


class CancelStaleTasksTests(unittest.TestCase):
    def setUp(self):
        self.db = _tmp_db()
        init_db(self.db)
        enqueue_tasks(
            self.db, _sample_plan(3), prompt_doc_path="/tmp/doc.html",
            model="m", provider="p", size="s", quality="q", output_format="png",
        )
        register_worker(self.db, "worker_0", "***/w0")

    def test_cancels_old_claimed_task(self):
        claim_task(self.db, "worker_0")
        # Manually set claimed_at to 25 minutes ago
        conn = sqlite3.connect(str(self.db))
        stale_time = (
            dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=25)
        ).isoformat()
        conn.execute(
            "UPDATE image_tasks SET claimed_at = ? WHERE id = 1",
            (stale_time,),
        )
        conn.commit()
        conn.close()

        cancelled = cancel_stale_tasks(self.db)
        self.assertEqual(cancelled, 1)

        conn = sqlite3.connect(str(self.db))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status, last_error FROM image_tasks WHERE id = 1").fetchone()
        conn.close()
        self.assertEqual(row["status"], "failed")
        self.assertIn("auto-cancelled: exceeded", row["last_error"])
        self.assertIn("1200s runtime", row["last_error"])

    def test_no_cancel_for_fresh_claimed_task(self):
        claim_task(self.db, "worker_0")
        set_worker_heartbeat(self.db, "worker_0", task_id=1)

        cancelled = cancel_stale_tasks(self.db)
        self.assertEqual(cancelled, 0)

        conn = sqlite3.connect(str(self.db))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status FROM image_tasks WHERE id = 1").fetchone()
        conn.close()
        self.assertEqual(row["status"], "claimed")

    def test_no_cancel_for_pending_tasks(self):
        cancelled = cancel_stale_tasks(self.db)
        self.assertEqual(cancelled, 0)

        conn = sqlite3.connect(str(self.db))
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT status FROM image_tasks").fetchall()
        conn.close()
        for row in rows:
            self.assertEqual(row["status"], "pending")

    def test_returns_cancelled_count(self):
        claim_task(self.db, "worker_0")
        claim_task(self.db, "worker_0")
        conn = sqlite3.connect(str(self.db))
        stale_time = (
            dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=25)
        ).isoformat()
        conn.execute(
            "UPDATE image_tasks SET claimed_at = ? WHERE status = 'claimed'",
            (stale_time,),
        )
        conn.commit()
        conn.close()

        cancelled = cancel_stale_tasks(self.db)
        self.assertEqual(cancelled, 2)


class QueueSummaryTests(unittest.TestCase):
    def setUp(self):
        self.db = _tmp_db()
        init_db(self.db)
        enqueue_tasks(
            self.db, _sample_plan(3), prompt_doc_path="/tmp/doc.html",
            model="m", provider="p", size="s", quality="q", output_format="png",
        )

    def test_summary_counts(self):
        register_worker(self.db, "w0", "***/w0")
        # Complete task 1
        claim_task(self.db, "w0")
        complete_task(self.db, 1, "w0")
        # Fail task 2 (max_attempts=1, single claim+fail exhausts it)
        claim_task(self.db, "w0")
        fail_task(self.db, 2, "w0", "err")

        s = queue_summary(self.db)
        self.assertEqual(s["total"], 3)
        self.assertEqual(s["done"], 1)
        self.assertEqual(s["failed"], 1)
        self.assertEqual(s["pending"], 1)

    def test_summary_with_output_dir_filter(self):
        s = queue_summary(self.db, output_dir="/tmp/output")
        self.assertEqual(s["total"], 3)


class CooldownTests(unittest.TestCase):
    def setUp(self):
        self.db = _tmp_db()
        init_db(self.db)

    def test_cooldown_active(self):
        set_cooldown(self.db, "w0", 60, "429 rate limit")
        self.assertTrue(is_in_cooldown(self.db, "w0"))

    def test_no_cooldown(self):
        self.assertFalse(is_in_cooldown(self.db, "w0"))

    def test_expired_cooldown(self):
        set_cooldown(self.db, "w0", -1, "already expired")
        self.assertFalse(is_in_cooldown(self.db, "w0"))


class QueuedPathsTests(unittest.TestCase):
    def setUp(self):
        self.db = _tmp_db()
        init_db(self.db)

    def test_returns_correct_paths(self):
        enqueue_tasks(
            self.db, _sample_plan(2), prompt_doc_path="/tmp/doc.html",
            model="m", provider="p", size="s", quality="q", output_format="png",
        )
        paths = queued_paths(self.db, "/tmp/output")
        self.assertEqual(paths, {"/tmp/output/img_001.png", "/tmp/output/img_002.png"})

    def test_empty_for_unknown_dir(self):
        paths = queued_paths(self.db, "/nonexistent")
        self.assertEqual(paths, set())


if __name__ == "__main__":
    unittest.main()
