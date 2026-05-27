from __future__ import annotations

from importlib import import_module
from pathlib import Path

from ..config import DEFAULT_PROVIDER
from .base import ProviderUnsupportedError


def normalize_provider(provider: str = "") -> str:
    return (provider or DEFAULT_PROVIDER).strip().lower()


def get_provider(provider: str = ""):
    normalized = normalize_provider(provider)
    if normalized in {"openai", "packyapi"}:
        return import_module("image_factory.providers.openai")
    if normalized in {"gemini", "gemini-cli"}:
        raise ProviderUnsupportedError(
            "Gemini CLI provider is not implemented yet. The provider adapter boundary is ready; "
            "add image_factory.providers.gemini_cli before using --provider gemini-cli."
        )
    raise ProviderUnsupportedError(f"Unknown provider: {provider}")


def submit_batch(
    input_path: Path,
    endpoint: str,
    completion_window: str,
    metadata: dict | None = None,
    allow_api: bool = False,
    provider: str = "",
    base_url: str | None = None,
) -> dict:
    return get_provider(provider).submit_batch(
        input_path,
        endpoint=endpoint,
        completion_window=completion_window,
        metadata=metadata,
        allow_api=allow_api,
        base_url=base_url,
    )


def retrieve_batch(
    batch_api_id: str,
    allow_api: bool = False,
    provider: str = "",
    base_url: str | None = None,
) -> dict:
    return get_provider(provider).retrieve_batch(
        batch_api_id,
        allow_api=allow_api,
        base_url=base_url,
    )


def download_file(
    file_id: str,
    destination: Path,
    allow_api: bool = False,
    provider: str = "",
    base_url: str | None = None,
) -> Path:
    return get_provider(provider).download_file(
        file_id,
        destination,
        allow_api=allow_api,
        base_url=base_url,
    )


def generate_images(
    prompt: str,
    model: str,
    size: str,
    quality: str,
    output_format: str = "png",
    images_per_prompt: int = 1,
    allow_api: bool = False,
    provider: str = "",
    image: list[str] | None = None,
    aspect_ratio: str | None = None,
    base_url: str | None = None,
    timeout: float | None = None,
    api_key: str | None = None,
) -> dict:
    return get_provider(provider).generate_images(
        prompt,
        model=model,
        size=size,
        quality=quality,
        output_format=output_format,
        images_per_prompt=images_per_prompt,
        allow_api=allow_api,
        image=image,
        aspect_ratio=aspect_ratio,
        base_url=base_url,
        timeout=timeout,
        api_key=api_key,
    )


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
    provider: str = "",
    base_url: str | None = None,
    timeout: float | None = None,
    api_key: str | None = None,
) -> dict:
    return get_provider(provider).edit_images(
        image_bytes=image_bytes,
        image_content_type=image_content_type,
        prompt=prompt,
        model=model,
        n=n,
        size=size,
        quality=quality,
        output_format=output_format,
        allow_api=allow_api,
        base_url=base_url,
        timeout=timeout,
        api_key=api_key,
    )
