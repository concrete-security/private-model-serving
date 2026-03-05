SHELL := /bin/bash

MODEL_NAME = openai/gpt-oss-120b
MODEL_DIR = models/openai_gpt-oss-120b
MODEL_ARCHIVE = $(MODEL_DIR).tar.gz
ENDPOINT ?= https://localhost

.PHONY: help download compress hash push verify clean

help:
	@echo "Client - Download, compress, hash, push gpt-oss-120b"
	@echo ""
	@echo "  download   Download model from HuggingFace"
	@echo "  compress   Create tar.gz archive"
	@echo "  hash       Compute local SHA-256 hash"
	@echo "  push       Push archive to CVM"
	@echo "  verify     Full verification (attest + hash + inference)"
	@echo "  clean      Remove model files and archive"

download:
	huggingface-cli download $(MODEL_NAME) \
		--local-dir $(MODEL_DIR) \
		--exclude "metal/*" "onnx/*" "*.gguf"

compress:
	tar czf $(MODEL_ARCHIVE) -C $(MODEL_DIR) .

hash:
	python compute_hash.py $(MODEL_DIR)

push:
	python ../examples/push_model.py --endpoint $(ENDPOINT) --file $(MODEL_ARCHIVE) --dev

verify:
	python verify.py --endpoint $(ENDPOINT) --dev

clean:
	rm -rf $(MODEL_DIR) $(MODEL_ARCHIVE)
