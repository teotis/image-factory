from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Iterable

from .characters import CHARACTER_ALIASES, GROUP_CHARACTER_NAMES, GROUP_TOKENS
from .io import read_json

CHARACTER_SPLIT_RE = re.compile(r"\s*(?:\+|/|、|,|，|&|和)\s*")
REFERENCE_SPLIT_RE = re.compile(r"\s*(?:,|，|;|；|\s+)\s*")

ROLE_KEYWORDS = {
    "近景": ["closeup", "face", "faces", "expression"],
    "特写": ["closeup", "face", "faces", "expression"],
    "表情": ["expression", "closeup", "face", "faces"],
    "脸": ["face", "faces", "closeup", "expression"],
    "全身": ["fullbody", "outfit", "lineup"],
    "立绘": ["fullbody", "outfit"],
    "站位": ["lineup", "group", "fullbody"],
    "服装": ["outfit", "fullbody"],
    "舞台服": ["outfit", "stage", "fullbody"],
    "群像": ["group", "lineup", "member_intro"],
    "五人": ["group", "lineup", "member_intro"],
    "合照": ["group", "lineup"],
    "成员": ["group", "member_intro", "lineup"],
    "舞台": ["stage", "instrument"],
    "live": ["stage", "instrument"],
    "演出": ["stage", "instrument"],
    "乐器": ["instrument", "guitar", "bass"],
    "吉他": ["instrument", "guitar"],
    "贝斯": ["instrument", "bass"],
    "鼓": ["instrument"],
    "校园": ["school"],
    "校服": ["school", "outfit"],
    "关系": ["relationship", "pair"],
    "双人": ["pair", "relationship"],
    "并肩": ["pair", "relationship"],
}

REALIZED_ROLE = "realized"
REFERENCE_TIER_IDENTITY = "identity_anchor"
REFERENCE_TIER_REALIZED = "realized_translation"
REFERENCE_TIER_CONTEXT = "context_support"
GROUP_SIGNAL_KEYWORDS = ("全员", "五人", "五位", "群像", "合照", "成员")
IDENTITY_ROLES = {
    "character",
    "character_card",
    "closeup",
    "face",
    "faces",
    "expression",
    "hair",
    "outfit",
    "fullbody",
    "body",
    "pose",
    "gesture",
}


def split_character_tokens(character: str) -> list[str]:
    return [part for part in CHARACTER_SPLIT_RE.split(character.strip()) if part]


def split_reference_ids(value: str) -> list[str]:
    return [part for part in REFERENCE_SPLIT_RE.split(value.strip()) if part]


def reference_index_path(specs_dir: Path) -> Path:
    return specs_dir / "references" / "index.json"


def load_reference_entries(specs_dir: Path) -> list[dict]:
    path = reference_index_path(specs_dir)
    if not path.exists():
        return []

    data = read_json(path)
    images = data.get("images", [])
    if not isinstance(images, list):
        raise ValueError(f"{path} must contain an images list")

    entries = []
    for raw in images:
        if not isinstance(raw, dict):
            raise ValueError(f"{path} contains a non-object reference image entry")
        entries.append(normalize_reference_entry(raw, specs_dir))
    return entries


def normalize_reference_entry(entry: dict, specs_dir: Path) -> dict:
    ref_id = str(entry.get("id", "")).strip()
    raw_path = str(entry.get("path", "")).strip()
    if not ref_id:
        raise ValueError("Reference image entry is missing id")
    if not raw_path:
        raise ValueError(f"Reference image {ref_id} is missing path")

    project_root = specs_dir.parent
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = project_root / path

    normalized = dict(entry)
    normalized["id"] = ref_id
    normalized["path"] = str(path)
    try:
        normalized["project_path"] = str(path.relative_to(project_root)).replace("\\", "/")
    except ValueError:
        normalized["project_path"] = ""
    normalized["characters"] = list(entry.get("characters") or [])
    normalized["groups"] = list(entry.get("groups") or [])
    normalized["roles"] = list(entry.get("roles") or [])
    normalized["priority"] = int(entry.get("priority") or 0)
    return normalized


