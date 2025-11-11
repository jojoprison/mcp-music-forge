# BUILD / RUN / DEPLOY

Этот гайд покрывает сборку, запуск и развёртывание `mcp-music-forge`.
Основной сценарий — Docker Compose. Локальный запуск (uv) оставлен как опция для разработки.

## Требования

- Docker + Docker Compose
- (Опционально для локальной разработки) Python 3.12, uv

## Переменные окружения (.env)

Смотри `.env.example`. Минимум:

- `STORAGE_DIR=./data`
- `DATABASE_URL=sqlite:///data/db.sqlite3`
- `REDIS_URL=redis://localhost:6379/0`
- `FFMPEG_BIN=ffmpeg`
- `API_HOST=0.0.0.0`
- `API_PORT=8033`
- `SOUNDCLOUD_COOKIE_FILE=` (опционально, соблюдая ToU)

## Запуск через Docker Compose (рекомендуется)

```bash
cp .env.example .env

# сборка образов и запуск стека
make compose-build
make compose-up

# Доступ:
# - API: http://localhost:8033
# - Admin: http://localhost:8033/admin
```

В стеке поднимаются:

- `redis` — брокер очереди
- `api` — HTTP API + MCP HTTP
- `worker` — ARQ воркер, обрабатывающий задания

Проверка:

```bash
curl -s http://localhost:8033/health | jq
# {"status": "ok"}

# Поставить задачу (SoundCloud ссылка с разрешённым скачиванием по ToU)
make enqueue URL="https://soundcloud.com/artist/track"

# Проверить статус
make status JOB=<job_id>
```

Полезные команды:

```bash
make compose-logs     # логи всех сервисов
make compose-ps       # статус контейнеров
make compose-restart  # рестарт сервисов
make compose-down     # остановить и удалить
```

## Локальная сборка и запуск (через uv) — опционально

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

# запустить API (локально)
uvicorn api.main:app --reload
# API: http://localhost:8033, Admin: http://localhost:8033/admin, MCP HTTP: /mcp

# запустить MCP (stdio) локально
python -m mcp_music_forge.mcp_app
```

## Воркеры и очередь

- Очередь: ARQ + Redis.
- Воркер поднимается автоматически как сервис `worker` в `docker-compose.yml`.
- Для локального запуска вне Docker (опционально):

```bash
arq workers.tasks.WorkerSettings
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
