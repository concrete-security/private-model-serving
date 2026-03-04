#!/usr/bin/env python3
"""
Example: Push model weights to a CVM.

Shows how a model owner pushes weights to the CVM inference service:
1. Connect to CVM endpoint
2. Push model via POST /push-model (provides HuggingFace URL)
3. Wait for download to complete
4. Verify /model-hash matches expected hash

Usage:
    python push_model.py --endpoint https://vllm.concrete-security.com \
                         --model-url https://huggingface.co/openai/gpt-oss-120b

    # Dev mode with self-signed certs
    python push_model.py --endpoint https://localhost --dev \
                         --model-url openai/gpt-oss-120b
"""

import argparse
import sys
import time

import requests
import urllib3


def push_model(
    session: requests.Session,
    endpoint: str,
    model_url: str,
    hf_token: str | None,
    verify_ssl: bool,
) -> bool:
    """Push model to CVM via /push-model endpoint.

    Args:
        session: Requests session.
        endpoint: CVM base URL.
        model_url: HuggingFace model URL or repo ID.
        hf_token: Optional HuggingFace token.
        verify_ssl: Whether to verify SSL certificates.

    Returns:
        True if push was accepted.
    """
    print(f"\nPushing model: {model_url}")

    payload = {"model_url": model_url}
    if hf_token:
        payload["hf_token"] = hf_token

    try:
        response = session.post(
            f"{endpoint}/push-model",
            json=payload,
            verify=verify_ssl,
            timeout=30,
        )

        if response.status_code == 200:
            data = response.json()
            print(f"  Status: {data['status']}")
            print(f"  Message: {data['message']}")
            return True
        elif response.status_code == 403:
            print("  Model already pushed (endpoint disabled)")
            return False
        elif response.status_code == 409:
            print("  Model download already in progress")
            return True
        else:
            print(f"  Error: HTTP {response.status_code}: {response.text}")
            return False

    except Exception as e:
        print(f"  Error: {e}")
        return False


def wait_for_model(
    session: requests.Session,
    endpoint: str,
    verify_ssl: bool,
    timeout: int = 7200,
    poll_interval: int = 30,
) -> bool:
    """Wait for model download to complete by polling /health.

    Args:
        session: Requests session.
        endpoint: CVM base URL.
        verify_ssl: Whether to verify SSL certificates.
        timeout: Max wait time in seconds.
        poll_interval: Seconds between polls.

    Returns:
        True if model is ready.
    """
    print(f"\nWaiting for model download (timeout: {timeout}s)...")
    start = time.time()

    while time.time() - start < timeout:
        try:
            response = session.get(
                f"{endpoint}/model-hash",
                verify=verify_ssl,
                timeout=10,
            )

            if response.status_code == 200:
                data = response.json()
                print(f"\n  Model ready!")
                print(f"  Hash: {data['hash']}")
                print(f"  Files: {len(data['files'])} files")
                return True
            elif response.status_code == 202:
                elapsed = int(time.time() - start)
                print(f"  Still downloading... ({elapsed}s elapsed)", end="\r")
            elif response.status_code == 500:
                data = response.json()
                print(f"\n  Download failed: {data.get('detail', 'unknown error')}")
                return False
        except Exception:
            pass

        time.sleep(poll_interval)

    print(f"\n  Timeout after {timeout}s")
    return False


def verify_hash(
    session: requests.Session,
    endpoint: str,
    verify_ssl: bool,
    expected_hash: str | None = None,
) -> bool:
    """Verify model hash after push.

    Args:
        session: Requests session.
        endpoint: CVM base URL.
        verify_ssl: Whether to verify SSL certificates.
        expected_hash: Expected hash to compare against.

    Returns:
        True if hash is valid (or no expected hash to compare).
    """
    print("\nVerifying model hash...")

    try:
        response = session.get(
            f"{endpoint}/model-hash",
            verify=verify_ssl,
            timeout=30,
        )

        if response.status_code == 200:
            data = response.json()
            print(f"  Hash: {data['hash']}")
            print(f"  Algorithm: {data['algorithm']}")
            print(f"  Files: {len(data['files'])}")

            if expected_hash:
                if data["hash"] == expected_hash:
                    print("  Verification: MATCH")
                    return True
                else:
                    print(f"  Verification: MISMATCH!")
                    print(f"  Expected: {expected_hash}")
                    return False
            else:
                print("  (No expected hash provided for comparison)")
                return True
        else:
            print(f"  Error: HTTP {response.status_code}")
            return False

    except Exception as e:
        print(f"  Error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Push model weights to CVM")
    parser.add_argument(
        "--endpoint",
        default="https://localhost",
        help="CVM endpoint URL (default: https://localhost)",
    )
    parser.add_argument(
        "--model-url",
        required=True,
        help="HuggingFace model URL or repo ID (e.g. openai/gpt-oss-120b)",
    )
    parser.add_argument("--hf-token", default=None, help="HuggingFace token (for private models)")
    parser.add_argument("--expected-hash", default=None, help="Expected model hash for verification")
    parser.add_argument("--dev", action="store_true", help="Dev mode (skip SSL verification)")
    parser.add_argument(
        "--timeout",
        type=int,
        default=7200,
        help="Download timeout in seconds (default: 7200 = 2h)",
    )
    parser.add_argument("--no-wait", action="store_true", help="Don't wait for download to complete")
    args = parser.parse_args()

    endpoint = args.endpoint.rstrip("/")
    verify_ssl = not args.dev

    if args.dev:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    session = requests.Session()

    print("=" * 60)
    print("CVM Model Serving - Push Model")
    print("=" * 60)
    print(f"Endpoint: {endpoint}")
    print(f"Model: {args.model_url}")

    # Step 1: Push model
    if not push_model(session, endpoint, args.model_url, args.hf_token, verify_ssl):
        sys.exit(1)

    # Step 2: Wait for download
    if not args.no_wait:
        if not wait_for_model(session, endpoint, verify_ssl, timeout=args.timeout):
            sys.exit(1)

        # Step 3: Verify hash
        if not verify_hash(session, endpoint, verify_ssl, args.expected_hash):
            sys.exit(1)
    else:
        print("\nSkipping download wait (--no-wait)")

    print("\nDone!")
    sys.exit(0)


if __name__ == "__main__":
    main()
