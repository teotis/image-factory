#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


CHECKS = [
    ("tests", [sys.executable, "-m", "unittest", "discover", "-s", str(ROOT / "tests"), "-v"]),
    ("prompt-docs", [sys.executable, str(ROOT / "scripts" / "check_prompt_docs.py")]),
    ("references", [sys.executable, str(ROOT / "scripts" / "check_references.py")]),
    ("agent-contracts", [sys.executable, str(ROOT / "scripts" / "sync_agent_contracts.py"), "--check"]),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run all project verification checks.")
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop after the first failing check instead of collecting all failures.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    failures: list[tuple[str, int, str]] = []
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(SRC) if not existing_pythonpath else f"{SRC}{os.pathsep}{existing_pythonpath}"

    for label, cmd in CHECKS:
        print(f"\n--- {label} ---")
        result = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=False)
        if result.returncode != 0:
            failures.append((label, result.returncode, " ".join(cmd)))
            if args.fail_fast:
                break

    if failures:
        print(f"\n{len(failures)} check(s) failed:", file=sys.stderr)
        for label, code, cmd in failures:
            print(f"  [{label}] exited {code}: {cmd}", file=sys.stderr)
        return 1

    print(f"\nAll {len(CHECKS)} checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
