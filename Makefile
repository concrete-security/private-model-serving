SHELL := /bin/bash
.DEFAULT_GOAL := help


# ─── Config ────────────────────────────────────────────────
COMPOSE_FILE       = docker-compose.yml
COMPOSE_DEV        = -f docker-compose.yml -f docker-compose.dev.yml
MODEL_NAME         ?= Qwen/Qwen2.5-0.5B-Instruct
MODEL_DIR          = scenarios/model-owner/models/$(notdir $(MODEL_NAME))
MODEL_ARCHIVE      = $(MODEL_DIR).tar
PUSH_TOKEN_FILE    = scenarios/model-owner/push-token.txt
MODEL_HASH_FILE    = scenarios/model-owner/model-hash.txt
CVM_ENV            = .env
CVM_NAME           ?= pms-$(shell date +%s)
# CVM_ID           ?= $(shell cat .cvm_id 2>/dev/null)
CVM_ID             ?= app_74d07bcb818413b1b5501dde7d09b818467c638c
SHADE_COMPOSE_FILE = docker-compose.shade.yml
PHALA_BOOT_TIMEOUT ?= 600

# ─── Phala LOG Containers URL ─────────────────────────────────────
PHALA_LOG_VLLM_URL   = https://cloud-api.phala.com/logs/prod5/containers/74d07bcb818413b1b5501dde7d09b818467c638c/vllm?text&bare&timestamps&tail=500
PHALA_LOG_MODEL_URL  = https://cloud-api.phala.com/logs/prod5/containers/74d07bcb818413b1b5501dde7d09b818467c638c/model-service?text&bare&timestamps&tail=50
PHALA_LOG_NGINX_URL  = https://cloud-api.phala.com/logs/prod5/containers/74d07bcb818413b1b5501dde7d09b818467c638c/nginx-cert-manager?text&bare&timestamps&tail=50
PHALA_LOG_ATTEST_URL = https://cloud-api.phala.com/logs/prod5/containers/74d07bcb818413b1b5501dde7d09b818467c638c/attestation-service?text&bare&timestamps&tail=50

# ─── Phala API helpers ─────────────────────────────────────
PHALA_API_BASE = https://cloud-api.phala.network/api/v1
PHALA_API_KEY  = $$(~/.claude/skills/phala-cloud/get-api-key.sh)
PHALA_CURL     = curl -s -H "X-API-Key: $$API_KEY"
PHALA_CURL_V   = curl -s -H "X-API-Key: $$API_KEY" -H "X-Phala-Version: 2025-10-28"

# Macro: fail if CVM_ID is empty
define require-cvm-id
	@test -n "$(CVM_ID)" || { echo "Error: CVM_ID not set (make $@ CVM_ID=app_xxx)"; exit 1; }
endef

.PHONY: help \
        app-dev-up app-dev-down app-dev-logs app-dev-clean app-dev-wait app-dev-test \
        shade-build \
        phala-list phala-allowed-envs phala-deploy phala-update phala-restart phala-wait \
        phala-info phala-status phala-logs phala-delete \
        check-token-sync \
        atls-setup atls-policy atls-model-owner-push atls-remote-hash atls-hash-verify atls-user-infer

