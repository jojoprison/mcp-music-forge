# MCP Music Forge

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

### Variant A: uv + local

```bash
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e '.[dev]'

# checks
black --check .
ruff check .
mypy .
pytest -q

# API dev
uvicorn api.main:app --reload
# MCP stdio
python -m mcp_music_forge.mcp_app
```

### Variant B: Docker Compose

```bash
cp .env.example .env
# build and start the stack
docker compose build
docker compose up
```

- API: http://localhost:8033
- Admin: http://localhost:8033/admin
- MCP HTTP: http://localhost:8033/mcp

## MCP Tools

- **`probe_url`**: provider detection and downloadability check.
- **`enqueue_download`**: create/duplicate a job, put it in the queue.
- **`get_job_status`**: status, artifacts, file links as MCP resources.
- Resources: `forge://jobs/<job_id>/{original|final}/<filename>` (file bytes).

## Documentation

- CI/CD: `docs/CI_CD.md`
- Build/Run/Deploy: `docs/BUILD_RUN_DEPLOY.md`
- Architecture: `docs/ARCHITECTURE.md`

## Legal Notes

- SoundCloud provider respects ToU: we only download if the track is downloadable (`downloadable`/`download_url`).
  Cookie file support is available, but use it strictly within the service's rules.
