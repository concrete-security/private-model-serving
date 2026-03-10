"""Tests for shade.generator module."""

from shade.config import (
    AppRef,
    AuthPlugin,
    CorsConfig,
    CvmConfig,
    PluginsConfig,
    RouteConfig,
    ServiceRef,
    ShadeConfig,
)
from shade.generator import generate


def _minimal_compose(services: dict | None = None) -> dict:
    """Create a minimal user compose dict."""
    if services is None:
        services = {"my-app": {"image": "python:3.11", "expose": ["8000"]}}
    return {"services": services}


class TestGenerateBasic:
    """Test basic generation."""

    def test_minimal_generation(self):
        config = ShadeConfig(
            app=AppRef(name="my-app"),
            cvm=CvmConfig(domain="example.com"),
        )
        result = generate(config, _minimal_compose())

        # Framework services should be present
        assert "nginx-cert-manager" in result["services"]
        assert "attestation-service" in result["services"]
        assert "auth-service" not in result["services"]

        # User service should be present
        assert "my-app" in result["services"]

        # Networks
        assert "proxy" in result["networks"]
        assert "attestation" in result["networks"]
        assert "auth" not in result["networks"]

    def test_user_service_ports_stripped(self):
        compose = {"services": {"my-app": {"image": "python:3.11", "ports": ["8000:8000"]}}}
        config = ShadeConfig(
            app=AppRef(name="my-app"),
            cvm=CvmConfig(domain="example.com"),
        )
        result = generate(config, compose)
        assert "ports" not in result["services"]["my-app"]

    def test_only_nginx_has_external_ports(self):
        config = ShadeConfig(
            app=AppRef(name="my-app"),
            cvm=CvmConfig(domain="example.com"),
        )
        result = generate(config, _minimal_compose())
        for svc_name, svc_def in result["services"].items():
            if svc_name == "nginx-cert-manager":
                assert "ports" in svc_def
                assert "80:80" in svc_def["ports"]
                assert "443:443" in svc_def["ports"]
            else:
                assert "ports" not in svc_def


class TestGenerateNetworks:
    """Test network assignment."""

    def test_main_app_auto_proxy(self):
        config = ShadeConfig(
            app=AppRef(name="my-app"),
            cvm=CvmConfig(domain="example.com"),
        )
        result = generate(config, _minimal_compose())
        app_networks = result["services"]["my-app"]["networks"]
        assert "proxy" in app_networks

    def test_main_app_in_services_keeps_extra_networks(self):
        config = ShadeConfig(
            app=AppRef(name="my-app"),
            services={"my-app": ServiceRef(networks=["proxy", "monitoring"])},
            cvm=CvmConfig(domain="example.com"),
        )
        result = generate(config, _minimal_compose())
        app_networks = result["services"]["my-app"]["networks"]
        assert "proxy" in app_networks
        assert "monitoring" in app_networks

    def test_explicit_service_networks(self):
        config = ShadeConfig(
            app=AppRef(name="my-app"),
            services={
                "my-app": ServiceRef(networks=["proxy"]),
                "redis": ServiceRef(networks=["proxy"]),
            },
            cvm=CvmConfig(domain="example.com"),
        )
        compose = {"services": {"my-app": {"image": "python:3.11"}, "redis": {"image": "redis:7"}}}
        result = generate(config, compose)
        assert "proxy" in result["services"]["redis"]["networks"]

    def test_nginx_networks_include_auth_when_enabled(self):
        config = ShadeConfig(
            app=AppRef(name="my-app"),
            cvm=CvmConfig(domain="example.com"),
            plugins=PluginsConfig(auth=AuthPlugin(enabled=True)),
        )
        result = generate(config, _minimal_compose())
        nginx_networks = result["services"]["nginx-cert-manager"]["networks"]
        assert "auth" in nginx_networks
        assert "auth" in result["networks"]

    def test_preserves_user_defined_networks(self):
        compose = {
            "services": {"my-app": {"image": "python:3.11", "networks": ["backend"]}},
            "networks": {"backend": {"driver": "bridge"}},
        }
        config = ShadeConfig(
            app=AppRef(name="my-app"),
            cvm=CvmConfig(domain="example.com"),
        )
        result = generate(config, compose)
        assert "backend" in result["networks"]


