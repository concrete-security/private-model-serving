# Private Model Serving

Confidential model serving built on [Shade](https://github.com/concrete-security/shade). A model owner pushes weights into a CVM, end users verify integrity via attestation and hash, then run inference.

## Architecture

```
                Model Owner                          End User
                    |                                    |
              POST /push-model                     GET /tdx_quote
              (tar archive + token)                GET /model-hash
                    |                              POST /v1/chat/completions
                    v                                    |
            ┌────────────────────────────────────────────┐
            │              CVM (TEE)                     │
            │                                            │
            │  nginx-cert-manager :443  (TLS + EKM)      │
            │     ├── /tdx_quote    → attestation-service│
            │     ├── /push-model   → model-service :8001│
            │     ├── /model-hash   → model-service :8001│
            │     └── /v1/*         → vllm :8000         │
            │                                            │
            │  shared volume: /models/current            │
            └────────────────────────────────────────────┘
```

## Shade Integration

This project uses [Shade](https://github.com/concrete-security/shade) as a dependency, not a fork. Shade is a CVM framework that wraps any containerized application with TEE infrastructure (TLS termination, TDX attestation, EKM channel binding, secure reverse proxy).

### Setup

```bash
# Install dependencies (includes Shade CLI)
uv sync

# Initialize Shade config (generates a template shade.yml)
uv run shade init

# Edit shade.yml to declare your routes, domain, and plugins
```

### shade.yml

The `shade.yml` file declares how Shade wraps your application:

```yaml
app:
  name: model-service

services:
  model-service:
    networks: [proxy]
  vllm:
    networks: [proxy]

cvm:
  domain: model-serving.example.com
  routes:
    - path: /push-model
      service: model-service
      port: 8001
    - path: /model-hash
      service: model-service
      port: 8001
    - path: /v1/
      service: vllm
      port: 8000
```

### Build

`shade build` reads `shade.yml` + `docker-compose.yml` and generates `docker-compose.shade.yml`, which adds nginx (TLS + reverse proxy) and attestation-service to your application services.

```bash
# Generate the production compose file
uv run shade build

# Start everything
docker compose -f docker-compose.shade.yml up -d
```

## Flow

1. **Boot** — CVM starts all services. vLLM polls model-service `/ready`, waiting for model.
2. **Push** — Model owner sends tar archive via `POST /push-model` with Bearer token. Model-service extracts to shared volume, computes SHA-256, verifies against expected hash. Endpoint is permanently disabled after first push (410 Gone). vLLM detects `/ready` and starts loading the model.
3. **Verify** — End user gets TDX quote from `/tdx_quote`, fetches hash from `/model-hash`, compares with hash published by model owner.
4. **Inference** — `POST /v1/chat/completions` (OpenAI-compatible).

## Quick Start

```bash
# Install dependencies
uv sync

# Dev mode (local HTTP, no TLS, no attestation)
make app-dev-up

# Production mode (TLS + attestation via Shade)
make docker-up
```

## Repository Structure

```
private-model-serving/
├── app/                        # Application: model-service (FastAPI)
│   ├── app.py                  # /push-model, /model-hash, /health, /ready
│   ├── utils.py                # Hash computation, sentinel
│   ├── Dockerfile
│   └── tests/
├── docker-compose.yml          # App services (vLLM + model-service)
├── shade.yml                   # Shade config (routes, domain, plugins)
├── model-owner/                # Model owner tools (push, hash)
├── user/                       # End user tools (verify, inference)
├── test_cvm_app.py             # App integration tests
└── pyproject.toml              # Dependencies (includes shade)
```

## Components

### model-service
FastAPI service managing model weights inside the CVM:

- **`POST /push-model`** — Receives tar archive of model weights + Bearer token. Extracts to `/models/current`, computes SHA-256, compares with expected hash. One-time only (410 Gone on repeat).
- **`GET /model-hash`** — Returns cached SHA-256 hash of model files.
- **`GET /health`** — Health check with model status.
- **`GET /ready`** — Returns 200 only after model is pushed. Used by vLLM to know when to start.

### Shade services (added by `shade build`)
- **nginx-cert-manager** — Reverse proxy with TLS 1.3 termination, Let's Encrypt, and EKM channel binding (RFC 9266).
- **attestation-service** — TDX attestation via dstack_sdk.

## Testing

```bash
# App unit tests
cd app && uv run pytest tests/ -v

# App integration tests (requires running containers + model pushed)
uv run pytest test_cvm_app.py -v
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `PUSH_TOKEN` | Bearer token for /push-model | Empty (no auth) |
| `MODEL_DIR` | Model storage path | `/models/current` |
| `DOMAIN` | Domain for TLS certificate | `localhost` |
