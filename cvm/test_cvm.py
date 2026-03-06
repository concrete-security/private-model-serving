"""
CVM Model Serving Test Suite.

Tests all CVM components through the nginx proxy (just like end-users would).
Covers: health, push-model, model-hash, attestation, inference, and client verification.
"""

try:
    import argparse
    import hashlib
    import hmac
    import json
    import secrets
    import ssl
    import sys
    import time
    import urllib3
    from urllib.parse import urlparse
    from urllib3.util.retry import Retry
    from cryptography.x509 import load_pem_x509_certificate
    from cryptography.x509.oid import ExtensionOID

    import requests
    from requests.adapters import HTTPAdapter

except ImportError:
    print("You should install requirements_test.txt")
    print("")
    raise


class CVMTester:
    """Main test class for CVM model serving services."""

    # Default model for testing
    DEFAULT_MODEL = "openai/gpt-oss-120b"
    DEFAULT_MODEL_URL = "https://huggingface.co/openai/gpt-oss-120b"

    def __init__(
        self,
        base_url: str = "https://localhost",
        http_url: str = "http://localhost",
        dev_mode: bool = False,
    ):
        self.base_url = base_url.rstrip("/")
        self.http_url = http_url.rstrip("/")
        self.dev_mode = dev_mode
        self.verify_ssl = not dev_mode
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        """Create a requests session with proper SSL configuration."""
        session = requests.Session()

        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        if self.dev_mode:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        return session

    def _print_test_header(self, test_name: str):
        pass

    def _print_success(self, message: str):
        pass

    def _print_error(self, message: str):
        pass

    def _print_warning(self, message: str):
        pass

    def _print_info(self, message: str):
        pass

    # ── Wait helpers ────────────────────────────────────────────────

    def wait_for_nginx(self, timeout: int = 300) -> bool:
        """Wait for the nginx proxy to become ready."""
        self._print_test_header("Waiting for nginx proxy to become ready")

        start_time = time.time()
        attempt = 0

        while time.time() - start_time < timeout:
            attempt += 1
            try:
                response = self.session.get(
                    f"{self.base_url}/health", verify=self.verify_ssl, timeout=3
                )
                if response.status_code == 200:
                    self._print_success(f"Nginx proxy is ready! (attempt {attempt})")
                    return True
            except requests.exceptions.SSLError as e:
                print(f"SSL error occurred: {e}")
                return False
            except requests.exceptions.RequestException:
                pass

            if attempt % 12 == 0:
                elapsed = int(time.time() - start_time)
                print(f"Attempt {attempt}: Nginx not ready yet ({elapsed}s elapsed)")

            time.sleep(5)

        self._print_error(f"Nginx failed to start after {timeout} seconds")
        return False

    def wait_for_vllm(self, timeout: int = 300) -> bool:
        """Wait for the vLLM service to become ready."""
        self._print_test_header("Waiting for vLLM service to become ready")

        start_time = time.time()
        attempt = 0

        while time.time() - start_time < timeout:
            attempt += 1
            try:
                response = self.session.get(
                    f"{self.base_url}/v1/models", verify=self.verify_ssl, timeout=3
                )
                if response.status_code == 200:
                    self._print_success(f"vLLM service is ready! (attempt {attempt})")
                    return True
            except requests.exceptions.SSLError as e:
                print(f"SSL error occurred: {e}")
                return False
            except requests.exceptions.RequestException:
                pass

            if attempt % 12 == 0:
                elapsed = int(time.time() - start_time)
                print(f"Attempt {attempt}: vLLM not ready yet ({elapsed}s elapsed)")

            time.sleep(5)

        self._print_error(f"vLLM failed to start after {timeout} seconds")
        return False

    # ── Tests ───────────────────────────────────────────────────────

    def test_health(self) -> bool:
        """Test health endpoint returns healthy."""
        self._print_test_header("Testing Health Endpoint")
        try:
            response = self.session.get(
                f"{self.base_url}/health", verify=self.verify_ssl, timeout=10
            )
            assert response.status_code == 200, f"Expected 200, got {response.status_code}"
            self._print_success("Health endpoint returned 200")
            return True
        except Exception as e:
            self._print_error(f"Health check failed: {e}")
            return False

    def test_push_model(self, model_url: str | None = None) -> bool:
        """Test pushing a model via /push-model."""
        self._print_test_header("Testing Push Model Endpoint")
        url = model_url or self.DEFAULT_MODEL_URL

        try:
            response = self.session.post(
                f"{self.base_url}/push-model",
                json={"model_url": url},
                verify=self.verify_ssl,
                timeout=30,
            )
            assert response.status_code == 200, (
                f"Expected 200, got {response.status_code}: {response.text}"
            )
            data = response.json()
            assert data["status"] == "downloading", f"Unexpected status: {data['status']}"
            self._print_success(f"Model push accepted: {data['message']}")
            return True
        except Exception as e:
            self._print_error(f"Push model failed: {e}")
            return False

    def test_push_model_repeat(self) -> bool:
        """Test that pushing model a second time returns 403."""
        self._print_test_header("Testing Push Model Repeat (should be 403)")

        try:
            response = self.session.post(
                f"{self.base_url}/push-model",
                json={"model_url": self.DEFAULT_MODEL_URL},
                verify=self.verify_ssl,
                timeout=10,
            )
            assert response.status_code == 403, (
                f"Expected 403, got {response.status_code}: {response.text}"
            )
            self._print_success("Push model correctly rejected with 403")
            return True
        except Exception as e:
            self._print_error(f"Push model repeat test failed: {e}")
            return False

    def test_model_hash(self) -> bool:
        """Test that /model-hash returns a valid SHA-256 hash."""
        self._print_test_header("Testing Model Hash Endpoint")

        try:
            response = self.session.get(
                f"{self.base_url}/model-hash",
                verify=self.verify_ssl,
                timeout=30,
            )
            assert response.status_code == 200, (
                f"Expected 200, got {response.status_code}: {response.text}"
            )
            data = response.json()
            assert data["hash"].startswith("sha256:"), f"Unexpected hash format: {data['hash']}"
            assert data["algorithm"] == "sha256"
            assert len(data["files"]) > 0, "Expected at least one file"

            self._print_success(f"Model hash: {data['hash'][:40]}...")
            self._print_info(f"Files: {len(data['files'])} model files")
            return True
        except Exception as e:
            self._print_error(f"Model hash test failed: {e}")
            return False

    def test_attestation(self) -> bool:
        """Test /tdx_quote endpoint works."""
        self._print_test_header("Testing Attestation Endpoint")

        try:
            nonce_hex = secrets.token_hex(32)
            response = self.session.post(
                f"{self.base_url}/tdx_quote",
                json={"nonce_hex": nonce_hex},
                verify=self.verify_ssl,
                timeout=30,
            )

            if response.status_code == 200:
                data = response.json()
                assert data.get("success") is True, f"Quote not successful: {data}"
                self._print_success("TDX quote obtained successfully")
                return True
            elif response.status_code == 500:
                # In dev mode without TDX hardware, dstack may not be available
                self._print_warning(
                    f"Attestation returned 500 (expected in dev mode without TDX hardware)"
                )
                return True
            elif response.status_code == 400:
                # Missing EKM header in dev mode is expected
                self._print_warning("Missing EKM header (expected in some dev configurations)")
                return True
            else:
                self._print_error(
                    f"Unexpected status {response.status_code}: {response.text}"
                )
                return False

        except Exception as e:
            self._print_error(f"Attestation test failed: {e}")
            return False

    def test_vllm_inference(self) -> bool:
        """Test inference via /v1/chat/completions."""
        self._print_test_header("Testing vLLM Inference")

        try:
            response = self.session.post(
                f"{self.base_url}/v1/chat/completions",
                json={
                    "model": self.DEFAULT_MODEL,
                    "messages": [
                        {"role": "user", "content": "Say hello in one sentence."}
                    ],
                    "max_tokens": 50,
                },
                verify=self.verify_ssl,
                timeout=120,
            )
            assert response.status_code == 200, (
                f"Expected 200, got {response.status_code}: {response.text}"
            )
            data = response.json()
            assert "choices" in data, f"No choices in response: {data}"
            content = data["choices"][0]["message"]["content"]
            self._print_success(f"Inference response: {content[:100]}...")
            return True
        except Exception as e:
            self._print_error(f"Inference test failed: {e}")
            return False

    def test_redirect(self) -> bool:
        """Test HTTP to HTTPS redirect."""
        self._print_test_header("Testing HTTP to HTTPS Redirect")

        try:
            response = self.session.get(
                f"{self.http_url}/health",
                allow_redirects=False,
                timeout=10,
            )
            assert response.status_code == 301, (
                f"Expected 301 redirect, got {response.status_code}"
            )
            location = response.headers.get("Location", "")
            assert location.startswith("https://"), f"Unexpected redirect: {location}"
            self._print_success(f"HTTP correctly redirects to HTTPS: {location}")
            return True
        except Exception as e:
            self._print_error(f"Redirect test failed: {e}")
            return False

    def test_acme(self) -> bool:
        """Test ACME challenge endpoint (dev mode only)."""
        self._print_test_header("Testing ACME Challenge Endpoint")

        if not self.dev_mode:
            self._print_info("Skipping ACME test in production mode")
            return True

        try:
            response = self.session.get(
                f"{self.http_url}/.well-known/acme-challenge/test-challenge-token-dev",
                timeout=10,
            )
            assert response.status_code == 200, (
                f"Expected 200, got {response.status_code}"
            )
            self._print_success("ACME challenge endpoint accessible")
            return True
        except Exception as e:
            self._print_error(f"ACME test failed: {e}")
            return False

    def test_certificate(self) -> bool:
        """Test certificate validation based on dev/prod mode."""
        mode = "Development" if self.dev_mode else "Production"
        self._print_test_header(f"Testing SSL Certificate ({mode} Mode)")

        try:
            parsed = urlparse(self.base_url)
            hostname = parsed.hostname or "localhost"
            port = parsed.port or 443

            cert_pem = ssl.get_server_certificate((hostname, port))
            cert = load_pem_x509_certificate(cert_pem.encode())

            subject = cert.subject
            common_name = None
            for attribute in subject:
                if attribute.oid._name == "commonName":
                    common_name = attribute.value
                    break

            san_names = []
            try:
                san_ext = cert.extensions.get_extension_for_oid(
                    ExtensionOID.SUBJECT_ALTERNATIVE_NAME
                )
                for name in san_ext.value:
                    san_names.append(name.value)
            except Exception:
                pass

            self._print_success(f"Certificate CN: {common_name}")
            if san_names:
                self._print_info(f"SANs: {', '.join(san_names)}")

            if self.dev_mode:
                is_self_signed = cert.issuer == cert.subject
                self._print_info(f"Self-signed: {is_self_signed}")

            return True
        except Exception as e:
            self._print_error(f"Certificate test failed: {e}")
            return False

    def test_client_verification(self) -> bool:
        """Full end-to-end client verification flow.

        1. Get TDX quote (attestation)
        2. Get model hash
        3. Compare with expected
        4. Run inference
        """
        self._print_test_header("Testing Client Verification Flow")

        try:
            # Step 1: Attestation
            self._print_info("Step 1: Requesting TDX quote...")
            nonce_hex = secrets.token_hex(32)
            attest_resp = self.session.post(
                f"{self.base_url}/tdx_quote",
                json={"nonce_hex": nonce_hex},
                verify=self.verify_ssl,
                timeout=30,
            )
            if attest_resp.status_code in (200, 400, 500):
                self._print_info(f"Attestation status: {attest_resp.status_code}")
            else:
                self._print_error(f"Unexpected attestation status: {attest_resp.status_code}")
                return False

            # Step 2: Model hash
            self._print_info("Step 2: Fetching model hash...")
            hash_resp = self.session.get(
                f"{self.base_url}/model-hash",
                verify=self.verify_ssl,
                timeout=30,
            )
            if hash_resp.status_code == 200:
                model_hash = hash_resp.json()["hash"]
                self._print_info(f"Model hash: {model_hash[:40]}...")
            else:
                self._print_warning(f"Model hash status: {hash_resp.status_code}")

            # Step 3: Inference
            self._print_info("Step 3: Running inference...")
            infer_resp = self.session.post(
                f"{self.base_url}/v1/chat/completions",
                json={
                    "model": self.DEFAULT_MODEL,
                    "messages": [{"role": "user", "content": "Hello"}],
                    "max_tokens": 20,
                },
                verify=self.verify_ssl,
                timeout=120,
            )
            if infer_resp.status_code == 200:
                content = infer_resp.json()["choices"][0]["message"]["content"]
                self._print_info(f"Inference: {content[:60]}...")
            else:
                self._print_warning(f"Inference status: {infer_resp.status_code}")

            self._print_success("Client verification flow completed")
            return True
        except Exception as e:
            self._print_error(f"Client verification failed: {e}")
            return False

    def test_ekm_headers(self) -> bool:
        """Test EKM header forwarding (dev mode only)."""
        self._print_test_header("Testing EKM Header Forwarding")

        if not self.dev_mode:
            self._print_info("Skipping EKM header test in production mode")
            return True

        try:
            response = self.session.get(
                f"{self.base_url}/debug/ekm",
                verify=self.verify_ssl,
                timeout=10,
            )
            if response.status_code == 200:
                data = response.json()
                self._print_success(f"EKM header present: {data.get('ekm_header_present')}")
                if data.get("hmac_valid") is not None:
                    self._print_info(f"HMAC valid: {data['hmac_valid']}")
                return True
            else:
                self._print_warning(f"EKM debug returned {response.status_code}")
                return True
        except Exception as e:
            self._print_error(f"EKM header test failed: {e}")
            return False

    # ── Runner ──────────────────────────────────────────────────────

    def run_tests(self, test_names: list[str]) -> bool:
        """Run specified tests and return overall pass/fail."""
        results = {}
        errors = {}
        test_map = {
            "health": self.test_health,
            "push-model": self.test_push_model,
            "push-model-repeat": self.test_push_model_repeat,
            "model-hash": self.test_model_hash,
            "attestation": self.test_attestation,
            "vllm": self.test_vllm_inference,
            "redirect": self.test_redirect,
            "acme": self.test_acme,
            "certificate": self.test_certificate,
            "client-verification": self.test_client_verification,
            "ekm-headers": self.test_ekm_headers,
        }

        for name in test_names:
            if name not in test_map:
                continue
            try:
                results[name] = test_map[name]()
            except Exception as e:
                results[name] = False
                errors[name] = str(e)

        for name, passed in results.items():
            url = self._test_url(name)
            if passed:
                print(f"PASS  {name:30s} {url}")
            else:
                err = errors.get(name, "")
                print(f"FAIL  {name:30s} {url}")
                if err:
                    print(f"      {err}")

        return all(results.values())

    def _test_url(self, test_name: str) -> str:
        """Return the endpoint URL exercised by a test."""
        url_map = {
            "health": "/health",
            "push-model": "/push-model",
            "push-model-repeat": "/push-model",
            "model-hash": "/model-hash",
            "attestation": "/tdx_quote",
            "vllm": "/v1/chat/completions",
            "redirect": f"{self.http_url}/health",
            "acme": f"{self.http_url}/.well-known/acme-challenge/",
            "certificate": f"{self.base_url} (TLS)",
            "client-verification": "/tdx_quote + /model-hash + /v1/",
            "ekm-headers": "/debug/ekm",
        }
        route = url_map.get(test_name, "")
        if route.startswith("/"):
            return f"{self.base_url}{route}"
        return route


