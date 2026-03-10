"""Utility functions for model management: hashing, filesystem checks, cleanup."""

import hashlib
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

SENTINEL = ".push_complete"
IGNORE_PATTERNS = {".DS_Store", "Thumbs.db", ".gitkeep", SENTINEL}
IGNORE_SUFFIXES = {".tmp", ".temp", ".partial", ".swp"}
IGNORE_DIRS = {"__pycache__", ".git", ".cache"}


def is_ignored(path: Path) -> bool:
    return (
        path.name in IGNORE_PATTERNS
        or path.suffix in IGNORE_SUFFIXES
        or any(part in IGNORE_DIRS for part in path.parts)
    )


def model_pushed(model_dir: Path) -> bool:
    return (model_dir / SENTINEL).exists()


def save_hash(model_dir: Path, hash_result: dict) -> None:
    """Write hash JSON to sentinel file — marks push complete + persists hash."""
    import json

    (model_dir / SENTINEL).write_text(json.dumps(hash_result))


def load_hash(model_dir: Path) -> dict | None:
    """Read cached hash from sentinel file. Returns None if not found."""
    import json

    path = model_dir / SENTINEL
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def compute_model_hash(model_dir: Path) -> tuple[str, list[str]]:
    """SHA-256 over sorted (path + content) of all files in model_dir."""
    if not model_dir.exists():
        raise FileNotFoundError(f"{model_dir} does not exist")

    files = sorted(
        str(p.relative_to(model_dir))
        for p in model_dir.rglob("*")
        if p.is_file() and not is_ignored(p.relative_to(model_dir))
    )
    if not files:
        raise FileNotFoundError("No model files found")

    hasher = hashlib.sha256()
    for i, rel_path in enumerate(files):
        hasher.update(rel_path.encode("utf-8"))
        with open(model_dir / rel_path, "rb") as f:
            while chunk := f.read(8 * 1024 * 1024):
                hasher.update(chunk)

    return hasher.hexdigest(), files


def cleanup_model_dir(model_dir: Path) -> None:
    if model_dir.exists():
        shutil.rmtree(model_dir)