# ─── Help ───────────────────────────────────────────────────
help:
	@echo "Private Model Serving"
	@echo "====================="
	@echo ""
	@echo "Level 1 — App dev (no TLS, no attestation):"
	@echo "  app-dev-up        Start vllm + model-service"
	@echo "  app-dev-down      Stop"
	@echo "  app-dev-logs      Follow logs"
	@echo "  app-dev-clean     Stop + remove volumes"
	@echo "  app-dev-test      Push model + run tests"
	@echo ""
	@echo "Phala deployment:"
	@echo "  shade-build             Generate Shade compose (nginx + TLS + attestation)"
	@echo "  phala-allowed-envs      List env var names for Phala allowed_envs"
	@echo "  phala-deploy            Deploy a new CVM to Phala Cloud"
	@echo "  phala-update            Update compose of existing CVM + restart"
	@echo "  phala-restart           Restart existing CVM"
	@echo "  phala-wait              Poll CVM boot status until online"
	@echo "  phala-info              Show CVM details"
	@echo "  phala-status            Show CVM boot status"
	@echo "  phala-logs              Show CVM serial + container logs"
	@echo "  phala-list              List all CVMs"
	@echo "  phala-delete            Delete a CVM"
	@echo ""
	@echo "Scenario (aTLS — attested TLS):"
	@echo "  atls-setup                   Build atlas Python binding"
	@echo "  atls-policy                  Generate policy.json from live CVM"
	@echo "  atls-model-owner-push        Push model via aTLS"
	@echo "  atls-remote-hash             Get model hash via aTLS"
	@echo "  atls-hash-verify             Compare local hash vs remote (aTLS)"
	@echo "  atls-user-infer              Run inference via aTLS"

# ─── App dev (local HTTP, no TLS, no nginx, no attestation) ──
app-dev-up:
	@echo "Starting app services (local HTTP, no TLS)..."
	@echo "  model-service → http://localhost:8001"
	@echo "  vllm          → http://localhost:8000"
	@echo ""
	docker compose $(COMPOSE_DEV) up -d --build

app-dev-down:
	docker compose $(COMPOSE_DEV) down

app-dev-logs:
	docker compose $(COMPOSE_DEV) logs -f

app-dev-clean:
	docker compose $(COMPOSE_DEV) down -v --remove-orphans

app-dev-wait:
	@echo "Waiting for vLLM to be ready (loading model, this takes a while)..."
	@until curl -sf http://localhost:8000/health >/dev/null 2>&1; do \
		printf "."; sleep 10; \
	done
	@echo ""
	@echo "vLLM is ready!"

app-dev-test:
	$(MAKE) app-dev-clean
	$(MAKE) app-dev-up
	@echo "Waiting for model-service..."
	@until curl -sf http://localhost:8001/health >/dev/null 2>&1; do sleep 2; done
	@echo ""
	@echo "Push model"
	cd scenarios/model-owner && make push
	@echo ""
	@echo "App dev tests (local HTTP, no TLS)"
	@echo ""
	@echo "Waiting for vLLM..."
	$(MAKE) app-dev-wait
	@echo ""
	@echo "Model owner tests"
	cd scenarios/model-owner && PROXY_ENDPOINT=http://localhost:8001 uv run pytest test_model_owner.py -v
	@echo ""
	@echo "User tests"
	cp $(MODEL_HASH_FILE) scenarios/user/model-hash.txt
	cd scenarios/user && PROXY_ENDPOINT=http://localhost:8001 VLLM_ENDPOINT=http://localhost:8000 uv run pytest test_user.py -v

# ─── Phala deployment ─────────────────────────────────────────
shade-build:
	@shade build -o $(SHADE_COMPOSE_FILE) > /dev/null

phala-allowed-envs: shade-build
	@shade env-list --json

phala-list:
	@API_KEY=$(PHALA_API_KEY) && \
	$(PHALA_CURL) "$(PHALA_API_BASE)/cvms/paginated?page=1&page_size=100" \
	  | jq '.items[] | {name, status, app_id, node: .node_info.name, instance: .resource.instance_type, vcpu: .resource.vcpu, memory_gb: .resource.memory_in_gb, urls: [.endpoints[].app]}'

