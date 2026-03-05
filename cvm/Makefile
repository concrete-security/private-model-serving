SHELL := /bin/bash

.PHONY: docker-up docker-down docker-logs docker-clean test

docker-up:
	clear
	docker compose up -d --build

docker-down:
	clear
	docker compose down -v

docker-logs:
	clear
	docker compose logs -f

docker-clean:
	docker compose down -v --remove-orphans

test:
	cd model-service && uv run pytest tests/ -v
