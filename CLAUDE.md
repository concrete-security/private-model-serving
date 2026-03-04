# CLAUDE.md

## Project Overview

CVM Model Serving is a generic, forkable repository demonstrating how to deploy a vLLM inference service inside a Confidential Virtual Machine (CVM), securely push model weights, and allow clients to verify CVM attestation + model integrity.

Built from Shade (TEE infrastructure) + Umbra (vLLM config) + new Model Service.

## Repository Structure

```
cvm-model-serving/
├── cvm/
│   ├── docker-compose.yml             # Production docker-compose
│   ├── docker-compose.dev.override.yml # Dev overrides (mock vLLM, local builds)
│   ├── Makefile                       # Build/test commands
│   ├── test_cvm.py                    # Integration test suite
│   ├── cert-manager/                  # Nginx + TLS + EKM (from Shade)
│   ├── attestation-service/           # TDX attestation (from Shade)
│   ├── model-service/                 # NEW: model push + hash
│   └── vllm-patch/                    # vLLM patches (from Umbra)
├── client/verify.py                   # Client verification demo
└── examples/push_model.py             # Model push example
```

## Build & Development Commands

```bash
cd cvm
make dev-full        # Full workflow: up, wait, test, down
make dev-up          # Start services with dev overrides
make dev-down        # Stop services
make test-all        # Run all integration tests
DEV=false make test-all  # Test in production mode
```

Individual tests:
```bash
make test-health
make test-push-model
make test-model-hash
make test-attestation
make test-vllm
make test-certificate
make test-ekm-headers
make test-client-verification
```

Model service unit tests:
```bash
cd cvm/model-service
uv run pytest tests/ -v
```

## Code Style

- Python 3.11+, managed with `uv`
- Ruff for linting/formatting (line-length=100, 4-space indent, double quotes)
- Google docstring convention

## Key Concepts

- **Model push flow**: Model owner POSTs HuggingFace URL to `/push-model`. Model-service downloads weights inside the CVM. One-time only.
- **Model hash**: Deterministic SHA-256 of all model files, computed inside CVM. Clients verify via attestation.
- **Shared volume**: `model-store` volume shared between model-service and vLLM at `/models/current`.
- **No auth for v1**: Authentication is not included. Routes are directly accessible.
- **EKM channel binding**: RFC 9266 TLS channel binding with HMAC-SHA256.

## Architecture

- nginx-cert-manager routes: `/push-model` + `/model-hash` → model-service:8001, `/v1/*` → vllm:8000, `/tdx_quote` → attestation-service:8080
- Routes are configured via `EXTRA_LOCATIONS` env var in docker-compose, processed by `render_nginx_conf.py`
- Networks: `proxy` (nginx ↔ vllm, model-service), `attestation` (nginx ↔ attestation-service)

## Testing Notes

- Integration tests run against docker-compose stack via `test_cvm.py`
- Use `--dev` flag for development mode (self-signed certs, mock vLLM)
- Model service has unit tests in `cvm/model-service/tests/`
- CVM tests require Docker and use `uv run` as the default Python runner

## Safety

- Never commit secrets; use environment variables
- Do not run destructive commands unless explicitly requested
- Treat attestation, TLS, EKM, and certificate flows as sensitive
