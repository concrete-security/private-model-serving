"""Tests for shade.config module."""

import pytest
from pydantic import ValidationError

from shade.config import (
    AppRef,
    AuthPlugin,
    CvmConfig,
    PluginsConfig,
    RouteConfig,
    ServiceRef,
    ShadeConfig,
    load_shade_config,
)


class TestMinimalConfig:
    """Test minimal valid configurations."""

    def test_minimal_config(self):
        config = ShadeConfig(
            app=AppRef(name="my-app"),
            cvm=CvmConfig(domain="example.com"),
        )
        assert config.app.name == "my-app"
        assert config.cvm.domain == "example.com"
        assert config.cvm.routes == []
        assert config.plugins.auth.enabled is False
        assert config.framework.version is None

    def test_app_name_required(self):
        with pytest.raises(ValidationError):
            ShadeConfig(cvm=CvmConfig(domain="example.com"))

    def test_domain_required(self):
        with pytest.raises(ValidationError):
            ShadeConfig(app=AppRef(name="my-app"), cvm=CvmConfig())


class TestRouteConfig:
    """Test route configuration validation."""

    def test_valid_route(self):
        route = RouteConfig(path="/", port=8000)
        assert route.path == "/"
        assert route.port == 8000
        assert route.service is None
        assert route.auth_required is False
        assert route.cors is True

    def test_route_with_service(self):
        route = RouteConfig(path="/admin", service="admin-panel", port=3000)
        assert route.service == "admin-panel"
        assert route.port == 3000

    def test_route_path_must_start_with_slash(self):
        with pytest.raises(ValidationError, match="must start with '/'"):
            RouteConfig(path="invalid", port=8000)

    def test_route_port_required(self):
        with pytest.raises(ValidationError):
            RouteConfig(path="/")


class TestValidateConfig:
    """Test config validation logic via Pydantic validators."""

    def test_duplicate_route_paths(self):
        with pytest.raises(ValidationError, match="Duplicate route path"):
            ShadeConfig(
                app=AppRef(name="my-app"),
                cvm=CvmConfig(
                    domain="example.com",
                    routes=[
                        RouteConfig(path="/", port=8000),
                        RouteConfig(path="/", port=9000),
                    ],
                ),
            )

    def test_reserved_path_conflict(self):
        with pytest.raises(ValidationError, match="framework-reserved path"):
            ShadeConfig(
                app=AppRef(name="my-app"),
                cvm=CvmConfig(
                    domain="example.com",
                    routes=[RouteConfig(path="/health", port=8000)],
                ),
            )

    def test_reserved_path_tdx_quote(self):
        with pytest.raises(ValidationError, match="framework-reserved path"):
            ShadeConfig(
                app=AppRef(name="my-app"),
                cvm=CvmConfig(
                    domain="example.com",
                    routes=[RouteConfig(path="/tdx_quote", port=8000)],
                ),
            )

    def test_auth_required_without_plugin(self):
        with pytest.raises(ValidationError, match="auth plugin is not enabled"):
            ShadeConfig(
                app=AppRef(name="my-app"),
                cvm=CvmConfig(
                    domain="example.com",
                    routes=[RouteConfig(path="/admin", port=8000, auth_required=True)],
                ),
            )

    def test_auth_required_with_plugin(self):
        config = ShadeConfig(
            app=AppRef(name="my-app"),
            cvm=CvmConfig(
                domain="example.com",
                routes=[RouteConfig(path="/admin", port=8000, auth_required=True)],
            ),
            plugins=PluginsConfig(auth=AuthPlugin(enabled=True)),
        )
        assert config.cvm.routes[0].auth_required is True

    def test_user_service_on_internal_network(self):
        with pytest.raises(ValidationError, match="framework-internal network"):
            ShadeConfig(
                app=AppRef(name="my-app"),
                services={"my-app": ServiceRef(networks=["proxy", "attestation"])},
                cvm=CvmConfig(domain="example.com"),
            )

    def test_route_target_not_on_proxy(self):
        with pytest.raises(ValidationError, match="not on 'proxy' network"):
            ShadeConfig(
                app=AppRef(name="my-app"),
                services={
                    "my-app": ServiceRef(networks=["proxy"]),
                    "admin": ServiceRef(networks=[]),
                },
                cvm=CvmConfig(
                    domain="example.com",
                    routes=[RouteConfig(path="/admin", service="admin", port=3000)],
                ),
            )

    def test_main_app_must_be_on_proxy(self):
        with pytest.raises(ValidationError, match="must be on 'proxy' network"):
            ShadeConfig(
                app=AppRef(name="my-app"),
                services={"my-app": ServiceRef(networks=[])},
                cvm=CvmConfig(domain="example.com"),
            )


class TestLoadShadeConfig:
    """Test load_shade_config with invalid YAML triggers Pydantic validation."""

    def test_load_duplicate_routes(self, tmp_path):
        config_file = tmp_path / "shade.yml"
        config_file.write_text(
            "app:\n"
            "  name: my-app\n"
            "cvm:\n"
            "  domain: example.com\n"
            "  routes:\n"
            "    - path: /\n"
            "      port: 8000\n"
            "    - path: /\n"
            "      port: 9000\n"
        )
        with pytest.raises(ValidationError, match="Duplicate route path"):
            load_shade_config(config_file)

    def test_load_reserved_path(self, tmp_path):
        config_file = tmp_path / "shade.yml"
        config_file.write_text(
            "app:\n"
            "  name: my-app\n"
            "cvm:\n"
            "  domain: example.com\n"
            "  routes:\n"
            "    - path: /health\n"
            "      port: 8000\n"
        )
        with pytest.raises(ValidationError, match="framework-reserved path"):
            load_shade_config(config_file)

    def test_load_auth_required_without_plugin(self, tmp_path):
        config_file = tmp_path / "shade.yml"
        config_file.write_text(
            "app:\n"
            "  name: my-app\n"
            "cvm:\n"
            "  domain: example.com\n"
            "  routes:\n"
            "    - path: /admin\n"
            "      port: 8000\n"
            "      auth_required: true\n"
        )
        with pytest.raises(ValidationError, match="auth plugin is not enabled"):
            load_shade_config(config_file)

    def test_load_non_dict_yaml(self, tmp_path):
        config_file = tmp_path / "shade.yml"
        config_file.write_text("just a string")
        with pytest.raises(ValueError, match="expected a YAML mapping"):
            load_shade_config(config_file)
