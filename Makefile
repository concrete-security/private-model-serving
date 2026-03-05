SHELL := /bin/bash

# ─── Configuration ────────────────────────────────────────────
MODEL_SERVICE  ?= http://localhost:8001
VLLM_ENDPOINT  ?= http://localhost:8000
MODEL_NAME     ?= openai/gpt-oss-120b
CURL            = curl -s

# Dev mode only — direct HTTP to each service.
# TODO: prod mode (through Shade nginx) not yet implemented.
_PUSH_URL     = $(MODEL_SERVICE)/push-model
_HASH_URL     = $(MODEL_SERVICE)/model-hash
_VLLM_URL     = $(VLLM_ENDPOINT)

# Derived paths
MODEL_DIR          = model-owner/models/$(notdir $(MODEL_NAME))
MODEL_ARCHIVE      = $(MODEL_DIR).tar
PUSH_TOKEN_FILE    = model-owner/push-token.txt
MODEL_HASH_FILE    = model-owner/model-hash.txt
CVM_ENV            = cvm/.env

.PHONY: cvm-up cvm-down cvm-wait \
        verify-token step-1-hash-local step-2-push \
        step-3-push-repeat step-4-user-verify

# ─── CVM management ──────────────────────────────────────────
cvm-up:
	@echo ""
	@echo "══════════════════════════════════════════════════════"
	@echo "  CLOUD PROVIDER — Starting application services"
	@echo "══════════════════════════════════════════════════════"
	$(MAKE) -C cvm dev-up

cvm-down:
	$(MAKE) -C cvm dev-down

cvm-wait:
	$(MAKE) -C cvm wait-services

# ─── Verify token: push-token.txt == cvm/.env ────────────────
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