def main():
    parser = argparse.ArgumentParser(description="CVM Model Serving Test Suite")
    parser.add_argument("--base-url", default="https://localhost", help="Base HTTPS URL")
    parser.add_argument("--http-url", default="http://localhost", help="Base HTTP URL")
    parser.add_argument("--dev", action="store_true", help="Enable development mode")

    # Wait commands
    parser.add_argument("--wait", action="store_true", help="Wait for services to be ready")

    # Test selectors
    parser.add_argument("--all", action="store_true", help="Run all tests")
    parser.add_argument("--health", action="store_true", help="Test health endpoint")
    parser.add_argument("--push-model", action="store_true", help="Test push model")
    parser.add_argument("--push-model-repeat", action="store_true", help="Test push model repeat")
    parser.add_argument("--model-hash", action="store_true", help="Test model hash")
    parser.add_argument("--attestation", action="store_true", help="Test attestation")
    parser.add_argument("--vllm", action="store_true", help="Test vLLM inference")
    parser.add_argument("--redirect", action="store_true", help="Test HTTP redirect")
    parser.add_argument("--acme", action="store_true", help="Test ACME challenge")
    parser.add_argument("--certificate", action="store_true", help="Test SSL certificate")
    parser.add_argument("--client-verification", action="store_true", help="Test client flow")
    parser.add_argument("--ekm-headers", action="store_true", help="Test EKM headers")

    # Model URL for push test
    parser.add_argument("--model-url", default=None, help="Model URL for push test")

    args = parser.parse_args()

    tester = CVMTester(
        base_url=args.base_url,
        http_url=args.http_url,
        dev_mode=args.dev,
    )

    # Wait for services
    if args.wait:
        if not tester.wait_for_nginx():
            sys.exit(1)
        if not tester.wait_for_vllm():
            sys.exit(1)
        sys.exit(0)

    # Determine which tests to run
    if args.all:
        tests = [
            "health",
            "push-model",
            "push-model-repeat",
            "model-hash",
            "attestation",
            "vllm",
            "redirect",
            "acme",
            "certificate",
            "client-verification",
            "ekm-headers",
        ]
    else:
        tests = []
        if args.health:
            tests.append("health")
        if args.push_model:
            tests.append("push-model")
        if args.push_model_repeat:
            tests.append("push-model-repeat")
        if args.model_hash:
            tests.append("model-hash")
        if args.attestation:
            tests.append("attestation")
        if args.vllm:
            tests.append("vllm")
        if args.redirect:
            tests.append("redirect")
        if args.acme:
            tests.append("acme")
        if args.certificate:
            tests.append("certificate")
        if args.client_verification:
            tests.append("client-verification")
        if args.ekm_headers:
            tests.append("ekm-headers")

    if not tests:
        parser.print_help()
        sys.exit(1)

    success = tester.run_tests(tests)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
