#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import html
import mimetypes
import os
import re
import sys
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image_factory.io import read_json, write_jsonl
from image_factory.prompt_docs import (
    build_copy_prompt,
    build_negative_prompt,
    build_variant_prompts,
    check_doc_quality,
    DEFAULT_COLOR_PALETTE,
    extract_primary_scene_text,
    get_platform_profile,
    infer_aspect_ratio,
    infer_scene_fields,
    platform_choices,
    reference_priority_label,
    retrieve_context_snippets,
)
from image_factory.prompts import build_prompt_records


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a human-readable Markdown prompt document from a theme.")
    parser.add_argument("--theme", required=True, help="图片主题，例如：高松灯在雨天便利店门口抱着歌词本等人")
    parser.add_argument("--character", help="角色或群体；省略时会尝试从主题中推断。")
    parser.add_argument("--mood", default="")
    parser.add_argument("--shot", default="")
    parser.add_argument("--lighting", default="")
    parser.add_argument("--color-palette", default="", help="色彩和曝光策略；省略时根据主题推断。")
    parser.add_argument("--lens", default="")
    parser.add_argument("--outfit", default="")
    parser.add_argument("--notes", default="")
    parser.add_argument("--refs", default="", help="可选：指定参考图 id，多个用逗号分隔；none 表示禁用。")
    parser.add_argument("--batch-id", default="prompt_doc")
    parser.add_argument("--specs-dir", type=Path, default=ROOT / "specs")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--doc-series", default="", help="Document filename series or source title, for example mygo.")
    parser.add_argument("--doc-date", default="", help="Document filename date in YYYYMMDD format. Defaults to today.")
    parser.add_argument("--doc-topic", default="", help="Short filename topic, for example live_stream or china_travel.")
    parser.add_argument("--html-out", type=Path, help="可选：指定自包含 HTML 输出路径。默认写出同名 _embedded.html。")
    parser.add_argument("--no-html", action="store_true", help="只写 Markdown，不生成内嵌图片 HTML。")
    parser.add_argument(
        "--platform",
        choices=platform_choices(),
        default="generic",
        help="外站交付格式。generic 为通用中文说明书。",
    )
    parser.add_argument("--aspect-ratio", default="", help="画幅，例如 16:9、3:2、9:16。省略时根据主题推断。")
    parser.add_argument("--variants", type=int, default=0, help="生成多少个分镜/变体 prompt；0 表示多场景主题自动按场景数生成。")
    parser.add_argument("--max-snippets", type=int, default=6, help="从素材库召回多少条相关资料。")
    parser.add_argument(
        "--markdown-image-mode",
        choices=["relative", "absolute"],
        default="relative",
        help="Markdown 中图片链接的写法。relative 适合 Typora 项目内预览，absolute 适合文档移动但仍依赖本机路径。",
    )
    parser.add_argument(
        "--html-image-max-edge",
        type=int,
        default=960,
        help="内嵌 HTML 图片的最长边像素。0 表示不压缩，直接嵌入原图。",
    )
    parser.add_argument(
        "--html-image-quality",
        type=int,
        default=82,
        help="内嵌 HTML 图片压缩为 JPEG 时的质量，范围 1-95。",
    )
    parser.add_argument("--write-jsonl", action="store_true", help="同时写出同名 .jsonl 机器记录。")
    return parser.parse_args()


def infer_character(theme: str, specs_dir: Path) -> str:
    lowered = theme.lower()

    index_path = specs_dir / "characters" / "index.json"
    if index_path.exists():
        index = read_json(index_path)

        spec_best_name: dict[str, str] = {}
        for name, spec in index.items():
            if len(name) <= 1:
                continue
            is_cjk = any("一" <= c <= "鿿" for c in name)
            if spec not in spec_best_name:
                spec_best_name[spec] = name
            elif is_cjk and len(name) > len(spec_best_name[spec]):
                spec_best_name[spec] = name

        # Case-insensitive matching for character names in theme
        theme_lower = theme.lower()
        matches = [
            (name, index[name])
            for name in index
            if len(name) > 1 and (name in theme or name.lower() in theme_lower)
        ]
        seen: set[str] = set()
        result: list[str] = []
        for name, spec in sorted(matches, key=lambda x: theme_lower.find(x[0].lower())):
            if spec not in seen:
                seen.add(spec)
                result.append(spec_best_name[spec])

        if result:
            return "、".join(result)

    if "mygo" in lowered or "mygo!!!!!" in lowered:
        return "MyGO"
    if "ave mujica" in lowered:
        return "Ave Mujica"
    if "crychic" in lowered:
        return "CRYCHIC"

    return ""


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
        raise ValueError("--doc-date must use YYYYMMDD format")
    dt.datetime.strptime(value, "%Y%m%d")
    return value


