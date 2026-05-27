"""IntentRepository — typed access to the generation task database.

This module encapsulates all SQLite operations behind a clean class interface.
External code should use IntentRepository instead of the raw task_queue functions.

During migration, task_queue.py functions remain as backward-compatible wrappers.
"""
from __future__ import annotations

import datetime as dt
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

from .io import write_json
from .models import (
    GenerationIntent,
    TaskState,
    task_state_from_str,
)
from .manifest import Manifest


# ---------------------------------------------------------------------------
# Database helpers (mirrored from task_queue.py — single source of truth here)
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS image_tasks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    enqueued_at     TEXT NOT NULL,
    enqueue_source  TEXT NOT NULL DEFAULT '',

    prompt_doc_path TEXT NOT NULL,
    prompt_sha256_16 TEXT NOT NULL,
    prompt_text     TEXT NOT NULL,
    prompt_title    TEXT NOT NULL DEFAULT '',
    prompt_source   TEXT NOT NULL DEFAULT 'main',
    prompt_index    INTEGER NOT NULL DEFAULT 1,
    theme           TEXT NOT NULL DEFAULT '',
    character       TEXT NOT NULL DEFAULT '',

    output_dir      TEXT NOT NULL,
    output_path     TEXT NOT NULL,

    status          TEXT NOT NULL DEFAULT 'pending',
    claimed_by      TEXT NOT NULL DEFAULT '',
    claimed_at      TEXT,

    model           TEXT NOT NULL,
    provider        TEXT NOT NULL,
    size            TEXT NOT NULL,
    quality         TEXT NOT NULL,
    output_format   TEXT NOT NULL,
    aspect_ratio    TEXT NOT NULL DEFAULT '',
    base_url        TEXT NOT NULL DEFAULT '',

    attempt_count   INTEGER NOT NULL DEFAULT 0,
    max_attempts    INTEGER NOT NULL DEFAULT 1,
    last_error      TEXT NOT NULL DEFAULT '',
    last_error_at   TEXT,
    generated_at    TEXT,
    retry_after     TEXT,
    priority        INTEGER NOT NULL DEFAULT 0,
    reference_images TEXT NOT NULL DEFAULT '',
    metadata_json   TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS workers (
    id              TEXT PRIMARY KEY,
    api_key_env     TEXT NOT NULL,
    run_id          TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'idle',
    current_task_id INTEGER,
    last_heartbeat  TEXT,
    started_at      TEXT NOT NULL,
    total_completed INTEGER NOT NULL DEFAULT 0,
    total_failed    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS key_cooldowns (
    worker_id       TEXT PRIMARY KEY,
    cooldown_until  TEXT NOT NULL,
    reason          TEXT NOT NULL DEFAULT '',
    triggered_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON image_tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_output_dir ON image_tasks(output_dir);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_output_path ON image_tasks(output_path);
CREATE INDEX IF NOT EXISTS idx_tasks_enqueued ON image_tasks(enqueued_at);
"""


# ---------------------------------------------------------------------------
# IntentRepository
# ---------------------------------------------------------------------------

class IntentRepository:
    """Typed repository for GenerationIntent tasks and worker management.

    Usage::

        repo = IntentRepository(db_path)
        repo.init_db()
        count = repo.enqueue(intents, ...)
        intent = repo.claim("worker_0")
        repo.complete(intent.id, "worker_0")
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)

    # -- Schema -----------------------------------------------------------

    def init_db(self) -> Path:
        """Initialize the database schema. Returns the db path."""
        conn = _connect(self.db_path)
        try:
            conn.executescript(SCHEMA)
            # Migrate existing databases that lack columns added after initial release
            for col, col_def in [
                ("prompt_source", "TEXT NOT NULL DEFAULT 'main'"),
                ("prompt_index", "INTEGER NOT NULL DEFAULT 1"),
                ("reference_images", "TEXT NOT NULL DEFAULT ''"),
            ]:
                try:
                    conn.execute(f"ALTER TABLE image_tasks ADD COLUMN {col} {col_def}")
                except sqlite3.OperationalError:
                    pass
            try:
                conn.execute("ALTER TABLE workers ADD COLUMN run_id TEXT NOT NULL DEFAULT ''")
            except sqlite3.OperationalError:
                pass
        finally:
            conn.close()
        return self.db_path

    # -- Task CRUD --------------------------------------------------------

    def enqueue(
        self,
        plan_entries: list[dict[str, Any]],
        prompt_doc_path: str,
        theme: str = "",
        character: str = "",
        model: str = "",
        provider: str = "",
        size: str = "",
        quality: str = "",
        output_format: str = "",
        aspect_ratio: str = "",
        base_url: str = "",
        enqueue_source: str = "",
        reference_images: str = "",
    ) -> int:
        """Insert a batch of plan entries as pending tasks. Returns count inserted."""
        conn = _connect(self.db_path)
        enqueued_at = _now_iso()
        source = enqueue_source or f"{os.uname().nodename}/{os.getpid()}"

        rows: list[tuple] = []
        for entry in plan_entries:
            rows.append((
                enqueued_at,
                source,
                prompt_doc_path,
                entry.get("prompt_sha256_16", ""),
                entry.get("prompt_text", ""),
                entry.get("prompt_title", ""),
                entry.get("prompt_source", "main"),
                entry.get("prompt_index", 1),
                theme,
                character,
                str(Path(entry.get("path", "")).parent),
                entry.get("path", ""),
                model,
                provider,
                size,
                quality,
                output_format,
                aspect_ratio,
                base_url,
                reference_images,
            ))

        try:
            conn.executemany(
                """INSERT INTO image_tasks (
                    enqueued_at, enqueue_source, prompt_doc_path, prompt_sha256_16,
                    prompt_text, prompt_title, prompt_source, prompt_index, theme, character,
                    output_dir, output_path,
                    model, provider, size, quality, output_format, aspect_ratio, base_url, reference_images
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )
            conn.commit()
            return len(rows)
        except sqlite3.IntegrityError:
            conn.rollback()
            inserted = 0
            for row in rows:
                try:
                    conn.execute(
                        """INSERT INTO image_tasks (
                            enqueued_at, enqueue_source, prompt_doc_path, prompt_sha256_16,
                            prompt_text, prompt_title, prompt_source, prompt_index, theme, character,
                            output_dir, output_path,
                            model, provider, size, quality, output_format, aspect_ratio, base_url, reference_images
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        row,
                    )
                    conn.commit()
                    inserted += 1
                except sqlite3.IntegrityError:
                    conn.rollback()
            return inserted
        finally:
            conn.close()

    def claim(
        self, worker_id: str, output_dir: str | None = None
    ) -> GenerationIntent | None:
        """Atomically claim one pending task. Returns GenerationIntent or None."""
        conn = _connect(self.db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            where = "status = 'pending' AND (retry_after IS NULL OR retry_after <= ?)"
            params: list = [_now_iso()]
            if output_dir:
                where += " AND output_dir = ?"
                params.append(output_dir)
            row = conn.execute(
                f"""SELECT * FROM image_tasks
                   WHERE {where}
                   ORDER BY priority DESC, id ASC
                   LIMIT 1""",
                params,
            ).fetchone()

            if row is None:
                conn.rollback()
                return None

            now = _now_iso()
            cur = conn.execute(
                """UPDATE image_tasks
                   SET status = 'claimed', claimed_by = ?, claimed_at = ?,
                       attempt_count = attempt_count + 1
                   WHERE id = ? AND status = 'pending'""",
                (worker_id, now, row["id"]),
            )
            if cur.rowcount == 0:
                conn.rollback()
                return None
            updated = conn.execute(
                "SELECT * FROM image_tasks WHERE id = ?",
                (row["id"],),
            ).fetchone()
            conn.commit()
            return GenerationIntent.from_row(updated)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def complete(self, task_id: int, worker_id: str) -> None:
        """Mark a task as done."""
        conn = _connect(self.db_path)
        try:
            conn.execute(
                """UPDATE image_tasks
                   SET status = 'done', generated_at = ?, last_error = ''
                   WHERE id = ? AND claimed_by = ?""",
                (_now_iso(), task_id, worker_id),
            )
            _bump_worker_completed(conn, worker_id)
            conn.commit()
        finally:
            conn.close()

    def fail(
        self,
        task_id: int,
        worker_id: str,
        error: str,
        retry_delay: float = 0,
        force_fail: bool = False,
    ) -> bool:
        """Mark task as failed. Returns True if permanently failed."""
        conn = _connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT attempt_count, max_attempts FROM image_tasks WHERE id = ?",
                (task_id,),
            ).fetchone()

            if row is None:
                _bump_worker_failed(conn, worker_id)
                conn.commit()
                return False

            if force_fail or row["attempt_count"] >= row["max_attempts"]:
                conn.execute(
                    """UPDATE image_tasks
                       SET status = 'failed', last_error = ?, last_error_at = ?,
                           claimed_by = ''
                       WHERE id = ?""",
                    (error, _now_iso(), task_id),
                )
                _bump_worker_failed(conn, worker_id)
                conn.commit()
                return True
            else:
                retry_after = None
                if retry_delay > 0:
                    retry_after = (
                        dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=retry_delay)
                    ).isoformat()
                conn.execute(
                    """UPDATE image_tasks
                       SET status = 'pending', claimed_by = '', last_error = ?,
                           last_error_at = ?, retry_after = ?
                       WHERE id = ?""",
                    (error, _now_iso(), retry_after, task_id),
                )
                _bump_worker_failed(conn, worker_id)
                conn.commit()
                return False
        finally:
            conn.close()

    def cancel(self, task_id: int, reason: str = "cancelled by user") -> bool:
        """Cancel a non-terminal task. Returns True if found."""
        conn = _connect(self.db_path)
        try:
            cur = conn.execute(
                """UPDATE image_tasks
                   SET status = 'failed', last_error = ?, last_error_at = ?, claimed_by = ''
                   WHERE id = ? AND status NOT IN ('done', 'failed')""",
                (reason, _now_iso(), task_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def cancel_stale(self, max_claimed_seconds: int = 1200) -> int:
        """Cancel tasks claimed longer than max_claimed_seconds. Returns count."""
        cutoff = (
            dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=max_claimed_seconds)
        ).isoformat()
        conn = _connect(self.db_path)
        try:
            cur = conn.execute(
                """UPDATE image_tasks
                   SET status = 'failed',
                       last_error = ?,
                       last_error_at = ?, claimed_by = ''
                   WHERE status = 'claimed' AND claimed_at < ?""",
                (f"auto-cancelled: exceeded {max_claimed_seconds}s runtime",
                 _now_iso(), cutoff),
            )
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    def cancel_exhausted(self) -> int:
        """Permanently fail claimed tasks that have exhausted max_attempts.

        These tasks are stuck: a worker claimed them but never called fail_task
        or complete_task.  Unlike cancel_stale (time-based) and reset_stale_claims
        (heartbeat-based), this catches tasks regardless of how recently they
        were claimed.
        """
        conn = _connect(self.db_path)
        try:
            cur = conn.execute(
                """UPDATE image_tasks
                   SET status = 'failed',
                       last_error = ?,
                       last_error_at = ?, claimed_by = ''
                   WHERE status = 'claimed' AND attempt_count >= max_attempts""",
                ("auto-cancelled: exhausted max_attempts", _now_iso()),
            )
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    def get_status(self, task_id: int) -> TaskState | None:
        """Return the TaskState of a task, or None if not found."""
        conn = _connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT status FROM image_tasks WHERE id = ?", (task_id,)
            ).fetchone()
            return task_state_from_str(row["status"]) if row else None
        finally:
            conn.close()

    def get_by_output_dir(self, output_dir: str) -> list[GenerationIntent]:
        """Return all intents for a given output directory."""
        conn = _connect(self.db_path)
        try:
            rows = conn.execute(
                """SELECT * FROM image_tasks
                   WHERE output_dir = ?
                   ORDER BY id ASC""",
                (output_dir,),
            ).fetchall()
            return [GenerationIntent.from_row(r) for r in rows]
        finally:
            conn.close()

    def queued_paths(self, output_dir: str) -> set[str]:
        """Return output_path values already in the queue for a directory."""
        conn = _connect(self.db_path)
        try:
            rows = conn.execute(
                "SELECT output_path FROM image_tasks WHERE output_dir = ?",
                (output_dir,),
            ).fetchall()
            return {row[0] for row in rows}
        finally:
            conn.close()

    def summary(self, output_dir: str | None = None) -> dict[str, Any]:
        """Return queue summary counts."""
        conn = _connect(self.db_path)
        try:
            if output_dir:
                rows = conn.execute(
                    """SELECT status, COUNT(*) as cnt
                       FROM image_tasks WHERE output_dir = ?
                       GROUP BY status""",
                    (output_dir,),
                ).fetchall()
                total = conn.execute(
                    "SELECT COUNT(*) FROM image_tasks WHERE output_dir = ?",
                    (output_dir,),
                ).fetchone()[0]
            else:
                rows = conn.execute(
                    "SELECT status, COUNT(*) as cnt FROM image_tasks GROUP BY status"
                ).fetchall()
                total = conn.execute("SELECT COUNT(*) FROM image_tasks").fetchone()[0]

            counts = {row["status"]: row["cnt"] for row in rows}
            return {
                "total": total,
                "pending": counts.get("pending", 0),
                "claimed": counts.get("claimed", 0),
                "done": counts.get("done", 0),
                "failed": counts.get("failed", 0),
            }
        finally:
            conn.close()

    # -- Recovery ---------------------------------------------------------

    def reset_stale_claims(
        self,
        stale_heartbeat_seconds: int = 600,
        claimed_at_cutoff_seconds: int | None = None,
    ) -> int:
        """Reset claimed tasks with stale worker heartbeats (crash recovery).

        Two independent checks:
        - heartbeat: worker's last_heartbeat older than stale_heartbeat_seconds
        - claimed_at: task claimed longer than claimed_at_cutoff_seconds
          (defaults to stale_heartbeat_seconds when not specified)
        """
        heartbeat_cutoff = (
            dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=stale_heartbeat_seconds)
        ).isoformat()
        _cutoff = claimed_at_cutoff_seconds if claimed_at_cutoff_seconds is not None else stale_heartbeat_seconds
        absolute_cutoff = (
            dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=_cutoff)
        ).isoformat()
        conn = _connect(self.db_path)
        try:
            cur = conn.execute(
                """UPDATE image_tasks
                   SET status = 'pending', claimed_by = '', claimed_at = NULL
                   WHERE status = 'claimed'
                     AND (
                       claimed_by IN (
                         SELECT id FROM workers
                         WHERE last_heartbeat IS NOT NULL AND last_heartbeat < ?
                       )
                       OR claimed_at < ?
                     )""",
                (heartbeat_cutoff, absolute_cutoff),
            )
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    def reset_claimed(self, worker_id: str) -> int:
        """Reset a worker's claimed tasks back to pending (crash recovery)."""
        conn = _connect(self.db_path)
        try:
            cur = conn.execute(
                """UPDATE image_tasks
                   SET status = 'pending', claimed_by = '', claimed_at = NULL
                   WHERE status = 'claimed' AND claimed_by = ?""",
                (worker_id,),
            )
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    def reset_other_run_claims(
        self, current_run_id: str, stale_heartbeat_seconds: int = 600
    ) -> int:
        """Reset tasks claimed by workers from a different, dead run.

        Only resets tasks whose owning worker has a stale heartbeat —
        workers from a live concurrent session are left untouched.
        """
        heartbeat_cutoff = (
            dt.datetime.now(dt.timezone.utc)
            - dt.timedelta(seconds=stale_heartbeat_seconds)
        ).isoformat()
        conn = _connect(self.db_path)
        try:
            cur = conn.execute(
                """UPDATE image_tasks
                   SET status = 'pending', claimed_by = '', claimed_at = NULL
                   WHERE status = 'claimed'
                     AND claimed_by IN (
                       SELECT id FROM workers
                       WHERE (run_id != ? OR run_id = '')
                         AND (last_heartbeat IS NULL OR last_heartbeat < ?)
                     )""",
                (current_run_id, heartbeat_cutoff),
            )
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    # -- Worker management ------------------------------------------------

    def register_worker(self, worker_id: str, api_key_env: str, run_id: str = "") -> None:
        conn = _connect(self.db_path)
        try:
            conn.execute(
                """INSERT OR REPLACE INTO workers
                   (id, api_key_env, run_id, status, started_at, last_heartbeat)
                   VALUES (?, ?, ?, 'idle', ?, ?)""",
                (worker_id, api_key_env, run_id, _now_iso(), _now_iso()),
            )
            conn.commit()
        finally:
            conn.close()

    def set_worker_heartbeat(
        self, worker_id: str, task_id: int | None = None
    ) -> None:
        conn = _connect(self.db_path)
        try:
            conn.execute(
                """UPDATE workers SET last_heartbeat = ?, current_task_id = ?,
                   status = CASE WHEN ? IS NULL THEN 'idle' ELSE 'busy' END
                   WHERE id = ?""",
                (_now_iso(), task_id, task_id, worker_id),
            )
            conn.commit()
        finally:
            conn.close()

    def set_worker_status(self, worker_id: str, status: str) -> None:
        conn = _connect(self.db_path)
        try:
            conn.execute(
                "UPDATE workers SET status = ?, last_heartbeat = ? WHERE id = ?",
                (status, _now_iso(), worker_id),
            )
            conn.commit()
        finally:
            conn.close()

    # -- Cooldown ---------------------------------------------------------

    def set_cooldown(self, worker_id: str, seconds: float, reason: str) -> None:
        """Set cooldown with exponential escalation for repeated cooldowns."""
        conn = _connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT reason FROM key_cooldowns WHERE worker_id = ?",
                (worker_id,),
            ).fetchone()
            count = 0
            if row:
                m = re.search(r'\[(\d+)\]', row["reason"] or "")
                if m:
                    count = int(m.group(1))
            count += 1
            actual_seconds = min(seconds * (2 ** (count - 1)), 120)
            enriched_reason = f"{reason} [{count}]"
            until = (
                dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=actual_seconds)
            ).isoformat()
            conn.execute(
                """INSERT OR REPLACE INTO key_cooldowns
                   (worker_id, cooldown_until, reason, triggered_at)
                   VALUES (?, ?, ?, ?)""",
                (worker_id, until, enriched_reason, _now_iso()),
            )
            conn.commit()
        finally:
            conn.close()

    def is_in_cooldown(self, worker_id: str) -> bool:
        conn = _connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT cooldown_until FROM key_cooldowns WHERE worker_id = ? AND cooldown_until > ?",
                (worker_id, _now_iso()),
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    # -- Manifest ---------------------------------------------------------

    def manifest(self, output_dir: str) -> dict[str, Any]:
        """Build a manifest dict from all tasks for one output_dir.

        Delegates to Manifest.from_intents() for canonical field generation.
        """
        intents = self.get_by_output_dir(output_dir)
        if not intents:
            return {}
        return Manifest.from_intents(intents).to_dict()

    def write_manifests(self) -> list[Path]:
        """Write manifest.json for every output_dir with tasks."""
        conn = _connect(self.db_path)
        try:
            dirs = [
                row[0]
                for row in conn.execute(
                    "SELECT DISTINCT output_dir FROM image_tasks ORDER BY output_dir"
                ).fetchall()
            ]
        finally:
            conn.close()

        written: list[Path] = []
        for output_dir in dirs:
            m = self.manifest(output_dir)
            if not m:
                continue
            manifest_path = Path(output_dir) / "manifest.json"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            write_json(manifest_path, m)
            written.append(manifest_path)
        return written

    def write_timing_logs(self) -> list[Path]:
        """Write _timing.json for every output_dir with done tasks.

        Records per-task timing (enqueue/claim/generate) and batch-level
        percentile summaries for offline performance analysis.
        """
        from statistics import mean, median, quantiles

        conn = _connect(self.db_path)
        try:
            dirs = [
                row[0]
                for row in conn.execute(
                    "SELECT DISTINCT output_dir FROM image_tasks ORDER BY output_dir"
                ).fetchall()
            ]
        finally:
            conn.close()

        written: list[Path] = []
        for output_dir in dirs:
            intents = self.get_by_output_dir(output_dir)
            if not intents:
                continue

            api_durations = []
            wait_durations = []
            total_durations = []
            details = []

            for t in intents:
                enq = _parse_iso(t.enqueued_at) if t.enqueued_at else None
                claimed = _parse_iso(t.claimed_at) if t.claimed_at else None
                generated = _parse_iso(t.generated_at) if t.generated_at else None

                wait_s = (claimed - enq).total_seconds() if enq and claimed else None
                api_s = (generated - claimed).total_seconds() if claimed and generated else None
                total_s = (generated - enq).total_seconds() if enq and generated else None

                detail = {
                    "seq": t.prompt_index,
                    "status": t.state.value if t.state else "unknown",
                    "enqueued": enq.isoformat() if enq else None,
                    "claimed": claimed.isoformat() if claimed else None,
                    "generated": generated.isoformat() if generated else None,
                    "api_s": round(api_s, 1) if api_s is not None else None,
                    "wait_s": round(wait_s, 1) if wait_s is not None else None,
                    "total_s": round(total_s, 1) if total_s is not None else None,
                    "attempts": t.attempt_count,
                }
                if t.last_error:
                    detail["error"] = t.last_error[:200]
                details.append(detail)

                if api_s is not None:
                    api_durations.append(api_s)
                if wait_s is not None:
                    wait_durations.append(wait_s)
                if total_s is not None:
                    total_durations.append(total_s)

            def pcts(data):
                if not data:
                    return {"n": 0, "min_s": None, "p50_s": None, "p95_s": None, "max_s": None, "mean_s": None}
                if len(data) < 2:
                    qs = [data[0]]
                else:
                    qs = quantiles(data, n=20)  # 5% steps
                return {
                    "n": len(data),
                    "min_s": round(min(data), 1),
                    "p50_s": round(median(data), 1),
                    "p95_s": round(qs[min(len(qs) - 1, 18)], 1) if qs else None,
                    "max_s": round(max(data), 1),
                    "mean_s": round(mean(data), 1),
                }

            status_counts = {"done": 0, "failed": 0, "pending": 0, "claimed": 0}
            for t in intents:
                s = t.state.value if t.state else "unknown"
                status_counts[s] = status_counts.get(s, 0) + 1

            enq_times = [
                _parse_iso(t.enqueued_at)
                for t in intents
                if t.enqueued_at
            ]
            gen_times = [
                _parse_iso(t.generated_at)
                for t in intents
                if t.generated_at
            ]

            log = {
                "batch": Path(output_dir).name,
                "started_at": min(enq_times).isoformat() if enq_times else None,
                "finished_at": max(gen_times).isoformat() if gen_times else None,
                "wall_seconds": (
                    round((max(gen_times) - min(enq_times)).total_seconds(), 1)
                    if enq_times and gen_times
                    else None
                ),
                "tasks": {
                    "total": len(intents),
                    **status_counts,
                },
                "durations": {
                    "api_call": pcts(api_durations),
                    "queue_wait": pcts(wait_durations),
                    "total": pcts(total_durations),
                },
                "details": details,
            }

            timing_path = Path(output_dir) / "_timing.json"
            timing_path.parent.mkdir(parents=True, exist_ok=True)
            write_json(timing_path, log)
            written.append(timing_path)

        return written


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _bump_worker_completed(conn: sqlite3.Connection, worker_id: str) -> None:
    conn.execute("DELETE FROM key_cooldowns WHERE worker_id = ?", (worker_id,))
    conn.execute(
        """UPDATE workers SET total_completed = total_completed + 1,
           status = 'idle', current_task_id = NULL, last_heartbeat = ?
           WHERE id = ?""",
        (_now_iso(), worker_id),
    )


def _bump_worker_failed(conn: sqlite3.Connection, worker_id: str) -> None:
    conn.execute(
        """UPDATE workers SET total_failed = total_failed + 1,
           status = 'idle', current_task_id = NULL, last_heartbeat = ?
           WHERE id = ?""",
        (_now_iso(), worker_id),
    )


def _parse_iso(value: str) -> dt.datetime:
    """Parse an ISO-8601 timestamp string; tolerate trailing Z and timezone offsets."""
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return dt.datetime.fromisoformat(value)
