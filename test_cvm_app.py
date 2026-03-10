"""CVM integration tests — requires running containers + model pushed."""

import requests

# uv run pytest test_cvm.py -v

MODEL_SERVICE = "http://localhost:8001"
VLLM = "http://localhost:8000"
MODEL = "openai/gpt-oss-120b"


def test_health():
    resp = requests.get(f"{MODEL_SERVICE}/health", timeout=10)
    assert resp.status_code == 200
    assert resp.json()["model_pushed"] is True


def test_ready():
    resp = requests.get(f"{MODEL_SERVICE}/ready", timeout=10)
    assert resp.status_code == 200


def test_model_hash():
    resp = requests.get(f"{MODEL_SERVICE}/model-hash", timeout=10)
    assert resp.status_code == 200
    data = resp.json()
    assert data["hash"].startswith("sha256:")
    assert data["algorithm"] == "sha256"
    assert len(data["files"]) > 0


def test_push_blocked():
    resp = requests.post(
        f"{MODEL_SERVICE}/push-model",
        files={"file": ("empty", b"")},
        timeout=10,
    )
    assert resp.status_code == 410


def test_inference():
    resp = requests.post(
        f"{VLLM}/v1/chat/completions",
        json={
            "model": MODEL,
            "messages": [{"role": "user", "content": "What is 2+2? Answer in one word."}],
            "max_tokens": 200,
        },
        timeout=120,
    )
    resp.raise_for_status()
    msg = resp.json()["choices"][0]["message"]
    assert msg.get("content") or msg.get("reasoning_content")
