# CLAUDE.md

## Project Overview

Application-only repo for confidential model serving: vLLM + model-service.
TEE infrastructure (nginx, TLS, attestation, EKM) comes from **Shade** via `shade build`.

Built from Shade (TEE framework) + Umbra (vLLM config) + new Model Service.

## Three Actors

| Actor | Role | Trust Level |
|-------|------|-------------|
| **Model Owner** | Generates push token, computes hash, pushes weights, publishes hash | Fully trusted |
| **Cloud Provider** | Hosts the CVM infrastructure | NOT trusted |
| **User** | Compares hash from model owner with CVM, runs inference | Trusted for own data |

## Repository Structure

```
private-model-serving/
├── Makefile                           # Root: full scenario (dev + prod modes)
├── model-owner/                       # Model Owner tools
│   ├── Makefile                       # download, archive, hash, push
│   ├── compute_hash.py                # Compute SHA-256 locally
│   └── verify.py                      # Verify attestation + hash after push
├── user/                              # End-User tools
│   └── verify.py                      # Compare hash + run inference
├── cvm/                               # CVM deployment (application only)
│   ├── docker-compose.dev.yml         # vLLM + model-service (no TEE infra)
│   ├── shade.yml                      # Shade config → shade build generates prod compose
│   ├── Makefile                       # Dev: up/down/wait
│   ├── test_cvm.py                    # Application-level integration tests
│   ├── model-service/                 # Model push + hash service (FastAPI)
│   └── vllm-patch/                    # vLLM Dockerfile (from Umbra)
```

## Shade Integration

```bash
# Dev mode (direct HTTP, no Shade):
make scenario                          # uses MODEL_SERVICE + VLLM_ENDPOINT

# Production mode (through Shade nginx):
cd cvm && shade build                  # reads shade.yml + docker-compose.dev.yml
ENDPOINT=https://model-serving.example.com make scenario
```

Shade adds automatically: nginx (ports 80/443), attestation-service, TLS 1.3, EKM.
Routes declared in `cvm/shade.yml`: `/push-model`, `/model-hash`, `/v1/` → services.

## Scenario Flow

```bash
make scenario        # Full scenario with real model weights
```

Individual steps:
```bash
make step-1-generate-token   # Model Owner generates Bearer token → cvm/.env
make step-2-hash-local       # Model Owner computes hash → publishes to users
make step-3-push             # Model Owner pushes archive → CVM extracts + verifies hash
make step-4-push-repeat      # Verify 410 Gone on second push
make step-5-user-verify      # User compares hash + runs inference
```

## Build & Development Commands

```bash
cd cvm
make dev-up          # Start vLLM + model-service
make dev-down        # Stop services
make wait-services   # Wait for readiness
```

Application-level tests:
```bash
python test_cvm.py --all               # All application tests
python test_cvm.py --health            # Just health
python test_cvm.py --wait              # Wait for services
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

- **Model push flow**: Model owner POSTs tar archive + Bearer token to `/push-model`. CVM extracts, computes hash, compares with expected hash. One-time only (410 Gone on repeat).
- **Model hash**: Deterministic SHA-256 of all model files. Same algorithm on model-owner side (`compute_hash.py`) and CVM side (`model_service.py`).
- **REPORTDATA**: `SHA512(nonce + EKM)` — session binding only (RFC 9266). Model hash is NOT included in REPORTDATA; it is communicated via HTTP response on `/model-hash`.
- **Auth**: Bearer token (v1). Protects against unauthorized access. Does NOT protect against cloud operator reading env vars. mTLS planned for v2.
- **Shared volume**: `model-store` volume shared between model-service and vLLM at `/models/current`.

## Architecture

With Shade (`shade build`):
- nginx routes: `/push-model` + `/model-hash` → model-service:8001, `/v1/*` → vllm:8000
- `/tdx_quote`, `/health` → handled by Shade automatically
- Networks: `proxy` (nginx ↔ app services), `attestation` (internal)

Without Shade (dev):
- model-service exposed on port 8001, vLLM on port 8000
- No TLS, no attestation

## Safety

- Never commit secrets; use environment variables
- Do not run destructive commands unless explicitly requested
- Treat attestation, TLS, EKM, and certificate flows as sensitive
