from __future__ import annotations

import base64
import datetime as dt
import hashlib
import math
import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .config import (
    DEFAULT_MODEL,
    DEFAULT_OUTPUT_FORMAT,
    DEFAULT_PROVIDER,
    DEFAULT_QUALITY,
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    DEFAULT_SIZE,
)
from .io import read_json, write_json
from .models import ErrorKind, ErrorPolicy, _error_status_code, _retry_after_seconds
from .providers import generate_images
from .results import extension_for_format, save_url
from .manifest import Manifest, content_hash_for_request, default_review_template


PROMPT_HEADINGS = (
    "推荐主 Prompt",
    "Positive Prompt",
    "Midjourney 单段 Prompt",
    "中文主 Prompt",
)

# Unified error policy — single source of truth for retry classification
_DEFAULT_ERROR_POLICY = ErrorPolicy()

# Kept for backward compatibility; prefer ErrorPolicy.classify() in new code
TRANSIENT_STATUS_CODES = frozenset({408, 409, 429, 500, 502, 503, 504, 520, 522, 524})
MAX_IMAGE_SIDE = 3840
MIN_IMAGE_PIXELS = 655_360
MAX_IMAGE_PIXELS = 8_294_400
POPULAR_ASPECT_RATIO_SIZES = {
    "1:1": "2048x2048",
    "16:9": "3840x2160",
    "9:16": "2160x3840",
}


@dataclass(frozen=True)
class PromptVariant:
    title: str
    prompt: str


@dataclass(frozen=True)
class PromptDoc:
    path: Path
    theme: str
    prompt: str
    variants: tuple[PromptVariant, ...] = ()
    title: str = ""
    character: str = ""
    aspect_ratio: str = ""
    platform: str = ""


@dataclass(frozen=True)
class OutputNaming:
    series: str
    date: str
    topic: str

    @property
    def prefix(self) -> str:
        return f"{self.date}_{self.series}_{self.topic}"


class _PromptDocHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.current_tag = ""
        self.buffer: list[str] = []
        self.current_heading = ""
        self.in_variant_section = False
        self.current_variant_title = ""
        self.title = ""
        self.headings: list[str] = []
        self.paragraphs: list[str] = []
        self.spans: list[str] = []
        self.pre_sections: list[tuple[str, str]] = []
        self.variant_sections: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key: value or "" for key, value in attrs}
        if tag == "section" and "variant" in attrs_dict.get("class", "").split():
            self.in_variant_section = True
            self.current_variant_title = ""
        if tag in {"title", "h1", "h2", "h3", "p", "span", "pre"}:
            self.current_tag = tag
            self.buffer = []

    def handle_data(self, data: str) -> None:
        if self.current_tag:
            self.buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "section" and self.in_variant_section:
            self.in_variant_section = False
            self.current_variant_title = ""
            return
        if tag != self.current_tag:
            return

        text = "".join(self.buffer).strip()
        if tag == "title":
            self.title = text
        elif tag == "h2":
            self.current_heading = text
            self.headings.append(text)
        elif tag == "h3" and self.in_variant_section:
            self.current_variant_title = text
        elif tag == "p":
            self.paragraphs.append(text)
        elif tag == "span":
            self.spans.append(text)
        elif tag == "pre":
            self.pre_sections.append((self.current_heading, text))
            if self.in_variant_section and text:
                self.variant_sections.append((self.current_variant_title, text))

        self.current_tag = ""
        self.buffer = []


def slugify_filename_part(value: str, fallback: str, max_length: int = 48) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    slug = re.sub(r"_+", "_", slug)
    if not slug:
        slug = fallback
    return slug[:max_length].strip("_") or fallback


def validate_doc_date(value: str | None = None) -> str:
    if not value:
        return dt.date.today().strftime("%Y%m%d")
    if not re.fullmatch(r"\d{8}", value):
        raise ValueError("date must use YYYYMMDD format")
    dt.datetime.strptime(value, "%Y%m%d")
    return value


