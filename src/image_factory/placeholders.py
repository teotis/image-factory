"""为未达成的图像生成任务生成中文占位图。"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# 标准输出尺寸（3:2 横图）
_WIDTH, _HEIGHT = 3504, 2336

# (标题, 说明) — 中文
ERROR_CATEGORIES: dict[str, tuple[str, str]] = {
    "rate_limited":   ("请求频率超限", "429 请求过于频繁，请稍后重试"),
    "content_policy": ("内容被拦截",   "生成内容触发安全策略限制"),
    "timeout":        ("请求超时",     "API 请求超时，网络或服务不稳定"),
    "server_error":   ("服务端错误",   "API 服务端异常（5xx）"),
    "cancelled":      ("任务已取消",   "该任务被用户或系统取消"),
    "quota":          ("额度不足",     "API 账户余额不足，请充值后重试"),
    "generic":        ("生成失败",     "图像生成未能完成"),
}


# ------------------------------------------------------------------
# 错误分类
# ------------------------------------------------------------------

def classify_error(error_text: str) -> str:
    """从错误信息归类错误类型，返回 ERROR_CATEGORIES 的 key。"""
    t = error_text.lower()
    if "429" in t or "rate limit" in t:
        return "rate_limited"
    if any(kw in t for kw in ("content_policy", "content filter", "safety", "blocked")):
        return "content_policy"
    if "timeout" in t or "timed out" in t or "超时" in t:
        return "timeout"
    if any(kw in t for kw in ("502", "503", "504", "server error")):
        return "server_error"
    if "cancel" in t or "取消" in t:
        return "cancelled"
    if any(kw in t for kw in ("403", "quota", "额度", "insufficient")):
        return "quota"
    return "generic"


# ------------------------------------------------------------------
# 字体查找
# ------------------------------------------------------------------

def _find_cjk_font() -> str:
    """查找系统上的 CJK 字体。"""
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
    ]
    for p in candidates:
        if Path(p).exists():
            return p
    return ""


# ------------------------------------------------------------------
# 占位图绘制
# ------------------------------------------------------------------

def write_failure_placeholder(
    output_path: Path,
    scene_desc: str = "",
    error_text: str = "",
    *,
    width: int = _WIDTH,
    height: int = _HEIGHT,
) -> Path:
    """为失败任务生成占位图并写入 output_path，返回路径。"""
    category = classify_error(error_text)
    title, hint = ERROR_CATEGORIES[category]

    img = Image.new("RGB", (width, height), color=(30, 30, 40))
    draw = ImageDraw.Draw(img)

    # 网格背景
    grid_color = (40, 40, 55)
    for x in range(0, width, 80):
        draw.line([(x, 0), (x, height)], fill=grid_color, width=1)
    for y in range(0, height, 80):
        draw.line([(0, y), (width, y)], fill=grid_color, width=1)

    cx, cy = width // 2, height // 2
    icon_size = min(width, height) // 6

    # 破损图片框
    frame_color = (80, 80, 100)
    x1, y1 = cx - icon_size, cy - icon_size
    x2, y2 = cx + icon_size, cy + icon_size
    draw.rectangle([x1, y1, x2, y2], outline=frame_color, width=6)

    # 山峰图标
    peak_color = (60, 60, 80)
    mx, my = cx, cy + icon_size // 4
    draw.polygon(
        [(mx - icon_size // 2, my), (mx, my - icon_size // 2), (mx + icon_size // 3, my + icon_size // 6)],
        fill=peak_color,
    )
    # 太阳
    sun_r = icon_size // 6
    draw.ellipse(
        [mx + icon_size // 4 - sun_r, my - icon_size // 3 - sun_r,
         mx + icon_size // 4 + sun_r, my - icon_size // 3 + sun_r],
        fill=(70, 70, 90),
    )

    # 红色 X 标记
    x_color = (180, 60, 60)
    margin = icon_size // 3
    draw.line([(x2 - margin, y1 + margin), (x1 + margin, y2 - margin)], fill=x_color, width=8)
    draw.line([(x1 + margin, y1 + margin), (x2 - margin, y2 - margin)], fill=x_color, width=8)

    # 字体
    font_path = _find_cjk_font()
    text_color = (160, 160, 180)
    accent_color = (200, 80, 80)
    try:
        title_font = ImageFont.truetype(font_path, width // 20) if font_path else ImageFont.load_default()
        desc_font = ImageFont.truetype(font_path, width // 35) if font_path else ImageFont.load_default()
        hint_font = ImageFont.truetype(font_path, width // 45) if font_path else ImageFont.load_default()
    except Exception:
        title_font = desc_font = hint_font = ImageFont.load_default()

    # 标题（中文分类）
    bbox = draw.textbbox((0, 0), title, font=title_font)
    tw = bbox[2] - bbox[0]
    draw.text((cx - tw // 2, cy + icon_size + icon_size // 2), title, fill=accent_color, font=title_font)

    # 场景描述
    if scene_desc:
        display = scene_desc
        bbox = draw.textbbox((0, 0), display, font=desc_font)
        tw = bbox[2] - bbox[0]
        max_w = width * 3 // 4
        while tw > max_w and len(display) > 5:
            display = display[:-2] + ".."
            bbox = draw.textbbox((0, 0), display, font=desc_font)
            tw = bbox[2] - bbox[0]
        draw.text((cx - tw // 2, cy + icon_size + icon_size), display, fill=text_color, font=desc_font)

    # 错误说明
    bbox = draw.textbbox((0, 0), hint, font=hint_font)
    tw = bbox[2] - bbox[0]
    draw.text((cx - tw // 2, cy + icon_size + icon_size * 3 // 2), hint, fill=(100, 100, 120), font=hint_font)

    # 错误原文（截断显示）
    if error_text and error_text != hint:
        err_display = error_text[:200] + ("..." if len(error_text) > 200 else "")
        bbox = draw.textbbox((0, 0), err_display, font=hint_font)
        tw = bbox[2] - bbox[0]
        max_w = width * 3 // 4
        while tw > max_w and len(err_display) > 10:
            err_display = err_display[:-4] + "..."
            bbox = draw.textbbox((0, 0), err_display, font=hint_font)
            tw = bbox[2] - bbox[0]
        draw.text((cx - tw // 2, cy + icon_size + icon_size * 2), err_display, fill=(80, 80, 100), font=hint_font)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(output_path), "PNG")
    return output_path


# ------------------------------------------------------------------
# 兜底扫描补写
# ------------------------------------------------------------------

def fill_missing_placeholders(db_path: Path) -> int:
    """扫描队列中所有 failed 任务，补写缺失的占位图。返回补写数量。"""
    from image_factory.repository import _connect

    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, output_path, prompt_title, last_error FROM image_tasks WHERE status = 'failed'"
        ).fetchall()
    finally:
        conn.close()

    filled = 0
    for row in rows:
        out = Path(row["output_path"])
        if out.exists():
            continue
        try:
            write_failure_placeholder(
                out,
                scene_desc=row["prompt_title"] or "",
                error_text=row["last_error"] or "",
            )
            filled += 1
        except Exception as exc:
            print(f"[warning] 补写占位图失败 (task {row['id']}): {exc}")
    return filled
