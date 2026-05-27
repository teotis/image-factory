"""Lightweight SQLite-based task queue for multi-key image generation.

All functions now delegate to IntentRepository in repository.py.
Public API signatures are unchanged for backward compatibility.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .repository import IntentRepository, SCHEMA, _connect, _now_iso  # noqa: F401 — re-exported for external callers

DEFAULT_QUEUE_DB = Path(__file__).resolve().parents[2] / "outputs" / "task_queue.db"


def _repo(db_path: Path) -> IntentRepository:
    return IntentRepository(db_path)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def init_db(db_path: Path | None = None) -> Path:
    path = Path(db_path) if db_path else DEFAULT_QUEUE_DB
    return _repo(path).init_db()


# ---------------------------------------------------------------------------
# Task CRUD
# ---------------------------------------------------------------------------

def enqueue_tasks(
    db_path: Path,
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
    return _repo(db_path).enqueue(
        plan_entries,
        prompt_doc_path=prompt_doc_path,
        theme=theme,
        character=character,
        model=model,
        provider=provider,
        size=size,
        quality=quality,
        output_format=output_format,
        aspect_ratio=aspect_ratio,
        base_url=base_url,
        enqueue_source=enqueue_source,
        reference_images=reference_images,
    )


def claim_task(db_path: Path, worker_id: str, output_dir: str | None = None) -> dict[str, Any] | None:
    intent = _repo(db_path).claim(worker_id, output_dir)
    if intent is None:
        return None
    return intent.to_row_dict()


def complete_task(db_path: Path, task_id: int, worker_id: str) -> None:
    _repo(db_path).complete(task_id, worker_id)


def fail_task(
    db_path: Path,
    task_id: int,
    worker_id: str,
    error: str,
    retry_delay: float = 0,
    force_fail: bool = False,
) -> bool:
    return _repo(db_path).fail(task_id, worker_id, error, retry_delay, force_fail)


def cancel_task(db_path: Path, task_id: int, reason: str = "cancelled by user") -> bool:
    return _repo(db_path).cancel(task_id, reason)


def cancel_stale_tasks(db_path: Path, max_claimed_seconds: int = 1200) -> int:
    return _repo(db_path).cancel_stale(max_claimed_seconds)


def cancel_exhausted_tasks(db_path: Path) -> int:
    return _repo(db_path).cancel_exhausted()


def get_task_status(db_path: Path, task_id: int) -> str | None:
    state = _repo(db_path).get_status(task_id)
    return state.value if state else None


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------

def reset_stale_claims(
    db_path: Path,
    stale_heartbeat_seconds: int = 600,
    claimed_at_cutoff_seconds: int | None = None,
) -> int:
    return _repo(db_path).reset_stale_claims(
        stale_heartbeat_seconds, claimed_at_cutoff_seconds
    )


def reset_other_run_claims(
    db_path: Path, current_run_id: str, stale_heartbeat_seconds: int = 600
) -> int:
    return _repo(db_path).reset_other_run_claims(
        current_run_id, stale_heartbeat_seconds
    )


def reset_claimed_tasks(db_path: Path, worker_id: str) -> int:
    return _repo(db_path).reset_claimed(worker_id)


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def queued_paths(db_path: Path, output_dir: str) -> set[str]:
    return _repo(db_path).queued_paths(output_dir)


def queue_summary(db_path: Path, output_dir: str | None = None) -> dict[str, Any]:
    return _repo(db_path).summary(output_dir)


# ---------------------------------------------------------------------------
# Worker management
# ---------------------------------------------------------------------------

def register_worker(db_path: Path, worker_id: str, api_key_env: str, run_id: str = "") -> None:
    _repo(db_path).register_worker(worker_id, api_key_env, run_id)


def set_worker_heartbeat(db_path: Path, worker_id: str, task_id: int | None = None) -> None:
    _repo(db_path).set_worker_heartbeat(worker_id, task_id)


def set_worker_status(db_path: Path, worker_id: str, status: str) -> None:
    _repo(db_path).set_worker_status(worker_id, status)


# ---------------------------------------------------------------------------
# Cooldown
# ---------------------------------------------------------------------------

def set_cooldown(db_path: Path, worker_id: str, seconds: float, reason: str) -> None:
    _repo(db_path).set_cooldown(worker_id, seconds, reason)


def is_in_cooldown(db_path: Path, worker_id: str) -> bool:
    return _repo(db_path).is_in_cooldown(worker_id)
