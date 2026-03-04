# CVM Model Serving

A generic, forkable repository demonstrating how a frontier AI lab can deploy an inference service (vLLM) inside a Confidential Virtual Machine (CVM), securely push model weights, and allow clients to verify CVM attestation + model integrity.

Built from [Shade](https://github.com/concrete-security/shade) (TEE infrastructure) + [Umbra](https://github.com/concrete-security/umbra) (vLLM config) + a new Model Update Service.

## Architecture

```
                    Model Owner                          Client
                        |                                  |
                  POST /push-model                   GET /tdx_quote
                  (model URL)                        GET /model-hash
                        |                            POST /v1/chat/completions
                        v                                  |
                ┌───────────────────────────────────────────┐
                │              CVM (TEE)                    │
                │                                           │
                │  ┌─────────────────────┐                  │
                │  │  nginx-cert-manager  │  (TLS + EKM)    │
                │  │  :443               │                  │
                │  └──┬──┬──┬──┬────────┘                  │
                │     │  │  │  │                            │
                │     │  │  │  └─► attestation-service      │
                │     │  │  │      :8080                    │
                │     │  │  │                               │
                │     │  │  └────► model-service             │
                │     │  │         :8001                    │
                │     │  │         /push-model              │
                │     │  │         /model-hash              │
                │     │  │                                  │
                │     │  └───────► vllm                     │
                │     │            :8000                    │
                │     │            /v1/chat/completions     │
                │     │                                    │
                │     └──── shared volume: model-store ────┘
                │            /models/current
                └───────────────────────────────────────────┘
```

## Execution Flow

### Phase 1 - Boot
CVM starts with nginx, attestation-service, model-service, and vLLM container. vLLM has no model to serve yet.

### Phase 2 - Model Push
Model owner POSTs `{"model_url": "https://huggingface.co/openai/gpt-oss-120b"}` to `/push-model`. Model-service downloads weights from HuggingFace into the shared volume. Endpoint is permanently disabled after first push. vLLM loads model from `/models/current`.

### Phase 3 - Client Verification
Client connects via HTTPS (RA-TLS in production). Gets TDX quote from `/tdx_quote`. Fetches model hash from `/model-hash`. Compares hash with expected value from model provider. If both checks pass, proceeds with inference via `/v1/chat/completions`.

## Quick Start

### Development (with mock vLLM)

```bash
cd cvm
make dev-up       # Start all services with mock vLLM
make test-all     # Run integration tests
make dev-down     # Stop services
```

### Full workflow

```bash
cd cvm
make dev-full     # Build, start, wait, test, stop
```

### Push a real model

```bash
# Start CVM services
cd cvm && make dev-up

# Push model weights (model-service downloads from HuggingFace)
python examples/push_model.py \
    --endpoint https://localhost \
    --model-url https://huggingface.co/openai/gpt-oss-120b \
    --dev

# Wait for download + vLLM loading (~90 min for large models)
# Then run full test suite
make test-all

# Client verification
python client/verify.py --endpoint https://localhost --dev
```

## Repository Structure

```
cvm-model-serving/
├── README.md                              # This file
├── CLAUDE.md                              # Dev guidance
├── cvm/
│   ├── docker-compose.yml                 # Production config
│   ├── docker-compose.dev.override.yml    # Dev/test config with mocks
│   ├── Makefile                           # Build/test commands
│   ├── test_cvm.py                        # Integration test suite
│   ├── requirements_test.txt              # Test dependencies
│   │
│   ├── cert-manager/                      # Nginx + TLS + EKM (from Shade)
│   │   ├── Dockerfile
│   │   ├── ngx_http_ekm_module/           # TLS EKM channel binding module
│   │   ├── nginx_conf/                    # Nginx config templates
│   │   └── src/cert_manager/              # Certificate management
│   │
│   ├── attestation-service/               # TDX attestation (from Shade)
│   │   ├── Dockerfile
│   │   ├── attestation_service.py
│   │   └── tests/
│   │
│   ├── model-service/                     # Model push & hash (NEW)
│   │   ├── Dockerfile
│   │   ├── model_service.py               # FastAPI: /push-model, /model-hash
│   │   ├── pyproject.toml
│   │   └── tests/
│   │
│   └── vllm-patch/                        # vLLM patches (from Umbra)
│       ├── Dockerfile
│       └── harmony-streaming-tool-call-fallback.patch
│
├── client/
│   └── verify.py                          # Client verification script
│
└── examples/
    └── push_model.py                      # Example: push model to CVM
```

## Components

### model-service (NEW)
FastAPI service managing model weights inside the CVM:

- **`POST /push-model`** - Accepts `{"model_url": "...", "hf_token": "..."}`. Downloads model from HuggingFace into `/models/current`. One-time only: returns 403 after first push.
- **`GET /model-hash`** - Returns deterministic SHA-256 hash of all model files. Computed inside the CVM, trustworthy via attestation.
- **`GET /health`** - Health check with model status.

### cert-manager (from Shade)
Nginx reverse proxy with TLS termination, Let's Encrypt certificate management, and TLS EKM channel binding (RFC 9266). Routes:
- `/push-model`, `/model-hash` → model-service
- `/v1/*` → vLLM
- `/tdx_quote` → attestation-service

### attestation-service (from Shade)
TDX attestation using dstack_sdk. Validates EKM headers with HMAC-SHA256 to prevent forgery.

### vllm-patch (from Umbra)
Custom vLLM Docker image with Harmony streaming tool call fallback patch.

## Security Model

1. **CVM Isolation**: All services run inside a Confidential Virtual Machine (Intel TDX).
2. **RA-TLS**: TLS termination inside the TEE with EKM channel binding.
3. **Attestation**: Clients verify TDX quotes to confirm code integrity.
4. **Model Integrity**: SHA-256 hash computed inside CVM; clients compare with known good hash.
5. **One-time Push**: `/push-model` is permanently disabled after first use.

## Forking & Customization

1. Fork this repository
2. Replace `openai/gpt-oss-120b` with your model
3. Update `docker-compose.yml` with your domain and vLLM config
4. Deploy to a CVM-capable environment (e.g., Phala Cloud)

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `EKM_SHARED_SECRET` | HMAC key for EKM header validation | Required in prod |
| `DOMAIN` | Domain for TLS certificate | `localhost` (dev) |
| `DEV_MODE` | Enable development mode | `false` |
| `MODEL_DIR` | Model storage path | `/models/current` |

## Testing

```bash
# Run all tests
cd cvm && make test-all

# Individual tests
make test-health
make test-push-model
make test-model-hash
make test-attestation
make test-vllm
make test-certificate
make test-client-verification
```
