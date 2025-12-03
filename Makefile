# Makefile for mcp-music-forge

.PHONY: help install lint test upb down logs ps clean enq stat dup dupb ddown

help:
	@echo ""
	@echo "  Docker Compose (Production / Stable)"
	@echo "    up           docker compose -f docker-compose.yml up -d"
	@echo "    upb          docker compose -f docker-compose.yml up -d --build"
	@echo "    down         docker compose -f docker-compose.yml down -v"
	@echo ""
	@echo "  Docker Compose (Development with Hot Reload)"
	@echo "    dup          docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d"
	@echo "    dupb         docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build"
	@echo "    ddown        docker compose -f docker-compose.yml -f docker-compose.dev.yml down -v"
	@echo ""
	@echo "    logs         docker compose logs -f"
	@echo "    ps           docker compose ps"
	@echo ""
	@echo "  API Helpers"
	@echo "    enq [URL=..]     POST /download (default: test URL)"
	@echo "    stat [JOB=..]    GET /jobs/{id} (default: last enqueued)"
	@echo ""
	@echo "  Development (local)"
	@echo "    install      create .venv, install deps, copy .env"
	@echo "    lint         ruff (fix), black, mypy"
	@echo "    test         pytest only"
	@echo ""
	@echo "    clean        remove caches and build artifacts"
	@echo ""

# ─────────────────────────────────────────────────────────────────────────────
# Docker Compose (Base)
# ─────────────────────────────────────────────────────────────────────────────
COMPOSE_BASE = -f docker-compose.yml

up:
	docker compose $(COMPOSE_BASE) up -d

upb:
	docker compose $(COMPOSE_BASE) up -d --build

down:
	docker compose $(COMPOSE_BASE) down -v

logs:
	docker compose logs -f

ps:
	docker compose ps

restart:
	docker compose $(COMPOSE_BASE) restart

# ─────────────────────────────────────────────────────────────────────────────
# Docker Compose (Dev - Hot Reload)
# ─────────────────────────────────────────────────────────────────────────────
COMPOSE_DEV = -f docker-compose.yml -f docker-compose.dev.yml

dup:
	docker compose $(COMPOSE_DEV) up -d

dupb:
	docker compose $(COMPOSE_DEV) up -d --build

ddown:
	docker compose $(COMPOSE_DEV) down -v

# ─────────────────────────────────────────────────────────────────────────────
# API Helpers
# ─────────────────────────────────────────────────────────────────────────────
# Default test URL
DEFAULT_SC_URL=https://soundcloud.com/cheetah_33/md_33

enq:
	@$(eval URL ?= $(DEFAULT_SC_URL))
	@echo "Enqueueing: $(URL)"
	@curl -s -X POST 'http://127.0.0.1:8033/download?url=$(URL)' > .last_response.json
	@cat .last_response.json | jq .
	@JOB_ID=$$(cat .last_response.json | jq -r '.job_id // empty'); \
	if [ -n "$$JOB_ID" ]; then \
		echo "$$JOB_ID" > .latest_job_id; \
		echo ""; \
		echo "Wait a moment and checking status..."; \
		sleep 1; \
		make stat JOB=$$JOB_ID; \
	else \
		echo "Error: Could not extract job_id from response"; \
	fi
	@rm -f .last_response.json

stat:
	@$(eval JOB ?= $(shell cat .latest_job_id 2>/dev/null))
	@test -n "$(JOB)" || (echo "Usage: make stat JOB=<job_id> (or run 'make enq' first)" && exit 1)
	@echo "Checking status for JOB=$(JOB)"
	@curl -s 'http://127.0.0.1:8033/jobs/$(JOB)' | jq .

# ─────────────────────────────────────────────────────────────────────────────
# Development (local)
# ─────────────────────────────────────────────────────────────────────────────
install:
	@[ -d .venv ] || uv venv --python 3.12
	uv pip install -e '.[dev]'
	@[ -f .env ] || (cp .env.example .env && echo "Created .env from .env.example")
	@echo "Activate: source .venv/bin/activate"

lint:
	.venv/bin/ruff check --fix .
	.venv/bin/black .
	.venv/bin/mypy .

test:
	.venv/bin/pytest -q

clean:
	rm -rf .mypy_cache .pytest_cache .ruff_cache build dist *.egg-info
	find . -type d -name "__pycache__" -exec rm -rf {} +
