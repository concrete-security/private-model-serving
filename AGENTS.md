# AGENTS.md

## Project Overview

Shade is a Python CLI and compose generator for running containerized apps behind a
TEE-aware ingress layer. It combines a user-owned `docker-compose.yml` with
`shade.yml` and produces a complete `docker-compose.shade.yml` that includes:

- `nginx-cert-manager` for TLS termination, certificate management, EKM forwarding, and reverse proxying
- `attestation-service` for TDX quote generation
- `auth-service` when the auth plugin is enabled

The primary user flow is:

1. `shade init`
2. edit `shade.yml`
3. `shade validate`
4. `shade build`
5. run `docker compose -f docker-compose.shade.yml up`

## Repository Layout

```text
shade/
├── src/shade/
│   ├── __init__.py          # package version
│   ├── api.py               # build/validate/init API
│   ├── cli.py               # Click CLI entrypoint
│   ├── compose.py           # docker-compose loading and validation helpers
│   ├── config.py            # Pydantic models for shade.yml
│   ├── generator.py         # merged compose generation
│   ├── versions.py          # pinned framework image registry
│   └── templates/shade.yml  # starter config used by `shade init`
├── services/
│   ├── cert-manager/        # nginx + cert lifecycle + EKM extraction
│   ├── attestation-service/ # FastAPI TDX attestation service
│   └── auth-service/        # simple bearer-token auth backend
├── tests/                   # root unit tests for the Python package
├── docker-compose.yml       # repo integration stack with a mock app
├── docker-compose.dev.override.yml
├── test_cvm.py              # end-to-end integration test runner
├── README.md                # user-facing project documentation
├── Makefile                 # local integration and test commands
├── pyproject.toml           # root package metadata and dev tooling
└── uv.lock
```

## CLI Surface

- `shade init [-d OUTPUT_DIR]`
- `shade validate [-c shade.yml] [-f docker-compose.yml]`
- `shade build [-c shade.yml] [-f docker-compose.yml] [-o docker-compose.shade.yml]`

The CLI delegates to `src/shade/api.py`. `build()` always validates first, then writes
the generated compose file with a short header.

## `shade.yml` Schema Highlights

Important fields implemented today:

- `app.name`: name of the main service in the user compose file
- `services.<name>.networks`: explicit network attachments for user services
- `cvm.domain`: public domain used by nginx/cert-manager
- `cvm.routes[]`: explicit path-to-service mappings
- `cvm.cors.origins`: regex strings forwarded to nginx config rendering
- `cvm.tls.mode`: `letsencrypt` or `self-signed`
- `cvm.tls.letsencrypt_staging`
- `cvm.tls.letsencrypt_account_version`
- `plugins.auth.enabled`

Each route supports:

- `path`
- `port`
- optional `service` (defaults to `app.name`)
- optional `auth_required`
- optional `cors` (default `true`)
- optional `websocket` (default `false`)

## Validation and Generation Rules

- Routes are explicit. There is no implicit catch-all beyond the routes the user declares.
- Reserved route paths are `/health`, `/tdx_quote`, `/_auth`, and `/debug/ekm`.
- User services cannot join framework-internal networks `attestation` or `auth`.
- A route targeting a non-app service requires that service to be placed on the `proxy` network in `shade.yml`.
- The main app service is auto-attached to `proxy` during generation even if omitted from `services`.
- User service `ports` are stripped from the generated compose so only nginx exposes host ports.
- User-defined `networks`, `volumes`, `configs`, and `secrets` are preserved in the generated output.
- `_escape_for_compose()` exists because nginx variables like `$host` and template variables like `${CORS_HEADERS}` must be escaped before passing through Docker Compose interpolation.

## Images and Versioning

- Root package version: `0.1.0`
- Framework images are pinned in `src/shade/versions.py`
- `tests/test_versions.py` checks that pinned images stay aligned with the root integration `docker-compose.yml`

When changing framework images, update both `src/shade/versions.py` and any checked-in integration compose references that are expected to match.

## Development Commands

```bash
# Install root dependencies
uv sync --dev

# CLI
uv run shade --help
uv run shade init
uv run shade validate
uv run shade build

# Root unit tests
uv run pytest tests/ -v
make unit-tests

# Integration stack
make dev-up
make test-all
make dev-full
make dev-down
```

## Testing Notes

- Root unit tests cover config parsing, compose validation, generator output, CLI behavior, API behavior, and version drift checks.
- `test_cvm.py` exercises the stack through nginx, including health checks, redirects, ACME behavior, certificate behavior, attestation paths, CORS, and dev-only EKM debug paths.
- The root `docker-compose.yml` and `docker-compose.dev.override.yml` are repository test fixtures, not examples of the generated `shade build` output format.
- Service directories contain their own code and, in some cases, their own tests and documentation.

## Contributor Notes

- Python formatting is handled with Ruff (`line-length = 100`, double quotes).
- Root tests target Python 3.11+.
- `AUTH_SERVICE_TOKEN` is required when the auth plugin is enabled; the auth service warns and fails auth requests if the token is unset or shorter than its configured minimum.
- Production-style attestation and key derivation assume `/var/run/dstack.sock` is available to framework services.