def infer_doc_series(theme: str, character: str = "", requested: str = "") -> str:
    requested_slug = slugify_filename_part(requested, "")
    if requested_slug:
        return requested_slug

    lowered = " ".join([theme, character]).lower()
    if "ave mujica" in lowered:
        return "ave_mujica"
    if "crychic" in lowered:
        return "crychic"
    if "mygo" in lowered or "mygo!!!!!" in lowered:
        return "mygo"

    mygo_names = (
        "tomori", "anon", "raana", "rana", "soyo", "taki",
        "高松灯", "灯", "千早爱音", "爱音", "要乐奈", "乐奈",
        "长崎素世", "素世", "椎名立希", "立希",
    )
    ave_mujica_names = ("mutsumi", "sakiko", "uika", "若叶睦", "丰川祥子", "三角初华")
    if any(name in lowered for name in mygo_names):
        return "mygo"
    if any(name in lowered for name in ave_mujica_names):
        return "ave_mujica"

    character_slug = slugify_filename_part(character, "")
    if character_slug:
        return character_slug
    return "prompt"


TOPIC_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("live stream", "live_stream"),
    ("stream", "live_stream"),
    ("china travel", "china_travel"),
    ("travel", "travel"),
    ("comic con", "comic_con"),
    ("fan meet", "fan_meet"),
    ("outdoor", "outdoor"),
    ("daily", "daily"),
    ("relationship", "relationship"),
    ("identity", "identity_patch"),
    ("reference", "reference_pack"),
    ("face lock", "face_lock"),
    ("cuteness", "cuteness"),
    ("band", "band"),
    ("stage", "stage"),
    ("rain", "rain"),
    ("convenience", "convenience_store"),
    ("直播", "live_stream"),
    ("中国", "china"),
    ("旅行", "travel"),
    ("漫展", "comic_con"),
    ("见面会", "fan_meet"),
    ("户外", "outdoor"),
    ("日常", "daily"),
    ("关系", "relationship"),
    ("身份", "identity_patch"),
    ("参考", "reference_pack"),
    ("脸", "face_lock"),
    ("可爱", "cuteness"),
    ("乐队", "band"),
    ("舞台", "stage"),
    ("雨", "rain"),
    ("便利店", "convenience_store"),
)


TOPIC_STOPWORDS = {
    "a",
    "an",
    "and",
    "at",
    "for",
    "in",
    "of",
    "on",
    "prompt",
    "the",
    "with",
}


def infer_doc_topic(theme: str, character: str = "", requested: str = "") -> str:
    requested_slug = slugify_filename_part(requested, "")
    if requested_slug:
        base_topic = requested_slug
    else:
        lowered = theme.lower()
        keyword_slugs = []
        for keyword, slug in TOPIC_KEYWORDS:
            if keyword in lowered and slug not in keyword_slugs:
                keyword_slugs.append(slug)
        if keyword_slugs:
            base_topic = "_".join(keyword_slugs[:3])
        else:
            words = [
                word
                for word in re.findall(r"[A-Za-z0-9]+", theme.lower())
                if word not in TOPIC_STOPWORDS
            ]
            if words:
                base_topic = "_".join(words[:5])
            else:
                digest = hashlib.sha1(theme.encode("utf-8")).hexdigest()[:8]
                character_slug = slugify_filename_part(character, "")
                base_topic = f"{character_slug}_{digest}" if character_slug else f"scene_{digest}"

    content_hash = hashlib.sha256(
        "\n".join([theme.strip(), character.strip()]).encode("utf-8")
    ).hexdigest()[:8]
    base_topic = slugify_filename_part(base_topic, "scene", max_length=80)
    if re.search(r"_[a-f0-9]{8}$", base_topic):
        return base_topic
    base_topic = slugify_filename_part(base_topic, "scene", max_length=39)
    return f"{base_topic}_{content_hash}"


def default_output_path(
    theme: str,
    character: str = "",
    doc_series: str = "",
    doc_date: str = "",
    doc_topic: str = "",
) -> Path:
    series = infer_doc_series(theme, character, doc_series)
    date = validate_doc_date(doc_date)
    topic = infer_doc_topic(theme, character, doc_topic)
    return ROOT / "prompts" / "docs" / f"{date}_{series}_{topic}.md"


