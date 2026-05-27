"""Core domain types for image_factory.

This module defines the unified type system for generation intents,
task states, and error policies. All other modules should import
types from here rather than defining their own representations.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# TaskState — the single source of truth for task lifecycle
# ---------------------------------------------------------------------------

class TaskState(Enum):
    """Unified task state enum.

    Replaces the scattered status strings previously defined independently
    in task_queue.py, prompt_doc_runs.py, and manifest_from_queue.py.
    """
    PENDING = "pending"
    CLAIMED = "claimed"
    GENERATING = "generating"
    SAVING = "saving"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


# States that indicate the task is actively being processed
ACTIVE_STATES = frozenset({TaskState.CLAIMED, TaskState.GENERATING, TaskState.SAVING})

# Terminal states — no further transitions possible
TERMINAL_STATES = frozenset({TaskState.DONE, TaskState.FAILED, TaskState.CANCELLED})


def task_state_from_str(value: str) -> TaskState:
    """Convert a string status to TaskState. Raises ValueError for unknown values."""
    try:
        return TaskState(value)
    except ValueError:
        raise ValueError(f"Unknown task state: {value!r}") from None


def manifest_status(intents: list[GenerationIntent]) -> str:
    """Aggregate a list of generation intents into a single manifest status.

    This is the pure function that replaces the scattered if/elif chains
    in manifest_from_queue.py and prompt_doc_runs.py.
    """
    if not intents:
        return "planned"

    states = [i.state for i in intents]

    done = sum(1 for s in states if s == TaskState.DONE)
    failed = sum(1 for s in states if s == TaskState.FAILED)
    active = sum(1 for s in states if s in ACTIVE_STATES)
    pending = sum(1 for s in states if s == TaskState.PENDING)
    total = len(states)

    if done >= total:
        return "complete"
    if failed >= total:
        return "failed"
    if done + failed >= total:
        return "partial"
    if done > 0:
        return "partial"
    if active > 0:
        return "running"
    if failed > 0 and pending == 0:
        return "failed"
    if pending > 0:
        return "queued"
    return "planned"


# ---------------------------------------------------------------------------
# GenerationIntent — the core domain entity
# ---------------------------------------------------------------------------

@dataclass
class GenerationIntent:
    """A single generation intent: one prompt → one image.

    Fields map 1:1 to the ``image_tasks`` SQLite table. This replaces
    the bare ``sqlite3.Row`` dictionaries that were previously passed
    around as ``dict[str, Any]``.
    """

    # Identity
    id: int = 0
    enqueued_at: str = ""
    enqueue_source: str = ""

    # Prompt source
    prompt_doc_path: str = ""
    prompt_sha256_16: str = ""
    prompt_text: str = ""
    prompt_title: str = ""
    prompt_source: str = "main"
    prompt_index: int = 1
    theme: str = ""
    character: str = ""

    # Output
    output_dir: str = ""
    output_path: str = ""

    # State
    state: TaskState = TaskState.PENDING
    claimed_by: str = ""
    claimed_at: str | None = None

    # Generation parameters
    model: str = ""
    provider: str = ""
    size: str = ""
    quality: str = ""
    output_format: str = ""
    aspect_ratio: str = ""
    base_url: str = ""

    # Retry
    attempt_count: int = 0
    max_attempts: int = 1
    last_error: str = ""
    last_error_at: str | None = None
    generated_at: str | None = None
    retry_after: str | None = None

    # Extras
    priority: int = 0
    reference_images: str = ""
    metadata_json: str = "{}"

    @classmethod
    def from_row(cls, row: Any) -> GenerationIntent:
        """Create from a sqlite3.Row or dict with string status."""
        d = dict(row)
        return cls(
            id=d.get("id", 0),
            enqueued_at=d.get("enqueued_at", ""),
            enqueue_source=d.get("enqueue_source", ""),
            prompt_doc_path=d.get("prompt_doc_path", ""),
            prompt_sha256_16=d.get("prompt_sha256_16", ""),
            prompt_text=d.get("prompt_text", ""),
            prompt_title=d.get("prompt_title", ""),
            prompt_source=d.get("prompt_source", "main"),
            prompt_index=d.get("prompt_index", 1),
            theme=d.get("theme", ""),
            character=d.get("character", ""),
            output_dir=d.get("output_dir", ""),
            output_path=d.get("output_path", ""),
            state=task_state_from_str(d.get("status", "pending")),
            claimed_by=d.get("claimed_by", ""),
            claimed_at=d.get("claimed_at"),
            model=d.get("model", ""),
            provider=d.get("provider", ""),
            size=d.get("size", ""),
            quality=d.get("quality", ""),
            output_format=d.get("output_format", ""),
            aspect_ratio=d.get("aspect_ratio", ""),
            base_url=d.get("base_url", ""),
            attempt_count=d.get("attempt_count", 0),
            max_attempts=d.get("max_attempts", 1),
            last_error=d.get("last_error", ""),
            last_error_at=d.get("last_error_at"),
            generated_at=d.get("generated_at"),
            retry_after=d.get("retry_after"),
            priority=d.get("priority", 0),
            reference_images=d.get("reference_images", ""),
            metadata_json=d.get("metadata_json", "{}"),
        )

    @property
    def output_path_prefix(self) -> str:
        """Extract the filename prefix from output_path (e.g. 'mygo_20260508_xxx_001.png' → 'mygo_20260508_xxx')."""
        stem = Path(self.output_path).stem
        # Strip trailing _NNN sequence number
        return stem.rsplit("_", 1)[0] if "_" in stem else stem

    @property
    def prompt_preview(self) -> str:
        """First 180 chars of normalized prompt text."""
        return " ".join(self.prompt_text.split())[:180]

    def to_row_dict(self) -> dict[str, Any]:
        """Convert back to dict matching sqlite3.Row format (for backward compat)."""
        return {
            "id": self.id,
            "enqueued_at": self.enqueued_at,
            "enqueue_source": self.enqueue_source,
            "prompt_doc_path": self.prompt_doc_path,
            "prompt_sha256_16": self.prompt_sha256_16,
            "prompt_text": self.prompt_text,
            "prompt_title": self.prompt_title,
            "prompt_source": self.prompt_source,
            "prompt_index": self.prompt_index,
            "theme": self.theme,
            "character": self.character,
            "output_dir": self.output_dir,
            "output_path": self.output_path,
            "status": self.state.value,
            "claimed_by": self.claimed_by,
            "claimed_at": self.claimed_at,
            "model": self.model,
            "provider": self.provider,
            "size": self.size,
            "quality": self.quality,
            "output_format": self.output_format,
            "aspect_ratio": self.aspect_ratio,
            "base_url": self.base_url,
            "attempt_count": self.attempt_count,
            "max_attempts": self.max_attempts,
            "last_error": self.last_error,
            "last_error_at": self.last_error_at,
            "generated_at": self.generated_at,
            "retry_after": self.retry_after,
            "priority": self.priority,
            "reference_images": self.reference_images,
            "metadata_json": self.metadata_json,
        }

    @property
    def is_retryable(self) -> bool:
        """Whether this task can be retried (not yet exhausted max attempts)."""
        return self.attempt_count < self.max_attempts


# ---------------------------------------------------------------------------
# ErrorPolicy — unified error classification and retry logic
# ---------------------------------------------------------------------------

class ErrorKind(Enum):
    """Classification of an API error."""
    TRANSIENT = "transient"      # Retryable: rate limit, server error, timeout
    PERMANENT = "permanent"      # Not retryable: bad request, auth error, etc.
    RATE_LIMITED = "rate_limited"  # Special transient: needs cooldown


@dataclass(frozen=True)
class ErrorPolicy:
    """Centralized error classification and retry delay computation.

    Replaces the duplicated logic in:
    - prompt_doc_runs.py: is_retryable_generation_error(), retry_after_seconds()
    - run_image_workers.py: _retry_delay_for_error(), COOLDOWN_* constants
    """

    transient_codes: frozenset[int] = frozenset(
        {408, 409, 429, 500, 502, 503, 504, 520, 522, 524}
    )
    rate_limit_codes: frozenset[int] = frozenset({429})
    overload_codes: frozenset[int] = frozenset({502, 503})
    max_retry_delay: int = 60
    default_transient_delay: int = 5
    cooldown_429: int = 8
    cooldown_503: int = 5
    cooldown_timeout: int = 10

    def classify(self, exc: Exception) -> ErrorKind:
        """Classify an exception into an ErrorKind."""
        status_code = _error_status_code(exc)
        if status_code is not None:
            if status_code in self.rate_limit_codes:
                return ErrorKind.RATE_LIMITED
            if status_code in self.transient_codes:
                return ErrorKind.TRANSIENT
            return ErrorKind.PERMANENT

        # Check error text for retryable signals
        text = str(exc).lower()
        if "retryable" in text and "true" in text:
            return ErrorKind.TRANSIENT

        exc_name = type(exc).__name__.lower()
        if any(kw in exc_name for kw in ("connection", "remote", "timeout", "protocol")):
            return ErrorKind.TRANSIENT
        if any(kw in text for kw in ("server disconnected", "connection error", "remote protocol")):
            return ErrorKind.TRANSIENT

        return ErrorKind.PERMANENT

    def retry_delay(self, exc: Exception, attempt: int = 1) -> int:
        """Compute retry delay in seconds for a given error and attempt number."""
        # First try to extract server-provided retry-after
        delay = _retry_after_seconds(exc)
        if delay > 0:
            return min(delay, self.max_retry_delay)

        # Exponential backoff based on attempt
        base = self.default_transient_delay
        return min(base * (2 ** (attempt - 1)), self.max_retry_delay)

    def cooldown_seconds(self, exc: Exception) -> float:
        """Return the worker cooldown duration for rate-limited/overloaded errors."""
        status_code = _error_status_code(exc)
        if status_code in self.rate_limit_codes:
            return self.cooldown_429
        if status_code in self.overload_codes:
            return self.cooldown_503
        return self.cooldown_timeout


# ---------------------------------------------------------------------------
# Internal helpers for ErrorPolicy
# ---------------------------------------------------------------------------

def _error_status_code(exc: Exception) -> int | None:
    """Extract HTTP status code from an exception."""
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    return response_status if isinstance(response_status, int) else None


def _retry_after_seconds(exc: Exception) -> int:
    """Extract retry-after header value from an exception."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", {}) or {}
    try:
        value = headers.get("retry-after") or headers.get("Retry-After")
    except AttributeError:
        value = None
    if value and str(value).isdigit():
        return min(int(value), 120)

    match = re.search(r"'retry_after':\s*(\d+)", str(exc))
    if match:
        return min(int(match.group(1)), 120)
    return 0
