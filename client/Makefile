SHELL := /bin/bash

# MODEL_NAME ?= openai/gpt-oss-120b
MODEL_NAME ?= Qwen/Qwen2.5-1.5B-Instruct
MODEL_DIR = .models/$(notdir $(MODEL_NAME))
MODEL_ARCHIVE = $(MODEL_DIR).tar
ENDPOINT ?= https://localhost
CURL = curl -sk

.PHONY: help download archive hash push push-repeat remote-hash verify clean

help:
	@echo "Client — Download, archive, hash, push model to CVM"
	@echo ""
	@echo "  make download      Download model from HuggingFace (safetensors only)"
	@echo "  make archive       Create tar archive"
	@echo "  make hash          Compute local SHA-256 hash of model files"
	@echo "  make push          Push tar archive to CVM /push-model"
	@echo "  make push-repeat   Verify /push-model returns 403 after first push"
	@echo "  make remote-hash   Fetch model hash from CVM /model-hash"
	@echo "  make verify        Full client verification (attest + hash + inference)"
	@echo "  make clean         Remove model files and archive"
	@echo ""
	@echo "Variables:"
	@echo "  MODEL_NAME  HuggingFace model (default: openai/gpt-oss-120b)"
	@echo "  ENDPOINT    CVM URL (default: https://localhost)"

download:
	huggingface-cli download $(MODEL_NAME) \
		--local-dir $(MODEL_DIR) \
		--exclude "*.bin" "*.pt" "*.ckpt" "consolidated*"
	@echo ""
	@du -sh $(MODEL_DIR)

archive:
	@if ! command -v pv &>/dev/null; then \
		echo "Installing pv for progress bar..."; \
		brew install pv; \
	fi
	@SIZE=$$(du -s $(MODEL_DIR) | awk '{print $$1}'); \
	tar -cf - -C $(MODEL_DIR) . | pv -s $${SIZE}k > $(MODEL_ARCHIVE)
	@echo ""
	@du -sh $(MODEL_ARCHIVE)

hash:
	python3 compute_hash.py $(MODEL_DIR)

push:
	@echo "POST $(ENDPOINT)/push-model  ← $(MODEL_ARCHIVE)"
	@$(CURL) -X POST $(ENDPOINT)/push-model \
		-F "file=@$(MODEL_ARCHIVE)" \
		-w "\nHTTP %{http_code}\n"

push-repeat:
	@echo "POST $(ENDPOINT)/push-model  (should return 403)"
	@$(CURL) -X POST $(ENDPOINT)/push-model \
		-F "file=@$(MODEL_ARCHIVE)" \
		-w "\nHTTP %{http_code}\n"

remote-hash:
	@echo "GET $(ENDPOINT)/model-hash"
	@$(CURL) $(ENDPOINT)/model-hash | python3 -m json.tool

verify:
	python3 verify.py --endpoint $(ENDPOINT) --dev

clean:
	rm -rf $(MODEL_DIR) $(MODEL_ARCHIVE)
