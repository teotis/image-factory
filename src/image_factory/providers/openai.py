from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from ..config import (
    API_BASE_URL_ENV,
    API_ENABLED_ENV,
    API_KEY_ENV,
    API_TIMEOUT_ENV,
    DEFAULT_COMPLETION_WINDOW,
    DEFAULT_ENDPOINT,
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
)
from .base import ApiDisabledError


def load_env() -> None:
    env_path = Path(__file__).resolve().parents[3] / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export ") :].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'\"")
            if key:
                os.environ[key] = value

    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(override=True)


def assert_api_enabled(allow_api: bool = False) -> None:
    load_env()
    env_enabled = os.getenv(API_ENABLED_ENV, "").strip().lower() in {"1", "true", "yes", "on"}
    if not env_enabled or not allow_api:
        raise ApiDisabledError(
            "OpenAI API calls are disabled for this project. To re-enable intentionally, "
            f"set {API_ENABLED_ENV}=1 in .env and pass --allow-api to the API script."
        )


MAX_INDEXED_KEYS = 10


def _resolve_api_keys() -> list[tuple[str, str]]:
    """Read all IMAGE_FACTORY_API_KEY variants from environment.

    Returns ``[(env_name, key_value), ...]``, preferring indexed keys
    (``IMAGE_FACTORY_API_KEY_0``, ``_1``, …) followed by the bare key and
    comma-separated multi-value fallback.
    """
    keys: list[tuple[str, str]] = []

    # indexed keys
    for n in range(MAX_INDEXED_KEYS):
        env_name = f"{API_KEY_ENV}_{n}"
        val = os.getenv(env_name, "").strip()
        if val:
            keys.append((env_name, val))

    # bare single key
    env_val = os.getenv(API_KEY_ENV, "").strip()
    if env_val:
        if "," in env_val:
            for i, key in enumerate(env_val.split(",")):
                key = key.strip()
                if key:
                    keys.append((f"{API_KEY_ENV}[{i}]", key))
        else:
            names = {name for name, _ in keys}
            if API_KEY_ENV not in names:
                keys.append((API_KEY_ENV, env_val))

    # OpenAI fallback
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    if openai_key:
        names = {name for name, _ in keys}
        if "OPENAI_API_KEY" not in names:
            keys.append(("OPENAI_API_KEY", openai_key))

    return keys


def _resolve_api_key(explicit: str | None = None) -> str | None:
    if explicit:
        return explicit
    keys = _resolve_api_keys()
    if keys:
        return keys[0][1]
    return None


def _resolve_base_url(explicit: str | None = None) -> str | None:
    if explicit:
        return explicit
    env_url = os.getenv(API_BASE_URL_ENV, "").strip()
    return env_url or None


def _resolve_timeout(explicit: float | None = None) -> float | None:
    if explicit is not None:
        return explicit if explicit > 0 else None
    raw = os.getenv(API_TIMEOUT_ENV, "").strip()
    if not raw:
        return float(DEFAULT_REQUEST_TIMEOUT_SECONDS)
    try:
        value = float(raw)
    except ValueError:
        return float(DEFAULT_REQUEST_TIMEOUT_SECONDS)
    return value if value > 0 else None


def get_client(
    allow_api: bool = False,
    base_url: str | None = None,
    api_key: str | None = None,
    timeout: float | None = None,
):
    assert_api_enabled(allow_api=allow_api)
    load_env()
    from openai import OpenAI

    resolved_key = _resolve_api_key(api_key)
    resolved_url = _resolve_base_url(base_url)
    resolved_timeout = _resolve_timeout(timeout)

    client_kwargs: dict[str, Any] = {}
    if resolved_key:
        client_kwargs["api_key"] = resolved_key
    if resolved_url:
        client_kwargs["base_url"] = resolved_url
    if resolved_timeout is not None:
        client_kwargs["timeout"] = resolved_timeout

    return OpenAI(**client_kwargs)


def to_plain(value: Any) -> dict:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "to_dict_recursive"):
        return value.to_dict_recursive()
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return json.loads(json.dumps(value, default=str))


def _data_uri_to_bytes(data_uri: str) -> tuple[bytes, str]:
    """Extract raw bytes and content type from a data URI.

    Returns (bytes, content_type). Raises ValueError for non-data-URI strings.
    """
    if not data_uri.startswith("data:"):
        raise ValueError(f"Not a data URI: {data_uri[:50]}...")
    header, _, encoded = data_uri.partition(",")
    content_type = header.split(";")[0].replace("data:", "", 1)
    return base64.b64decode(encoded), content_type


