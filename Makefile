SHELL := /bin/bash

# ─── Shade framework config ─────────────────────────────────
COMPOSE_FILE = docker-compose.yml
DEV_COMPOSE_FILE = docker-compose.dev.override.yml
NGINX_URL = https://localhost
NGINX_HTTP_URL = http://localhost
DEV ?= true
DEV_FLAG = $(if $(filter true,$(DEV)),--dev,)
PYTHON_RUNNER ?= uv run

# ─── Application config ─────────────────────────────────────
MODEL_SERVICE  ?= http://localhost:8001
VLLM_ENDPOINT  ?= http://localhost:8000
MODEL_NAME     ?= openai/gpt-oss-120b
CURL            = curl -s

_PUSH_URL     = $(MODEL_SERVICE)/push-model
_HASH_URL     = $(MODEL_SERVICE)/model-hash
_VLLM_URL     = $(VLLM_ENDPOINT)

MODEL_DIR          = model-owner/models/$(notdir $(MODEL_NAME))
MODEL_ARCHIVE      = $(MODEL_DIR).tar
PUSH_TOKEN_FILE    = model-owner/push-token.txt
MODEL_HASH_FILE    = model-owner/model-hash.txt
CVM_ENV            = .env

.PHONY: help \
        app-dev-up app-dev-down app-dev-logs app-dev-clean \
        dev-up dev-down dev-logs dev-clean \
        docker-up docker-down docker-logs prod-clean \
        shade-build shade-validate wait-services \
        test-all test-health test-attestation test-app test-redirect \
        test-acme test-certificate test-cors test-ekm-headers unit-tests \
        verify-token step-1-hash-local step-2-push \
        step-3-push-repeat step-4-user-verify

# ─── Help ───────────────────────────────────────────────────
help:
	@echo "Private Model Serving (Shade Framework)"
	@echo "========================================"
	@echo ""
	@echo "App dev (no TLS, no attestation):"
	@echo "  app-dev-up        Start vllm + model-service"
	@echo "  app-dev-down      Stop"
	@echo "  app-dev-logs      Follow logs"
	@echo "  app-dev-clean     Stop + remove volumes"
	@echo ""
	@echo "Dev (app + nginx + attestation, self-signed TLS):"
	@echo "  dev-up            Start full dev stack"
	@echo "  dev-down          Stop"
	@echo "  dev-logs          Follow logs"
	@echo "  dev-clean         Stop + remove volumes"
	@echo ""
	@echo "Prod (shade build, real TLS):"
	@echo "  docker-up         Build + start"
	@echo "  docker-down       Stop"
	@echo "  docker-logs       Follow logs"
	@echo "  prod-clean        Stop + remove volumes"
	@echo ""
	@echo "Scenario:"
	@echo "  step-1-hash-local   Model Owner computes hash locally"
	@echo "  step-2-push         Model Owner pushes weights to CVM"
	@echo "  step-3-push-repeat  Verify double push is blocked"
	@echo "  step-4-user-verify  User verifies hash + runs inference"
	@echo ""
	@echo "Tests:"
	@echo "  test-all          Run all integration tests"
	@echo "  unit-tests        Run shade unit tests"

# ─── App dev (local HTTP, no TLS, no nginx, no attestation) ──
app-dev-up:
	@clear
	@echo "🔥 Starting app services (local HTTP, no TLS)..."
	@echo "  model-service → http://localhost:8001"
	@echo "  vllm          → http://localhost:8000"
	@echo ""
	docker compose -f $(COMPOSE_FILE) up -d --build

app-dev-down:
	@clear
	docker compose -f $(COMPOSE_FILE) down

app-dev-logs:
	@clear
	docker compose -f $(COMPOSE_FILE) logs -f

app-dev-clean:
	@clear
	docker compose -f $(COMPOSE_FILE) down -v --remove-orphans

app-dev-wait:
	@echo "Waiting for vLLM to be ready (loading 120B model, this takes a while)..."
	@until curl -sf http://localhost:8000/health >/dev/null 2>&1; do \
		printf "."; sleep 10; \
	done
	@echo ""
	@echo "vLLM is ready!"


app-dev-test:
	@echo ""
	@echo "═══ 🔥 Push model 🔥 ═══"
	cd model-owner && make Push
	@echo ""
	@clear
	@echo "🔥 App dev tests (local HTTP, no TLS) 🔥"

	@echo "═══ 🔥 Waiting for vLLM 🔥 ═══"
	$(MAKE) app-dev-wait
	@echo ""
	@echo "═══ 🔥 Model owner tests 🔥 ═══"
	cd model-owner && PROXY_ENDPOINT=http://localhost:8001 uv run pytest test_model_owner.py -v
	@echo ""
	@echo "═══ 🔥 User tests 🔥 ═══"
	cd user && PROXY_ENDPOINT=http://localhost:8001 VLLM_ENDPOINT=http://localhost:8000 uv run pytest test_user.py -v