def build_scene(args: argparse.Namespace) -> dict:
    character = args.character or infer_character(args.theme, args.specs_dir)
    inferred = infer_scene_fields(args.theme)
    primary_scene = extract_primary_scene_text(args.theme)
    return {
        "id": "001",
        "character": character,
        "scene": args.theme,
        "mood": args.mood or inferred.get("mood", ""),
        "shot": args.shot or inferred.get("shot", ""),
        "lighting": args.lighting or inferred.get("lighting", ""),
        "color_palette": args.color_palette or inferred.get("color_palette", DEFAULT_COLOR_PALETTE),
        "lens": args.lens or inferred.get("lens", ""),
        "outfit": args.outfit or inferred.get("outfit", ""),
        "notes": args.notes or inferred.get("notes", ""),
        "refs": args.refs,
    }


def markdown_image_target(path: str, output_dir: Path, mode: str = "relative") -> str:
    image_path = Path(path)
    if mode == "relative":
        try:
            target = os.path.relpath(image_path, start=output_dir)
        except ValueError:
            target = str(image_path)
    else:
        target = str(image_path)

    target = target.replace("\\", "/")
    escaped = target.replace(")", "%29")
    if " " in escaped:
        return f"<{escaped}>"
    return escaped


def image_markdown(path: str, alt: str, output_dir: Path, mode: str = "relative") -> str:
    return f"![{alt}]({markdown_image_target(path, output_dir, mode)})"


def render_doc(
    record: dict,
    theme: str,
    output_path: Path,
    image_mode: str = "relative",
    platform: str = "generic",
    aspect_ratio: str = "",
    context_snippets: list | None = None,
    copy_prompt: str = "",
    negative_prompt: str = "",
    variant_prompts: list[dict] | None = None,
    quality_notes: list[str] | None = None,
) -> str:
    profile = get_platform_profile(platform)
    context_snippets = context_snippets or []
    variant_prompts = variant_prompts or []
    quality_notes = quality_notes or []
    copy_prompt = copy_prompt or record["prompt"]

    lines = [
        "# 图片生成 Prompt 文档",
        "",
        f"主题：{theme}",
        "",
        f"角色/对象：{record.get('character') or '未指定'}",
        "",
        f"外站格式：{profile.label}",
        "",
        f"画幅：{aspect_ratio or '未指定'}",
        "",
        "## 交付摘要",
        "",
        profile.description,
        "",
        profile.usage_hint,
        "",
        f"## {profile.prompt_label}",
        "",
        "```text",
        copy_prompt,
        "```",
        "",
    ]

    if negative_prompt:
        lines.extend(
            [
                f"## {profile.negative_label}",
                "",
                "```text",
                negative_prompt,
                "```",
                "",
            ]
        )

    if variant_prompts:
        lines.extend(["## 分镜/变体", ""])
        for variant in variant_prompts:
            lines.extend([f"### {variant['title']}", ""])
            if variant.get("scene"):
                lines.append(f"- 场景：{variant['scene']}")
            if variant.get("time"):
                lines.append(f"- 时间/光线：{variant['time']}")
            if variant.get("focus"):
                lines.append(f"- 画面重点：{variant['focus']}")
            if variant.get("guardrails"):
                lines.append("- 防偏航：" + "；".join(variant["guardrails"]))
            if any(variant.get(key) for key in ("scene", "time", "focus", "guardrails")):
                lines.append("")
            lines.extend(
                [
                    "```text",
                    variant["prompt"],
                    "```",
                    "",
                ]
            )

    if context_snippets:
        lines.extend(["## 命中资料", ""])
        for snippet in context_snippets:
            lines.extend(
                [
                    f"- `{snippet.source}:{snippet.line}` {snippet.text}",
                ]
            )
        lines.append("")

    lines.extend(
        [
            "## 完整规格 Prompt",
            "",
            "```text",
            record["prompt"],
            "```",
            "",
            "## 参考图（按优先级排序）",
            "",
        ]
    )

    reference_images = record.get("reference_images") or []
    if not reference_images:
        lines.extend(
            [
                "本主题没有自动匹配到参考图。可在命令中使用 `--character` 或 `--refs` 指定。",
                "",
            ]
        )
    else:
        for index, image in enumerate(reference_images, 1):
            lines.extend(
                [
                    f"### {index}. {image['id']}",
                    "",
                    image_markdown(image["path"], image["id"], output_path.parent, image_mode),
                    "",
                    f"- 工程路径：`{image.get('project_path') or image['path']}`",
                    f"- 本机路径：`{image['path']}`",
                    f"- 优先级：{reference_priority_label(image)}",
                    f"- 用途：{image.get('notes', '')}",
                    f"- 尺寸：{image.get('width', '')}x{image.get('height', '')}",
                    "",
                ]
        )

    lines.extend(
        [
            "## 质检提示",
            "",
        ]
    )
    if quality_notes:
        lines.extend(f"- {note}" for note in quality_notes)
    else:
        lines.append("- 未发现明显缺口。")
    lines.append("")

    lines.extend(
        [
            "## 使用提醒",
            "",
            "- 参考图按排序使用：二次元/原作图是身份根参考，先锁定脸型轮廓、五官气质、眉眼神态、表情习惯、身形姿态和动作节奏；发型、服装、乐器与随身物件按场景辅助调整。",
            "- 参考图用于稳定角色识别和群像关系，不要求复刻原图，也不要用乐器、包、衣服颜色替代人物本身的辨识。",
            "- Markdown 版本适合在工程目录内用 Typora 预览，图片仍是文件链接。",
            "- 同名 `_embedded.html` 是自包含版本，会把压缩后的参考图数据写入 HTML，适合单文件移动或分享。",
            "- 实际提交给外部生图模型时，最稳妥的方式仍是复制 Prompt，并把参考图作为图片附件上传。",
            "- 如果后续走文本生图，只使用 Prompt 文本；如果走图像输入或编辑流程，再读取上方参考图。",
            "",
        ]
    )
    return "\n".join(lines)


