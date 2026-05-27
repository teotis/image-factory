#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def iter_markdown_docs(docs_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in docs_dir.glob("*.md")
        if path.is_file() and not path.name.startswith("._")
    )


def find_delivery_issues(docs_dir: Path) -> list[str]:
    issues: list[str] = []
    for markdown_path in iter_markdown_docs(docs_dir):
        html_path = markdown_path.with_name(f"{markdown_path.stem}_embedded.html")
        if not html_path.exists():
            issues.append(f"missing embedded HTML for {markdown_path}")
            continue

        markdown = markdown_path.read_text(encoding="utf-8")
        html = html_path.read_text(encoding="utf-8")
        if "![" in markdown and 'src="data:image/' not in html:
            issues.append(f"HTML does not embed image data for {markdown_path}")

    return issues


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate prompt docs have paired embedded HTML.")
    parser.add_argument("--docs-dir", type=Path, default=ROOT / "prompts" / "docs")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    issues = find_delivery_issues(args.docs_dir)
    if issues:
        for issue in issues:
            print(f"ERROR {issue}", file=sys.stderr)
        return 1

    print(f"Validated {len(iter_markdown_docs(args.docs_dir))} prompt docs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
