#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image_factory.references import inspect_reference_file, load_reference_entries, validate_reference_files, validate_reference_path_ownership


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate and inspect local reference image resources.")
    parser.add_argument("--specs-dir", type=Path, default=ROOT / "specs")
    parser.add_argument("--show-sha256", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    entries = load_reference_entries(args.specs_dir)
    validate_reference_files(entries)

    ownership_issues = validate_reference_path_ownership(entries)
    if ownership_issues:
        for issue in ownership_issues:
            print(f"ERROR {issue}", file=sys.stderr)
        raise SystemExit(1)

    for entry in entries:
        info = inspect_reference_file(entry)
        size = f"{info['width']}x{info['height']}" if info["width"] and info["height"] else "unknown"
        line = f"OK {info['id']} {size} {info['bytes']} bytes {info['path']}"
        if args.show_sha256:
            line += f" sha256={info['sha256']}"
        print(line)

    print(f"Validated {len(entries)} reference images.")


if __name__ == "__main__":
    main()