def original_image_data_uri(path: str) -> str:
    image_path = Path(path)
    mime_type = mimetypes.guess_type(str(image_path))[0] or "application/octet-stream"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def image_data_uri(path: str, max_edge: int = 960, quality: int = 82) -> str:
    if max_edge <= 0:
        return original_image_data_uri(path)

    image_path = Path(path)
    try:
        from PIL import Image, ImageOps

        with Image.open(image_path) as image:
            image = ImageOps.exif_transpose(image)
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGBA")
                background = Image.new("RGB", image.size, (255, 255, 255))
                background.paste(image, mask=image.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")

            resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
            image.thumbnail((max_edge, max_edge), resample)
            output = BytesIO()
            image.save(
                output,
                format="JPEG",
                quality=max(1, min(95, quality)),
                optimize=True,
                progressive=True,
            )
    except Exception:
        print(
            f"[warning] Cannot compress {path}, embedding original "
            f"(size={Path(path).stat().st_size} bytes, HTML may be large)",
            file=sys.stderr,
        )
        return original_image_data_uri(path)

    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def render_html(
    record: dict,
    theme: str,
    platform: str = "generic",
    aspect_ratio: str = "",
    context_snippets: list | None = None,
    copy_prompt: str = "",
    negative_prompt: str = "",
    variant_prompts: list[dict] | None = None,
    quality_notes: list[str] | None = None,
    image_max_edge: int = 960,
    image_quality: int = 82,
) -> str:
    profile = get_platform_profile(platform)
    context_snippets = context_snippets or []
    variant_prompts = variant_prompts or []
    quality_notes = quality_notes or []
    copy_prompt = copy_prompt or record["prompt"]

    reference_images = record.get("reference_images") or []
    image_cards = []
    for index, image in enumerate(reference_images, 1):
        image_cards.append(
            f"""
          <figure class="reference-card">
            <img src="{image_data_uri(image['path'], image_max_edge, image_quality)}" alt="{html.escape(image['id'])}">
            <figcaption>
              <strong>{index}. {html.escape(image['id'])}</strong>
              <em>{html.escape(reference_priority_label(image))}</em>
              <span>{html.escape(image.get('notes', ''))}</span>
              <code>{html.escape(image.get('project_path') or image['path'])}</code>
            </figcaption>
          </figure>"""
        )

    if not image_cards:
        image_section = "<p>本主题没有自动匹配到参考图。可在命令中使用 <code>--character</code> 或 <code>--refs</code> 指定。</p>"
    else:
        image_section = '<div class="reference-grid">' + "\n".join(image_cards) + "\n        </div>"

    negative_section = ""
    if negative_prompt:
        negative_section = f"""
    <h2>{html.escape(profile.negative_label)}</h2>
    <pre>{html.escape(negative_prompt)}</pre>"""

    variant_section = ""
    if variant_prompts:
        variant_cards = []
        for variant in variant_prompts:
            meta_bits = []
            if variant.get("scene"):
                meta_bits.append(f"<li><strong>场景：</strong>{html.escape(variant['scene'])}</li>")
            if variant.get("time"):
                meta_bits.append(f"<li><strong>时间/光线：</strong>{html.escape(variant['time'])}</li>")
            if variant.get("focus"):
                meta_bits.append(f"<li><strong>画面重点：</strong>{html.escape(variant['focus'])}</li>")
            if variant.get("guardrails"):
                meta_bits.append(
                    f"<li><strong>防偏航：</strong>{html.escape('；'.join(variant['guardrails']))}</li>"
                )
            meta_html = f"<ul>{''.join(meta_bits)}</ul>" if meta_bits else ""
            variant_cards.append(
                f"""
          <section class="variant">
            <h3>{html.escape(variant['title'])}</h3>
            {meta_html}
            <pre>{html.escape(variant['prompt'])}</pre>
          </section>"""
            )
        variant_section = "\n    <h2>分镜/变体</h2>\n" + "\n".join(variant_cards)

    snippet_section = ""
    if context_snippets:
        items = "\n".join(
            f"<li><code>{html.escape(snippet.source)}:{snippet.line}</code> {html.escape(snippet.text)}</li>"
            for snippet in context_snippets
        )
        snippet_section = f"""
    <h2>命中资料</h2>
    <ul>{items}</ul>"""

    quality_items = quality_notes or ["未发现明显缺口。"]
    quality_section = "\n".join(f"<li>{html.escape(note)}</li>" for note in quality_items)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(theme)} - 图片生成 Prompt 文档</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #1d2433;
      --muted: #667085;
      --line: #d8dee8;
      --paper: #ffffff;
      --soft: #f5f7fb;
      --accent: #2f6f9f;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: #eef2f7;
      color: var(--ink);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      line-height: 1.65;
    }}
    main {{
      width: min(1080px, calc(100% - 32px));
      margin: 32px auto 56px;
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 36px;
      box-shadow: 0 18px 50px rgba(20, 31, 56, 0.12);
    }}
    h1, h2 {{ line-height: 1.25; }}
    h1 {{ margin: 0 0 10px; font-size: 34px; }}
    h2 {{ margin: 36px 0 14px; padding-bottom: 8px; border-bottom: 1px solid var(--line); font-size: 24px; }}
    h3 {{ margin: 24px 0 10px; font-size: 18px; }}
    p {{ margin: 0 0 14px; }}
    .lead {{ color: var(--muted); }}
    .notice {{
      margin-top: 18px;
      padding: 12px 14px;
      border: 1px solid #b8d9ff;
      border-radius: 8px;
      background: #eef6ff;
      color: #1d4f7a;
    }}
    .reference-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 16px;
    }}
    .reference-card {{
      margin: 0;
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--soft);
    }}
    .reference-card img {{
      display: block;
      width: 100%;
      max-height: 360px;
      object-fit: contain;
      background: #10141f;
    }}
    figcaption {{
      display: grid;
      gap: 4px;
      padding: 12px;
      background: #fff;
    }}
    figcaption em {{
      color: #2f6f9f;
      font-size: 13px;
      font-style: normal;
      font-weight: 700;
    }}
    figcaption span {{ color: var(--muted); font-size: 14px; }}
    code, pre {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "PingFang SC", "Microsoft YaHei", monospace;
    }}
    code {{
      font-size: 13px;
      overflow-wrap: anywhere;
    }}
    pre {{
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      margin: 0;
      padding: 16px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #111827;
      color: #f8fafc;
      font-size: 14px;
      line-height: 1.7;
    }}
    .meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 16px;
    }}
    .meta span {{
      padding: 5px 9px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: var(--soft);
      color: var(--muted);
      font-size: 13px;
    }}
    ul {{ padding-left: 22px; }}
    li {{ margin-bottom: 8px; }}
    .variant pre {{ background: #172033; }}
    @media print {{
      body {{ background: #fff; }}
      main {{ width: 100%; margin: 0; border: 0; border-radius: 0; box-shadow: none; }}
      .reference-card img {{ max-height: 280px; }}
    }}
  </style>
</head>
<body>
  <main>
    <h1>图片生成 Prompt 文档</h1>
    <p class="lead">主题：{html.escape(theme)}</p>
    <div class="meta">
      <span>{html.escape(profile.label)}</span>
      <span>画幅：{html.escape(aspect_ratio or '未指定')}</span>
      <span>角色/对象：{html.escape(record.get('character') or '未指定')}</span>
    </div>
    <p class="notice">这是自包含 HTML：参考图已经以压缩 base64 数据嵌入文件。参考图按排序使用，二次元/原作图是身份根参考，先锁定脸型轮廓、五官气质、眉眼神态、表情习惯、身形姿态和动作节奏；发型、服装、乐器与随身物件按场景辅助调整，不要用乐器、包、衣服颜色替代人物本身的辨识；实际给外部模型生图时，仍建议复制 Prompt，并把参考图作为图片附件上传。</p>

    <h2>{html.escape(profile.prompt_label)}</h2>
    <pre>{html.escape(copy_prompt)}</pre>
    {negative_section}
    {variant_section}
    {snippet_section}

    <h2>参考图</h2>
    {image_section}

    <h2>完整规格 Prompt</h2>
    <pre>{html.escape(record['prompt'])}</pre>

    <h2>质检提示</h2>
    <ul>{quality_section}</ul>
  </main>
</body>
</html>
"""


def main() -> None:
    args = parse_args()
    scene = build_scene(args)
    if args.out:
        out = args.out
    else:
        try:
            out = default_output_path(
                args.theme,
                scene.get("character", ""),
                args.doc_series,
                args.doc_date,
                args.doc_topic,
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
    html_out = args.html_out or out.with_name(f"{out.stem}_embedded.html")
    records = build_prompt_records([scene], args.specs_dir, args.batch_id, out.with_suffix(".jsonl"))
    record = records[0]
    aspect_ratio = args.aspect_ratio or infer_aspect_ratio(args.theme, record.get("character", ""))
    profile = get_platform_profile(args.platform)
    context_query = "\n".join(str(value) for value in scene.values() if value)
    context_snippets = retrieve_context_snippets(args.specs_dir, context_query, max_snippets=args.max_snippets)
    copy_prompt = build_copy_prompt(record, args.theme, profile, aspect_ratio, context_snippets)
    negative_prompt = build_negative_prompt(
        args.specs_dir,
        context=args.theme,
        character=record.get("character", ""),
    )
    variant_prompts = build_variant_prompts(record, args.theme, aspect_ratio, count=args.variants)
    if args.variants > 0 and not variant_prompts:
        print(
            "[note] Requested {requested} variant(s) but none were generated. "
            "Storyboard variants require MyGO five-member travel keywords; "
            "single-char multi-scene variants require scene-list syntax. "
            "A plain single-scene theme will not produce variants.".format(requested=args.variants)
        )
    quality_notes = check_doc_quality(record, aspect_ratio, context_snippets, copy_prompt, profile)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        render_doc(
            record,
            args.theme,
            out,
            args.markdown_image_mode,
            platform=args.platform,
            aspect_ratio=aspect_ratio,
            context_snippets=context_snippets,
            copy_prompt=copy_prompt,
            negative_prompt=negative_prompt,
            variant_prompts=variant_prompts,
            quality_notes=quality_notes,
        ),
        encoding="utf-8",
    )

    if not args.no_html:
        html_out.parent.mkdir(parents=True, exist_ok=True)
        html_out.write_text(
            render_html(
                record,
                args.theme,
                platform=args.platform,
                aspect_ratio=aspect_ratio,
                context_snippets=context_snippets,
                copy_prompt=copy_prompt,
                negative_prompt=negative_prompt,
                variant_prompts=variant_prompts,
                quality_notes=quality_notes,
                image_max_edge=args.html_image_max_edge,
                image_quality=args.html_image_quality,
            ),
            encoding="utf-8",
        )

    if args.write_jsonl:
        write_jsonl(out.with_suffix(".jsonl"), records)

    print(f"Wrote prompt doc to {out}")
    if not args.no_html:
        print(f"Wrote embedded HTML to {html_out}")
    if record.get("reference_image_ids"):
        print(f"Reference images: {record['reference_image_ids']}")
    else:
        character = record.get("character", "")
        if character:
            print(f"Reference images: none (no matches for '{character}' in specs/references/index.json)")
        else:
            print("Reference images: none (no character resolved)")
    if context_snippets:
        print("Context snippets: " + ", ".join(f"{item.source}:{item.line}" for item in context_snippets))
    else:
        print("Context snippets: none")
    if quality_notes:
        print("Quality notes: " + " | ".join(quality_notes))
    else:
        print("Quality notes: none")


if __name__ == "__main__":
    main()
