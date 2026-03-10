# CLAUDE.md

## Project Overview

Private Model Serving — confidential model serving built on top of the **Shade** framework.

Shade is a CVM (Confidential Virtual Machine) framework that wraps any containerized application with TEE infrastructure: TLS termination, TDX attestation, EKM channel binding, and secure reverse proxying.

This repo is a Shade-based application that adds: vLLM inference + a model push/hash service (FastAPI).

## Three Actors

| Actor | Role | Trust Level |
|-------|------|-------------|
| **Model Owner** | Generates push token, computes hash, pushes weights, publishes hash | Fully trusted |
| **Cloud Provider** | Hosts the CVM infrastructure | NOT trusted |
| **User** | Compares hash from model owner with CVM, runs inference | Trusted for own data |

## Repository Structure

```
private-model-serving/              # Shade framework + application
├── src/shade/                      # Shade CLI: build/validate/init
├── services/                       # Shade services (cert-manager, attestation, auth)
├── tests/                          # Shade unit tests
├── pyproject.toml                  # Shade package metadata
├── uv.lock
│
├── app/                            # Application: model-service (FastAPI)
│   ├── app.py                      # /push-model, /model-hash, /health, /ready
│   ├── utils.py                    # SHA-256 hash computation
│   ├── Dockerfile
│   ├── pyproject.toml
│   └── tests/
│
├── docker-compose.yml              # Application services (vLLM + model-service)
├── shade.yml                       # Shade config (routes, domain, plugins)
├── docker-compose.mock.yml         # Shade mock app (framework testing only)
├── docker-compose.dev.override.yml # Shade dev overrides
│
├── model-owner/                    # Model Owner tools (hash, push, verify)
├── user/                           # End-User tools (verify, inference)
│
├── Makefile                        # Shade infra + app scenario targets
├── test_cvm.py                     # Shade framework integration tests
├── test_cvm_app.py                 # Application integration tests
└── CLAUDE.md
```

## Shade Integration

```bash
# Build: shade wraps app services with TLS + attestation
uv run shade build

# Dev mode (direct HTTP, no Shade nginx):
make dev-up          # docker compose -f docker-compose.yml up
make dev-down

# Production mode (through Shade nginx):
make shade-build     # generates docker-compose.shade.yml
docker compose -f docker-compose.shade.yml up -d
```

Shade adds automatically: nginx (ports 80/443), attestation-service, TLS 1.3, EKM.
Routes declared in `shade.yml`: `/push-model`, `/model-hash`, `/v1/` → services.

## Scenario Flow

```bash
make step-1-hash-local   # Model Owner computes hash locally
make step-2-push         # Model Owner pushes archive to CVM
make step-3-push-repeat  # Verify 410 Gone on second push
make step-4-user-verify  # User compares hash + runs inference
```

## Build & Development Commands

```bash
# Shade unit tests
uv run pytest tests/ -v
make unit-tests

# Shade integration tests (mock app through nginx)
make dev-full        # Full workflow: up, wait, test, down
make test-all        # All integration tests

# Application unit tests
cd app && uv run pytest tests/ -v

# Application integration tests (requires running containers)
uv run pytest test_cvm_app.py -v
```

## Code Style

- Python 3.11+, managed with `uv`
- Ruff for linting/formatting (line-length=100, 4-space indent, double quotes)
- Google docstring convention
- Conventional Commits: `feat(app): ...`, `fix(shade): ...`

## Key Concepts

- **shade.yml**: User config declaring app name, domain, routes, plugins
- **Model push flow**: Model owner POSTs tar archive + Bearer token to `/push-model`. One-time only (410 Gone on repeat).
- **Model hash**: Deterministic SHA-256 of all model files. Same algorithm on model-owner side and CVM side.
- **REPORTDATA**: `SHA512(nonce + EKM)` — session binding only (RFC 9266). Model hash communicated via HTTP on `/model-hash`.
- **Shared volume**: `model-store` volume shared between model-service and vLLM at `/models/current`.

## Safety

- Never commit secrets; use environment variables
- Do not run destructive commands unless explicitly requested
- Treat attestation, TLS, EKM, and certificate flows as sensitive
