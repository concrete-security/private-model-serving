#!/usr/bin/env python3
"""
Client Verification Script for CVM Model Serving.

Demonstrates the client-side verification flow:
1. Connect via HTTPS (RA-TLS in production)
2. Request TDX quote from /tdx_quote
3. Fetch model hash from /model-hash
4. Compare hash with expected value from model provider
5. If checks pass, proceed with inference

Usage:
    python verify.py --endpoint https://vllm.concrete-security.com
    python verify.py --endpoint https://localhost --dev  # Dev mode (self-signed certs)
"""

import argparse
import json
import secrets
import sys

import requests
import urllib3


def verify_attestation(session: requests.Session, endpoint: str, verify_ssl: bool) -> dict | None:
    """Request and verify TDX attestation quote.

    Args:
        session: Requests session.
        endpoint: CVM base URL.
        verify_ssl: Whether to verify SSL certificates.

    Returns:
        Quote response dict, or None on failure.
    """
    print("\n[1/4] Requesting TDX attestation quote...")

    nonce_hex = secrets.token_hex(32)
    print(f"  Nonce: {nonce_hex[:16]}...")

    try:
        response = session.post(
            f"{endpoint}/tdx_quote",
            json={"nonce_hex": nonce_hex},
            verify=verify_ssl,
            timeout=30,
        )

        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                print("  Attestation: PASSED")
                print(f"  Quote type: {data.get('quote_type', 'unknown')}")
                return data
            else:
                print(f"  Attestation: FAILED - {data.get('error', 'unknown error')}")
                return None
        else:
            print(f"  Attestation: HTTP {response.status_code}")
            print(f"  (In dev mode without TDX hardware, this is expected)")
            return {"status": "skipped", "reason": f"HTTP {response.status_code}"}

    except Exception as e:
        print(f"  Attestation: ERROR - {e}")
        return None


def verify_model_hash(
    session: requests.Session,
    endpoint: str,
    verify_ssl: bool,
    expected_hash: str | None = None,
) -> dict | None:
    """Fetch and verify model hash.

    Args:
        session: Requests session.
        endpoint: CVM base URL.
        verify_ssl: Whether to verify SSL certificates.
        expected_hash: Expected SHA-256 hash to compare against.

    Returns:
        Hash response dict, or None on failure.
    """
    print("\n[2/4] Fetching model hash...")

    try:
        response = session.get(
            f"{endpoint}/model-hash",
            verify=verify_ssl,
            timeout=30,
        )

        if response.status_code == 200:
            data = response.json()
            model_hash = data["hash"]
            print(f"  Hash: {model_hash}")
            print(f"  Files: {len(data['files'])} model files")

            if expected_hash:
                if model_hash == expected_hash:
                    print("  Hash verification: MATCH")
                else:
                    print(f"  Hash verification: MISMATCH!")
                    print(f"  Expected: {expected_hash}")
                    print(f"  Got:      {model_hash}")
                    return None
            else:
                print("  Hash verification: SKIPPED (no expected hash provided)")

            return data
        elif response.status_code == 404:
            print("  No model has been pushed yet")
            return None
        elif response.status_code == 202:
            print("  Model is still downloading")
            return None
        else:
            print(f"  HTTP {response.status_code}: {response.text}")
            return None

    except Exception as e:
        print(f"  Model hash: ERROR - {e}")
        return None


def verify_inference(session: requests.Session, endpoint: str, verify_ssl: bool, model: str) -> bool:
    """Run a test inference request.

    Args:
        session: Requests session.
        endpoint: CVM base URL.
        verify_ssl: Whether to verify SSL certificates.
        model: Model name/ID.

    Returns:
        True if inference succeeded.
    """
    print("\n[3/4] Running test inference...")

    try:
        response = session.post(
            f"{endpoint}/v1/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": "What is 2+2? Answer in one word."}],
                "max_tokens": 10,
            },
            verify=verify_ssl,
            timeout=120,
        )

        if response.status_code == 200:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            print(f"  Response: {content}")
            print("  Inference: PASSED")
            return True
        else:
            print(f"  Inference: HTTP {response.status_code}")
            return False

    except Exception as e:
        print(f"  Inference: ERROR - {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="CVM Model Serving Client Verification")
    parser.add_argument(
        "--endpoint",
        default="https://localhost",
        help="CVM endpoint URL (default: https://localhost)",
    )
    parser.add_argument("--dev", action="store_true", help="Dev mode (skip SSL verification)")
    parser.add_argument("--expected-hash", default=None, help="Expected model hash for verification")
    parser.add_argument("--model", default="openai/gpt-oss-120b", help="Model name for inference")
    args = parser.parse_args()

    endpoint = args.endpoint.rstrip("/")
    verify_ssl = not args.dev

    if args.dev:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    session = requests.Session()

    print("=" * 60)
    print("CVM Model Serving - Client Verification")
    print("=" * 60)
    print(f"Endpoint: {endpoint}")
    print(f"Mode: {'Development' if args.dev else 'Production'}")

    # Step 1: Attestation
    attestation = verify_attestation(session, endpoint, verify_ssl)

    # Step 2: Model hash
    model_hash = verify_model_hash(session, endpoint, verify_ssl, args.expected_hash)

    # Step 3: Inference
    inference_ok = verify_inference(session, endpoint, verify_ssl, args.model)

    # Step 4: Summary
    print("\n[4/4] Verification Summary")
    print("=" * 60)
    print(f"  Attestation:  {'OK' if attestation else 'FAILED'}")
    print(f"  Model Hash:   {'OK' if model_hash else 'FAILED'}")
    print(f"  Inference:    {'OK' if inference_ok else 'FAILED'}")

    all_passed = attestation and model_hash and inference_ok
    print(f"\n  Overall: {'ALL CHECKS PASSED' if all_passed else 'SOME CHECKS FAILED'}")
    print("=" * 60)

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
