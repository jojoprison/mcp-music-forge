# Makefile for mcp-music-forge

.PHONY: help install lint test upb down logs ps clean enq stat

help:
	@echo ""
	@echo "  Docker Compose"
	@echo "    upb          docker compose up -d --build"
	@echo "    down         docker compose down -v"
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
# Docker Compose
# ─────────────────────────────────────────────────────────────────────────────
upb:
	docker compose up -d --build

down:
	docker compose down -v

logs:
	docker compose logs -f

ps:
	docker compose ps

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
	@$(eval JOB_ID := $(shell cat .last_response.json | jq -r '.job_id // empty'))
	@if [ -n "$(JOB_ID)" ]; then \
		echo "$(JOB_ID)" > .latest_job_id; \
		echo ""; \
		echo "Wait a moment and checking status..."; \
		sleep 1; \
		make stat JOB=$(JOB_ID); \
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
