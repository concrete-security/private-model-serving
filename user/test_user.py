"""User verification: compare model hash + run inference."""

import os

import requests

# uv run pytest test_user.py -v

PROXY_ENDPOINT = os.environ.get("PROXY_ENDPOINT", "http://localhost")
VLLM_ENDPOINT = os.environ.get("VLLM_ENDPOINT", PROXY_ENDPOINT)
VERIFY_TLS = os.environ.get("VERIFY_TLS", "1") != "0"
MODEL    = "Qwen/Qwen2.5-0.5B-Instruct"
EXPECTED_HASH_FILE = "model-hash.txt"


def test_model_hash():
    expected = open(EXPECTED_HASH_FILE).read().strip()
    resp = requests.get(f"{PROXY_ENDPOINT}/model-hash", timeout=30, verify=VERIFY_TLS)
    resp.raise_for_status()
    assert resp.json()["hash"] == expected


def test_inference():
    resp = requests.post(
        f"{VLLM_ENDPOINT}/v1/chat/completions",
        json={
            "model": MODEL,
            "messages": [{"role": "user", "content": "What is 2+2? Answer in one word."}],
            "max_tokens": 200,
        },
        timeout=120,
        verify=VERIFY_TLS,
    )
    resp.raise_for_status()
    msg = resp.json()["choices"][0]["message"]
    assert msg.get("content") or msg.get("reasoning_content")
