# MCP Music Forge

English | **[Русский](docs/README_RU.md)**

---

A scalable MCP plugin/service for downloading and processing audio:
SoundCloud (starting point), then YouTube/Yandex Music/Spotify; transcoding,
tagging and cover art embedding, HTTP API, MCP tools, audio workers.

## Quickstart

### Variant A: Docker Compose (recommended)

```bash
cp .env.example .env
make upb       # build and start the stack
```

**Endpoints:**
- API: http://localhost:8033
- Admin: http://localhost:8033/admin
- MCP HTTP: http://localhost:8033/mcp

**Management:**
```bash
make logs      # logs
make ps        # container status
make up        # just up
make down      # stop and remove
```

---

### Variant B: Local (uv)

```bash
make install   # create .venv, install deps, copy .env
source .venv/bin/activate

make lint      # ruff + black + mypy
make test      # mypy + pytest

# run API
uvicorn api.main:app --reload

# MCP (stdio)
python -m mcp_music_forge.mcp_app
```

## API Examples

```bash
# health check
curl -s http://localhost:8033/health | jq
# {"status": "ok"}

# enqueue download (SoundCloud URL with allowed download per ToU)
curl -s -X POST 'http://localhost:8033/download?url=https://soundcloud.com/artist/track' | jq
# {"job_id": "abc123", "status": "queued"}

# check job status
curl -s http://localhost:8033/jobs/<job_id> | jq
```

## MCP Tools

- **`probe_url`**: provider detection and downloadability check.
- **`enqueue_download`**: create/duplicate a job, put it in the queue.
- **`get_job_status`**: status, artifacts, file links as MCP resources.
- Resources: `forge://jobs/<job_id>/{original|final}/<filename>` (file bytes).

## Project Overview

- **MCP Server** (`mcp_music_forge/`): job management, resource provider, and MCP tools.
- **HTTP API** (`api/`): `POST /download`, `GET /jobs/{id}`, `/health`, admin interface.
- **Providers** (`providers/`): adapters for sources (starting with SoundCloud).
- **Transcoder** (`transcoder/`): a wrapper around `ffmpeg`.
- **Storage** (`storage/`): local FS (can be replaced with S3, etc.).
- **Queue** (`core/services/queue.py`): ARQ + Redis; a wrapper in `workers/`.

## Documentation

- [Build / Run / Deploy](docs/BUILD_RUN_DEPLOY.md)
- [Architecture](docs/ARCHITECTURE.md)
- [CI/CD](docs/CI_CD.md)

## Legal Notes

- SoundCloud provider respects ToU: we only download if the track is downloadable (`downloadable`/`download_url`).
- Cookie file support is available, but use it strictly within the service's rules.