# ─── Dev (app + nginx + attestation, self-signed TLS) ────────
# In dev mode there is only one endpoint https://localhost).
# Nginx is the single entry point. It routes everything:
#   - https://localhost/push-model → model-service:8001
#   - https://localhost/model-hash → model-service:8001
#   - https://localhost/v1/* → vllm:8000
#   - https://localhost/tdx_quote → attestation:8080

dev-up:
	@echo "Starting full dev stack..."
	docker compose -f $(COMPOSE_FILE) -f $(DEV_COMPOSE_FILE) up -d --build

dev-down:
	docker compose -f $(COMPOSE_FILE) -f $(DEV_COMPOSE_FILE) down

dev-logs:
	clear
	docker compose -f $(COMPOSE_FILE) -f $(DEV_COMPOSE_FILE) logs -f

dev-clean:
	docker compose -f $(COMPOSE_FILE) -f $(DEV_COMPOSE_FILE) down -v --remove-orphans

dev-wait:
	@echo "Waiting for vLLM to be ready..."
	@until curl -skf https://localhost/health >/dev/null 2>&1; do \
		printf "."; sleep 10; \
	done
	@echo ""
	@echo "vLLM is ready!"

dev-test:
	@clear
	@echo "🔒 Dev tests (HTTPS, self-signed TLS) 🔒"
	@echo ""
	@echo "═══ 🔒 Push model 🔒 ═══"
	cd model-owner && make push ENDPOINT=https://localhost CURL="curl -sk"
	@echo ""
	@echo "═══ 🔒 Waiting for vLLM 🔒 ═══"
	$(MAKE) dev-wait
	@echo ""
	@echo "═══ 🔒 Model owner tests 🔒 ═══"
	cd model-owner && PROXY_ENDPOINT=https://localhost VERIFY_TLS=0 uv run pytest test_model_owner.py -v
	@echo ""
	@echo "═══ 🔒 User tests 🔒 ═══"
	cd user && PROXY_ENDPOINT=https://localhost VERIFY_TLS=0 uv run pytest test_user.py -v

# ─── Prod (shade build, real TLS) ────────────────────────────
docker-up: shade-build
	docker compose -f docker-compose.shade.yml up -d --build

docker-down:
	docker compose -f docker-compose.shade.yml down -v

docker-logs:
	docker compose -f docker-compose.shade.yml logs -f

prod-clean:
	docker compose -f docker-compose.shade.yml down -v --remove-orphans

# ─── Shade infrastructure ───────────────────────────────────
shade-build:
	$(PYTHON_RUNNER) shade build

shade-validate:
	$(PYTHON_RUNNER) shade validate

wait-services:
	$(PYTHON_RUNNER) test_cvm.py $(DEV_FLAG) --wait --base-url $(NGINX_URL)

# ─── Shade integration tests ────────────────────────────────
test-all:
	$(PYTHON_RUNNER) test_cvm.py $(DEV_FLAG) --all --base-url $(NGINX_URL) --http-url $(NGINX_HTTP_URL)

test-health:
	$(PYTHON_RUNNER) test_cvm.py $(DEV_FLAG) --health --base-url $(NGINX_URL)

test-attestation:
	$(PYTHON_RUNNER) test_cvm.py $(DEV_FLAG) --attestation --base-url $(NGINX_URL)

test-app:
	$(PYTHON_RUNNER) test_cvm.py $(DEV_FLAG) --app --base-url $(NGINX_URL)

test-redirect:
	$(PYTHON_RUNNER) test_cvm.py $(DEV_FLAG) --redirect --base-url $(NGINX_URL) --http-url $(NGINX_HTTP_URL)

test-acme:
	$(PYTHON_RUNNER) test_cvm.py $(DEV_FLAG) --acme --base-url $(NGINX_URL) --http-url $(NGINX_HTTP_URL)

test-certificate:
	$(PYTHON_RUNNER) test_cvm.py $(DEV_FLAG) --certificate --base-url $(NGINX_URL)

test-cors:
	$(PYTHON_RUNNER) test_cvm.py $(DEV_FLAG) --cors --base-url $(NGINX_URL)

test-ekm-headers:
	$(PYTHON_RUNNER) test_cvm.py $(DEV_FLAG) --ekm-headers --base-url $(NGINX_URL)

unit-tests:
	$(PYTHON_RUNNER) pytest --cov=shade --cov-report=term-missing --cov-fail-under=98 tests/ -v

