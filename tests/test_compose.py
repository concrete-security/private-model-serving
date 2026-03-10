"""Tests for shade.compose module."""

import pytest
import yaml

from shade.compose import load_user_compose, validate_app_service, validate_route_services
from shade.config import AppRef, CvmConfig, RouteConfig, ShadeConfig


@pytest.fixture
def tmp_compose(tmp_path):
    """Helper to create a temporary compose file."""

    def _create(content: dict) -> str:
        path = tmp_path / "docker-compose.yml"
        with open(path, "w") as f:
            yaml.dump(content, f)
        return str(path)

    return _create


class TestLoadUserCompose:
    """Test compose file loading."""

    def test_load_valid_compose(self, tmp_compose):
        path = tmp_compose(
            {
                "services": {
                    "app": {"image": "python:3.11"},
                }
            }
        )
        data = load_user_compose(path)
        assert "services" in data
        assert "app" in data["services"]

    def test_load_missing_file(self):
        with pytest.raises(FileNotFoundError):
            load_user_compose("/nonexistent/docker-compose.yml")

    def test_load_missing_services_key(self, tmp_compose):
        path = tmp_compose({"version": "3"})
        with pytest.raises(ValueError, match="'services' key"):
            load_user_compose(path)

    def test_load_invalid_yaml(self, tmp_path):
        path = tmp_path / "docker-compose.yml"
        path.write_text("just a string")
        with pytest.raises(ValueError, match="expected a YAML mapping"):
            load_user_compose(str(path))


class TestValidateAppService:
    """Test app service validation."""

    def test_app_exists(self):
        data = {"services": {"my-app": {"image": "python:3.11"}}}
        errors = validate_app_service(data, "my-app")
        assert errors == []

    def test_app_missing(self):
        data = {"services": {"other": {"image": "python:3.11"}}}
        errors = validate_app_service(data, "my-app")
        assert len(errors) == 1
        assert "my-app" in errors[0]


class TestValidateRouteServices:
    """Test route service validation."""

    def test_valid_routes(self):
        data = {"services": {"my-app": {}, "admin": {}}}
        config = ShadeConfig(
            app=AppRef(name="my-app"),
            cvm=CvmConfig(
                domain="example.com",
                routes=[
                    RouteConfig(path="/", port=8000),
                    RouteConfig(path="/admin", service="admin", port=3000),
                ],
            ),
        )
        errors = validate_route_services(data, config)
        assert errors == []

    def test_route_targets_missing_service(self):
        data = {"services": {"my-app": {}}}
        config = ShadeConfig(
            app=AppRef(name="my-app"),
            cvm=CvmConfig(
                domain="example.com",
                routes=[
                    RouteConfig(path="/admin", service="admin", port=3000),
                ],
            ),
        )
        errors = validate_route_services(data, config)
        assert len(errors) == 1
        assert "admin" in errors[0]
