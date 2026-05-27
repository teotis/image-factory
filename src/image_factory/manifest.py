"""Manifest dataclass — the canonical schema for generation run manifests.

Replaces the three scattered manifest-building code paths:
- prompt_doc_runs.build_run_manifest()
- strategy._build_initial_manifest()
- repository.IntentRepository.manifest()

All consumers that build a manifest should go through Manifest.from_intents()
or the Manifest dataclass constructor, so the field set and semantics are consistent
regardless of which pipeline stage produced the manifest.
"""
from __future__ import annotations

import dataclasses
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import DEFAULT_REQUEST_TIMEOUT_SECONDS
from .models import GenerationIntent, TaskState, manifest_status


@dataclass
class Manifest:
    """Canonical manifest for an image generation run.

    Every field has a stable default so that callers can override only what
    they care about.  Use ``Manifest.from_intents(intents, **overrides)`` to
    populate the computed fields (prompt_plan, generated, errors, status,
    counts, prompt_source, etc.) from a list of GenerationIntent.
    """

    # -- document identity -------------------------------------------------
    prompt_doc: str = ""
    theme: str = ""
    platform: str = ""
    character: str = ""
    aspect_ratio: str = ""

    # -- output ------------------------------------------------------------
    output_dir: str = ""
    file_prefix: str = ""
    content_hash: str = ""

    # -- counts ------------------------------------------------------------
    target_count: int = 0
    existing_count: int = 0
    remaining_count: int = 0

    # -- plan --------------------------------------------------------------
    planned_paths: list[str] = field(default_factory=list)
    prompt_source: str = "main"
    available_variant_count: int = 0
    prompt_plan: list[dict[str, Any]] = field(default_factory=list)

    # -- generation parameters ---------------------------------------------
    model: str = ""
    provider: str = ""
    requested_size: str = ""
    size: str = ""
    size_source: str = "requested_size"
    quality: str = ""
    output_format: str = ""
    images_per_call: int = 1
    max_attempts: int = 5

    # -- execution control -------------------------------------------------
    execute: bool = False
    base_url: str | None = None
    request_timeout_seconds: float | None = DEFAULT_REQUEST_TIMEOUT_SECONDS
    fallback_to_plan_on_api_error: bool = False
    fallback_reason: str = ""

    # -- status & results --------------------------------------------------
    status: str = "planned"
    generated: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    review: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Factory: from a list of GenerationIntent
    # ------------------------------------------------------------------

    @classmethod
    def from_intents(
        cls,
        intents: list[GenerationIntent],
        **overrides: Any,
    ) -> Manifest:
        """Build a Manifest from a list of GenerationIntent.

        All computed fields (prompt_plan, generated, errors, status,
        counts, prompt_source, available_variant_count) are derived
        directly from the intents.  Pass keyword arguments to override
        any field (e.g. ``platform``, ``execute``, ``base_url``).
        """
        if not intents:
            return cls(**overrides)

        first = intents[0]
        total = len(intents)

        # -- counts --------------------------------------------------------
        done = sum(1 for i in intents if i.state == TaskState.DONE)
        failed = sum(1 for i in intents if i.state == TaskState.FAILED)
        pending = sum(1 for i in intents if i.state == TaskState.PENDING)
        claimed = sum(1 for i in intents if i.state == TaskState.CLAIMED)
        existing_with_placeholders = done + failed
        remaining = pending + claimed
        status = manifest_status(intents)

        # -- paths & prefix ------------------------------------------------
        prefix = first.output_path_prefix
        planned_paths = [i.output_path for i in intents]

        # -- prompt_plan ---------------------------------------------------
        prompt_plan: list[dict[str, Any]] = []
        for i in intents:
            prompt_plan.append({
                "sequence": i.id,
                "path": i.output_path,
                "prompt_source": i.prompt_source or "main",
                "prompt_index": i.prompt_index or 1,
                "prompt_title": i.prompt_title,
                "prompt_sha256_16": i.prompt_sha256_16,
                "prompt_preview": i.prompt_preview,
            })

        # -- generated items -----------------------------------------------
        generated: list[dict[str, Any]] = []
        for i in intents:
            if i.state == TaskState.DONE:
                generated.append({
                    "attempt": i.attempt_count,
                    "path": i.output_path,
                    "prompt_source": i.prompt_source or "main",
                    "prompt_index": i.prompt_index or 1,
                    "prompt_title": i.prompt_title,
                    "prompt_sha256_16": i.prompt_sha256_16,
                    "revised_prompt": "",
                    "generated_at": i.generated_at or "",
                })
            elif i.state == TaskState.FAILED:
                generated.append({
                    "attempt": i.attempt_count,
                    "path": i.output_path,
                    "prompt_source": i.prompt_source or "main",
                    "prompt_index": i.prompt_index or 1,
                    "prompt_title": i.prompt_title,
                    "prompt_sha256_16": i.prompt_sha256_16,
                    "revised_prompt": "",
                    "generated_at": i.last_error_at or "",
                    "placeholder": True,
                    "error": i.last_error,
                })

        # -- prompt_source & variant count ---------------------------------
        prompt_source_values = {i.prompt_source or "main" for i in intents}
        has_variants = any(s != "main" for s in prompt_source_values)
        resolved_prompt_source = "variants" if has_variants else "main"
        variant_indices = {
            i.prompt_index for i in intents if (i.prompt_source or "main") != "main"
        }
        available_variant_count = len(variant_indices) if variant_indices else 0

        # -- size_source ---------------------------------------------------
        size_source = (
            f"aspect_ratio:{first.aspect_ratio}" if first.aspect_ratio else "requested_size"
        )

        # -- base ----------------------------------------------------------
        base: dict[str, Any] = {
            "prompt_doc": first.prompt_doc_path,
            "theme": first.theme,
            "platform": "",
            "character": first.character,
            "aspect_ratio": first.aspect_ratio,
            "output_dir": first.output_dir,
            "file_prefix": prefix,
            "content_hash": content_hash_for_request(first.theme, first.character),
            "target_count": total,
            "existing_count": existing_with_placeholders,
            "remaining_count": remaining,
            "planned_paths": planned_paths,
            "prompt_source": resolved_prompt_source,
            "available_variant_count": available_variant_count,
            "prompt_plan": prompt_plan,
            "model": first.model,
            "provider": first.provider,
            "requested_size": first.size,
            "size": first.size,
            "size_source": size_source,
            "quality": first.quality,
            "output_format": first.output_format,
            "images_per_call": 1,
            "max_attempts": first.max_attempts,
            "execute": True,
            "base_url": first.base_url or None,
            "request_timeout_seconds": DEFAULT_REQUEST_TIMEOUT_SECONDS,
            "fallback_to_plan_on_api_error": False,
            "status": status,
            "generated": generated,
            "errors": [
                {"task_id": i.id, "error": i.last_error}
                for i in intents if i.state == TaskState.FAILED
            ],
            "review": default_review_template(),
        }

        # Apply caller overrides
        base.update(overrides)
        return cls(**base)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Export to a plain dict (e.g. for JSON serialisation)."""
        return dataclasses.asdict(self)

    # ------------------------------------------------------------------
    # Mutation helpers — used by strategies during execution
    # ------------------------------------------------------------------

    def add_generated(self, intent: GenerationIntent, attempt: int, revised_prompt: str = "") -> None:
        """Append a generated entry from a successfully completed intent."""
        self.generated.append({
            "attempt": attempt,
            "path": intent.output_path,
            "prompt_source": intent.prompt_source or "main",
            "prompt_index": intent.prompt_index or 1,
            "prompt_title": intent.prompt_title,
            "prompt_sha256_16": intent.prompt_sha256_16,
            "revised_prompt": revised_prompt,
            "generated_at": intent.generated_at or "",
        })

    def sync_counts(self, done_count: int) -> None:
        """Update existing_count and remaining_count from a done count."""
        self.existing_count = done_count
        self.remaining_count = max(0, self.target_count - done_count)


# ------------------------------------------------------------------
# Shared helpers
# ------------------------------------------------------------------

def content_hash_for_request(theme: str, character: str = "") -> str:
    """Deterministic 8-hex-char hash of theme + character for directory disambiguation."""
    payload = "\n".join([theme.strip(), character.strip()]).strip()
    if not payload:
        return hashlib.sha256(b"").hexdigest()[:8]
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]


def default_review_template() -> dict[str, Any]:
    return {
        "status": "not_reviewed",
        "criteria": {
            "character_identity": "角色相似度、脸型轮廓、眉眼气质、表情习惯",
            "temperament_match": "是否保住角色精神状态与人物本人感，而非只有表皮特征",
            "realism_translation": "是否转成可信真人照片比例与材质，而不是动漫脸、假人脸或模板脸",
            "group_readability": "多人图里主次人物是否清楚、边缘角色是否可辨、是否避免同脸",
            "cuteness": "可爱感、少女感、角色风采是否成立",
            "hair_color": "发色和发型轮廓是否保留且不过度假发化",
            "maturity_control": "是否避免欧美成熟化、疲惫现实主义和职业化脸",
            "color_exposure": "是否避免灰暗低饱和，保留清晰色块和正常曝光",
            "life_action": "动作是否生活化、有关系和事件，而非空洞摆拍",
            "hands_props": "手、乐器、道具是否自然，不抢走角色识别",
            "body_integrity": "整体人体结构是否正常——头颈肩臂手脚关系清楚，无融合/缺失/断裂，关节可见且连续",
        },
        "items": [],
        "summary": "人物不过关时，先修角色身份、气质、真人转译和群像可辨识性，再处理环境氛围。",
    }