phala-info:
	$(require-cvm-id)
	@API_KEY=$(PHALA_API_KEY) && \
	$(PHALA_CURL) "$(PHALA_API_BASE)/cvms/$(CVM_ID)" \
	  | jq '{id, name, status, created_at, app_id, vm_uuid, instance_id, node: .node_info.name, node_status: .node_info.status, resource: {instance_type: .resource.instance_type, vcpu: .resource.vcpu, memory_in_gb: .resource.memory_in_gb, disk_in_gb: .resource.disk_in_gb, gpus: .resource.gpus}, os: .os.name, os_version: .os.version, endpoints: [.endpoints[].app], instance_endpoints: [.endpoints[].instance], gateway_domain: .gateway.base_domain, kms: {type: .kms_type, endpoint: .kms_info.rpc_endpoint}, public_logs: .public_logs, public_sysinfo: .public_sysinfo, public_tcbinfo: .public_tcbinfo, compose_hash: .compose_hash, docker_compose_hash: .docker_compose_hash, pre_launch_script_hash: .pre_launch_script_hash}'

phala-status:
	$(require-cvm-id)
	@API_KEY=$(PHALA_API_KEY) && \
	$(PHALA_CURL) "$(PHALA_API_BASE)/cvms/$(CVM_ID)/stats" \
	  | jq '{is_online, status, boot_error, boot_progress}'

phala-delete:
	@test -n "$(CVM_ID_TO_DELETE)" || { echo "Error: usage: make phala-delete CVM_ID_TO_DELETE=app_xxx"; exit 1; }
	@test "$(CVM_ID_TO_DELETE)" != "$(CVM_ID)" || { echo "Error: refusing to delete the active CVM ($(CVM_ID)). Use phala-restart instead."; exit 1; }
	@API_KEY=$(PHALA_API_KEY) && \
	echo "Deleting $(CVM_ID_TO_DELETE)..." && \
	$(PHALA_CURL) -X DELETE "$(PHALA_API_BASE)/cvms/$(CVM_ID_TO_DELETE)" > /dev/null && \
	echo "✅Deleted."

phala-logs:
	$(require-cvm-id)
	@API_KEY=$(PHALA_API_KEY) && \
	SYSLOG=$$($(PHALA_CURL_V) "$(PHALA_API_BASE)/cvms/$(CVM_ID)" | jq -r '.syslog_endpoint') && \
	echo "=== Serial logs (boot) ===" && \
	curl -fsSL "$${SYSLOG}&ch=serial" 2>&1 | strings | tail -50 && \
	echo "" && \
	echo "=== Container logs (stdout) ===" && \
	curl -fsSL "$${SYSLOG}&ch=stdout" 2>&1 | strings | tail -50