def find_latest_prompt_html(docs_dir: Path) -> Path:
    candidates = sorted(docs_dir.glob("*_embedded.html"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not candidates:
        raise FileNotFoundError(f"No *_embedded.html prompt docs found in {docs_dir}")
    return candidates[0]


def parse_prompt_doc_html(path: Path) -> PromptDoc:
    parser = _PromptDocHTMLParser()
    parser.feed(path.read_text(encoding="utf-8"))

    prompt = select_prompt_text(parser.pre_sections)
    if not prompt:
        raise ValueError(f"{path} does not contain a usable prompt <pre> block")

    theme = first_usable_value(
        extract_prefixed_value(parser.paragraphs + parser.spans, "主题："),
        parser.title.split(" - ", 1)[0].strip() if parser.title else "",
        path.stem.removesuffix("_embedded"),
    )

    return PromptDoc(
        path=path,
        theme=theme,
        prompt=prompt,
        variants=tuple(
            PromptVariant(title=title or f"Variant {index:02d}", prompt=variant_prompt)
            for index, (title, variant_prompt) in enumerate(parser.variant_sections, start=1)
        ),
        title=parser.title,
        character=first_usable_value(extract_prefixed_value(parser.spans, "角色/对象：")),
        aspect_ratio=first_usable_value(extract_prefixed_value(parser.spans, "画幅：")),
        platform=first_usable_value(first_non_meta_span(parser.spans)),
    )


def select_prompt_text(pre_sections: list[tuple[str, str]]) -> str:
    for preferred_heading in PROMPT_HEADINGS:
        for heading, text in pre_sections:
            if preferred_heading in heading and text:
                return text
    for heading, text in pre_sections:
        if "完整规格 Prompt" not in heading and text:
            return text
    return pre_sections[0][1] if pre_sections else ""


def extract_prefixed_value(values: list[str], prefix: str) -> str:
    for value in values:
        normalized = " ".join(value.split())
        if normalized.startswith(prefix):
            return normalized[len(prefix) :].strip()
    return ""


def first_non_meta_span(spans: list[str]) -> str:
    for span in spans:
        if not any(span.startswith(prefix) for prefix in ("画幅：", "角色/对象：")):
            return span.strip()
    return ""


def first_usable_value(*values: str) -> str:
    for value in values:
        value = value.strip()
        if value and not looks_corrupt_metadata(value):
            return value
    return values[-1].strip() if values else ""


def looks_corrupt_metadata(value: str) -> bool:
    compact = re.sub(r"\s+", "", value)
    if not compact:
        return True
    question_marks = compact.count("?") + compact.count("\ufffd")
    meaningful = re.findall(r"[A-Za-z0-9\u4e00-\u9fff]", compact)
    return question_marks >= max(3, len(compact) // 2) and len(meaningful) == 0


def infer_output_naming(
    source_path: Path,
    theme: str = "",
    series: str = "",
    date: str = "",
    topic: str = "",
) -> OutputNaming:
    stem = source_path.stem.removesuffix("_embedded")
    parsed = re.fullmatch(r"(?P<date>\d{8})_(?P<series>.+?)_(?P<topic>.+)", stem)

    final_series = slugify_filename_part(series, "")
    final_date = validate_doc_date(date or (parsed.group("date") if parsed else ""))
    final_topic = slugify_filename_part(topic, "")

    if not final_series:
        if parsed:
            final_series = slugify_filename_part(parsed.group("series"), "prompt")
        else:
            final_series = infer_series_from_text(f"{stem} {theme}")

    if not final_topic:
        if parsed:
            final_topic = slugify_filename_part(parsed.group("topic"), "scene")
        else:
            final_topic = infer_topic_from_stem(stem, final_series)

    return OutputNaming(final_series, final_date, final_topic)


def infer_series_from_text(text: str) -> str:
    lowered = text.lower()
    if "mygo" in lowered:
        return "mygo"
    if "ave_mujica" in lowered or "ave mujica" in lowered:
        return "ave_mujica"
    if "crychic" in lowered:
        return "crychic"
    return slugify_filename_part(text.split("_", 1)[0], "prompt", max_length=24)


def infer_topic_from_stem(stem: str, series: str) -> str:
    topic = stem.removesuffix("_embedded")
    if topic.startswith(series + "_"):
        topic = topic[len(series) + 1 :]
    topic = re.sub(r"(?:^|_)prompt$", "", topic)
    topic = re.sub(r"_+", "_", topic).strip("_")
    return slugify_filename_part(topic, "scene")


def existing_image_paths(output_dir: Path, prefix: str, extension: str) -> list[Path]:
    # strip optional content hash suffix so legacy (unhashed) files are also matched
    base = re.sub(r"_[a-f0-9]{8}$", "", prefix)
    pattern = re.compile(rf"^{re.escape(base)}(?:_[a-f0-9]{{8}})?_(\d+)\.{re.escape(extension)}$")
    paths = set(output_dir.glob(f"{prefix}_*.{extension}"))
    if base != prefix:
        paths |= set(output_dir.glob(f"{base}_*.{extension}"))
    return sorted(p for p in paths if pattern.match(p.name))


def _clean_stale_manifest_if_complete(base_dir: Path, disk_count: int = 0) -> None:
    """Delete manifest.json if it claims status 'complete' but disk state contradicts it."""
    manifest_path = base_dir / "manifest.json"
    if not manifest_path.exists():
        return
    try:
        manifest = read_json(manifest_path)
    except Exception:
        return
    if manifest.get("status") != "complete":
        return
    if disk_count == 0 or disk_count < manifest.get("existing_count", 0):
        manifest_path.unlink(missing_ok=True)


def _next_run_dir(base_dir: Path, prefix: str, extension: str, allow_resume: bool = False) -> Path:
    """Return base_dir if no sequence images exist; otherwise find next _rN suffix.

    When *allow_resume* is True and the base directory contains a manifest with
    status ``partial`` or ``planned`` and fewer images than the target, return
    the base directory itself so the batch can be resumed in-place.
    """
    if not base_dir.exists():
        return base_dir
    existing = existing_image_paths(base_dir, prefix, extension)
    if not existing:
        _clean_stale_manifest_if_complete(base_dir)
        return base_dir
    if allow_resume:
        manifest_path = base_dir / "manifest.json"
        if manifest_path.exists():
            try:
                manifest = read_json(manifest_path)
            except Exception:
                manifest = {}
            if manifest.get("status") in ("partial", "planned") and manifest.get("existing_count", 0) < manifest.get(
                "target_count", 0
            ):
                return base_dir
    if not allow_resume:
        _clean_stale_manifest_if_complete(base_dir, len(existing))
    run = 2
    while True:
        candidate = base_dir.with_name(f"{base_dir.name}_r{run}")
        if not candidate.exists():
            return candidate
        if not existing_image_paths(candidate, prefix, extension):
            return candidate
        run += 1


def next_sequence_number(paths: list[Path], prefix: str) -> int:
    highest = 0
    pattern = re.compile(rf"^{re.escape(prefix)}_(\d+)\.[^.]+$")
    for path in paths:
        match = pattern.match(path.name)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def planned_paths(output_dir: Path, prefix: str, extension: str, start: int, count: int) -> list[str]:
    return [str(output_dir / f"{prefix}_{index:03d}.{extension}") for index in range(start, start + count)]


def resolve_prompt_source(doc: PromptDoc, prompt_source: str = "auto") -> str:
    normalized = (prompt_source or "auto").strip().lower()
    if normalized not in {"auto", "main", "variants"}:
        raise ValueError("prompt_source must be one of: auto, main, variants")
    if normalized == "auto":
        return "variants" if doc.variants else "main"
    if normalized == "variants" and not doc.variants:
        raise ValueError(f"{doc.path} does not contain variant prompt <pre> blocks")
    return normalized


def prompt_for_plan_index(doc: PromptDoc, prompt_source: str, index: int) -> tuple[int, str, str]:
    if prompt_source == "variants":
        variant_index = index % len(doc.variants)
        variant = doc.variants[variant_index]
        return variant_index + 1, variant.title, variant.prompt
    return 1, "推荐主 Prompt", doc.prompt


def prompt_digest(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


def normalize_aspect_ratio(value: str | None) -> str:
    text = (value or "").strip().replace("：", ":").lower()
    if not text or text in {"auto", "未指定", "none", "null"}:
        return ""
    match = re.fullmatch(r"(\d+)\s*[:x/]\s*(\d+)", text)
    if not match:
        return ""
    width = int(match.group(1))
    height = int(match.group(2))
    if width <= 0 or height <= 0:
        return ""
    divisor = math.gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


def largest_supported_size_for_aspect_ratio(aspect_ratio: str) -> str | None:
    normalized = normalize_aspect_ratio(aspect_ratio)
    if not normalized:
        return None
    if normalized in POPULAR_ASPECT_RATIO_SIZES:
        return POPULAR_ASPECT_RATIO_SIZES[normalized]

    width_ratio, height_ratio = (int(part) for part in normalized.split(":", 1))
    best: tuple[int, int, int] | None = None
    for height in range(16, MAX_IMAGE_SIDE + 1, 16):
        width_numerator = height * width_ratio
        if width_numerator % height_ratio != 0:
            continue
        width = width_numerator // height_ratio
        if width <= 0 or width > MAX_IMAGE_SIDE or width % 16 != 0:
            continue
        long_side = max(width, height)
        short_side = min(width, height)
        if long_side / short_side > 3:
            continue
        pixels = width * height
        if MIN_IMAGE_PIXELS <= pixels <= MAX_IMAGE_PIXELS and (best is None or pixels > best[2]):
            best = (width, height, pixels)
    if best is None:
        return None
    return f"{best[0]}x{best[1]}"


def resolve_effective_size(requested_size: str, aspect_ratio: str | None) -> tuple[str, str]:
    normalized = normalize_aspect_ratio(aspect_ratio)
    if not normalized:
        return requested_size, "requested_size"
    resolved = largest_supported_size_for_aspect_ratio(normalized)
    if not resolved:
        return requested_size, "requested_size"
    return resolved, f"aspect_ratio:{normalized}"


def build_prompt_plan(
    doc: PromptDoc,
    prompt_source: str,
    output_dir: Path,
    prefix: str,
    extension: str,
    start: int,
    count: int,
) -> list[dict]:
    plan: list[dict] = []
    for sequence in range(start, start + count):
        prompt_index, prompt_title, prompt_text = prompt_for_plan_index(doc, prompt_source, sequence - 1)
        plan.append(
            {
                "sequence": sequence,
                "path": str(output_dir / f"{prefix}_{sequence:03d}.{extension}"),
                "prompt_source": prompt_source,
                "prompt_index": prompt_index,
                "prompt_title": prompt_title,
                "prompt_text": prompt_text,
                "prompt_sha256_16": prompt_digest(prompt_text),
                "prompt_preview": " ".join(prompt_text.split())[:180],
            }
        )
    return plan


def save_generated_image(item: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if item.get("b64_json"):
        path.write_bytes(base64.b64decode(item["b64_json"]))
        return
    if item.get("url"):
        save_url(item["url"], path)
        return
    raise ValueError("image generation response item has no b64_json or url")


def error_status_code(exc: Exception) -> int | None:
    """Extract HTTP status code from an exception. Delegates to models._error_status_code."""
    return _error_status_code(exc)


def retry_after_seconds(exc: Exception) -> int:
    """Extract retry-after delay. Delegates to models._retry_after_seconds."""
    return _retry_after_seconds(exc)


def is_retryable_generation_error(exc: Exception) -> bool:
    """Check if error is retryable. Uses unified ErrorPolicy for classification."""
    return _DEFAULT_ERROR_POLICY.classify(exc) in (ErrorKind.TRANSIENT, ErrorKind.RATE_LIMITED)


def merge_existing_review(manifest_path: Path, manifest: Manifest) -> Manifest:
    review = default_review_template()
    if manifest_path.exists():
        try:
            existing = read_json(manifest_path)
        except Exception:
            existing = {}
        if isinstance(existing.get("review"), dict):
            review.update(existing["review"])
    manifest.review = review
    return manifest


def build_run_manifest(
    doc: PromptDoc,
    output_dir: Path,
    naming: OutputNaming,
    target_count: int,
    existing_paths: list[Path],
    extension: str,
    model: str,
    provider: str,
    size: str,
    quality: str,
    output_format: str,
    max_attempts: int,
    execute: bool,
    base_url: str | None = None,
    aspect_ratio: str | None = None,
    prompt_source: str = "auto",
    request_timeout_seconds: float | None = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    fallback_to_plan_on_api_error: bool = False,
) -> Manifest:
    remaining = max(0, target_count - len(existing_paths))
    start = next_sequence_number(existing_paths, naming.prefix)
    resolved_prompt_source = resolve_prompt_source(doc, prompt_source)
    effective_aspect_ratio = aspect_ratio or doc.aspect_ratio
    effective_size, size_source = resolve_effective_size(size, effective_aspect_ratio)
    prompt_plan = build_prompt_plan(
        doc,
        resolved_prompt_source,
        output_dir,
        naming.prefix,
        extension,
        start,
        remaining,
    )
    manifest = Manifest(
        prompt_doc=str(doc.path),
        theme=doc.theme,
        platform=doc.platform,
        character=doc.character,
        aspect_ratio=effective_aspect_ratio,
        output_dir=str(output_dir),
        file_prefix=naming.prefix,
        content_hash=content_hash_for_request(doc.theme, doc.character),
        target_count=target_count,
        existing_count=len(existing_paths),
        remaining_count=remaining,
        planned_paths=planned_paths(output_dir, naming.prefix, extension, start, remaining),
        prompt_source=resolved_prompt_source,
        available_variant_count=len(doc.variants),
        prompt_plan=prompt_plan,
        model=model,
        provider=provider,
        requested_size=size,
        size=effective_size,
        size_source=size_source,
        quality=quality,
        output_format=output_format,
        max_attempts=max_attempts,
        execute=execute,
        base_url=base_url,
        request_timeout_seconds=request_timeout_seconds,
        fallback_to_plan_on_api_error=fallback_to_plan_on_api_error,
        review=default_review_template(),
    )
    return manifest


def generate_until_target(
    html_path: Path,
    target_count: int = 0,
    output_dir: Path | None = None,
    series: str = "",
    date: str = "",
    topic: str = "",
    model: str = DEFAULT_MODEL,
    provider: str = DEFAULT_PROVIDER,
    size: str = DEFAULT_SIZE,
    quality: str = DEFAULT_QUALITY,
    output_format: str = DEFAULT_OUTPUT_FORMAT,
    max_attempts: int | None = None,
    execute: bool = False,
    allow_api: bool = False,
    manifest_path: Path | None = None,
    base_url: str | None = None,
    aspect_ratio: str | None = None,
    image_urls: list[str] | None = None,
    force: bool = False,
    resume: bool = False,
    prompt_source: str = "auto",
    request_timeout_seconds: float | None = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    fallback_to_plan_on_api_error: bool = False,
) -> dict:
    html_path = Path(html_path)
    if not html_path.exists():
        raise FileNotFoundError(f"Prompt doc HTML not found: {html_path}")
    if target_count < 0:
        raise ValueError("target_count must be >= 0")

    doc = parse_prompt_doc_html(html_path)
    if target_count <= 0:
        target_count = len(doc.variants) if doc.variants else 4
    resolved_prompt_source = resolve_prompt_source(doc, prompt_source)
    naming = infer_output_naming(html_path, doc.theme, series=series, date=date, topic=topic)
    extension = extension_for_format(output_format)
    base_dir = Path(output_dir) if output_dir else html_path.parents[2] / "outputs" / "prompt_docs" / naming.prefix
    base_dir = base_dir.resolve()

    if execute:
        if force:
            output_dir = base_dir
            stale = existing_image_paths(output_dir, naming.prefix, extension)
            if stale:
                for path in stale:
                    path.unlink(missing_ok=True)
                print(f"[force] cleaned {len(stale)} existing image(s) from {output_dir}")
        else:
            _allow_resume = False
            _manifest_path = base_dir / "manifest.json"
            if resume and _manifest_path.exists():
                try:
                    _existing_manifest = read_json(_manifest_path)
                except Exception:
                    _existing_manifest = {}
                if _existing_manifest.get("status") in ("partial", "planned") and _existing_manifest.get(
                    "existing_count", 0
                ) < _existing_manifest.get("target_count", 0):
                    _allow_resume = True
            output_dir = _next_run_dir(base_dir, naming.prefix, extension, allow_resume=_allow_resume)
            if output_dir != base_dir:
                print(f"[auto] using new run directory: {output_dir}")
            elif _allow_resume:
                print(f"[resume] continuing partial batch in {output_dir}")
    else:
        output_dir = base_dir

    output_dir.mkdir(parents=True, exist_ok=True)

    current = existing_image_paths(output_dir, naming.prefix, extension)
    remaining = max(0, target_count - len(current))
    if max_attempts is None:
        max_attempts = remaining + min(3, max(remaining, 1))
    manifest = build_run_manifest(
        doc,
        output_dir,
        naming,
        target_count,
        current,
        extension,
        model,
        provider,
        size,
        quality,
        output_format,
        max_attempts,
        execute,
        base_url=base_url,
        aspect_ratio=aspect_ratio,
        prompt_source=resolved_prompt_source,
        request_timeout_seconds=request_timeout_seconds,
        fallback_to_plan_on_api_error=fallback_to_plan_on_api_error,
    )
    manifest_path = manifest_path or output_dir / "manifest.json"
    manifest = merge_existing_review(manifest_path, manifest)

    if not execute or manifest.remaining_count <= 0:
        if execute and manifest.remaining_count <= 0:
            manifest.status = "skipped"
            print(
                f"[skipped] {manifest.existing_count} existing image(s) already >= target {target_count}. "
                f"Use --force to regenerate."
            )
        else:
            manifest.status = "complete" if manifest.remaining_count <= 0 else "planned"
        write_json(manifest_path, manifest.to_dict())
        result = manifest.to_dict()
        result["manifest_path"] = str(manifest_path)
        return result

    sequence = next_sequence_number(current, naming.prefix)
    saved_count = len(current)
    attempts = 0
    manifest.status = "running"
    write_json(manifest_path, manifest.to_dict())

    while saved_count < target_count and attempts < max_attempts:
        attempts += 1
        prompt_index, prompt_title, prompt_text = prompt_for_plan_index(doc, resolved_prompt_source, sequence - 1)
        try:
            response = generate_images(
                prompt_text,
                model=model,
                provider=provider,
                size=manifest.size,
                quality=quality,
                output_format=output_format,
                images_per_prompt=1,
                allow_api=allow_api,
                image=image_urls,
                aspect_ratio=None,
                base_url=base_url,
                timeout=request_timeout_seconds,
            )
        except Exception as exc:
            error_entry = {
                "attempt": attempts,
                "prompt_source": resolved_prompt_source,
                "prompt_index": prompt_index,
                "prompt_title": prompt_title,
                "status_code": error_status_code(exc),
                "error": str(exc),
            }
            manifest.errors.append(error_entry)
            manifest.status = "partial" if saved_count else "retrying"
            manifest.sync_counts(saved_count)
            write_json(manifest_path, manifest.to_dict())
            if is_retryable_generation_error(exc):
                if attempts >= max_attempts:
                    if fallback_to_plan_on_api_error:
                        manifest.status = "fallback_planned"
                        manifest.fallback_reason = (
                            "Provider API remained unavailable after retryable errors; "
                            "kept variant prompt plan for non-API/session fallback generation."
                        )
                        manifest.sync_counts(saved_count)
                        write_json(manifest_path, manifest.to_dict())
                        result = manifest.to_dict()
                        result["manifest_path"] = str(manifest_path)
                        return result
                    break
                delay = retry_after_seconds(exc)
                if delay <= 0 and error_status_code(exc) is None:
                    delay = 5
                if delay > 0:
                    print(
                        f"[retry] attempt {attempts} failed for {prompt_title}; "
                        f"waiting {delay}s before retry."
                    )
                    time.sleep(delay)
                else:
                    print(f"[retry] attempt {attempts} failed for {prompt_title}; retrying.")
                continue
            raise

        data = response.get("data") or []
        if not data:
            manifest.errors.append({"attempt": attempts, "error": "response contained no image data"})
            manifest.status = "partial" if saved_count else "retrying"
            manifest.sync_counts(saved_count)
            write_json(manifest_path, manifest.to_dict())
            continue

        for item in data:
            if saved_count >= target_count:
                break
            image_path = output_dir / f"{naming.prefix}_{sequence:03d}.{extension}"
            save_generated_image(item, image_path)
            manifest.generated.append(
                {
                    "attempt": attempts,
                    "path": str(image_path),
                    "prompt_source": resolved_prompt_source,
                    "prompt_index": prompt_index,
                    "prompt_title": prompt_title,
                    "prompt_sha256_16": prompt_digest(prompt_text),
                    "revised_prompt": item.get("revised_prompt", ""),
                    "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                }
            )
            sequence += 1
            saved_count += 1

        manifest.sync_counts(saved_count)
        manifest.status = "complete" if saved_count >= target_count else "partial"
        write_json(manifest_path, manifest.to_dict())

    if saved_count >= target_count:
        manifest.status = "complete"
    elif saved_count > 0:
        manifest.status = "partial"
    else:
        manifest.status = "failed"
    manifest.sync_counts(saved_count)
    write_json(manifest_path, manifest.to_dict())
    result = manifest.to_dict()
    result["manifest_path"] = str(manifest_path)
    return result