def validate_reference_files(entries: Iterable[dict]) -> None:
    missing = [f"{entry['id']} -> {entry['path']}" for entry in entries if not Path(entry["path"]).exists()]
    if missing:
        raise FileNotFoundError("Missing reference image files:\n" + "\n".join(missing))


def validate_reference_path_ownership(entries: Iterable[dict]) -> list[str]:
    issues: list[str] = []
    for entry in entries:
        pp = str(entry.get("project_path", ""))
        if not pp:
            issues.append(
                f"{entry['id']}: path is outside the project ({entry['path']})"
            )
        elif not pp.startswith("assets/references/"):
            issues.append(
                f"{entry['id']}: reference path must be under assets/references/, got {pp}"
            )
    return issues


def reference_tier(entry: dict) -> str:
    roles = set(entry.get("roles") or [])
    if REALIZED_ROLE in roles:
        return REFERENCE_TIER_REALIZED
    if reference_is_original_identity(entry):
        return REFERENCE_TIER_IDENTITY
    return REFERENCE_TIER_CONTEXT


def compact_reference_entry(entry: dict) -> dict:
    keys = [
        "id",
        "source",
        "path",
        "project_path",
        "width",
        "height",
        "characters",
        "groups",
        "roles",
        "priority",
        "notes",
    ]
    compact = {key: entry[key] for key in keys if key in entry}
    compact["reference_tier"] = reference_tier(entry)
    return compact


_TIER_SORT_ORDER = {
    REFERENCE_TIER_IDENTITY: 0,
    REFERENCE_TIER_REALIZED: 1,
    REFERENCE_TIER_CONTEXT: 2,
}


def ref_paths_to_data_uris(
    paths: list[str],
    max_edge: int = 1536,
    quality: int = 92,
) -> list[str]:
    """Compress a flat list of reference image paths to data URIs.

    No tier filtering — the caller is responsible for selection and limits.
    """
    uris: list[str] = []
    for path in paths:
        p = Path(path)
        if not p.is_file():
            continue
        uris.append(_image_to_data_uri(p, max_edge, quality))
    return uris


def refs_to_compressed_data_uris(
    refs: list[dict],
    max_edge: int = 1536,
    quality: int = 92,
    max_images: int = 5,
) -> list[str]:
    """Convert reference image entries to compressed base64 data URIs.

    Sorts by tier (identity > realized > context) then priority desc,
    applies per-tier caps (realized ≤ 2, context ≤ 1, total ≤ max_images),
    and compresses each image via PIL thumbnail + JPEG encode.
    Falls back to raw base64 when PIL is unavailable or fails.
    """
    if not refs:
        return []

    # Sort: tier priority first, then numeric priority desc
    sorted_refs = sorted(
        refs,
        key=lambda r: (
            _TIER_SORT_ORDER.get(r.get("reference_tier", ""), 99),
            -(r.get("priority", 0)),
        ),
    )

    # Apply tier limits
    selected: list[dict] = []
    counts: dict[str, int] = {REFERENCE_TIER_IDENTITY: 0, REFERENCE_TIER_REALIZED: 0, REFERENCE_TIER_CONTEXT: 0}
    for ref in sorted_refs:
        if len(selected) >= max_images:
            break
        tier = ref.get("reference_tier", "")
        if tier == REFERENCE_TIER_REALIZED and counts[tier] >= 2:
            continue
        if tier == REFERENCE_TIER_CONTEXT and counts[tier] >= 1:
            continue
        selected.append(ref)
        counts[tier] = counts.get(tier, 0) + 1

    uris: list[str] = []
    for ref in selected:
        path = Path(ref["path"])
        if not path.is_file():
            continue
        uris.append(_image_to_data_uri(path, max_edge, quality))
    return uris


