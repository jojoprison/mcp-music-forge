# BUILD / RUN / DEPLOY

Этот гайд покрывает сборку, запуск и развёртывание `mcp-music-forge`.

## Требования

- Python 3.12
- ffmpeg (локально: `brew install ffmpeg`)
- Redis (локально: `brew install redis && redis-server` или через Docker Compose)
- Опционально: Docker + Docker Compose

## Переменные окружения (.env)

Смотри `.env.example`. Минимум:

- `STORAGE_DIR=./data`
- `DATABASE_URL=sqlite:///data/db.sqlite3`
- `REDIS_URL=redis://localhost:6379/0`
- `FFMPEG_BIN=ffmpeg`
- `API_HOST=0.0.0.0`
- `API_PORT=8033`
- `SOUNDCLOUD_COOKIE_FILE=` (опционально, соблюдая ToU)

## Локальная сборка и запуск (через uv)

```bash
# создать окружение
uv venv --python 3.12
source .venv/bin/activate

# установить зависимости (включая dev)
uv pip install -e '.[dev]'

# прогнать проверки
black --check .
ruff check .
mypy .
pytest -q

# запустить API
uvicorn api.main:app --reload
# API: http://localhost:8033, Admin: http://localhost:8033/admin, MCP HTTP: /mcp

# запустить MCP (stdio)
python -m mcp_music_forge.mcp_app
```

## Запуск через Docker Compose

```bash
cp .env.example .env

# сборка образов и запуск стека
docker compose build
docker compose up

# Доступ:
# - API: http://localhost:8033
# - Admin: http://localhost:8033/admin
```

## Воркеры и очередь

- Очередь: ARQ + Redis.
- Воркер поднимается как отдельный сервис в `docker-compose.yml` или как отдельный процесс:

```bash
# локально, при активном .venv
arq workers.tasks.WorkerSettings -w 1
```

## Примеры запросов

```bash
# поставить задачу скачивания (SoundCloud ссылка)
curl -X POST 'http://localhost:8033/download?url=https://soundcloud.com/artist/track'

# статус задачи
curl 'http://localhost:8033/jobs/<job_id>'
```

## Деплой

### Вариант 1: Docker Compose (single host)

- Скопировать `.env`, настроить пути/порты, примонтировать `./data`.
- Запустить: `docker compose up -d`.

### Вариант 2: Kubernetes (подготовка)

- Собрать образ API/worker из `Dockerfile.api`.
- Пробросить переменные окружения как `ConfigMap`/`Secret`.
- PVC для `STORAGE_DIR`.
- Внешний Redis (или встроенный chart).
- Ingress для API.

## Наблюдаемость

- Если задан `OTEL_EXPORTER_OTLP_ENDPOINT`, API автоматически включает трассинг FastAPI.
- Логи — структурированные (structlog, JSON).

## Правовые ограничения

- Провайдер SoundCloud уважает ToU: скачивание возможно только если трек помечен как `downloadable`/имеет
  `download_url`.
- Cookie‑файл поддерживается, но использовать строго в рамках правил сервиса.
