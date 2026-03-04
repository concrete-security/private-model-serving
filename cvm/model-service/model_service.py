"""Model Service — receives model weights via HTTPS upload, exposes integrity hash."""

import hashlib
import logging
import os
import tarfile
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

MODEL_DIR = Path(os.environ.get("MODEL_DIR", "/models/current"))

app = FastAPI(title="Model Service", version="0.1.0")

_model_pushed = False
_lock = threading.Lock()


IGNORE_PATTERNS = {".DS_Store", "Thumbs.db", ".gitkeep"}
IGNORE_SUFFIXES = {".tmp", ".temp", ".partial", ".swp"}
IGNORE_DIRS = {"__pycache__", ".git"}


def _is_ignored(path: Path) -> bool:
    return (
        path.name in IGNORE_PATTERNS
        or path.suffix in IGNORE_SUFFIXES
        or any(part in IGNORE_DIRS for part in path.parts)
    )


def compute_model_hash() -> tuple[str, list[str]]:
    """SHA-256 over sorted (path + content) of all files in MODEL_DIR."""
    if not MODEL_DIR.exists():
        raise FileNotFoundError(f"{MODEL_DIR} does not exist")

    files = sorted(
        str(p.relative_to(MODEL_DIR))
        for p in MODEL_DIR.rglob("*")
        if p.is_file() and not _is_ignored(p.relative_to(MODEL_DIR))
    )
    if not files:
        raise FileNotFoundError("No model files found")

    hasher = hashlib.sha256()
    for i, rel_path in enumerate(files):
        logger.info(f"Hashing: {i + 1}/{len(files)}")
        hasher.update(rel_path.encode("utf-8"))
        try:
            with open(MODEL_DIR / rel_path, "rb") as f:
                while chunk := f.read(8192):
                    hasher.update(chunk)
        except OSError as e:
            raise IOError(f"Failed to read {rel_path}: {e}")

    return hasher.hexdigest(), files


@app.get("/health")
async def health():
    return {"status": "healthy", "model_pushed": _model_pushed}


@app.post("/push-model")
async def push_model(file: UploadFile, expected_hash: str | None = None):
    """Receive a tar.gz archive of model weights. One-time only.

    Args:
        file: tar.gz archive of model weights.
        expected_hash: Optional "sha256:<hex>" to verify after extraction.
    """
    global _model_pushed

    with _lock:
        if _model_pushed:
            raise HTTPException(status_code=403, detail="Model already pushed")
        _model_pushed = True

    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    try:
        with tarfile.open(fileobj=file.file, mode="r:gz") as tar:
            tar.extractall(path=MODEL_DIR, filter="data")
    except Exception as e:
        logger.error(f"Failed to extract model archive: {e}")
        with _lock:
            _model_pushed = False
        raise HTTPException(status_code=400, detail=f"Invalid archive: {e}")

    if expected_hash:
        digest, _ = compute_model_hash()
        actual = f"sha256:{digest}"
        if actual != expected_hash:
            logger.error(f"Hash mismatch: expected {expected_hash}, got {actual}")
            with _lock:
                _model_pushed = False
            raise HTTPException(
                status_code=400,
                detail=f"Hash mismatch: expected {expected_hash}, got {actual}",
            )

    logger.info(f"Model extracted to {MODEL_DIR}")
    return {"status": "ok"}


@app.get("/model-hash")
async def model_hash():
    if not _model_pushed:
        raise HTTPException(status_code=404, detail="No model pushed yet")

    try:
        digest, files = compute_model_hash()
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {"hash": f"sha256:{digest}", "algorithm": "sha256", "files": files}
