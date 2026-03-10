SHELL := /bin/bash

# FULL_MODEL_NAME ?= Qwen/Qwen2.5-1.5B-Instruct
FULL_MODEL_NAME ?= Qwen/Qwen2.5-0.5B-Instruct
MODEL_NAME := $(notdir $(FULL_MODEL_NAME))

MODEL_DIR := models/$(MODEL_NAME)
MODEL_ARCHIVE := $(MODEL_DIR).tar

ENDPOINT ?= http://localhost:8001
PUSH_TOKEN_FILE ?= push-token.txt
MODEL_HASH_FILE ?= model-hash.txt
CURL = curl -sk

.PHONY:  download archive hash-local hash-remote push health test clean

download:
	@clear
	hf download $(FULL_MODEL_NAME) \
		--local-dir $(MODEL_DIR) \
		--exclude "*.bin" "*.pt" "*.ckpt" "consolidated*" "original/*"
	@echo ""
	@du -sh $(MODEL_DIR)
	# ~1G  models/Qwen2.5-0.5B-Instruct


archive:
	@clear
	tar -cf - -C $(MODEL_DIR) . | pv > $(MODEL_ARCHIVE)
	du -sh $(MODEL_ARCHIVE)

hash-local:
	@python3 compute_hash.py $(MODEL_DIR) | tee /dev/stderr | grep '^sha256:' > $(MODEL_HASH_FILE)
	@echo "Hash saved to $(MODEL_HASH_FILE)"

push:
	@test -f $(PUSH_TOKEN_FILE) || { echo "Error: $(PUSH_TOKEN_FILE) not found."; exit 1; }
	@test -f $(MODEL_HASH_FILE) || { echo "Error: $(MODEL_HASH_FILE) not found. Run 'make hash-local' first."; exit 1; }

	@echo "POST $(ENDPOINT)/push-model  ← $(MODEL_ARCHIVE)"
	@echo "  Token: $(PUSH_TOKEN_FILE)"
	@echo "  Expected hash: $$(cat $(MODEL_HASH_FILE))"
	@curl -k -# -X POST $(ENDPOINT)/push-model \
		-H "Authorization: Bearer $$(cat $(PUSH_TOKEN_FILE))" \
		-F "file=@$(MODEL_ARCHIVE)" \
		-F "expected_hash=$$(cat $(MODEL_HASH_FILE))" \
		-w "\nHTTP %{http_code}\n" 2>&1

hash-remote:
	@echo "GET $(ENDPOINT)/model-hash"
	@$(CURL) $(ENDPOINT)/model-hash | python3 -m json.tool

health:
	@$(CURL) $(ENDPOINT)/health | python3 -m json.tool

test:
	uv run pytest test_model_owner.py -v

clean:
	rm -rf $(MODEL_DIR) $(MODEL_ARCHIVE) $(MODEL_HASH_FILE)
