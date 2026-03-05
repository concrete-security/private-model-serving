"""User verification: compare model hash + run inference."""

import requests

# uv run pytest test_user.py -v

HASH_URL = "http://localhost:8001"
VLLM_URL = "http://localhost:8000"
MODEL    = "openai/gpt-oss-120b"
EXPECTED_HASH_FILE = "model-hash.txt"


def test_model_hash():
    expected = open(EXPECTED_HASH_FILE).read().strip()
    resp = requests.get(f"{HASH_URL}/model-hash", timeout=30)
    resp.raise_for_status()
    assert resp.json()["hash"] == expected


def test_inference():
    resp = requests.post(
        f"{VLLM_URL}/v1/chat/completions",
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
