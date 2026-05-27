#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BLOCKED_NAMES = frozenset({".env", ".env.local", ".env.production", ".env.staging"})
BLOCKED_PREFIXES = (".tmp/", "outputs/_testtemp/", "outputs/_unittest_tmp/")
BLOCKED_SUFFIXES = (".pyc",)
BLOCKED_BASENAMES = frozenset({".DS_Store"})
BLOCKED_DOTUNDER_PREFIX = "._"

EXEMPT_PREFIXES = ("prompts/docs/",)
EXEMPT_SUFFIXES = ("_embedded.html",)
EXEMPT_PATH_PREFIXES = ("outputs/prompt_docs/",)

SECRET_PATTERNS = [
    (re.compile(r"(?:api[_-]?key|apikey|secret|token|password|auth)\s*[:=]\s*['\"]?\s*([A-Za-z0-9_\-+/]{20,})", re.IGNORECASE), "possible secret assigned to key/token/secret variable"),
    (re.compile(r"sk-[A-Za-z0-9_\-]{32,}"), "OpenAI-style API key"),
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{32,}"), "Anthropic API key"),
]

BINARY_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".tiff",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".mp3", ".mp4", ".avi", ".mov", ".mkv", ".wav", ".flac",
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
    ".o", ".a", ".so", ".dylib", ".dll", ".exe",
    ".db", ".sqlite", ".sqlite3",
})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check staged files for safety issues before commit.")
    parser.add_argument("--no-secrets", action="store_true", help="Skip secret scanning of staged file contents.")
    return parser.parse_args()


def staged_files() -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "-z"],
        capture_output=True, text=True, cwd=ROOT,
    )
    if result.returncode != 0:
        print("ERROR: git diff --cached failed", file=sys.stderr)
        sys.exit(1)
    raw = result.stdout.strip("\0")
    if not raw:
        return []
    return [f for f in raw.split("\0") if f]


def block_path(filepath: str) -> str | None:
    name = Path(filepath).name
    if name in BLOCKED_NAMES and name != ".env.example":
        return f"blocked sensitive file: {filepath}"

    for prefix in BLOCKED_PREFIXES:
        if filepath == prefix or filepath.startswith(prefix):
            return f"blocked temporary/non-deliverable path: {filepath}"

    for suffix in BLOCKED_SUFFIXES:
        if filepath.endswith(suffix):
            return f"blocked compiled artifact: {filepath}"

    if name.startswith(BLOCKED_DOTUNDER_PREFIX):
        return f"blocked AppleDouble/resource fork: {filepath}"

    if name in BLOCKED_BASENAMES and filepath != name:
        if not any(filepath.startswith(p) for p in EXEMPT_PATH_PREFIXES):
            return f"blocked metadata file: {filepath}"

    return None


def is_exempt(filepath: str) -> bool:
    for prefix in EXEMPT_PREFIXES:
        if filepath.startswith(prefix):
            return True
    for suffix in EXEMPT_SUFFIXES:
        if filepath.endswith(suffix):
            return True
    for prefix in EXEMPT_PATH_PREFIXES:
        if filepath.startswith(prefix):
            return True
    return False


def likely_binary(filepath: str) -> bool:
    return Path(filepath).suffix.lower() in BINARY_EXTENSIONS


def scan_secrets(filepath: str) -> list[str]:
    issues: list[str] = []
    if likely_binary(filepath):
        return issues

    full_path = ROOT / filepath
    try:
        content = full_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return issues

    for pattern, description in SECRET_PATTERNS:
        if pattern.search(content):
            issues.append(f"possible secret in {filepath}: {description}")
    return issues


def main() -> int:
    args = parse_args()
    files = staged_files()

    if not files:
        print("No staged files.")
        return 0

    issues: list[str] = []

    for filepath in files:
        if is_exempt(filepath):
            continue

        block_reason = block_path(filepath)
        if block_reason:
            issues.append(block_reason)
            continue

        if not args.no_secrets:
            issues.extend(scan_secrets(filepath))

    if issues:
        for issue in issues:
            print(f"ERROR {issue}", file=sys.stderr)
        print(f"\n{len(issues)} safety issue(s) found in staged files.", file=sys.stderr)
        print("Re-run with individual git add for files you intend to commit.", file=sys.stderr)
        return 1

    print(f"Staged safety check passed ({len(files)} file(s)).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
