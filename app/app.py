"""Model Service — receives model weights via upload, exposes integrity hash."""

import hmac
import logging
import os
import tarfile
import threading
import time
from pathlib import Path


from fastapi import Depends, FastAPI, Form, HTTPException, UploadFile
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from utils import cleanup_model_dir, compute_model_hash, load_hash, model_pushed, save_hash

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logging.getLogger("uvicorn.access").addFilter(
    lambda r: not any(p in r.getMessage() for p in ("/health", "/ready"))
)
logger = logging.getLogger(__name__)

MODEL_DIR = Path(os.environ.get("MODEL_DIR", "/models/current"))
PUSH_TOKEN = os.environ.get("PUSH_TOKEN", "")

app = FastAPI(title="Model Service", version="0.1.0")


@app.middleware("http")
async def reject_push_early(request, call_next):
    if request.url.path == "/push-model" and model_pushed(MODEL_DIR):
        from starlette.responses import JSONResponse

        return JSONResponse(status_code=410, content={"detail": "Model already pushed"})
    return await call_next(request)

_lock = threading.Lock()
_cached_hash: dict | None = None

_bearer = HTTPBearer(auto_error=False)


def verify_push_token(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> None:
    if not PUSH_TOKEN:
        return
    if not creds:
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    if not hmac.compare_digest(creds.credentials, PUSH_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid push token")


@app.get("/health")
async def health():
    return {"status": "healthy", "model_pushed": model_pushed(MODEL_DIR)}


@app.get("/ready")
async def ready():
    if not model_pushed(MODEL_DIR):
        raise HTTPException(status_code=503, detail="Model not pushed yet")
    return {"status": "ready"}


@app.post("/push-model", dependencies=[Depends(verify_push_token)])
async def push_model(file: UploadFile, expected_hash: str | None = Form(None)):
    """Receive a tar archive of model weights. One-time only."""
    global _cached_hash

    logger.info("Starting push_model...")

    with _lock:
        if model_pushed(MODEL_DIR):
            raise HTTPException(status_code=410, detail="Model already pushed")

        MODEL_DIR.mkdir(parents=True, exist_ok=True)

        t0 = time.monotonic()
        logger.info("Archive received, extracting...")
        try:
            with tarfile.open(fileobj=file.file, mode="r:*") as tar:
                tar.extractall(path=MODEL_DIR, filter="data")
        except Exception as e:
            logger.error(f"Failed to extract model archive: {e}")
            cleanup_model_dir(MODEL_DIR)
            raise HTTPException(status_code=400, detail=f"Invalid archive: {e}")

        t1 = time.monotonic()
        logger.info(f"Extraction complete in {t1 - t0:.1f}s, computing hash...")
        digest, files = compute_model_hash(MODEL_DIR)
        actual = f"sha256:{digest}"
        t2 = time.monotonic()
        logger.info(f"Hash computed in {t2 - t1:.1f}s")

        if expected_hash and actual != expected_hash:
            logger.error(f"Hash mismatch: expected {expected_hash}, got {actual}")
            cleanup_model_dir(MODEL_DIR)
            raise HTTPException(
                status_code=400,
                detail=f"Hash mismatch: expected {expected_hash}, got {actual}",
            )

        _cached_hash = {"hash": actual, "algorithm": "sha256", "files": files}
        save_hash(MODEL_DIR, _cached_hash)

    logger.info(f"Push complete in {t2 - t0:.1f}s, vLLM will start loading the model")
    return {"status": "ok"}


@app.get("/model-hash")
async def model_hash():
    if not model_pushed(MODEL_DIR):
        raise HTTPException(status_code=404, detail="No model pushed yet")

    if _cached_hash:
        return _cached_hash

    cached = load_hash(MODEL_DIR)
    if cached:
        return cached

    digest, files = compute_model_hash(MODEL_DIR)
    return {"hash": f"sha256:{digest}", "algorithm": "sha256", "files": files}
