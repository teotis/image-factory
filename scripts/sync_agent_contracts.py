#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENTS_PATH = ROOT / "AGENTS.md"
CLAUDE_PATH = ROOT / "CLAUDE.md"
GEMINI_PATH = ROOT / "GEMINI.md"

GENERATED_NOTICE = "<!-- Generated from AGENTS.md. Do not edit directly. -->"


def read_agents() -> str:
    return AGENTS_PATH.read_text(encoding="utf-8").strip() + "\n"


def render_gemini() -> str:
    return """# Gemini CLI Entry

本文件是 Gemini CLI 专用入口。共享工程规则来自：

@./AGENTS.md

## Gemini CLI Notes

- 修改 `AGENTS.md` 后，使用 `/memory reload` 重新加载 Gemini CLI 上下文。
- 可用 `/memory show` 检查最终上下文是否包含共享规则。
- 不要在本文件复制共享主规则；需要调整通用规则时只改 `AGENTS.md`。
"""


def render_claude() -> str:
    return """@AGENTS.md

# Claude Code adapter

This repository uses AGENTS.md as the shared source of truth. See that file for all project rules, conventions, and validation commands.

## Claude Code Notes

- 修改共享规则后，运行 `python3 scripts/sync_agent_contracts.py` 同步 Claude Code 入口。
- 不要在本文件复制共享主规则；需要调整通用规则时只改 `AGENTS.md`。
"""


def expected_files() -> dict[Path, str]:
    return {
        CLAUDE_PATH: render_claude(),
        GEMINI_PATH: render_gemini(),
    }


def sync() -> None:
    for path, content in expected_files().items():
        path.write_text(content, encoding="utf-8")


def check() -> list[str]:
    issues = []
    if not AGENTS_PATH.exists():
        return [f"missing {AGENTS_PATH}"]
    for path, expected in expected_files().items():
        if not path.exists():
            issues.append(f"missing {path}")
            continue
        actual = path.read_text(encoding="utf-8")
        if actual != expected:
            issues.append(f"{path} is not in sync with {AGENTS_PATH}")
    return issues


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync agent entry files from AGENTS.md.")
    parser.add_argument("--check", action="store_true", help="Only check whether generated entry files are current.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.check:
        issues = check()
        if issues:
            for issue in issues:
                print(f"ERROR {issue}", file=sys.stderr)
            return 1
        print("Agent entry files are in sync.")
        return 0

    sync()
    print(
        f"Synced {CLAUDE_PATH.name} and {GEMINI_PATH.name} from {AGENTS_PATH}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
