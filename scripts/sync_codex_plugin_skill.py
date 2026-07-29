"""Synchronize the canonical Codex skill into the distributable plugin."""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / "skills" / "tochi-satei-kun"
DESTINATION = REPO_ROOT / "plugins" / "tochi-satei-kun" / "skills" / "tochi-satei-kun"
IGNORED_NAMES = {"__pycache__", ".DS_Store", ".pytest_cache", "output", "tests", "PR_HANDOFF.md"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}


def included_files(root: Path) -> set[Path]:
    return {
        path.relative_to(root)
        for path in root.rglob("*")
        if path.is_file()
        and not any(part in IGNORED_NAMES for part in path.relative_to(root).parts)
        and path.suffix not in IGNORED_SUFFIXES
    }


def differences() -> list[str]:
    if not SOURCE.is_dir():
        return [f"canonical skill is missing: {SOURCE}"]
    if not DESTINATION.is_dir():
        return [f"plugin skill is missing: {DESTINATION}"]

    source_files = included_files(SOURCE)
    destination_files = included_files(DESTINATION)
    messages = [f"missing from plugin: {path}" for path in sorted(source_files - destination_files)]
    messages += [f"extra in plugin: {path}" for path in sorted(destination_files - source_files)]
    messages += [
        f"content differs: {path}"
        for path in sorted(source_files & destination_files)
        if not filecmp.cmp(SOURCE / path, DESTINATION / path, shallow=False)
    ]
    return messages


def sync() -> None:
    if not SOURCE.is_dir():
        raise FileNotFoundError(f"canonical skill is missing: {SOURCE}")
    if DESTINATION.exists():
        shutil.rmtree(DESTINATION)
    shutil.copytree(
        SOURCE,
        DESTINATION,
        ignore=shutil.ignore_patterns(
            "__pycache__",
            "*.pyc",
            "*.pyo",
            ".DS_Store",
            ".pytest_cache",
            "output",
            "tests",
            "PR_HANDOFF.md",
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero when the plugin copy differs from the canonical skill",
    )
    args = parser.parse_args()

    if args.check:
        mismatches = differences()
        if mismatches:
            print("Codex plugin skill is out of sync:", file=sys.stderr)
            for mismatch in mismatches:
                print(f"- {mismatch}", file=sys.stderr)
            return 1
        print("Codex plugin skill is in sync.")
        return 0

    sync()
    print(f"Synchronized {SOURCE} -> {DESTINATION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
