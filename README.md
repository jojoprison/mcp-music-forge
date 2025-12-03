# MCP Music Forge

English | **[Русский](docs/README_RU.md)**

---

A scalable MCP plugin/service for downloading and processing audio:
SoundCloud (starting point), then YouTube/Yandex Music/Spotify; transcoding,
tagging and cover art embedding, HTTP API, MCP tools, audio workers.

## Project Overview

- **MCP Server** (`mcp_music_forge/`): job management, resource provider, and MCP tools.
- **HTTP API** (`api/`): `POST /download`, `GET /jobs/{id}`, `/health`, admin interface.
- **Providers** (`providers/`): adapters for sources (starting with SoundCloud).
- **Transcoder** (`transcoder/`): a wrapper around `ffmpeg`.
- **Storage** (`storage/`): local FS (can be replaced with S3, etc.).
- **Queue** (`core/services/queue.py`): ARQ + Redis; a wrapper in `workers/`.

## Quickstart

### Variant A: Docker Compose (recommended)

```bash
cp .env.example .env

# build and start the stack
docker compose up -d --build

# verify
curl -s http://localhost:8033/health | jq
```

**Endpoints:**
- API: http://localhost:8033
- Admin: http://localhost:8033/admin
- MCP HTTP: http://localhost:8033/mcp

**Management:**
```bash
docker compose logs -f      # logs
docker compose ps           # container status
docker compose restart      # restart
docker compose down -v      # stop and remove
```

---

### Variant B: Local (uv)

```bash
# create env and install deps
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e '.[dev]'

# copy .env
cp .env.example .env

# checks
ruff check .
black --check .
mypy .
pytest -q

# run API
uvicorn api.main:app --reload

# MCP (stdio)
python -m mcp_music_forge.mcp_app
```

## MCP Tools

- **`probe_url`**: provider detection and downloadability check.
- **`enqueue_download`**: create/duplicate a job, put it in the queue.
- **`get_job_status`**: status, artifacts, file links as MCP resources.
- Resources: `forge://jobs/<job_id>/{original|final}/<filename>` (file bytes).

## Documentation

- [Build / Run / Deploy](docs/BUILD_RUN_DEPLOY.md)
- [Architecture](docs/ARCHITECTURE.md)
- [CI/CD](docs/CI_CD.md)

## Legal Notes

- SoundCloud provider respects ToU: we only download if the track is downloadable (`downloadable`/`download_url`).
- Cookie file support is available, but use it strictly within the service's rules.