def submit_batch(
    input_path: Path,
    endpoint: str = DEFAULT_ENDPOINT,
    completion_window: str = DEFAULT_COMPLETION_WINDOW,
    metadata: dict | None = None,
    allow_api: bool = False,
    base_url: str | None = None,
) -> dict:
    client = get_client(allow_api=allow_api, base_url=base_url)
    with input_path.open("rb") as handle:
        uploaded = client.files.create(file=handle, purpose="batch")

    batch = client.batches.create(
        input_file_id=uploaded.id,
        endpoint=endpoint,
        completion_window=completion_window,
        metadata=metadata or {},
    )
    result = to_plain(batch)
    result["input_file_id"] = uploaded.id
    return result


def retrieve_batch(batch_api_id: str, allow_api: bool = False, base_url: str | None = None) -> dict:
    client = get_client(allow_api=allow_api, base_url=base_url)
    return to_plain(client.batches.retrieve(batch_api_id))


def download_file(file_id: str, destination: Path, allow_api: bool = False, base_url: str | None = None) -> Path:
    client = get_client(allow_api=allow_api, base_url=base_url)
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = client.files.content(file_id)

    if hasattr(content, "write_to_file"):
        content.write_to_file(str(destination))
        return destination

    if hasattr(content, "read"):
        data = content.read()
    elif hasattr(content, "content"):
        data = content.content
    elif isinstance(content, (bytes, bytearray)):
        data = content
    else:
        data = str(content).encode("utf-8")

    destination.write_bytes(data)
    return destination


def generate_images(
    prompt: str,
    model: str,
    size: str,
    quality: str,
    output_format: str = "png",
    images_per_prompt: int = 1,
    allow_api: bool = False,
    image: list[str] | None = None,
    aspect_ratio: str | None = None,
    base_url: str | None = None,
    timeout: float | None = None,
    api_key: str | None = None,
) -> dict:
    # When reference images are present, route to images.edit() (multipart upload)
    # because /v1/images/generations does not support reference images.
    if image:
        primary_data_uri = image[0]
        try:
            image_bytes, image_content_type = _data_uri_to_bytes(primary_data_uri)
        except (ValueError, Exception) as exc:
            logger.warning("Failed to decode primary reference image (%d total): %s", len(image), exc)
        else:
            edit_size = size
            if aspect_ratio and not size:
                edit_size = "1024x1024"
                logger.info("Edit endpoint does not support aspect_ratio=%s, falling back to size=%s", aspect_ratio, edit_size)
            logger.info(
                "Routing to images.edit(): %d reference image(s), using primary (%s, %d bytes)",
                len(image), image_content_type, len(image_bytes),
            )
            return edit_images(
                image_bytes=image_bytes,
                image_content_type=image_content_type,
                prompt=prompt,
                model=model,
                n=images_per_prompt,
                size=edit_size,
                quality=quality,
                output_format=output_format,
                allow_api=allow_api,
                base_url=base_url,
                timeout=timeout,
                api_key=api_key,
            )

    # Standard text-to-image generation
    client = get_client(allow_api=allow_api, base_url=base_url, timeout=timeout, api_key=api_key)

    generate_kwargs: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "n": images_per_prompt,
    }

    if quality:
        generate_kwargs["quality"] = quality
    if output_format:
        generate_kwargs["output_format"] = output_format

    # aspect_ratio and size are mutually exclusive per DALL-E spec
    extra_body: dict[str, Any] = {}
    if aspect_ratio:
        extra_body["aspect_ratio"] = aspect_ratio
    else:
        generate_kwargs["size"] = size
    if extra_body:
        generate_kwargs["extra_body"] = extra_body

    response = client.images.generate(**generate_kwargs)
    return to_plain(response)


def edit_images(
    image_bytes: bytes,
    image_content_type: str,
    prompt: str,
    model: str = "gpt-image-2",
    n: int = 1,
    size: str = "1024x1024",
    quality: str = "",
    output_format: str = "png",
    allow_api: bool = False,
    base_url: str | None = None,
    timeout: float | None = None,
    api_key: str | None = None,
) -> dict:
    client = get_client(allow_api=allow_api, base_url=base_url, timeout=timeout, api_key=api_key)

    kwargs: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "n": n,
        "image": ("reference.png", image_bytes, image_content_type),
    }
    if size:
        kwargs["size"] = size
    if quality:
        kwargs["quality"] = quality
    if output_format:
        kwargs["output_format"] = output_format

    response = client.images.edit(**kwargs)
    return to_plain(response)