# Deploy to Phala Cloud (all images must be public).
# Requires: CVM_NAME set in Makefile config, .env with PUSH_TOKEN
#
# Phase 1 — Provision: POST /cvms/provision
#   - Sends the generated compose + allowed_envs
#   - Returns: app_id, compose_hash, app_env_encrypt_pubkey
#
# Phase 2 — Encrypt env vars: x25519 + AES-256-GCM
#   - Encrypts {env: [{key, value}, ...]} with the pubkey from Phase 1
#
# Phase 3 — Commit: POST /cvms
#   - Sends app_id + compose_hash + encrypted_env to create the CVM
phala-deploy: shade-build
	@test -f $(CVM_ENV) || { echo "Error: $(CVM_ENV) not found"; exit 1; }
	@API_KEY=$(PHALA_API_KEY) && \
	echo "" && \
	echo "═══ Phase 1: Provision ═══" && \
	echo "🔄 Getting allowed_envs from shade env-list..." && \
	ALLOWED_ENVS=$$(shade env-list --json) && \
	echo "✅ allowed_envs=$$ALLOWED_ENVS" && \
	echo "🔄 Sending POST /cvms/provision (name=$(CVM_NAME), instance=tdx.large)..." && \
	PROVISION=$$($(PHALA_CURL) -X POST \
	  -H "Content-Type: application/json" \
	  "$(PHALA_API_BASE)/cvms/provision" \
	  -d "$$(jq -n \
	    --arg name "$(CVM_NAME)" \
	    --arg compose "$$(<$(SHADE_COMPOSE_FILE))" \
	    --argjson allowed "$$ALLOWED_ENVS" \
	    '{ \
	      name: $$name, \
	      instance_type: "tdx.large", \
	      compose_file: { \
	        docker_compose_file: $$compose, \
	        allowed_envs: $$allowed, \
	        features: ["kms", "tproxy-net"], \
	        kms_enabled: true, \
	        manifest_version: 2, \
	        name: $$name, \
	        gateway_enabled: true, \
	        public_logs: true, \
	        public_sysinfo: true, \
	        runner: "docker-compose" \
	      }, \
	      listed: false, \
	      teepod_id: 26 \
	    }')") && \
	echo "🔄 Checking provision response..." && \
	APP_ID=$$(echo "$$PROVISION" | jq -r '.app_id') && \
	test "$$APP_ID" != "null" || { echo "❌ FAILED:"; echo "$$PROVISION" | jq .; exit 1; } && \
	COMPOSE_HASH=$$(echo "$$PROVISION" | jq -r '.compose_hash') && \
	PUBKEY=$$(echo "$$PROVISION" | jq -r '.app_env_encrypt_pubkey') && \
	echo "✅ app_id=$$APP_ID" && \
	echo "✅ compose_hash=$$COMPOSE_HASH" && \
	echo "✅ pubkey=$$PUBKEY" && \
	echo "" && \
	echo "═══ Phase 2: Encrypt env vars ═══" && \
	echo "🔄 Reading PUSH_TOKEN from $(CVM_ENV)..." && \
	PUSH_TOKEN=$$(grep '^PUSH_TOKEN=' $(CVM_ENV) | cut -d= -f2) && \
	echo "🔄 Building JSON payload: [{key:PUSH_TOKEN, value:***}]..." && \
	ENV_JSON=$$(jq -n --arg pt "$$PUSH_TOKEN" \
	  '[{key:"PUSH_TOKEN",value:$$pt}]') && \
	echo "🔄 Running scripts/encrypt_env.py (x25519 ECDH + AES-256-GCM)..." && \
	ENCRYPTED=$$(uv run python scripts/encrypt_env.py "$$PUBKEY" "$$ENV_JSON") && \
	echo "✅ encrypted payload ($${#ENCRYPTED} hex chars)" && \
	echo "" && \
	echo "═══ Phase 3: Commit ═══" && \
	echo "🔄 Sending POST /cvms (app_id + compose_hash + encrypted_env)..." && \
	RESULT=$$($(PHALA_CURL) -X POST \
	  -H "Content-Type: application/json" \
	  "$(PHALA_API_BASE)/cvms" \
	  -d "$$(jq -n \
	    --arg a "$$APP_ID" \
	    --arg h "$$COMPOSE_HASH" \
	    --arg e "$$ENCRYPTED" \
	    '{app_id:$$a, compose_hash:$$h, encrypted_env:$$e}')") && \
	echo "🔄 Checking commit response..." && \
	CVM_ID=$$(echo "$$RESULT" | jq -r '.app_id') && \
	test "$$CVM_ID" != "null" || { echo "❌ FAILED:"; echo "$$RESULT" | jq .; exit 1; } && \
	echo "✅" && \
	echo "$$RESULT" | jq '{id, name, status, app_id}' && \
	echo "app_$$CVM_ID" > .cvm_id && \
	echo "" && \
	echo "CVM ID saved to .cvm_id" && \
	$(MAKE) phala-wait CVM_ID=app_$$CVM_ID

