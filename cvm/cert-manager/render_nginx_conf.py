"""Render nginx config templates from environment variables.

Reads template files and substitutes variables:
- DOMAIN: Server domain (default: "localhost")
- CORS_ORIGINS: JSON array of regex patterns (default: "" = no CORS)
- DEV_MODE: "true" to use https-dev template (default: "false")
- AUTH_ENABLED: "true" to include /_auth location (default: "true")
- UPSTREAM_HOST: Backward compat: main app host (default: "" = not used)
- UPSTREAM_PORT: Backward compat: main app port (default: "")
- EXTRA_UPSTREAMS: Pre-rendered nginx upstream blocks (default: "")
- EXTRA_LOCATIONS: Pre-rendered nginx location blocks (default: "")

When UPSTREAM_HOST is set (backward compat mode), the renderer auto-generates
an upstream and catch-all location, prepending/appending to EXTRA_UPSTREAMS/EXTRA_LOCATIONS.
"""

import json
import os
import logging

logger = logging.getLogger("render-nginx-conf")
logging.basicConfig(level=logging.INFO, format="%(message)s")

TEMPLATE_DIR = "/app/nginx_conf"
OUTPUT_DIR = "/app/nginx_conf"


def render_cors_block(origins_json: str) -> str:
    """Generate nginx CORS if-blocks from a JSON array of regex patterns."""
    if not origins_json or origins_json.strip() in ("", "[]"):
        return ""

    try:
        origins = json.loads(origins_json)
    except json.JSONDecodeError:
        logger.warning(f"Invalid CORS_ORIGINS JSON: {origins_json}, skipping CORS")
        return ""

    if not origins:
        return ""

    lines = ['    set $cors_origin "";']
    for pattern in origins:
        lines.append(f"    if ($http_origin ~ '{pattern}') {{")
        lines.append("        set $cors_origin $http_origin;")
        lines.append("    }")
    return "\n".join(lines)


def render_cors_headers(has_cors: bool) -> str:
    """Generate CORS header directives for a location block."""
    if not has_cors:
        return ""

    return """
        # Handle preflight OPTIONS requests
        if ($request_method = 'OPTIONS') {
            add_header 'Vary' 'Origin' always;
            add_header 'Access-Control-Allow-Origin' $cors_origin always;
            add_header 'Access-Control-Allow-Methods' 'GET, POST, OPTIONS' always;
            add_header 'Access-Control-Allow-Headers' 'DNT,User-Agent,X-Requested-With,If-Modified-Since,Cache-Control,Content-Type,Range' always;
            add_header 'Access-Control-Max-Age' 1728000 always;
            add_header 'Content-Type' 'text/plain; charset=utf-8' always;
            add_header 'Content-Length' 0 always;
            return 204;
        }

        # Add CORS headers for actual requests
        add_header 'Vary' 'Origin' always;
        add_header 'Access-Control-Allow-Origin' $cors_origin always;
        add_header 'Access-Control-Allow-Methods' 'GET, POST, OPTIONS' always;
        add_header 'Access-Control-Allow-Headers' 'DNT,User-Agent,X-Requested-With,If-Modified-Since,Cache-Control,Content-Type,Range' always;
        add_header 'Access-Control-Expose-Headers' 'Content-Length,Content-Range' always;"""


def render_auth_location(auth_enabled: bool) -> str:
    """Generate the internal auth subrequest location block."""
    if not auth_enabled:
        return ""

    return """    # Internal auth subrequest endpoint
    location = /_auth {
        internal;
        proxy_pass http://auth-service:8081/auth;
        proxy_pass_request_body off;
        proxy_set_header Content-Length "";
        proxy_set_header X-Original-URI $request_uri;
        # Forward the Authorization header with the Bearer token
        proxy_set_header Authorization $http_authorization;
    }"""


def render_default_upstream(host: str, port: str) -> str:
    """Generate the default upstream block for backward compat."""
    return f"""# Default app upstream
upstream app_backend {{
    server {host}:{port};
}}"""


def render_default_catchall(has_cors: bool) -> str:
    """Generate the default catch-all location for backward compat."""
    cors_headers = render_cors_headers(has_cors)
    return f"""    # Proxy to app service (catch-all)
    location / {{
{cors_headers}

        proxy_pass http://app_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}"""


def render_template(template_path: str, variables: dict) -> str:
    """Read a template file and substitute variables."""
    with open(template_path, "r") as f:
        content = f.read()

    for key, value in variables.items():
        content = content.replace(f"${{{key}}}", value)

    return content


def main():
    domain = os.environ.get("DOMAIN", "localhost")
    cors_origins = os.environ.get("CORS_ORIGINS", "")
    dev_mode = os.environ.get("DEV_MODE", "false").lower() == "true"
    auth_enabled = os.environ.get("AUTH_ENABLED", "true").lower() == "true"

    # Backward compat: UPSTREAM_HOST/PORT for Phase 1 (cvm/) usage
    upstream_host = os.environ.get("UPSTREAM_HOST", "")
    upstream_port = os.environ.get("UPSTREAM_PORT", "")

    # Pre-rendered fragments from Shade generator (Phase 3+)
    extra_upstreams = os.environ.get("EXTRA_UPSTREAMS", "")
    extra_locations = os.environ.get("EXTRA_LOCATIONS", "")

    cors_block = render_cors_block(cors_origins)
    has_cors = bool(cors_block)
    cors_headers = render_cors_headers(has_cors)
    auth_location = render_auth_location(auth_enabled)

    # Backward compat: if UPSTREAM_HOST is set, generate default upstream + catch-all
    if upstream_host:
        default_upstream = render_default_upstream(upstream_host, upstream_port or "8000")
        default_catchall = render_default_catchall(has_cors)

        if extra_upstreams:
            extra_upstreams = default_upstream + "\n\n" + extra_upstreams
        else:
            extra_upstreams = default_upstream

        if extra_locations:
            extra_locations = extra_locations + "\n\n" + default_catchall
        else:
            extra_locations = default_catchall

    # Resolve template variables within EXTRA_LOCATIONS (e.g., ${CORS_HEADERS})
    # since these fragments may come from the Shade generator with placeholders.
    extra_locations = extra_locations.replace("${CORS_HEADERS}", cors_headers)

    variables = {
        "DOMAIN": domain,
        "CORS_BLOCK": cors_block,
        "CORS_HEADERS": cors_headers,
        "AUTH_LOCATION": auth_location,
        "EXTRA_UPSTREAMS": extra_upstreams,
        "EXTRA_LOCATIONS": extra_locations,
    }

    # Render base.conf
    base_tmpl = os.path.join(TEMPLATE_DIR, "base.conf.tmpl")
    base_conf = render_template(base_tmpl, variables)
    base_out = os.path.join(OUTPUT_DIR, "base.conf")
    with open(base_out, "w") as f:
        f.write(base_conf)
    logger.info(f"Rendered {base_out}")

    # Render https.conf (or https-dev.conf)
    https_tmpl_name = "https-dev.conf.tmpl" if dev_mode else "https.conf.tmpl"
    https_tmpl = os.path.join(TEMPLATE_DIR, https_tmpl_name)
    https_conf = render_template(https_tmpl, variables)
    https_out = os.path.join(OUTPUT_DIR, "https.conf")
    with open(https_out, "w") as f:
        f.write(https_conf)
    logger.info(f"Rendered {https_out} (from {https_tmpl_name})")


if __name__ == "__main__":
    main()
