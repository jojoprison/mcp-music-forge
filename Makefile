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

.PHONY: help venv install update freeze format lint lint-fix type test check precommit api mcp redis compose-up compose-down enqueue job status clean

help:
	@echo "Targets:"
	@echo "  venv           - create .venv via uv"
	@echo "  install        - install deps (dev) with uv"
	@echo "  update         - update deps (uv pip sync)"
	@echo "  freeze         - export requirements.txt (lockless)"
	@echo "  format         - run black"
	@echo "  lint           - run ruff check"
	@echo "  lint-fix       - run ruff --fix"
	@echo "  type           - run mypy"
	@echo "  test           - run pytest"
	@echo "  check          - black --check, ruff, mypy, pytest"
	@echo "  precommit      - pre-commit run -a"
	@echo "  api            - run uvicorn api.main:app --reload"
	@echo "  mcp            - run MCP stdio server"
	@echo "  redis          - run local redis via docker"
	@echo "  compose-up     - docker compose up"
	@echo "  compose-down   - docker compose down"
	@echo "  enqueue URL=.. - POST /download?url=.."
	@echo "  status JOB=..  - GET /jobs/{id}"

venv:
	$(UV) venv --python 3.12
	@echo "Activate: source .venv/bin/activate"

install: venv
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
	$(UVICORN) api.main:app --reload

mcp:
	$(PY) -m mcp_music_forge.mcp_app

redis:
	docker run --rm -p 6379:6379 redis:7-alpine

compose-up:
	docker compose up --build

compose-down:
	docker compose down -v

enqueue:
	@test -n "$(URL)" || (echo "Usage: make enqueue URL=..." && exit 1)
	curl -s -X POST 'http://127.0.0.1:8000/download?url=$(URL)' | jq .

status:
	@test -n "$(JOB)" || (echo "Usage: make status JOB=<job_id>" && exit 1)
	curl -s 'http://127.0.0.1:8000/jobs/$(JOB)' | jq .

clean:
	rm -rf .mypy_cache .pytest_cache .ruff_cache build dist *.egg-info
