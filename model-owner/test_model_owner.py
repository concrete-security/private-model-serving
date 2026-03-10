"""Model Owner verification: hash comparison + auth enforcement."""

import os

import requests

# uv run pytest test_model_owner.py -v
# ENDPOINT=https://localhost VERIFY_TLS=0 uv run pytest test_model_owner.py -v

ENDPOINT = os.environ.get("PROXY_ENDPOINT", "http://localhost:8001")
VERIFY_TLS = os.environ.get("VERIFY_TLS", "1") != "0"
EXPECTED_HASH_FILE = "model-hash.txt"


def test_hash_matches_local():
    """CVM hash must match the locally computed hash."""
    expected = open(EXPECTED_HASH_FILE).read().strip()
    resp = requests.get(f"{ENDPOINT}/model-hash", timeout=30, verify=VERIFY_TLS)
    assert resp.status_code == 200
    actual = resp.json()["hash"]
    assert actual == expected, f"Hash mismatch: expected {expected}, got {actual}"


def test_push_rejected_bad_token():
    """Push with a wrong Bearer token must be rejected."""
    resp = requests.post(
        f"{ENDPOINT}/push-model",
        headers={"Authorization": "Bearer wrong-token"},
        files={"file": ("dummy.tar", b"fake")},
        data={"expected_hash": "sha256:0000"},
        timeout=30,
        verify=VERIFY_TLS,
    )
    assert resp.status_code in (401, 410), f"Expected 401 or 410, got {resp.status_code}"
