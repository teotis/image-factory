from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from pathlib import Path

from .characters import GROUP_CHARACTER_NAMES
from .config import REQUIRED_SCENE_COLUMNS
from .io import read_json, read_text
from .references import reference_image_ids, select_reference_images

CUSTOM_ID_RE = re.compile(r"[^a-zA-Z0-9_-]+")


def sanitize_id(value: str) -> str:
    value = value.strip().replace(" ", "_")
    value = CUSTOM_ID_RE.sub("_", value)
    return value.strip("_") or "item"


def strip_top_heading(text: str) -> str:
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("# "):
        return "\n".join(lines[1:]).strip()
    return text.strip()


def load_scenes(path: Path) -> list[dict]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = [column for column in REQUIRED_SCENE_COLUMNS if column not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path} is missing required columns: {', '.join(missing)}")
        return [dict(row) for row in reader if any((value or "").strip() for value in row.values())]


def load_character_index(specs_dir: Path) -> dict[str, str]:
    index_path = specs_dir / "characters" / "index.json"
    if not index_path.exists():
        return {}
    return read_json(index_path)


def split_character_field(character: str) -> list[str]:
    parts = re.split(r"\s*(?:\+|/|、|,|，|&|和)\s*", character.strip())
    return [part for part in parts if part]


def resolve_character_specs(character: str, specs_dir: Path) -> list[tuple[str, str]]:
    from .characters import CHARACTER_ALIASES

    index = load_character_index(specs_dir)
    # Build case-insensitive index lookup for robust matching
    index_lower = {k.lower(): v for k, v in index.items()}
    # Build case-insensitive alias lookup
    aliases_lower = {k.lower(): v for k, v in CHARACTER_ALIASES.items()}

    raw_names = [character] if character in index else split_character_field(character)
    names = []
    for name in raw_names:
        names.extend(GROUP_CHARACTER_NAMES.get(name, [name]))

    resolved: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name in names:
        # Resolve alias first (case-insensitive)
        canonical = aliases_lower.get(name.lower(), name)
        # Then lookup in index (case-insensitive)
        filename = index_lower.get(canonical.lower()) or index.get(canonical)
        if not filename:
            continue
        path = specs_dir / "characters" / filename
        path_key = str(path)
        if path_key in seen or not path.exists():
            continue
        seen.add(path_key)
        resolved.append((canonical, strip_top_heading(read_text(path))))
    return resolved


def scene_details(scene: dict) -> str:
    ordered_keys = [
        ("scene", "场景"),
        ("mood", "情绪"),
        ("shot", "镜头"),
        ("lighting", "光线"),
        ("color_palette", "色彩/曝光"),
        ("lens", "镜头语言"),
        ("outfit", "服装"),
        ("notes", "补充"),
    ]
    lines = []
    for key, label in ordered_keys:
        value = (scene.get(key) or "").strip()
        if value:
            lines.append(f"- {label}：{value}")
    return "\n".join(lines)


def build_prompt(scene: dict, specs_dir: Path) -> str:
    style_bible = strip_top_heading(read_text(specs_dir / "style_bible.md"))
    negative_rules = strip_top_heading(read_text(specs_dir / "negative_rules.md"))
    character = (scene.get("character") or "").strip()
    character_specs = resolve_character_specs(character, specs_dir)

    if character_specs:
        character_text = "\n\n".join(f"### {name}\n{text}" for name, text in character_specs)
    else:
        character_text = f"角色：{character}\n\n请保持该角色的核心识别度和性格气质。"

    return "\n\n".join(
        [
            "你正在生成一张现实化的乐队日常照片。",
            "## 项目固定风格\n" + style_bible,
            "## 角色设定\n" + character_text,
            "## 本张图片\n" + scene_details(scene),
            "画面目标：第一眼要有画面冲击、故事性或温馨平静的日常感。主体清楚，表情自然，避免空洞摆拍。",
            "## 避免事项\n" + negative_rules,
        ]
    ).strip()


def build_prompt_records(
    scenes: list[dict],
    specs_dir: Path,
    batch_id: str,
    prompt_path: Path | None = None,
) -> list[dict]:
    records: list[dict] = []
    used_ids: set[str] = set()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for index, scene in enumerate(scenes, 1):
        scene_id = (scene.get("id") or f"{index:03d}").strip()
        base_custom_id = f"{sanitize_id(batch_id)}_{sanitize_id(scene_id)}"
        custom_id = base_custom_id
        suffix = 2
        while custom_id in used_ids:
            custom_id = f"{base_custom_id}_{suffix}"
            suffix += 1
        used_ids.add(custom_id)

        prompt = build_prompt(scene, specs_dir)
        reference_context = "\n".join(
            str(value) for key, value in scene.items()
            if value and key not in ("id", "refs", "reference_refs")
        )
        reference_images = select_reference_images(
            (scene.get("character") or "").strip(),
            specs_dir,
            explicit_refs=(scene.get("refs") or scene.get("reference_refs") or "").strip(),
            context=reference_context,
        )
        records.append(
            {
                "custom_id": custom_id,
                "batch_id": batch_id,
                "scene_id": scene_id,
                "character": (scene.get("character") or "").strip(),
                "scene": (scene.get("scene") or "").strip(),
                "mood": (scene.get("mood") or "").strip(),
                "shot": (scene.get("shot") or "").strip(),
                "lighting": (scene.get("lighting") or "").strip(),
                "color_palette": (scene.get("color_palette") or "").strip(),
                "reference_images": reference_images,
                "reference_image_ids": reference_image_ids(reference_images),
                "prompt": prompt,
                "prompt_path": str(prompt_path or ""),
                "request_path": "",
                "output_path": "",
                "status": "planned",
                "openai_batch_id": "",
                "error": "",
                "revised_prompt": "",
                "created_at": now,
                "updated_at": now,
                "metadata": {key: value for key, value in scene.items() if key not in {"id"}},
            }
        )

    return records
