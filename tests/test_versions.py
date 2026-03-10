"""Tests for shade.versions module."""

import re
from pathlib import Path

import pytest
import yaml

from shade.versions import LATEST_VERSION, VERSIONS, get_images


class TestGetImages:
    """Test version image resolution."""

    def test_latest_version(self):
        images = get_images()
        assert "cert-manager" in images
        assert "attestation-service" in images
        assert "auth-service" in images

    def test_explicit_version(self):
        images = get_images(LATEST_VERSION)
        assert "cert-manager" in images

    def test_unknown_version(self):
        with pytest.raises(ValueError, match="Unknown framework version"):
            get_images("9.9.9")

    def test_all_images_are_pinned(self):
        """All images must use a pinned tag (e.g. :sha-<hex>) or digest (@sha256:<hex>)."""
        pinned_pattern = re.compile(r"^[^@:]+(?::[^\s@]+|@sha256:[0-9a-f]{64})$")
        for version, images in VERSIONS.items():
            for service, image_ref in images.items():
                assert pinned_pattern.match(image_ref), (
                    f"Version {version} service '{service}' must be pinned: {image_ref}"
                )


class TestImageDrift:
    """Verify pinned images in docker-compose.yml are properly pinned."""

    COMPOSE_PATH = Path(__file__).resolve().parent.parent / "docker-compose.yml"
    PINNED_PATTERN = re.compile(r"^[^@:]+(?::[^\s@]+|@sha256:[0-9a-f]{64})$")

    def test_app_images_are_pinned(self):
        """All images in docker-compose.yml must use a pinned tag or digest."""
        compose = yaml.safe_load(self.COMPOSE_PATH.read_text(encoding="utf-8"))
        services = compose.get("services", {})

        checked = 0
        for name, svc in services.items():
            image = svc.get("image")
            if not image:
                continue
            assert self.PINNED_PATTERN.match(image), (
                f"Service '{name}' image must be pinned: {image}"
            )
            checked += 1

        assert checked > 0, "No pinned images found in docker-compose.yml"
