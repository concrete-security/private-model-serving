# Private Model Serving

A reference implementation demonstrating how a frontier AI lab (e.g., OpenAI, Anthropic, Mistral AI) can:

- **Deploy an inference service** (vLLM) inside a Confidential Virtual Machine (CVM)
- **Securely push model weights** into the CVM (one-time push in this v1; update/rotation planned for v2)
- **Allow clients to verify** the CVM attestation and the integrity (hash) of the served model weights

## Entities

| Entity | Role |
|--------|------|
| **Model Owner** | Computes model hash, pushes weights |
| **End User** | Verifies attestation + model hash, runs inference |
| **TEE Provider** | Hosts the CVM (here: [Phala Cloud](https://phala.network/)) |

## Prerequisites

- Python 3.11+, [uv](https://docs.astral.sh/uv/)
- Rust toolchain (for Atlas Python binding)
- Docker with Compose
- A Phala Cloud account + API key (for CVM deployment)

## Setup

```bash
# Clone
git clone https://github.com/concrete-security/private-model-serving.git
cd private-model-serving

# Install Shade CLI (TEE wrapper)
uv tool install shade --from git+https://github.com/concrete-security/shade.git@feat/shade-dev-mode

# Build Atlas Python binding (attested TLS)
make atls-setup
```

## Built with

- **[Shade](https://github.com/concrete-security/shade)** — wraps the application to make it TEE-friendly: adds TLS termination, TDX attestation service, and nginx reverse proxy. You declare routes and domain in `shade.yml`, then `shade build` merges it with your `docker-compose.yml` into a CVM-ready deployment.
- **[Atlas](https://github.com/concrete-security/atlas)** — provides attested TLS (aTLS) for secure communication between entities. Verifies TDX quotes, bootchain, app compose hash, and binds attestation to the TLS session via EKM (RFC 9266).

## Architecture

```
            Model Owner                          End User
                |                                    |
          POST /push-model (aTLS)            GET /model-hash (aTLS)
                |                            POST /v1/chat/completions (aTLS)
                v                                    v
        ┌────────────────────────────────────────────────┐
        │                CVM (TEE)                       │
        │                                                │
        │  nginx :443  (TLS + EKM session binding)       │
        │     ├── /tdx_quote    → attestation-service    │
        │     ├── /push-model   → model-service :8001    │
        │     ├── /model-hash   → model-service :8001    │
        │     └── /v1/*         → vllm :8000             │
        │                                                │
        │  shared volume: /models/current                │
        └────────────────────────────────────────────────┘
```

## 1. Model Owner: local development

Test the application locally (no TLS, no attestation):

```bash
make app-dev-up       # Start vllm + model-service on localhost
make app-dev-test     # Push model + run tests
make app-dev-down
```

## 2. Deploy to Phala Cloud (TEE provider)

Phala Cloud provides Intel TDX CVMs. The deployment workflow:

```bash
# Generate the TEE-ready compose (adds nginx + attestation-service via Shade)
make shade-build

# Deploy a new CVM
make phala-deploy

# Or update an existing CVM and restart
make phala-update

# Monitor
make phala-status
make phala-logs
```

`phala-deploy` does: provision CVM → encrypt env vars → commit → poll until online.

## 3. aTLS workflow (attested TLS via Atlas)

Once the CVM is deployed, all interactions go through aTLS. Atlas verifies TDX attestation before any data is exchanged.

```bash
# Build atlas Python binding (once)
make atls-setup

# Generate attestation policy from the live CVM
# Fetches bootchain measurements (MRTD, RTMR0-2), OS image hash, app compose
make atls-policy

# Model Owner: push weights via aTLS
make atls-model-owner-push

# End User: verify model integrity (local hash vs CVM hash via aTLS)
make atls-hash-verify

# End User: run inference via aTLS
make atls-user-infer
```

> **Note**: the first inference request on CPU can be slow (>60s) and may timeout due to nginx's default 60s `proxy_read_timeout`. Subsequent requests are faster once the model is warmed up. This could be fixed in v2 by adding configurable `proxy_read_timeout` per route in Shade's nginx configuration.

## Endpoints

### attestation-service (via Atlas aTLS)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/tdx_quote` | POST | Returns TDX quote with event log. Called automatically by Atlas during the aTLS handshake — not called directly by users. |

### model-service

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/push-model` | POST | Upload model weights (tar archive + Bearer token). One-time only — returns 410 Gone on repeat. |
| `/model-hash` | GET | SHA-256 hash of the served model files. Returns 404 if no model pushed yet. |
| `/health` | GET | Health check with model status. |
| `/ready` | GET | Returns 200 only after model is pushed. Used by vLLM to know when to start. |

## Repository structure

```
├── app/                     # model-service (FastAPI): /push-model, /model-hash, /health, /ready
├── scenarios/model-owner/             # Model owner: push token, local hash, model archive
├── scenarios/user/                    # End user: expected hash for verification
├── scripts/encrypt_env.py   # Phala env encryption (x25519 + AES-256-GCM)
├── docker-compose.yml       # App services (vLLM + model-service)
├── shade.yml                # Shade config (routes, domain, TLS)
├── docker-compose.shade.yml # Generated by shade build (DO NOT EDIT)
├── policy.json              # Generated by make atls-policy (DO NOT EDIT)
├── Makefile                 # All targets
└── .env                     # PUSH_TOKEN (not committed)
```

## Tests

```bash
# Unit tests (model-service)
cd app && VIRTUAL_ENV= uv sync --group test && .venv/bin/python -m pytest tests/ -v

# Integration tests (start containers, push model, run tests, stop)
make app-dev-test
```
