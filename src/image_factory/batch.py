from __future__ import annotations

from pathlib import Path

from .config import DEFAULT_ENDPOINT, DEFAULT_MODEL, DEFAULT_OUTPUT_FORMAT, DEFAULT_QUALITY, DEFAULT_SIZE
from .io import read_jsonl, write_jsonl


def make_request(
    record: dict,
    model: str = DEFAULT_MODEL,
    size: str = DEFAULT_SIZE,
    quality: str = DEFAULT_QUALITY,
    output_format: str = DEFAULT_OUTPUT_FORMAT,
    images_per_prompt: int = 1,
    aspect_ratio: str | None = None,
    image_urls: list[str] | None = None,
) -> dict:
    body: dict = {
        "model": model,
        "prompt": record["prompt"],
    }

    if aspect_ratio:
        body["aspect_ratio"] = aspect_ratio
    else:
        body["size"] = size

    if quality:
        body["quality"] = quality
    if output_format:
        body["output_format"] = output_format
    if images_per_prompt > 1:
        body["n"] = images_per_prompt
    if image_urls:
        body["image"] = image_urls

    return {
        "custom_id": record["custom_id"],
        "method": "POST",
        "url": DEFAULT_ENDPOINT,
        "body": body,
    }


def build_requests(
    prompt_records: list[dict],
    model: str = DEFAULT_MODEL,
    size: str = DEFAULT_SIZE,
    quality: str = DEFAULT_QUALITY,
    output_format: str = DEFAULT_OUTPUT_FORMAT,
    images_per_prompt: int = 1,
    aspect_ratio: str | None = None,
    image_urls: list[str] | None = None,
) -> list[dict]:
    return [
        make_request(
            record,
            model=model,
            size=size,
            quality=quality,
            output_format=output_format,
            images_per_prompt=images_per_prompt,
            aspect_ratio=aspect_ratio,
            image_urls=image_urls,
        )
        for record in prompt_records
    ]


def read_prompt_records(path: Path) -> list[dict]:
    rows = read_jsonl(path)
    for row in rows:
        if "custom_id" not in row or "prompt" not in row:
            raise ValueError(f"{path} contains a row without custom_id or prompt")
    return rows


def write_requests(path: Path, requests: list[dict]) -> None:
    write_jsonl(path, requests)