# ─── Verify token: push-token.txt == .env ────────────────────
verify-token:
	@diff -q <(cat $(PUSH_TOKEN_FILE)) <(grep '^PUSH_TOKEN=' $(CVM_ENV) | cut -d= -f2) \
		&& echo "verify-token: OK" \
		|| { echo "verify-token: KO — $(PUSH_TOKEN_FILE) and $(CVM_ENV) differ"; exit 1; }

# ─── Step 1: Model Owner computes local hash ─────────────────
step-1-hash-local:
	@echo ""
	@echo "══════════════════════════════════════════════════════"
	@echo "  MODEL OWNER — Step 1: Compute model hash locally"
	@echo "══════════════════════════════════════════════════════"
	@test -d $(MODEL_DIR) || { echo "Error: $(MODEL_DIR) not found. Download the model first."; exit 1; }
	@python3 model-owner/compute_hash.py $(MODEL_DIR) \
		| tee /dev/stderr | grep '^sha256:' > $(MODEL_HASH_FILE)
	@echo ""
	@echo "Hash saved to $(MODEL_HASH_FILE)"
	@echo "→ Model Owner publishes this hash to users: $$(cat $(MODEL_HASH_FILE))"

# ─── Step 2: Model Owner pushes weights ──────────────────────
step-2-push:
	@echo ""
	@echo "══════════════════════════════════════════════════════"
	@echo "  MODEL OWNER — Step 2: Push model weights to CVM"
	@echo "══════════════════════════════════════════════════════"
	@test -f $(PUSH_TOKEN_FILE) || { echo "Error: no token in $(PUSH_TOKEN_FILE)."; exit 1; }
	@test -f $(MODEL_HASH_FILE) || { echo "Error: no hash. Run step-1-hash-local first."; exit 1; }
	@test -f $(MODEL_ARCHIVE) || { echo "Error: $(MODEL_ARCHIVE) not found. Archive the model first."; exit 1; }
	@echo "Pushing to $(_PUSH_URL)"
	@echo "  Token:         $(PUSH_TOKEN_FILE)"
	@echo "  Expected hash: $$(cat $(MODEL_HASH_FILE))"
	@echo "  Archive:       $(MODEL_ARCHIVE)"
	@echo ""
	@HTTP_CODE=$$($(CURL) -o /tmp/push-response.json -w "%{http_code}" \
		-X POST $(_PUSH_URL) \
		-H "Authorization: Bearer $$(cat $(PUSH_TOKEN_FILE))" \
		-F "file=@$(MODEL_ARCHIVE)" \
		-F "expected_hash=$$(cat $(MODEL_HASH_FILE))"); \
	echo ""; \
	cat /tmp/push-response.json; echo ""; \
	echo "HTTP $$HTTP_CODE"; \
	if [ "$$HTTP_CODE" = "200" ]; then \
		echo ""; \
		echo "CVM extracted the archive, computed SHA-256, compared with expected hash."; \
		echo "Push endpoint is now permanently disabled (410 Gone)."; \
	else \
		echo "FAIL — push returned HTTP $$HTTP_CODE"; exit 1; \
	fi

# ─── Step 3: Verify double push is blocked ────────────────────
step-3-push-repeat:
	@echo ""
	@echo "══════════════════════════════════════════════════════"
	@echo "  MODEL OWNER — Step 3: Verify double push is blocked"
	@echo "══════════════════════════════════════════════════════"
	@echo "POST $(_PUSH_URL)  (expecting 410 Gone)"
	@HTTP_CODE=$$($(CURL) -o /dev/null -w "%{http_code}" -X POST $(_PUSH_URL) \
		-H "Authorization: Bearer $$(cat $(PUSH_TOKEN_FILE))" \
		-F "file=@/dev/null"); \
	echo "HTTP $$HTTP_CODE"; \
	if [ "$$HTTP_CODE" = "410" ]; then \
		echo "PASS — second push correctly rejected (410 Gone)"; \
	else \
		echo "FAIL — expected 410, got $$HTTP_CODE"; exit 1; \
	fi

# ─── Step 4: User verifies hash + runs inference ─────────────
step-4-user-verify:
	@echo ""
	@echo "══════════════════════════════════════════════════════"
	@echo "  USER — Step 4: Verify model hash + run inference"
	@echo "══════════════════════════════════════════════════════"
	@test -f $(MODEL_HASH_FILE) || { echo "Error: no expected hash. The model owner must publish it first."; exit 1; }
	@echo "User received expected hash from model owner: $$(cat $(MODEL_HASH_FILE))"
	@echo ""
	cd user && uv run pytest test_user.py -v
