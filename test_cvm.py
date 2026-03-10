"""
Shade Framework Test Suite.

This script tests all Shade framework components through the nginx proxy (just like end-users would).
Tests framework-provided endpoints: /health, /tdx_quote, EKM, ACME, TLS.
"""

import argparse
import json
import secrets
import ssl
import sys
import time
from urllib.parse import urlparse

import requests
import urllib3
from cryptography.x509 import load_pem_x509_certificate
from cryptography.x509.oid import ExtensionOID
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class ShadeTester:
    """Main test class for Shade framework services"""

    def __init__(
        self,
        base_url: str = "https://localhost",
        http_url: str = "http://localhost",
        dev_mode: bool = False,
    ):
        self.base_url = base_url.rstrip("/")
        self.http_url = http_url.rstrip("/")
        self.dev_mode = dev_mode
        self.verify_ssl = not dev_mode  # In production mode, verify SSL certificates
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        """Create a requests session with proper SSL configuration"""
        session = requests.Session()

        # Configure retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        if self.dev_mode:
            # In dev mode, disable SSL warnings for self-signed certificates
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        return session

    def _print_test_header(self, test_name: str):
        """Print test header"""
        print("")
        print("-" * (len(test_name) + 4))
        print(f"🧪 {test_name}")
        print("-" * (len(test_name) + 4))

    def _print_success(self, message: str):
        """Print success message"""
        print(f"✅ {message}")

    def _print_error(self, message: str):
        """Print error message"""
        print(f"❌ {message}")

    def _print_warning(self, message: str):
        """Print warning message"""
        print(f"⚠️  {message}")

    def _print_info(self, message: str):
        """Print info message"""
        print(f"ℹ️  {message}")

    def wait_for_app(self, timeout: int = 300) -> bool:
        """Wait for the app service to become ready (reachable through nginx proxy)"""
        self._print_test_header("Waiting for app service to become ready")

        start_time = time.time()
        attempt = 0

        while time.time() - start_time < timeout:
            attempt += 1
            try:
                response = self.session.get(f"{self.base_url}/v1/models", verify=self.verify_ssl, timeout=3)
                if response.status_code == 200:
                    self._print_success(f"App service is ready! (attempt {attempt})")
                    return True
            except requests.exceptions.SSLError as e:
                print(f"SSL error occurred: {e}")
                return False
            except requests.exceptions.RequestException as e:
                self._print_warning(f"request exception: {type(e)} {e}")
                pass

            if attempt % 12 == 0:  # Print every minute
                elapsed = int(time.time() - start_time)
                print(f"Attempt {attempt}: App service not ready yet, waiting... ({elapsed}s elapsed)")

            time.sleep(5)

        self._print_error(f"App service failed to start after {timeout} seconds")
        return False

    def wait_for_nginx(self, timeout: int = 300) -> bool:
        """Wait for the nginx proxy to become ready"""
        self._print_test_header("Waiting for nginx proxy to become ready")

        start_time = time.time()
        attempt = 0

        while time.time() - start_time < timeout:
            attempt += 1
            try:
                response = self.session.get(f"{self.base_url}/health", verify=self.verify_ssl, timeout=3)
                if response.status_code == 200:
                    self._print_success(f"Nginx proxy is ready! (attempt {attempt})")
                    return True
            except requests.exceptions.SSLError as e:
                print(f"SSL error occurred: {e}")
                return False
            except requests.exceptions.RequestException as e:
                self._print_warning(f"request exception: {type(e)} {e}")
                pass

            if attempt % 12 == 0:  # Print every minute
                elapsed = int(time.time() - start_time)
                print(f"Attempt {attempt}: Nginx proxy not ready yet, waiting... ({elapsed}s elapsed)")

            time.sleep(5)

        self._print_error(f"Nginx proxy failed to start after {timeout} seconds")
        return False

    def test_certificate(self) -> bool:
        """Test certificate validation based on dev/prod mode"""
        mode = "Development" if self.dev_mode else "Production"
        self._print_test_header(f"Testing SSL Certificate ({mode} Mode)")

        try:
            # Parse URL to get hostname and port
            parsed = urlparse(self.base_url)
            hostname = parsed.hostname or "localhost"
            port = parsed.port or 443

            # Get certificate
            cert_pem = ssl.get_server_certificate((hostname, port))
            cert = load_pem_x509_certificate(cert_pem.encode())

            # Extract subject and issuer information
            subject = cert.subject
            issuer = cert.issuer

            # Get common name from subject
            common_name = None
            for attribute in subject:
                if attribute.oid._name == "commonName":
                    common_name = attribute.value
                    break

            # Check Subject Alternative Names
            san_names = []
            try:
                san_ext = cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
                for name in san_ext.value:
                    san_names.append(name.value)
            except Exception as e:
                self._print_info(f"Could not parse Subject Alternative Names: {e}")

            localhost_valid = (
                common_name in ["localhost", "127.0.0.1"] or "localhost" in san_names or "127.0.0.1" in san_names
            )

            if localhost_valid:
                if self.dev_mode:
                    self._print_success(f"Certificate is valid for localhost (CN: {common_name}, SAN: {san_names})")
                else:
                    self._print_error("Certificate is valid for localhost while in production mode")
                    return False
            else:
                if self.dev_mode:
                    self._print_warning(f"Certificate is not valid for localhost (CN: {common_name}, SAN: {san_names})")

            # Check if it's self-signed by comparing issuer and subject
            is_self_signed = subject == issuer

            if self.dev_mode:
                # In dev mode, expect self-signed certificates
                if is_self_signed:
                    self._print_success("Certificate is self-signed (as expected in dev mode)")
                else:
                    issuer_cn = None
                    for attribute in issuer:
                        if attribute.oid._name == "commonName":
                            issuer_cn = attribute.value
                            break
                    self._print_warning(
                        f"Certificate is not self-signed in dev mode (signed by: {issuer_cn or 'Unknown'})"
                    )
            else:
                # In production mode, expect certificates from trusted CA (trusted: should be checked during HTTPS requests)
                if is_self_signed:
                    self._print_error("Certificate is self-signed in production mode (should be from trusted CA)")
                    return False
                else:
                    issuer_cn = None
                    for attribute in issuer:
                        if attribute.oid._name == "commonName":
                            issuer_cn = attribute.value
                            break
                    self._print_success(f"Certificate is signed by trusted CA: {issuer_cn or 'Unknown'}")

            # Print certificate details
            self._print_info(f"Certificate valid from: {cert.not_valid_before_utc} to {cert.not_valid_after_utc}")

            return True

        except Exception as e:
            self._print_error(f"Certificate test failed: {str(e)}")
            return False

    def test_http_redirect(self) -> bool:
        """Test HTTP to HTTPS redirect"""
        self._print_test_header("Testing HTTP to HTTPS Redirect")

        try:
            # Test redirect without following it
            response = self.session.get(f"{self.http_url}/health", allow_redirects=False, timeout=3)

            if response.status_code == 301:
                location = response.headers.get("location", "")
                if location.startswith("https://"):
                    self._print_success(f"HTTP redirects to HTTPS: {location}")
                    return True
                else:
                    self._print_error(f"HTTP redirects but not to HTTPS: {location}")
                    return False
            else:
                self._print_error(f"Expected 301 redirect, got {response.status_code}")
                return False

        except requests.exceptions.RequestException as e:
            self._print_error(f"HTTP redirect test failed: {str(e)}")
            return False

    def test_acme_challenge(self) -> bool:
        """Test ACME challenge endpoint configuration"""
        self._print_test_header("Testing ACME Challenge Endpoint")

        try:
            # Test 1: Check that ACME challenge endpoint returns 404 for non-existent challenge
            # This is the expected behavior when no challenge file exists
            test_token = "test-token-12345"
            challenge_url = f"{self.http_url}/.well-known/acme-challenge/{test_token}"

            response = self.session.get(challenge_url, allow_redirects=False, timeout=3)

            if response.status_code == 404:
                self._print_success("ACME challenge endpoint correctly returns 404 for non-existent challenge")
            else:
                self._print_error(
                    f"ACME challenge endpoint returned unexpected status {response.status_code} (expected 404)"
                )
                return False

            # Test 2: Check that ACME challenge path doesn't redirect to HTTPS
            # ACME challenges must be served over HTTP for Let's Encrypt to work
            if response.status_code not in [301, 302, 307, 308]:
                self._print_success("ACME challenge endpoint doesn't redirect to HTTPS (correct behavior)")
            else:
                location = response.headers.get("location", "")
                self._print_error(f"ACME challenge endpoint redirects to {location} (should serve over HTTP)")
                return False

            # Test 3: Check content-type handling for challenge responses
            # The response should allow plain text content
            content_type = response.headers.get("content-type", "")
            self._print_info(f"ACME challenge endpoint content-type: {content_type}")

            # Test 4: Test with different challenge token formats
            # ACME challenge tokens are base64url encoded strings
            test_tokens = [
                "abcd1234",  # Simple alphanumeric
                "abcd-1234_efgh",  # With valid base64url characters
                "test.token.with.dots",  # With dots
                "VGVzdENoYWxsZW5nZVRva2Vu",  # Base64url encoded
            ]

            for token in test_tokens:
                token_url = f"{self.http_url}/.well-known/acme-challenge/{token}"
                token_response = self.session.get(token_url, allow_redirects=False, timeout=3)

                if token_response.status_code == 404:
                    continue  # Expected for non-existent files
                elif token_response.status_code == 200:
                    self._print_info(f"Challenge token '{token}' returned 200 (file exists)")
                else:
                    self._print_warning(
                        f"Challenge token '{token}' returned unexpected status {token_response.status_code}"
                    )

            # Test 5: Verify proper directory traversal protection
            # Attempt to access files outside the challenge directory
            malicious_paths = [
                "../../../etc/passwd",
                "..%2F..%2F..%2Fetc%2Fpasswd",  # URL encoded
                "....//....//....//etc/passwd",  # Double dots
            ]

            for path in malicious_paths:
                malicious_url = f"{self.http_url}/.well-known/acme-challenge/{path}"
                malicious_response = self.session.get(malicious_url, allow_redirects=False, timeout=3)

                if malicious_response.status_code in [404, 403]:
                    continue  # Good - should not allow directory traversal
                elif malicious_response.status_code == 200:
                    # Check if we actually got system files (bad)
                    content = malicious_response.text.lower()
                    if "root:" in content or "/bin/bash" in content:
                        self._print_error(f"Directory traversal vulnerability detected with path: {path}")
                        return False
                    else:
                        # 200 but not system files - might be a custom 404 page
                        self._print_info(f"Path '{path}' returned 200 but doesn't appear to be system file")

            self._print_success("ACME challenge endpoint has proper directory traversal protection")

            # Test 6: Test actual file serving using embedded test files
            # In development mode, test files are embedded via docker-compose configs
            if self.dev_mode:
                # Pre-defined test challenge files embedded in docker-compose.dev.override.yml
                test_challenges = [
                    {
                        "token": "test-challenge-token-dev",
                        "expected_content": "test-challenge-response-content-dev-mode-12345",
                    },
                    {
                        "token": "VGVzdENoYWxsZW5nZURldg",
                        "expected_content": "base64url-encoded-token-response-content",
                    },
                    {
                        "token": "dev-test-with-hyphens",
                        "expected_content": "hyphenated-token-response-for-testing",
                    },
                ]

                file_serving_success = 0
                for challenge in test_challenges:
                    token = challenge["token"]
                    expected_content = challenge["expected_content"]

                    try:
                        # Test file retrieval via HTTP
                        file_url = f"{self.http_url}/.well-known/acme-challenge/{token}"
                        file_response = self.session.get(file_url, allow_redirects=False, timeout=3)

                        if file_response.status_code == 200:
                            actual_content = file_response.text.strip()
                            if expected_content in actual_content:
                                self._print_success(f"ACME challenge file '{token}' served correctly")
                                file_serving_success += 1
                            else:
                                self._print_warning(
                                    f"Content mismatch for '{token}'. Expected: '{expected_content}', Got: '{actual_content}'"
                                )
                        else:
                            self._print_warning(
                                f"Could not retrieve test challenge file '{token}' (status: {file_response.status_code})"
                            )

                    except requests.exceptions.RequestException as e:
                        self._print_warning(f"Failed to test challenge token '{token}': {str(e)}")

                if file_serving_success > 0:
                    self._print_success(
                        f"ACME challenge file serving works correctly ({file_serving_success}/{len(test_challenges)} files)"
                    )
                else:
                    self._print_warning("ACME challenge file serving failed for all test files")
                    self._print_info("Note: Test files are embedded via docker-compose.dev.override.yml configs")
                    self._print_info("      Ensure services are started with the override file: make dev-up")

            return True

        except requests.exceptions.RequestException as e:
            self._print_error(f"ACME challenge test failed: {str(e)}")
            return False

    def test_health(self) -> bool:
        """Test health endpoint"""
        self._print_test_header("Testing Health Endpoint")

        try:
            response = self.session.get(f"{self.base_url}/health", verify=self.verify_ssl, timeout=3)

            if response.status_code == 200:
                self._print_success("Health endpoint working via HTTPS")
                return True
            else:
                self._print_error(f"Health endpoint failed with status {response.status_code}")
                return False

        except requests.exceptions.RequestException as e:
            self._print_error(f"Health endpoint test failed: {str(e)}")
            return False

    def test_attestation(self) -> bool:
        """Test attestation service endpoints"""
        mode = "Development" if self.dev_mode else "Production"
        self._print_test_header(f"Testing Attestation Service Endpoints ({mode} Mode)")

        try:
            # Generate a random nonce (32 bytes = 64 hex characters)
            nonce_hex = secrets.token_hex(32)

            # Payload only — nginx's EKM module sets X-TLS-EKM-Channel-Binding
            # from the actual TLS session, overriding any client-supplied header.
            payload = {"nonce_hex": nonce_hex}

            response = self.session.post(
                f"{self.base_url}/tdx_quote",
                json=payload,
                verify=self.verify_ssl,
                timeout=3,
            )

            if response.status_code == 200:
                self._print_success("TDX quote endpoint working via HTTPS")
                try:
                    data = response.json()
                    if "quote" in data:
                        self._print_info(f"Received quote with length: {len(data['quote'])}")
                except json.JSONDecodeError:
                    self._print_info("Response received but not JSON")
                return True
            elif response.status_code == 500:
                if self.dev_mode:
                    # In dev mode, 500 errors are acceptable (mock environment)
                    self._print_warning("TDX quote endpoint may require TDX environment (acceptable in dev mode)")
                    self._print_info(f"Response status: {response.status_code}")
                    return True
                else:
                    # In production mode, 500 errors are failures
                    self._print_error("TDX quote endpoint failed with status 500 (not acceptable in production)")
                    return False
            else:
                self._print_error(f"TDX quote endpoint failed with status {response.status_code}")
                return False

        except requests.exceptions.RequestException as e:
            self._print_error(f"Attestation test failed: {str(e)}")
            return False

    def test_cors(self) -> bool:
        """Test CORS configuration on multiple endpoints"""
        self._print_test_header("Testing CORS Configuration on Multiple Endpoints")

        # Test framework endpoints for CORS
        test_endpoints = [
            {
                "path": "/tdx_quote",
                "name": "TDX Quote (Attestation)",
                "test_methods": ["OPTIONS", "POST"],
                "post_payload": {"nonce_hex": secrets.token_hex(32)},
            },
            {
                "path": "/v1/models",
                "name": "App Models",
                "test_methods": ["OPTIONS", "GET"],
                "post_payload": None,
            },
        ]

        # Test allowed origins
        allowed_origins = [
            "https://app.concrete-security.com",
            "https://secure.concrete-security.com",
            "https://demo.vercel.app",
            "https://my-app.vercel.app",
        ]

        try:
            success = True

            # Helper function to test CORS for a specific endpoint
            def test_cors_for_endpoint(endpoint_info):
                endpoint_success = True
                path = endpoint_info["path"]
                name = endpoint_info["name"]

                self._print_info(f"Testing {name} ({path})")

                # Test OPTIONS preflight for allowed origins
                for origin in allowed_origins:
                    headers = {
                        "Origin": origin,
                        "Access-Control-Request-Method": "POST" if "POST" in endpoint_info["test_methods"] else "GET",
                    }

                    response = self.session.options(
                        f"{self.base_url}{path}",
                        headers=headers,
                        verify=self.verify_ssl,
                        timeout=3,
                    )

                    if response.status_code == 204:
                        cors_origin = response.headers.get("Access-Control-Allow-Origin", "")
                        allowed_methods = response.headers.get("Access-Control-Allow-Methods", "")

                        if origin in cors_origin:
                            self._print_success(f"  ✓ {name} OPTIONS working for {origin}")
                        else:
                            self._print_error(f"  ✗ {name} CORS failed for {origin}: got '{cors_origin}'")
                            endpoint_success = False

                        if "GET" in allowed_methods and "POST" in allowed_methods and "OPTIONS" in allowed_methods:
                            self._print_success(f"  ✓ {name} correct methods allowed: {allowed_methods}")
                        else:
                            self._print_error(f"  ✗ {name} incorrect allowed methods: {allowed_methods}")
                            endpoint_success = False
                    else:
                        self._print_error(f"  ✗ {name} OPTIONS failed for {origin}: status {response.status_code}")
                        endpoint_success = False

                    # Test actual requests for allowed origin
                    # Note: nginx's EKM module sets X-TLS-EKM-Channel-Binding from TLS,
                    # so no need to construct a fake header here.
                    headers = {"Origin": origin}

                    for method in endpoint_info["test_methods"]:
                        if method == "OPTIONS":
                            continue  # Already tested above

                        try:
                            if method == "GET":
                                response = self.session.get(
                                    f"{self.base_url}{path}",
                                    headers=headers,
                                    verify=self.verify_ssl,
                                    timeout=10,
                                )
                            elif method == "POST" and endpoint_info["post_payload"]:
                                response = self.session.post(
                                    f"{self.base_url}{path}",
                                    json=endpoint_info["post_payload"],
                                    headers=headers,
                                    verify=self.verify_ssl,
                                    timeout=10,
                                )
                            else:
                                self._print_warning(f"  ~ {name} Unsupported method {method} for testing")

                            cors_origin = response.headers.get("Access-Control-Allow-Origin", "")
                            if origin in cors_origin:
                                self._print_success(f"  ✓ {name} {method} request CORS working")
                            else:
                                self._print_error(
                                    f"  ✗ {name} {method} CORS failed: expected {origin}, got '{cors_origin}'"
                                )
                                endpoint_success = False

                        except requests.exceptions.RequestException as e:
                            # For app endpoints, some errors are expected in dev mode
                            if path.startswith("/v1/") and self.dev_mode:
                                self._print_info(
                                    f"  ~ {name} {method} request error (acceptable in dev): {str(e)[:100]}..."
                                )
                            else:
                                self._print_error(f"  ✗ {name} {method} request failed: {str(e)}")
                                endpoint_success = False

                # Test disallowed origin (just one per endpoint)
                disallowed_origin = "https://malicious.com"
                headers = {"Origin": disallowed_origin}

                response = self.session.options(
                    f"{self.base_url}{path}",
                    headers=headers,
                    verify=self.verify_ssl,
                    timeout=3,
                )

                cors_origin = response.headers.get("Access-Control-Allow-Origin", "")
                if cors_origin == "" or cors_origin == "null":
                    self._print_success(f"  ✓ {name} correctly blocked disallowed origin")
                elif disallowed_origin not in cors_origin:
                    self._print_success(f"  ✓ {name} correctly blocked disallowed origin")
                else:
                    self._print_error(f"  ✗ {name} incorrectly allowed disallowed origin: {disallowed_origin}")
                    endpoint_success = False

                return endpoint_success

            # Test each endpoint
            for endpoint in test_endpoints:
                if not test_cors_for_endpoint(endpoint):
                    success = False

            return success

        except requests.exceptions.RequestException as e:
            self._print_error(f"CORS test failed: {str(e)}")
            return False

    def test_app(self) -> bool:
        """Test app proxy endpoints"""
        self._print_test_header("Testing App Proxy Endpoints")

        success = True

        # Test models endpoint (mock app)
        try:
            response = self.session.get(f"{self.base_url}/v1/models", verify=self.verify_ssl, timeout=3)

            if response.status_code == 200:
                self._print_success("App models endpoint working via HTTPS proxy")
                try:
                    data = response.json()
                    models = data.get("data", [])
                    self._print_info(f"Available models: {len(models)}")
                    for model in models[:3]:
                        self._print_info(f"  - {model.get('id', 'Unknown')}")
                except json.JSONDecodeError:
                    self._print_warning("Models response not in expected JSON format")
            else:
                self._print_error(f"App models endpoint failed with status {response.status_code}")
                success = False

        except requests.exceptions.RequestException as e:
            self._print_error(f"App models test failed: {str(e)}")
            success = False

        # Test echo endpoint (mock app specific)
        try:
            response = self.session.get(f"{self.base_url}/echo", verify=self.verify_ssl, timeout=3)

            if response.status_code == 200:
                self._print_success("App echo endpoint working via HTTPS proxy")
            else:
                self._print_error(f"App echo endpoint failed with status {response.status_code}")
                success = False

        except requests.exceptions.RequestException as e:
            self._print_error(f"App echo test failed: {str(e)}")
            success = False

        return success

    def test_ekm_headers(self) -> bool:
        """Test EKM header forwarding (development mode only)"""
        self._print_test_header("Testing EKM Header Forwarding (Dev Only)")

        if not self.dev_mode:
            self._print_warning("Skipping EKM header test (not in dev mode)")
            return True

        success = True

        # Verify debug endpoint is accessible
        try:
            response = self.session.get(
                f"{self.base_url}/debug/ekm",
                verify=self.verify_ssl,
                timeout=5,
            )

            if response.status_code != 200:
                self._print_error(f"Debug endpoint returned {response.status_code}")
                return False

            data = response.json()

            # Check if debug mode is enabled
            if "error" in data:
                self._print_warning(f"Debug endpoint not enabled: {data.get('message')}")
                return False

            # Verify EKM header is present
            if not data.get("ekm_header_present"):
                self._print_error("EKM header not present in request")
                success = False
            else:
                self._print_success("EKM header present in request")

            # Check header format
            header_format = data.get("format", "unknown")
            if header_format == "signed":
                self._print_success("EKM header uses signed format")

                # Verify HMAC validation
                if not data.get("hmac_valid"):
                    self._print_error("HMAC validation failed!")
                    success = False
                else:
                    self._print_success("HMAC validation passed")

                # Verify EKM value length (should be 64 hex characters = 32 bytes)
                ekm_full = data.get("ekm_full", "")
                if len(ekm_full) != 64:
                    self._print_error(f"EKM value length is {len(ekm_full)}, expected 64")
                    success = False
                else:
                    self._print_success("EKM value has correct length (64 hex chars)")

                # Verify it's valid hex
                try:
                    bytes.fromhex(ekm_full)
                    self._print_success("EKM value is valid hex encoding")
                    self._print_info(f"  EKM value: {ekm_full[:32]}...{ekm_full[-8:]}")
                except ValueError:
                    self._print_error(f"EKM value is not valid hex: {ekm_full}")
                    success = False
            else:
                self._print_error(f"EKM header format is '{header_format}', expected 'signed'")
                success = False

        except requests.exceptions.RequestException as e:
            self._print_error(f"EKM header test failed: {str(e)}")
            success = False
        except Exception as e:
            self._print_error(f"EKM header test failed: {str(e)}")
            success = False

        # Verify EKM consistency within same session
        if success:
            self._print_info("Testing EKM consistency within same TLS session...")
            same_session_ekm_values = []

            try:
                # Reuse the same session for multiple requests
                same_session = requests.Session()
                for i in range(3):
                    response = same_session.get(
                        f"{self.base_url}/debug/ekm",
                        verify=self.verify_ssl,
                        timeout=5,
                    )
                    if response.status_code == 200:
                        data = response.json()
                        ekm_full = data.get("ekm_full", "")
                        same_session_ekm_values.append(ekm_full)
                same_session.close()

                # Check that all values are identical (same TLS session)
                unique_count = len(set(same_session_ekm_values))
                total_count = len(same_session_ekm_values)
                if unique_count == 1 and total_count == 3:
                    self._print_success(f"All {total_count} requests in same session produced identical EKM")
                else:
                    self._print_error(
                        f"EKM values within same session are not consistent! (unique: {unique_count}/{total_count})"
                    )
                    success = False

            except Exception as e:
                self._print_error(f"EKM consistency test failed: {str(e)}")
                success = False

        # Verify EKM uniqueness across sessions
        if success:
            self._print_info("Testing EKM uniqueness across TLS sessions...")
            ekm_values = []

            try:
                for i in range(3):
                    # Create a fresh session for each request to force new TCP/TLS connection
                    fresh_session = requests.Session()
                    response = fresh_session.get(
                        f"{self.base_url}/debug/ekm",
                        verify=self.verify_ssl,
                        timeout=5,
                    )
                    fresh_session.close()  # Explicitly close to ensure connection is terminated

                    if response.status_code == 200:
                        data = response.json()
                        ekm_full = data.get("ekm_full", "")
                        ekm_values.append(ekm_full)

                # Check that all values are unique (different TLS sessions)
                unique_count = len(set(ekm_values))
                total_count = len(ekm_values)
                if unique_count == total_count and total_count == 3:
                    self._print_success(f"All {total_count} sessions produced unique EKM values")
                else:
                    self._print_error(f"EKM values are not unique! (unique: {unique_count}/{total_count})")
                    success = False

            except Exception as e:
                self._print_error(f"EKM uniqueness test failed: {str(e)}")
                success = False

        # Verify clients cannot spoof the EKM header
        if success:
            self._print_info("Testing that clients cannot spoof EKM header...")

            try:
                # Try to send a fake EKM header
                fake_ekm = "0" * 64  # Fake EKM value (all zeros)

                spoofed_session = requests.Session()
                response = spoofed_session.get(
                    f"{self.base_url}/debug/ekm",
                    headers={"X-TLS-EKM-Channel-Binding": fake_ekm},
                    verify=self.verify_ssl,
                    timeout=5,
                )
                spoofed_session.close()

                if response.status_code == 200:
                    data = response.json()
                    actual_ekm = data.get("ekm_full", "")

                    # The actual EKM should NOT be the fake one we sent
                    if actual_ekm == fake_ekm:
                        self._print_error("Security issue: Client-provided EKM header was not overridden by nginx!")
                        success = False
                    else:
                        self._print_success("Client-provided EKM header correctly overridden by nginx")
                        self._print_info(f"  Client sent: {fake_ekm}")
                        self._print_info(f"  Server used: {actual_ekm[:32]}...{actual_ekm[-8:]}")
                else:
                    self._print_error(f"Debug endpoint returned {response.status_code}")
                    success = False

            except Exception as e:
                self._print_error(f"EKM spoofing test failed: {str(e)}")
                success = False

        return success

    def run_all_tests(self) -> bool:
        """Run all test suites"""
        mode = "Development" if self.dev_mode else "Production"
        print("")
        print("")
        print(f"🚀 Shade Framework Test Suite - Starting full tests ({mode} Mode)")
        print("=" * 60)

        results = {
            "certificate": self.test_certificate(),
            "redirect": self.test_http_redirect(),
            "acme": self.test_acme_challenge(),
            "health": self.test_health(),
            "attestation": self.test_attestation(),
            "cors": self.test_cors(),
            "app": self.test_app(),
            "ekm_headers": self.test_ekm_headers(),
        }

        print("\n" + "=" * 50)
        print("📊 Test Results Summary")
        print("=" * 50)

        passed = 0
        total = len(results)

        for test_name, result in results.items():
            status = "✅ PASS" if result else "❌ FAIL"
            print(f"{test_name.upper():12} {status}")
            if result:
                passed += 1

        print(f"\nTotal: {passed}/{total} tests passed")

        if passed == total:
            print("🎉 All tests passed!")
            return True
        else:
            print("⚠️  Some tests failed or had warnings")
            return False


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Shade Framework Test Suite - Test framework components via nginx proxy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --all                    # Run all tests
  %(prog)s --health                 # Test only health endpoint
  %(prog)s --certificate            # Test only certificate validation
  %(prog)s --acme                   # Test only ACME challenge endpoint (Let's Encrypt compatibility)
  %(prog)s --attestation --app      # Test attestation and app endpoints
  %(prog)s --wait                   # Wait for services to be ready
  %(prog)s --base-url https://myhost:8443  # Use custom base URL
        """,
    )

    parser.add_argument(
        "--base-url",
        default="https://localhost",
        help="Base HTTPS URL for testing (default: https://localhost)",
    )
    parser.add_argument(
        "--http-url",
        default="http://localhost",
        help="Base HTTP URL for redirect testing (default: http://localhost)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Service wait timeout in seconds (default: 300)",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Run in development mode (accept self-signed certs and 500 errors for quotes)",
    )

    # Test selection
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all tests (default if no specific tests selected)",
    )
    parser.add_argument("--wait", action="store_true", help="Wait for services to be ready")
    parser.add_argument("--certificate", action="store_true", help="Test SSL certificate validation")
    parser.add_argument("--redirect", action="store_true", help="Test HTTP to HTTPS redirect")
    parser.add_argument("--acme", action="store_true", help="Test ACME challenge endpoint")
    parser.add_argument("--health", action="store_true", help="Test health endpoint")
    parser.add_argument("--attestation", action="store_true", help="Test attestation service endpoints")
    parser.add_argument("--cors", action="store_true", help="Test CORS configuration")
    parser.add_argument("--app", action="store_true", help="Test app proxy endpoints")
    parser.add_argument("--ekm-headers", action="store_true", help="Test EKM header forwarding (dev mode only)")

    args = parser.parse_args()

    # If no specific tests selected, run all
    if not any(
        [
            args.wait,
            args.certificate,
            args.redirect,
            args.acme,
            args.health,
            args.attestation,
            args.cors,
            args.app,
            args.ekm_headers,
        ]
    ):
        args.all = True

    tester = ShadeTester(args.base_url, args.http_url, args.dev)

    # Wait for services if requested or if running all tests
    if args.wait or args.all:
        if not tester.wait_for_nginx(args.timeout):
            sys.exit(1)

    if args.wait or args.all:
        if not tester.wait_for_app(args.timeout):
            sys.exit(1)

    # Run selected tests
    if args.all:
        success = tester.run_all_tests()
        sys.exit(0 if success else 1)

    # Run individual tests
    success = True

    if args.certificate:
        success &= tester.test_certificate()

    if args.redirect:
        success &= tester.test_http_redirect()

    if args.acme:
        success &= tester.test_acme_challenge()

    if args.health:
        success &= tester.test_health()

    if args.attestation:
        success &= tester.test_attestation()

    if args.cors:
        success &= tester.test_cors()

    if args.app:
        success &= tester.test_app()

    if args.ekm_headers:
        success &= tester.test_ekm_headers()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
