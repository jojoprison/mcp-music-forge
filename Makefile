# Makefile for mcp-music-forge

PY=.venv/bin/python
UV=uv
BLACK=.venv/bin/black
RUFF=.venv/bin/ruff
MYPY=.venv/bin/mypy
PYTEST=.venv/bin/pytest
PRECOMMIT=.venv/bin/pre-commit
UVICORN=.venv/bin/uvicorn
ARQ=.venv/bin/arq

# Runtime defaults
HOST ?= 0.0.0.0
PORT ?= 8033
DATA_DIR ?= data
REDIS_URL ?= redis://localhost:6379/0

.PHONY: help venv venv-recreate install update freeze format lint lint-fix type test check precommit api mcp worker redis compose-up compose-down enqueue job status clean

	help:
	@echo "Targets:"
	@echo "  venv           - create .venv via uv"
	@echo "  install        - install deps (dev) with uv"
	@echo "  update         - update deps (uv pip sync)"
	@echo "  freeze         - export requirements.txt (lockless)"
	@echo "  lint           - run ruff check"
	@echo "  lint-fix       - run ruff --fix"
	@echo "  type           - run mypy"
	@echo "  test           - run pytest"
	@echo "  check          - black --check, ruff, mypy, pytest"
	@echo "  precommit      - pre-commit run -a"
	@echo "  api            - run uvicorn api.main:app --reload"
	@echo "  mcp            - run MCP stdio server"
	@echo "  worker         - run ARQ worker"
	@echo "  redis          - run local redis via docker"
	@echo "  compose-up     - docker compose up"
	@echo "  compose-down   - docker compose down"
	@echo "  enqueue URL=.. - POST /download?url=.."
	@echo "  status JOB=..  - GET /jobs/{id}"

venv:
	@[ -d .venv ] || ($(UV) venv --python 3.12 && echo "Activate: source .venv/bin/activate")

venv-recreate:
	$(UV) venv --python 3.12 --clear
	@echo "Recreated .venv. Activate: source .venv/bin/activate"

install:
	@[ -d .venv ] || $(UV) venv --python 3.12
	$(UV) pip install -e '.[dev]'

update: venv
	$(UV) pip install -U -e '.[dev]'

freeze:
	$(PY) -m pip freeze > requirements.txt

format:
	$(BLACK) .

lint:
	$(RUFF) check .

lint-fix:
	$(RUFF) check --fix .

type:
	$(MYPY) .

test:
	$(PYTEST) -q

check:
	$(BLACK) --check . && $(RUFF) check . && $(MYPY) . && $(PYTEST) -q

precommit:
	$(PRECOMMIT) run -a

api:
	STORAGE_DIR=$(DATA_DIR) \
	DATABASE_URL=sqlite:///$(DATA_DIR)/db.sqlite3 \
	REDIS_URL=$(REDIS_URL) \
	$(UVICORN) api.main:app --reload --host $(HOST) --port $(PORT)

mcp:
	STORAGE_DIR=$(DATA_DIR) \
	DATABASE_URL=sqlite:///$(DATA_DIR)/db.sqlite3 \
	REDIS_URL=$(REDIS_URL) \
	$(PY) -m mcp_music_forge.mcp_app

worker:
	STORAGE_DIR=$(DATA_DIR) \
	DATABASE_URL=sqlite:///$(DATA_DIR)/db.sqlite3 \
	REDIS_URL=$(REDIS_URL) \
	$(ARQ) workers.tasks.WorkerSettings

redis:
	docker run --rm -p 6379:6379 redis:7-alpine

compose-up:
	docker compose up --build

compose-down:
	docker compose down -v

enqueue:
	@test -n "$(URL)" || (echo "Usage: make enqueue URL=..." && exit 1)
	curl -s -X POST 'http://127.0.0.1:8033/download?url=$(URL)' | jq .

status:
	@test -n "$(JOB)" || (echo "Usage: make status JOB=<job_id>" && exit 1)
	curl -s 'http://127.0.0.1:8033/jobs/$(JOB)' | jq .

clean:
	rm -rf .mypy_cache .pytest_cache .ruff_cache build dist *.egg-info
