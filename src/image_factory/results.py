from __future__ import annotations

import base64
import json
import time
from pathlib import Path

import httpx

from .config import DEFAULT_REQUEST_TIMEOUT_SECONDS
from .io import read_jsonl, write_json


def extension_for_format(output_format: str) -> str:
    normalized = output_format.lower().strip(".")
    if normalized in {"jpg", "jpeg"}:
        return "jpg"
    if normalized in {"webp", "png"}:
        return normalized
    return "png"


def save_url(url: str, path: Path) -> None:
    last_exc = None
    for attempt in range(3):
        try:
            resp = httpx.get(url, timeout=DEFAULT_REQUEST_TIMEOUT_SECONDS, follow_redirects=True)
            resp.raise_for_status()
            # 校验 Content-Type — 非图片响应不保存
            content_type = resp.headers.get("content-type", "")
            if not content_type.startswith("image/"):
                raise ValueError(f"unexpected content-type: {content_type}")
            path.write_bytes(resp.content)
            return
        except httpx.HTTPStatusError as exc:
            # 4xx 客户端错误不可重试
            if exc.response.status_code < 500:
                raise
            last_exc = exc
            if attempt < 2:
                time.sleep(2 ** attempt)
        except Exception as exc:
            last_exc = exc
            if attempt < 2:
                time.sleep(2 ** attempt)  # 1s, 2s
    raise last_exc


def save_images_from_batch_output(
    results_path: Path,
    output_dir: Path,
    output_format: str = "png",
) -> dict[str, dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir = output_dir / "_metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    extension = extension_for_format(output_format)

    updates: dict[str, dict] = {}
    for row in read_jsonl(results_path):
        custom_id = row.get("custom_id", "")
        if not custom_id:
            continue

        error = row.get("error")
        response = row.get("response") or {}
        body = response.get("body") or {}
        if error or response.get("status_code", 200) >= 400:
            updates[custom_id] = {
                "status": "failed",
                "error": json.dumps(error or body, ensure_ascii=False),
            }
            continue

        data = body.get("data") or []
        saved_paths: list[str] = []
        revised_prompts: list[str] = []
        for index, item in enumerate(data, 1):
            suffix = "" if len(data) == 1 else f"_{index:02d}"
            image_path = output_dir / f"{custom_id}{suffix}.{extension}"
            if item.get("b64_json"):
                image_path.write_bytes(base64.b64decode(item["b64_json"]))
            elif item.get("url"):
                save_url(item["url"], image_path)
            else:
                continue
            saved_paths.append(str(image_path))
            if item.get("revised_prompt"):
                revised_prompts.append(item["revised_prompt"])

        write_json(metadata_dir / f"{custom_id}.json", row)
        if saved_paths:
            updates[custom_id] = {
                "status": "downloaded",
                "output_path": ";".join(saved_paths),
                "revised_prompt": "\n---\n".join(revised_prompts),
                "error": "",
            }
        else:
            updates[custom_id] = {
                "status": "completed_no_image",
                "error": "No b64_json or url image payload found in response body.",
            }

    return updates
