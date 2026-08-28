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
- `YOUTUBE_COOKIE_FILE=` (опционально) — путь к `cookies.txt`. Без него часть
  видео не отдаётся: YouTube периодически принимает датацентровый адрес за
  бота. 🛑 Экспортировать в приватном окне и **не** с основного аккаунта —
  yt-dlp предупреждает о риске блокировки.
- `YOUTUBE_POT_BASE_URL=` (опционально) — адрес sidecar-провайдера
  proof-of-origin токенов. Пусто — плагин идёт на свой дефолт
  `127.0.0.1:4416`.

## Запуск через Docker Compose (рекомендуется)

```bash
cp .env.example .env
make up        # сборка и запуск стека
```

**Эндпоинты:**
- API: http://localhost:8033
- Админка: http://localhost:8033/admin
- MCP HTTP: http://localhost:8033/mcp

В стеке поднимаются:

- `redis` — брокер очереди
- `api` — HTTP API + MCP HTTP (и телеграм-бот: он поллится **внутри** этого
  процесса, отдельного контейнера у него нет)
- `worker` — ARQ воркер, обрабатывающий задания
- `pot-provider` — sidecar `bgutil`, выдаёт YouTube proof-of-origin токены на
  `127.0.0.1:4416` (только в `docker-compose.prod.yml`)

Управление:

```bash
make logs      # логи
make ps        # статус контейнеров
make restart   # рестарт
make down      # остановка и удаление
```

## Локальная сборка и запуск (через uv) — опционально

```bash
make install   # создать .venv, установить зависимости, скопировать .env
source .venv/bin/activate

make lint      # ruff + black
make test      # mypy + pytest

# запустить API
uvicorn api.main:app --reload
# API: http://localhost:8033, Admin: http://localhost:8033/admin, MCP HTTP: /mcp

# запустить MCP (stdio)
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
# проверка здоровья
curl -s http://localhost:8033/health | jq
# {"status": "ok"}

# поставить задачу скачивания (SoundCloud ссылка с разрешённым скачиванием по ToU)
curl -s -X POST 'http://localhost:8033/download?url=https://soundcloud.com/artist/track' | jq
# {"job_id": "abc123", "status": "queued"}

# статус задачи
curl -s http://localhost:8033/jobs/<job_id> | jq
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
