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

## Flow

1. **Boot** — CVM starts all services. vLLM polls model-service `/ready`, waiting for model.
2. **Push** — Model owner sends tar archive via `POST /push-model` with Bearer token. Model-service extracts to shared volume, computes SHA-256, verifies against expected hash. Endpoint is permanently disabled after first push (410 Gone). vLLM detects `/ready` and starts loading the model.
3. **Verify** — End user gets TDX quote from `/tdx_quote`, fetches hash from `/model-hash`, compares with hash published by model owner.
4. **Inference** — `POST /v1/chat/completions` (OpenAI-compatible).

## Quick Start

```bash
# Start services
make docker-up

# Push model (from model-owner/)
cd model-owner && make push

# Run user tests (from user/)
cd user && uv run pytest test_user.py -v
```

## Repository Structure

```
private-model-serving/
├── app/                        # Application: model-service (FastAPI)
│   ├── app.py                  # /push-model, /model-hash, /health, /ready
│   ├── utils.py                # Hash computation, sentinel
│   ├── Dockerfile
│   └── tests/
├── services/                   # Shade infra (from fork)
│   ├── cert-manager/           # nginx + TLS + EKM
│   ├── attestation-service/    # TDX quotes
│   └── auth-service/           # Token auth plugin
├── src/shade/                  # Shade CLI
├── docker-compose.yml          # App services (vLLM + model-service)
├── docker-compose.mock.yml     # Shade mock app (framework testing only)
├── shade.yml                   # Route config
├── model-owner/                # Model owner tools (push, hash)
├── user/                       # End user tools (verify, inference)
├── test_cvm.py                 # Shade integration tests
└── test_cvm_app.py             # App integration tests
```

## Components

### model-service
FastAPI service managing model weights inside the CVM:

- **`POST /push-model`** — Receives tar archive of model weights + Bearer token. Extracts to `/models/current`, computes SHA-256, compares with expected hash. One-time only (410 Gone on repeat).
- **`GET /model-hash`** — Returns cached SHA-256 hash of model files.
- **`GET /health`** — Health check with model status.
- **`GET /ready`** — Returns 200 only after model is pushed. Used by vLLM to know when to start.

### cert-manager (from Shade)
Nginx reverse proxy with TLS termination, Let's Encrypt certificates, and TLS EKM channel binding (RFC 9266).

### attestation-service (from Shade)
TDX attestation using dstack_sdk. Validates EKM headers with HMAC-SHA256.

## Testing

```bash
# App unit tests
cd app && uv run pytest tests/ -v

# App integration tests (requires running containers + model pushed)
uv run pytest test_cvm_app.py -v

# Shade unit tests
uv run pytest tests/ -v
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `PUSH_TOKEN` | Bearer token for /push-model | Empty (no auth) |
| `MODEL_DIR` | Model storage path | `/models/current` |
| `DOMAIN` | Domain for TLS certificate | `localhost` |