class TestGenerateRoutes:
    """Test route generation."""

    def test_no_routes_no_upstreams(self):
        config = ShadeConfig(
            app=AppRef(name="my-app"),
            cvm=CvmConfig(domain="example.com"),
        )
        result = generate(config, _minimal_compose())
        nginx_env = result["services"]["nginx-cert-manager"]["environment"]
        # No EXTRA_UPSTREAMS or EXTRA_LOCATIONS env vars
        env_keys = [e.split("=", 1)[0] for e in nginx_env]
        assert "EXTRA_UPSTREAMS" not in env_keys
        assert "EXTRA_LOCATIONS" not in env_keys

    def test_routes_generate_upstreams(self):
        config = ShadeConfig(
            app=AppRef(name="my-app"),
            services={"my-app": ServiceRef(networks=["proxy"])},
            cvm=CvmConfig(
                domain="example.com",
                routes=[RouteConfig(path="/", port=8000)],
            ),
        )
        result = generate(config, _minimal_compose())
        nginx_env = result["services"]["nginx-cert-manager"]["environment"]
        upstreams = [e for e in nginx_env if e.startswith("EXTRA_UPSTREAMS=")]
        assert len(upstreams) == 1
        assert "my_app_8000" in upstreams[0]
        assert "server my-app:8000" in upstreams[0]

    def test_routes_generate_locations(self):
        config = ShadeConfig(
            app=AppRef(name="my-app"),
            services={"my-app": ServiceRef(networks=["proxy"])},
            cvm=CvmConfig(
                domain="example.com",
                routes=[RouteConfig(path="/", port=8000)],
            ),
        )
        result = generate(config, _minimal_compose())
        nginx_env = result["services"]["nginx-cert-manager"]["environment"]
        locations = [e for e in nginx_env if e.startswith("EXTRA_LOCATIONS=")]
        assert len(locations) == 1
        assert "location /" in locations[0]
        assert "proxy_pass http://my_app_8000" in locations[0]

    def test_multi_service_routes(self):
        compose = {
            "services": {
                "api": {"image": "python:3.11"},
                "admin": {"image": "node:20"},
            }
        }
        config = ShadeConfig(
            app=AppRef(name="api"),
            services={
                "api": ServiceRef(networks=["proxy"]),
                "admin": ServiceRef(networks=["proxy"]),
            },
            cvm=CvmConfig(
                domain="example.com",
                routes=[
                    RouteConfig(path="/", port=8000),
                    RouteConfig(path="/admin", service="admin", port=3000),
                ],
            ),
        )
        result = generate(config, compose)
        nginx_env = result["services"]["nginx-cert-manager"]["environment"]
        upstreams = [e for e in nginx_env if e.startswith("EXTRA_UPSTREAMS=")][0]
        assert "api_8000" in upstreams
        assert "admin_3000" in upstreams

    def test_auth_required_route(self):
        config = ShadeConfig(
            app=AppRef(name="my-app"),
            services={"my-app": ServiceRef(networks=["proxy"])},
            cvm=CvmConfig(
                domain="example.com",
                routes=[
                    RouteConfig(path="/admin", port=8000, auth_required=True),
                ],
            ),
            plugins=PluginsConfig(auth=AuthPlugin(enabled=True)),
        )
        result = generate(config, _minimal_compose())
        nginx_env = result["services"]["nginx-cert-manager"]["environment"]
        locations = [e for e in nginx_env if e.startswith("EXTRA_LOCATIONS=")][0]
        assert "auth_request /_auth" in locations

    def test_websocket_route_includes_upgrade_headers(self):
        config = ShadeConfig(
            app=AppRef(name="my-app"),
            services={"my-app": ServiceRef(networks=["proxy"])},
            cvm=CvmConfig(
                domain="example.com",
                routes=[RouteConfig(path="/admin", port=8000, websocket=True)],
            ),
        )
        result = generate(config, _minimal_compose())
        nginx_env = result["services"]["nginx-cert-manager"]["environment"]
        locations = [e for e in nginx_env if e.startswith("EXTRA_LOCATIONS=")][0]
        assert "proxy_http_version 1.1" in locations
        assert "proxy_set_header Upgrade $$http_upgrade" in locations
        assert "proxy_set_header Connection $$connection_upgrade" in locations
        assert "proxy_read_timeout 3600s" in locations
        assert "proxy_send_timeout 3600s" in locations

    def test_non_websocket_route_excludes_upgrade_headers(self):
        config = ShadeConfig(
            app=AppRef(name="my-app"),
            services={"my-app": ServiceRef(networks=["proxy"])},
            cvm=CvmConfig(
                domain="example.com",
                routes=[RouteConfig(path="/", port=8000)],
            ),
        )
        result = generate(config, _minimal_compose())
        nginx_env = result["services"]["nginx-cert-manager"]["environment"]
        locations = [e for e in nginx_env if e.startswith("EXTRA_LOCATIONS=")][0]
        assert "proxy_http_version" not in locations
        assert "Upgrade" not in locations


