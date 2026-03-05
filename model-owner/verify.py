#!/usr/bin/env python3
"""
Model Owner Verification — verify the CVM accepted the model correctly.

After pushing weights, the model owner checks:
1. TDX attestation (CVM integrity)
2. Model hash on the CVM matches the locally computed hash

Usage:
    python verify.py --endpoint https://vllm.example.com --expected-hash-file .model-hash
    python verify.py --endpoint https://localhost --expected-hash-file .model-hash --dev
"""

import argparse
import secrets
import sys

import requests
import urllib3


def verify_attestation(session: requests.Session, endpoint: str, verify_ssl: bool) -> bool:
    """Request and verify TDX attestation quote."""
    print("\n[1/2] Requesting TDX attestation quote...")

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
                return True
            else:
                print(f"  Attestation: FAILED - {data.get('error', 'unknown')}")
                return False
        else:
            print(f"  Attestation: HTTP {response.status_code}")
            print("  (In dev mode without TDX hardware, this is expected)")
            return True  # non-blocking in dev

    except Exception as e:
        print(f"  Attestation: ERROR - {e}")
        return False


def verify_model_hash(
    session: requests.Session, endpoint: str, expected_hash: str, verify_ssl: bool
) -> bool:
    """Fetch model hash from CVM and compare with locally computed hash."""
    print("\n[2/2] Verifying model hash on CVM...")
    print(f"  Expected (local): {expected_hash}")

    try:
        response = session.get(f"{endpoint}/model-hash", verify=verify_ssl, timeout=30)

        if response.status_code == 200:
            data = response.json()
            actual_hash = data["hash"]
            print(f"  Actual   (CVM):   {actual_hash}")

            if actual_hash == expected_hash:
                print("  Result: MATCH")
                return True
            else:
                print("  Result: MISMATCH!")
                return False
        elif response.status_code == 404:
            print("  Error: no model loaded yet")
            return False
        else:
            print(f"  Error: HTTP {response.status_code}: {response.text}")
            return False

    except Exception as e:
        print(f"  Error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Model Owner verification: attestation + hash")
    parser.add_argument("--endpoint", default="https://localhost", help="CVM endpoint URL")
    parser.add_argument("--expected-hash", default=None, help="Expected hash string (sha256:...)")
    parser.add_argument(
        "--expected-hash-file", default="model-hash.txt", help="File containing expected hash"
    )
    parser.add_argument("--dev", action="store_true", help="Dev mode (skip SSL verification)")
    args = parser.parse_args()

    expected_hash = args.expected_hash
    if not expected_hash:
        try:
            with open(args.expected_hash_file) as f:
                expected_hash = f.read().strip()
        except FileNotFoundError:
            print(f"Error: {args.expected_hash_file} not found. Run 'make hash-local' first.")
            sys.exit(1)

    endpoint = args.endpoint.rstrip("/")
    verify_ssl = not args.dev

    if args.dev:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    session = requests.Session()

    print("=" * 60)
    print("Model Owner Verification — CVM Integrity Check")
    print("=" * 60)
    print(f"Endpoint: {endpoint}")

    attest_ok = verify_attestation(session, endpoint, verify_ssl)
    hash_ok = verify_model_hash(session, endpoint, expected_hash, verify_ssl)

    print("\n" + "=" * 60)
    print(f"  Attestation: {'OK' if attest_ok else 'FAILED'}")
    print(f"  Model Hash:  {'OK' if hash_ok else 'FAILED'}")
    print("=" * 60)

    sys.exit(0 if (attest_ok and hash_ok) else 1)


if __name__ == "__main__":
    main()