def _image_to_data_uri(image_path: Path, max_edge: int, quality: int) -> str:
    """Compress an image via PIL thumbnail + JPEG, return as data URI.

    Falls back to raw base64 when PIL is unavailable or fails.
    """
    try:
        from io import BytesIO

        from PIL import Image, ImageOps

        with Image.open(image_path) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGBA")
                background = Image.new("RGB", img.size, (255, 255, 255))
                background.paste(img, mask=img.getchannel("A"))
                img = background
            else:
                img = img.convert("RGB")

            resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS", 1)
            img.thumbnail((max_edge, max_edge), resample)
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=max(1, min(95, quality)), optimize=True, progressive=True)
            import base64
            return f"data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode('ascii')}"
    except Exception:
        import base64
        import mimetypes
        mime = mimetypes.guess_type(str(image_path))[0] or "application/octet-stream"
        return f"data:{mime};base64,{base64.b64encode(image_path.read_bytes()).decode('ascii')}"


def select_reference_images(
    character: str,
    specs_dir: Path,
    explicit_refs: str = "",
    max_auto_refs: int | None = None,
    context: str = "",
) -> list[dict]:
    entries = load_reference_entries(specs_dir)
    if not entries:
        return []

    by_id = {entry["id"]: entry for entry in entries}
    explicit_ids = split_reference_ids(explicit_refs)

    if any(ref_id.lower() == "none" for ref_id in explicit_ids):
        return []

    if explicit_ids and not (len(explicit_ids) == 1 and explicit_ids[0].lower() == "auto"):
        selected = []
        for ref_id in explicit_ids:
            if ref_id.lower() == "auto":
                selected.extend(select_auto_reference_images(character, entries, max_auto_refs, context=context))
                continue
            if ref_id not in by_id:
                raise ValueError(f"Unknown reference image id: {ref_id}")
            selected.append(by_id[ref_id])
        selected = dedupe_entries(selected)
        validate_reference_files(selected)
        return [compact_reference_entry(entry) for entry in selected]

    selected = select_auto_reference_images(character, entries, max_auto_refs, context=context)
    validate_reference_files(selected)
    return [compact_reference_entry(entry) for entry in selected]


def select_auto_reference_images(
    character: str,
    entries: list[dict],
    max_auto_refs: int | None = None,
    context: str = "",
) -> list[dict]:
    token_list = split_character_tokens(character)
    tokens = set(token_list)
    if not tokens:
        return []

    limit = max_auto_refs
    if limit is None:
        limit = 8 if tokens_are_group(tokens) else 6 if len(tokens) > 1 else 4

    matched = []
    for entry in entries:
        if entry.get("auto") is False:
            continue
        names = set(entry.get("characters", [])) | set(entry.get("groups", []))
        if tokens & names:
            matched.append(entry)

    group_matches = [entry for entry in matched if reference_is_group_like(entry)]
    if tokens_are_group(tokens) and context_or_tokens_want_group(context, tokens) and group_matches:
        return balance_reference_mix(
            select_group_reference_images(token_list, entries, group_matches, limit, context),
            limit,
            context,
            tokens,
        )

    matched.sort(key=lambda entry: (-reference_score(entry, context, tokens), entry["id"]))
    if len(tokens) > 1 and not tokens_are_group(tokens):
        return balance_reference_mix(
            select_balanced_character_references(token_list, matched, limit, context),
            limit,
            context,
            tokens,
        )
    return balance_reference_mix(dedupe_entries(matched), limit, context, tokens)