class TestGenerateAuth:
    """Test auth plugin generation."""

    def test_auth_disabled_by_default(self):
        config = ShadeConfig(
            app=AppRef(name="my-app"),
            cvm=CvmConfig(domain="example.com"),
        )
        result = generate(config, _minimal_compose())
        assert "auth-service" not in result["services"]

    def test_auth_enabled(self):
        config = ShadeConfig(
            app=AppRef(name="my-app"),
            cvm=CvmConfig(domain="example.com"),
            plugins=PluginsConfig(auth=AuthPlugin(enabled=True)),
        )
        result = generate(config, _minimal_compose())
        assert "auth-service" in result["services"]
        auth_svc = result["services"]["auth-service"]
        assert "auth" in auth_svc["networks"]
        assert "8081" in auth_svc["expose"]


class TestGenerateVolumes:
    """Test volume handling."""

    def test_tls_volume_always_present(self):
        config = ShadeConfig(
            app=AppRef(name="my-app"),
            cvm=CvmConfig(domain="example.com"),
        )
        result = generate(config, _minimal_compose())
        assert "tls-certs-keys" in result["volumes"]

    def test_preserves_user_volumes(self):
        compose = {
            "services": {"my-app": {"image": "python:3.11"}},
            "volumes": {"my-data": None},
        }
        config = ShadeConfig(
            app=AppRef(name="my-app"),
            cvm=CvmConfig(domain="example.com"),
        )
        result = generate(config, compose)
        assert "my-data" in result["volumes"]


class TestGenerateConfigs:
    """Test top-level configs and secrets preservation."""

    def test_preserves_user_configs(self):
        compose = {
            "services": {
                "my-app": {
                    "image": "python:3.11",
                    "configs": [{"source": "app_config", "target": "/app/config.yml"}],
                },
            },
            "configs": {
                "app_config": {"file": "./config.yml"},
            },
        }
        config = ShadeConfig(
            app=AppRef(name="my-app"),
            cvm=CvmConfig(domain="example.com"),
        )
        result = generate(config, compose)
        assert "configs" in result
        assert "app_config" in result["configs"]
        assert result["configs"]["app_config"] == {"file": "./config.yml"}

    def test_preserves_user_secrets(self):
        compose = {
            "services": {
                "my-app": {
                    "image": "python:3.11",
                    "secrets": ["db_password"],
                },
            },
            "secrets": {
                "db_password": {"file": "./db_password.txt"},
            },
        }
        config = ShadeConfig(
            app=AppRef(name="my-app"),
            cvm=CvmConfig(domain="example.com"),
        )
        result = generate(config, compose)
        assert "secrets" in result
        assert "db_password" in result["secrets"]
        assert result["secrets"]["db_password"] == {"file": "./db_password.txt"}

    def test_no_configs_key_when_absent(self):
        config = ShadeConfig(
            app=AppRef(name="my-app"),
            cvm=CvmConfig(domain="example.com"),
        )
        result = generate(config, _minimal_compose())
        assert "configs" not in result
        assert "secrets" not in result


class TestGenerateCors:
    """Test CORS origins in nginx env."""

    def test_cors_origins_in_env(self):
        config = ShadeConfig(
            app=AppRef(name="my-app"),
            cvm=CvmConfig(
                domain="example.com",
                cors=CorsConfig(origins=["https://example.com", "https://app.example.com"]),
            ),
        )
        result = generate(config, _minimal_compose())
        nginx_env = result["services"]["nginx-cert-manager"]["environment"]
        cors_env = [e for e in nginx_env if e.startswith("CORS_ORIGINS=")][0]
        assert "https://example.com" in cors_env
        assert "https://app.example.com" in cors_env

    def test_empty_cors_origins(self):
        config = ShadeConfig(
            app=AppRef(name="my-app"),
            cvm=CvmConfig(domain="example.com"),
        )
        result = generate(config, _minimal_compose())
        nginx_env = result["services"]["nginx-cert-manager"]["environment"]
        cors_env = [e for e in nginx_env if e.startswith("CORS_ORIGINS=")][0]
        assert cors_env == "CORS_ORIGINS=[]"


class TestGenerateDictNetworks:
    """Test network merging when user compose uses dict-style networks."""

    def test_dict_style_networks_merged(self):
        compose = {
            "services": {
                "my-app": {
                    "image": "python:3.11",
                    "networks": {"backend": {"aliases": ["app"]}},
                },
            },
        }
        config = ShadeConfig(
            app=AppRef(name="my-app"),
            cvm=CvmConfig(domain="example.com"),
        )
        result = generate(config, compose)
        app_networks = result["services"]["my-app"]["networks"]
        # Dict-style preserved, proxy added
        assert "backend" in app_networks
        assert "proxy" in app_networks

    def test_unexpected_network_type_fallback(self):
        compose = {
            "services": {
                "my-app": {
                    "image": "python:3.11",
                    "networks": "not-a-list-or-dict",
                },
            },
        }
        config = ShadeConfig(
            app=AppRef(name="my-app"),
            cvm=CvmConfig(domain="example.com"),
        )
        result = generate(config, compose)
        app_networks = result["services"]["my-app"]["networks"]
        assert "proxy" in app_networks
