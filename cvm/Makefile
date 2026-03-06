SHELL := /bin/bash

# Docker Compose files
COMPOSE_FILE = docker-compose.yml
DEV_COMPOSE_FILE = docker-compose.dev.override.yml
LOCAL_MACOS_COMPOSE_FILE = docker-compose.dev-local-macos.override.yml

# Service endpoints - all traffic goes through nginx proxy
NGINX_URL = https://localhost
NGINX_HTTP_URL = http://localhost

# Development mode flag - set DEV=false for production testing
DEV ?= true
DEV_FLAG = $(if $(filter true,$(DEV)),--dev,)

# Python runner command
PYTHON_RUNNER ?= uv run

.PHONY: help docker-login dev-full dev-up dev-down dev-local-macos-up dev-local-macos-down test-all test-health test-push-model test-model-hash test-attestation test-vllm test-redirect test-acme test-certificate test-ekm-headers test-client-verification wait-services

docker-login:
	@gh auth token | docker login ghcr.io -u $(shell gh api user -q .login) --password-stdin

help:
	@echo "CVM Model Serving - Build, Run, and Test"
	@echo "========================================="
	@echo ""
	@echo "Development Commands:"
	@echo "  dev-full      Full dev workflow: build, up, wait, test"
	@echo "  dev-up        Start services in development mode"
	@echo "  dev-down      Stop development services"
	@echo ""
	@echo "Test Commands:"
	@echo "  test-all               Run all tests"
	@echo "  test-health            Test health endpoint"
	@echo "  test-push-model        Test model push endpoint"
	@echo "  test-model-hash        Test model hash endpoint"
	@echo "  test-attestation       Test attestation service"
	@echo "  test-vllm              Test vLLM inference"
	@echo "  test-redirect          Test HTTP to HTTPS redirect"
	@echo "  test-acme              Test ACME challenge endpoint"
	@echo "  test-certificate       Test SSL certificate"
	@echo "  test-ekm-headers       Test EKM header forwarding (dev only)"
	@echo "  test-client-verification  Test full client verification flow"
	@echo ""
	@echo "Environment Variables:"
	@echo "  DEV             Set to 'false' for production mode testing"
	@echo "                  (default: true - development mode)"
	@echo "  PYTHON_RUNNER   Set how to run python scripts"
	@echo "                  (default: uv run)"
	@echo ""
	@echo "Examples:"
	@echo "  make dev-full                          # Full development workflow"
	@echo "  make dev-up                            # Start dev docker compose"
	@echo "  make test-push-model                   # Test only model push"
	@echo "  DEV=false make test-all                # Run all tests in production mode"

# Development workflow
dev-full: dev-down dev-up
	DEV=true $(MAKE) wait-services
	DEV=true $(MAKE) test-all
	$(MAKE) dev-down

dev-up:
	@echo "Starting services in development mode..."
	docker compose -f $(COMPOSE_FILE) -f $(DEV_COMPOSE_FILE) up -d --build

dev-down:
	@echo "Stopping development services..."
	docker compose -f $(COMPOSE_FILE) -f $(DEV_COMPOSE_FILE) down

dev-local-macos-up: docker-login
	docker compose -f $(COMPOSE_FILE) -f $(LOCAL_MACOS_COMPOSE_FILE) up -d --build

dev-local-macos-down:
	docker compose -f $(COMPOSE_FILE) -f $(LOCAL_MACOS_COMPOSE_FILE) down

wait-services:
	$(PYTHON_RUNNER) test_cvm.py $(DEV_FLAG) --wait --base-url $(NGINX_URL)

test-all:
	$(PYTHON_RUNNER) test_cvm.py $(DEV_FLAG) --all --base-url $(NGINX_URL) --http-url $(NGINX_HTTP_URL)

test-health:
	$(PYTHON_RUNNER) test_cvm.py $(DEV_FLAG) --health --base-url $(NGINX_URL)

test-push-model:
	$(PYTHON_RUNNER) test_cvm.py $(DEV_FLAG) --push-model --base-url $(NGINX_URL)

test-model-hash:
	$(PYTHON_RUNNER) test_cvm.py $(DEV_FLAG) --model-hash --base-url $(NGINX_URL)

test-attestation:
	$(PYTHON_RUNNER) test_cvm.py $(DEV_FLAG) --attestation --base-url $(NGINX_URL)

test-vllm:
	$(PYTHON_RUNNER) test_cvm.py $(DEV_FLAG) --vllm --base-url $(NGINX_URL)

test-redirect:
	$(PYTHON_RUNNER) test_cvm.py $(DEV_FLAG) --redirect --base-url $(NGINX_URL) --http-url $(NGINX_HTTP_URL)

test-acme:
	$(PYTHON_RUNNER) test_cvm.py $(DEV_FLAG) --acme --base-url $(NGINX_URL) --http-url $(NGINX_HTTP_URL)

test-certificate:
	$(PYTHON_RUNNER) test_cvm.py $(DEV_FLAG) --certificate --base-url $(NGINX_URL)

test-ekm-headers:
	$(PYTHON_RUNNER) test_cvm.py $(DEV_FLAG) --ekm-headers --base-url $(NGINX_URL)

test-client-verification:
	$(PYTHON_RUNNER) test_cvm.py $(DEV_FLAG) --client-verification --base-url $(NGINX_URL)