# Update compose of an existing CVM + restart (no new app_id).
# Requires: CVM_ID set (or .cvm_id file)
phala-update: shade-build
	$(require-cvm-id)
	@API_KEY=$(PHALA_API_KEY) && \
	echo "Updating compose for $(CVM_ID)..." && \
	TMPFILE=$$(mktemp) && \
	HTTP_CODE=$$($(PHALA_CURL) -o "$$TMPFILE" -w "%{http_code}" \
	  -X PATCH -H "Content-Type: text/yaml" \
	  "$(PHALA_API_BASE)/cvms/$(CVM_ID)/docker-compose" \
	  --data-binary @$(SHADE_COMPOSE_FILE)) && \
	if [ "$$HTTP_CODE" = "200" ] || [ "$$HTTP_CODE" = "202" ]; then \
	  rm -f "$$TMPFILE" && \
	  echo "Compose updated. Restarting..." && \
	  $(PHALA_CURL) -X POST -H "Content-Type: application/json" \
	    "$(PHALA_API_BASE)/cvms/$(CVM_ID)/restart" \
	    -d '{"force": false}' > /dev/null && \
	  echo "Restart triggered. Run 'make phala-wait' to poll status."; \
	else \
	  echo "Update failed (HTTP $$HTTP_CODE):" && cat "$$TMPFILE" | jq . && rm -f "$$TMPFILE" && exit 1; \
	fi

# Restart an existing CVM without changing compose.
phala-restart:
	$(require-cvm-id)
	@API_KEY=$(PHALA_API_KEY) && \
	echo "Restarting $(CVM_ID)..." && \
	$(PHALA_CURL) -X POST -H "Content-Type: application/json" \
	  "$(PHALA_API_BASE)/cvms/$(CVM_ID)/restart" \
	  -d '{"force": false}' > /dev/null && \
	echo "Restart triggered." && \
	$(MAKE) phala-wait CVM_ID=$(CVM_ID)

# Poll CVM boot status until online, error, or Ctrl-C
phala-wait:
	$(require-cvm-id)
	@API_KEY=$(PHALA_API_KEY) && \
	echo "Polling $(CVM_ID) every 15s (Ctrl-C to stop)..." && \
	ELAPSED=0 && ONLINE=false && BOOT_ERR="" && \
	while [ "$$ONLINE" != "true" ] && [ -z "$$BOOT_ERR" ]; do \
	  sleep 15; \
	  ELAPSED=$$((ELAPSED + 15)); \
	  STATS=$$($(PHALA_CURL) "$(PHALA_API_BASE)/cvms/$(CVM_ID)/stats"); \
	  STATUS=$$(echo "$$STATS" | jq -r '.status'); \
	  ONLINE=$$(echo "$$STATS" | jq -r '.is_online'); \
	  PROGRESS=$$(echo "$$STATS" | jq -r '.boot_progress // empty'); \
	  BOOT_ERR=$$(echo "$$STATS" | jq -r '.boot_error // empty'); \
	  SYSLOG=$$($(PHALA_CURL_V) "$(PHALA_API_BASE)/cvms/$(CVM_ID)" | jq -r '.syslog_endpoint // empty'); \
	  LAST_LOG=""; \
	  if [ -n "$$SYSLOG" ]; then \
	    LAST_LOG=$$(curl -fsSL "$${SYSLOG}&ch=serial" 2>/dev/null | strings | tail -1 | sed 's/.*] //'); \
	  fi; \
	  printf "  [%3ds] status=%-10s online=%-5s boot_progress=%-20s %s\n" $$ELAPSED "$$STATUS" "$$ONLINE" "$$PROGRESS" "$$LAST_LOG"; \
	  if [ "$$STATUS" = "stopped" ]; then echo "❌ CVM stopped"; break; fi; \
	done && \
	echo "" && \
	if [ "$$ONLINE" = "true" ]; then \
	  echo "🎉 CVM is online!"; \
	elif [ -n "$$BOOT_ERR" ]; then \
	  echo "❌ Boot error: $$BOOT_ERR" && \
	  echo "  Logs: make phala-logs CVM_ID=$(CVM_ID)" && \
	  echo "  Delete: make phala-delete CVM_ID=$(CVM_ID)"; \
	fi

# ─── Verify token: push-token.txt == .env ────────────────────
check-token-sync:
	@diff -q <(cat $(PUSH_TOKEN_FILE)) <(grep '^PUSH_TOKEN=' $(CVM_ENV) | cut -d= -f2) \
		&& echo "check-token-sync: OK" \
		|| { echo "check-token-sync: KO — $(PUSH_TOKEN_FILE) and $(CVM_ENV) differ"; exit 1; }

