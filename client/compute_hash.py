#!/usr/bin/env python3
"""Compute model hash locally — same algorithm as the CVM model-service."""

import argparse
import hashlib
import sys
from pathlib import Path

IGNORE_PATTERNS = {".DS_Store", "Thumbs.db", ".gitkeep"}
IGNORE_SUFFIXES = {".tmp", ".temp", ".partial", ".swp"}
IGNORE_DIRS = {"__pycache__", ".git", ".cache"}


def _is_ignored(path: Path) -> bool:
    return (
        path.name in IGNORE_PATTERNS
        or path.suffix in IGNORE_SUFFIXES
        or any(part in IGNORE_DIRS for part in path.parts)
    )


def compute_model_hash(model_dir: Path) -> tuple[str, list[str]]:
    """SHA-256 over sorted (path + content) of all files in model_dir."""
    files = sorted(
        str(p.relative_to(model_dir))
        for p in model_dir.rglob("*")
        if p.is_file() and not _is_ignored(p.relative_to(model_dir))
    )
    if not files:
        print("No model files found", file=sys.stderr)
        sys.exit(1)

    hasher = hashlib.sha256()
    for i, rel_path in enumerate(files):
        print(f"Hashing: {i + 1}/{len(files)} {rel_path}")
        hasher.update(rel_path.encode("utf-8"))
        with open(model_dir / rel_path, "rb") as f:
            while chunk := f.read(8192):
                hasher.update(chunk)

    return hasher.hexdigest(), files


def main():
    p = argparse.ArgumentParser(description="Compute model hash (same as CVM model-service)")
    p.add_argument("model_dir", type=Path, help="Path to model directory")
    args = p.parse_args()

    if not args.model_dir.is_dir():
        print(f"Not a directory: {args.model_dir}", file=sys.stderr)
        sys.exit(1)

    digest, files = compute_model_hash(args.model_dir)
    print(f"\nsha256:{digest}")
    print(f"Files: {len(files)}")


if __name__ == "__main__":
    main()
