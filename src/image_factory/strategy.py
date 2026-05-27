"""Execution strategies for image generation.

Defines the ExecutionStrategy protocol and SequentialStrategy implementation.
ConcurrentStrategy lives in scripts/run_image_workers.py (it depends on
worker threading, signal handling, and API key resolution).
"""
from __future__ import annotations

import base64
import datetime as dt
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .config import (
    DEFAULT_MODEL,
    DEFAULT_OUTPUT_FORMAT,
    DEFAULT_PROVIDER,
    DEFAULT_QUALITY,
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    DEFAULT_SIZE,
)
from .io import write_json
from .models import ErrorKind, ErrorPolicy, GenerationIntent, TaskState, task_state_from_str
from .providers import generate_images
from .manifest import Manifest
from .prompt_doc_runs import (
    PromptDoc,
    OutputNaming,
    build_prompt_plan,
    existing_image_paths,
    infer_output_naming,
    merge_existing_review,
    next_sequence_number,
    parse_prompt_doc_html,
    prompt_digest,
    prompt_for_plan_index,
    resolve_effective_size,
    resolve_prompt_source,
    save_generated_image,
)
from .results import extension_for_format, save_url


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

class ExecutionStrategy(Protocol):
    """Any strategy that can execute a list of generation intents."""

    def run(
        self,
        intents: list[GenerationIntent],
        repo: Any,  # IntentRepository — avoided circular import
        *,
        allow_api: bool = False,
    ) -> dict[str, Any]:
        """Execute generation. Returns a manifest-style result dict."""
        ...


# ---------------------------------------------------------------------------
# SequentialStrategy — replaces generate_until_target()
# ---------------------------------------------------------------------------

@dataclass
class SequentialStrategy:
    """Single-process sequential generation. Direct replacement for the
    ``--execute --direct`` code path.
    """

    error_policy: ErrorPolicy | None = None

    def __post_init__(self) -> None:
        if self.error_policy is None:
            self.error_policy = ErrorPolicy()

    def run(
        self,
        intents: list[GenerationIntent],
        repo: Any,
        *,
        allow_api: bool = False,
    ) -> dict[str, Any]:
        """Generate images sequentially, updating each intent's state in-place
        and writing a manifest after each image.
        """
        if not intents:
            return {"status": "planned", "generated": [], "errors": []}

        first = intents[0]
        output_dir = Path(first.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        manifest = _build_initial_manifest(intents)
        manifest_path = output_dir / "manifest.json"

        if not allow_api:
            # Plan-only mode
            write_json(manifest_path, manifest.to_dict())
            result = manifest.to_dict()
            result["manifest_path"] = str(manifest_path)
            return result

        remaining_intents = [i for i in intents if i.state == TaskState.PENDING]
        if not remaining_intents:
            manifest.status = "skipped"
            write_json(manifest_path, manifest.to_dict())
            result = manifest.to_dict()
            result["manifest_path"] = str(manifest_path)
            return result

        manifest.status = "running"
        write_json(manifest_path, manifest.to_dict())

        saved_count = sum(1 for i in intents if i.state == TaskState.DONE)

        for intent in remaining_intents:
            policy = self.error_policy
            attempts = 0

            while attempts < intent.max_attempts and intent.state == TaskState.PENDING:
                attempts += 1
                try:
                    response = generate_images(
                        intent.prompt_text,
                        model=intent.model,
                        provider=intent.provider,
                        size=first.size,
                        quality=intent.quality,
                        output_format=intent.output_format,
                        images_per_prompt=1,
                        allow_api=allow_api,
                        aspect_ratio=None,
                        base_url=first.base_url or None,
                        timeout=DEFAULT_REQUEST_TIMEOUT_SECONDS,
                    )
                except Exception as exc:
                    error_entry = {
                        "attempt": attempts,
                        "path": intent.output_path,
                        "prompt_source": intent.prompt_source,
                        "prompt_index": intent.prompt_index,
                        "prompt_title": intent.prompt_title,
                        "status_code": _exc_status_code(exc),
                        "error": str(exc),
                    }
                    manifest.errors.append(error_entry)

                    kind = policy.classify(exc)
                    if kind in (ErrorKind.TRANSIENT, ErrorKind.RATE_LIMITED):
                        delay = policy.retry_delay(exc, attempts)
                        if delay > 0:
                            print(f"[retry] attempt {attempts} failed for {intent.prompt_title}; waiting {delay}s")
                            time.sleep(delay)
                        else:
                            print(f"[retry] attempt {attempts} failed for {intent.prompt_title}")
                        continue
                    # Permanent failure
                    intent.state = TaskState.FAILED
                    intent.last_error = str(exc)[:300]
                    intent.last_error_at = dt.datetime.now(dt.timezone.utc).isoformat()
                    break

                data = response.get("data") or []
                if not data:
                    manifest.errors.append({"attempt": attempts, "path": intent.output_path, "error": "no image data"})
                    continue

                item = data[0]
                image_path = Path(intent.output_path)
                save_generated_image(item, image_path)
                intent.state = TaskState.DONE
                intent.generated_at = dt.datetime.now(dt.timezone.utc).isoformat()
                saved_count += 1

                manifest.add_generated(intent, attempts, item.get("revised_prompt", ""))
                break  # success, move to next intent

            # Update manifest after each intent
            manifest.sync_counts(saved_count)
            manifest.status = "partial" if saved_count < manifest.target_count else "complete"
            write_json(manifest_path, manifest.to_dict())

        # Final status
        if saved_count >= manifest.target_count:
            manifest.status = "complete"
        elif saved_count > 0:
            manifest.status = "partial"
        else:
            manifest.status = "failed"
        write_json(manifest_path, manifest.to_dict())
        result = manifest.to_dict()
        result["manifest_path"] = str(manifest_path)
        return result


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _build_initial_manifest(intents: list[GenerationIntent]) -> Manifest:
    """Build an initial Manifest from a list of intents (pre-execution).

    Delegates to Manifest.from_intents() for canonical field generation.
    """
    if not intents:
        return Manifest(status="planned")
    return Manifest.from_intents(intents)


def _exc_status_code(exc: Exception) -> int | None:
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    return response_status if isinstance(response_status, int) else None