# ─── aTLS (attested TLS via Atlas) ─────────────────────────────
ATLAS_PYTHON = cd ../atlas/python &&
CVM_DOMAIN   = $(shell grep 'domain:' shade.yml | head -1 | awk '{print $$2}')

atls-setup:
	@echo "Building atlas Python binding..."
	$(ATLAS_PYTHON) PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 uv run maturin develop --release
	@echo "OK"

atls-policy: shade-build
	@shade policy generate \
		--domain $(CVM_DOMAIN) \
		--allowed-tcb-status "UpToDate,SWHardeningNeeded" \
		-f $(SHADE_COMPOSE_FILE) \
		-o policy.json
	@echo "policy.json generated"

require-policy:
	@test -f $(CURDIR)/policy.json || { echo "Error: policy.json not found. Run 'make atls-policy' first."; exit 1; }

atls-model-owner-push: require-policy
	@$(ATLAS_PYTHON) uv run python -c "\
	import json, os, sys; from atlas import httpx; \
	P='$(CURDIR)'; \
	policy = json.load(open(P+'/policy.json')); \
	client = httpx.Client(atls_policy_per_hostname={'$(CVM_DOMAIN)': policy}); \
	h = client.get('https://$(CVM_DOMAIN)/model-hash', timeout=30); \
	_ = (print('✅ Model already pushed'), client.close(), sys.exit(0)) if h.status_code == 200 else None; \
	token = open(P+'/$(PUSH_TOKEN_FILE)').read().strip(); \
	expected = open(P+'/$(MODEL_HASH_FILE)').read().strip(); \
	archive = P+'/$(MODEL_ARCHIVE)'; \
	print(f'🔄 Pushing {os.path.basename(archive)} via aTLS...'); \
	r = client.post('https://$(CVM_DOMAIN)/push-model', \
	  files={'file': (os.path.basename(archive), open(archive,'rb'), 'application/x-tar')}, \
	  data={'expected_hash': expected}, \
	  headers={'Authorization': f'Bearer {token}'}, timeout=600); \
	client.close(); s=r.status_code; \
	print('✅ Pushed') if s==200 else (print(f'❌ Error: HTTP {s} — {r.text}'), sys.exit(1))"

atls-remote-hash: require-policy
	@$(ATLAS_PYTHON) uv run python -c "\
	import json; from atlas import httpx; \
	policy = json.load(open('$(CURDIR)/policy.json')); \
	client = httpx.Client(atls_policy_per_hostname={'$(CVM_DOMAIN)': policy}); \
	r = client.get('https://$(CVM_DOMAIN)/model-hash', timeout=30); \
	print(r.json()['hash']); \
	client.close()"

atls-hash-verify:
	@LOCAL=$$(cat $(MODEL_HASH_FILE)) && \
	REMOTE=$$($(MAKE) -s atls-remote-hash) && \
	echo "Local:  $$LOCAL" && \
	echo "Remote: $$REMOTE" && \
	if [ "$$LOCAL" = "$$REMOTE" ]; then echo "✅"; else echo "❌" && exit 1; fi

atls-user-infer: require-policy
	@$(ATLAS_PYTHON) uv run python -c "\
	import json; from atlas import httpx; \
	policy = json.load(open('$(CURDIR)/policy.json')); \
	client = httpx.Client(atls_policy_per_hostname={'$(CVM_DOMAIN)': policy}); \
	r = client.post('https://$(CVM_DOMAIN)/v1/chat/completions', \
	  json={'model':'$(MODEL_NAME)','messages':[{'role':'user','content':'What is the capital of France?'}],'max_tokens':50}, timeout=120); \
	r.raise_for_status(); \
	print(r.json()['choices'][0]['message']['content']); \
	client.close()"
