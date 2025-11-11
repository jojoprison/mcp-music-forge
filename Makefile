# Makefile for mcp-music-forge (Docker-first)

UV=uv
PY=.venv/bin/python
BLACK=.venv/bin/black
RUFF=.venv/bin/ruff
MYPY=.venv/bin/mypy
PYTEST=.venv/bin/pytest
PRECOMMIT=.venv/bin/pre-commit

.PHONY: help venv venv-recreate install update check precommit upb down build logs ps enqueue status clean

help:
	@echo "Targets:"
	@echo "  venv             - create .venv via uv (optional for dev)"
	@echo "  install          - install deps (dev) with uv (optional for dev)"
	@echo "  update           - update deps (dev) with uv"
	@echo "  check            - black --check, ruff, mypy, pytest"
	@echo "  precommit        - pre-commit run -a"
	@echo "  build     \t  - docker compose build"
	@echo "  upb      \t  - docker compose build + up"
	@echo "  down        \t  - docker compose down -v"
	@echo "  logs     \t  - docker compose logs -f"
	@echo "  ps       \t  - docker compose ps"
	@echo "  enqueue URL=..   - POST /download?url=.. (expects API on 8033)"
	@echo "  status JOB=..    - GET /jobs/{id} (expects API on 8033)"

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

check:
	$(BLACK) --check . && $(RUFF) check . && $(MYPY) . && $(PYTEST) -q

precommit:
	$(PRECOMMIT) run -a

build:
	docker compose build

upb:
	docker compose up -d --build

down:
	docker compose down -v

logs:
	docker compose logs -f

ps:
	docker compose ps

enqueue:
	@test -n "$(URL)" || (echo "Usage: make enqueue URL=..." && exit 1)
	curl -s -X POST 'http://127.0.0.1:8033/download?url=$(URL)' | jq .

status:
	@test -n "$(JOB)" || (echo "Usage: make status JOB=<job_id>" && exit 1)
	curl -s 'http://127.0.0.1:8033/jobs/$(JOB)' | jq .

clean:
	rm -rf .mypy_cache .pytest_cache .ruff_cache build dist *.egg-info