def balance_reference_mix(
    selected: list[dict],
    limit: int,
    context: str = "",
    character_tokens: set[str] | None = None,
) -> list[dict]:
    """Keep identity anchors first while reserving room for a realized translation when available."""
    selected = dedupe_entries(selected)
    if limit <= 0:
        return []

    identity = [entry for entry in selected if reference_tier(entry) == REFERENCE_TIER_IDENTITY]
    realized = [entry for entry in selected if reference_tier(entry) == REFERENCE_TIER_REALIZED]
    context_refs = [entry for entry in selected if reference_tier(entry) == REFERENCE_TIER_CONTEXT]

    context_refs.sort(key=lambda entry: (-reference_score(entry, context, character_tokens), entry["id"]))
    realized.sort(key=lambda entry: (-reference_score(entry, context, character_tokens), entry["id"]))

    if not identity:
        return (context_refs + realized)[:limit]

    group_scene = context_or_tokens_want_group(context, character_tokens or set())
    context_limit = 1 if group_scene and limit >= 5 else max(1, min(2, limit // 3))
    realized_limit = 1 if limit <= 5 else 2
    context_refs = context_refs[:context_limit]
    realized = realized[:realized_limit]

    reserved_count = len(context_refs) + len(realized)
    identity_limit = max(1, limit - reserved_count)
    selected_identity = identity[:identity_limit]

    # Ensure at least one face/closeup identity anchor is present for single-character tasks.
    face_roles = {"face", "faces", "closeup", "expression"}
    has_face_selected = any(set(e.get("roles", [])) & face_roles for e in selected_identity)
    if not has_face_selected:
        face_identity = [e for e in identity if set(e.get("roles", [])) & face_roles]
        if face_identity:
            selected_identity[-1] = face_identity[0]

    ordered = selected_identity + context_refs + realized
    return dedupe_entries(ordered)[:limit]


def select_group_reference_images(
    token_list: list[str],
    entries: list[dict],
    group_matches: list[dict],
    limit: int,
    context: str = "",
) -> list[dict]:
    selected: list[dict] = []
    group_tokens = {token for token in token_list if token in GROUP_CHARACTER_NAMES}

    for group_token in token_list:
        for member in GROUP_CHARACTER_NAMES.get(group_token, []):
            candidates = [
                entry
                for entry in entries
                if entry.get("auto") is not False
                and reference_matches_token(entry, member)
                and reference_is_original_identity(entry)
                and not reference_is_group_like(entry)
            ]
            face_candidates = [
                entry
                for entry in candidates
                if set(entry.get("roles", [])) & {"face", "faces", "closeup", "expression", "hair"}
            ]
            candidates = face_candidates or candidates
            candidates.sort(key=lambda entry: (-reference_score(entry, context, {member}), entry["id"]))
            for entry in candidates:
                if entry not in selected:
                    selected.append(entry)
                    break
            if len(selected) >= limit:
                return dedupe_entries(selected)[:limit]

    original_group_refs = [
        entry
        for entry in group_matches
        if reference_is_group_like(entry) and REALIZED_ROLE not in set(entry.get("roles", []))
    ]
    add_best_group_reference(selected, original_group_refs, context, preferred_roles={"faces", "closeup"})
    add_best_group_reference(selected, original_group_refs, context, preferred_roles={"fullbody", "lineup", "member_intro"})

    realized_group_refs = [
        entry
        for entry in group_matches
        if reference_is_group_like(entry) and REALIZED_ROLE in set(entry.get("roles", []))
    ]
    add_best_group_reference(selected, realized_group_refs, context, preferred_roles={"photo_style", "rehearsal", "relationship"})

    fill_candidates = original_group_refs + realized_group_refs + group_matches
    fill_candidates.sort(key=lambda entry: (-reference_score(entry, context, group_tokens), entry["id"]))
    for entry in fill_candidates:
        if entry not in selected:
            selected.append(entry)
        if len(selected) >= limit:
            break

    return dedupe_entries(selected)[:limit]


def add_best_group_reference(
    selected: list[dict],
    candidates: list[dict],
    context: str = "",
    preferred_roles: set[str] | None = None,
) -> None:
    preferred_roles = preferred_roles or set()
    ranked = [
        entry
        for entry in candidates
        if entry not in selected and (not preferred_roles or bool(set(entry.get("roles", [])) & preferred_roles))
    ]
    if not ranked:
        return
    ranked.sort(key=lambda entry: (-reference_score(entry, context), entry["id"]))
    selected.append(ranked[0])


def select_balanced_character_references(
    token_list: list[str],
    matched: list[dict],
    limit: int,
    context: str = "",
) -> list[dict]:
    selected: list[dict] = []

    for token in token_list:
        candidates = [entry for entry in matched if reference_matches_token(entry, token)]
        primary_candidates = [
            entry
            for entry in candidates
            if reference_is_original_identity(entry) and not reference_is_group_like(entry)
        ]
        fallback_candidates = [
            entry
            for entry in candidates
            if REALIZED_ROLE not in set(entry.get("roles", [])) and not reference_is_group_like(entry)
        ]
        ranked = primary_candidates or fallback_candidates or candidates
        ranked.sort(key=lambda entry: (-reference_score(entry, context, {token}), entry["id"]))

        for entry in ranked:
            if entry not in selected:
                selected.append(entry)
                break
        if len(selected) >= limit:
            return dedupe_entries(selected)[:limit]

    realized_candidates = [
        entry
        for entry in matched
        if entry not in selected and reference_tier(entry) == REFERENCE_TIER_REALIZED
    ]
    realized_candidates.sort(key=lambda entry: (-reference_score(entry, context), entry["id"]))
    if realized_candidates and len(selected) < limit:
        selected.append(realized_candidates[0])

    for entry in matched:
        if entry not in selected:
            selected.append(entry)
        if len(selected) >= limit:
            break

    return dedupe_entries(selected)[:limit]


def reference_matches_token(entry: dict, token: str) -> bool:
    names = set(entry.get("characters", [])) | set(entry.get("groups", []))
    return token in names


def reference_is_original_identity(entry: dict) -> bool:
    roles = set(entry.get("roles", []))
    return REALIZED_ROLE not in roles and bool(roles & IDENTITY_ROLES)


def explicit_context_members(context: str) -> set[str]:
    found: set[str] = set()
    lowered = context.lower()
    for names in GROUP_CHARACTER_NAMES.values():
        for name in names:
            if name in context:
                found.add(name)
    for alias, canonical in CHARACTER_ALIASES.items():
        if alias.lower() in lowered:
            found.add(canonical)
    return found


def context_has_group_signal(context: str) -> bool:
    context_lower = context.lower()
    return any(keyword in context_lower for keyword in GROUP_SIGNAL_KEYWORDS)


def reference_score(entry: dict, context: str = "", character_tokens: set[str] | None = None) -> int:
    score = int(entry.get("priority") or 0)
    context_lower = context.lower()
    roles = set(entry.get("roles", []))
    character_tokens = character_tokens or set()
    wants_group = context_or_tokens_want_group(context, character_tokens)
    explicit_members = explicit_context_members(context)

    if REALIZED_ROLE in roles:
        score += 15
    elif roles & IDENTITY_ROLES:
        score += 100

    for keyword, preferred_roles in ROLE_KEYWORDS.items():
        if keyword.lower() not in context_lower:
            continue
        score += 25 * len(roles & set(preferred_roles))

    if wants_group:
        if reference_is_group_like(entry):
            score += 80
        elif "character" in roles:
            score -= 60
    elif reference_is_group_like(entry):
        if len(character_tokens) == 1:
            score -= 50
        if len(explicit_members) >= 2:
            score -= 90

    return score


def context_or_tokens_want_group(context: str, character_tokens: set[str]) -> bool:
    explicit_members = explicit_context_members(context)
    if len(explicit_members) >= 2 and not context_has_group_signal(context):
        return False
    return tokens_are_group(character_tokens) and context_has_group_signal(context) or context_has_group_signal(context)


def tokens_are_group(tokens: set[str]) -> bool:
    return bool(tokens & GROUP_TOKENS)


def reference_is_group_like(entry: dict) -> bool:
    return bool(set(entry.get("roles", [])) & {"group", "lineup", "member_intro"})


def dedupe_entries(entries: Iterable[dict]) -> list[dict]:
    selected = []
    seen = set()
    for entry in entries:
        ref_id = entry["id"]
        if ref_id in seen:
            continue
        selected.append(entry)
        seen.add(ref_id)
    return selected


def reference_image_ids(reference_images: list[dict]) -> str:
    return ",".join(image["id"] for image in reference_images)


def inspect_reference_file(entry: dict) -> dict:
    path = Path(entry["path"])
    data = path.read_bytes()
    return {
        "id": entry["id"],
        "path": str(path),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "width": entry.get("width", ""),
        "height": entry.get("height", ""),
    }
