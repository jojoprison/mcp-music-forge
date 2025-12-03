# MCP Music Forge

**[English](../README.md)** | Русский

---

Масштабируемый MCP-плагин/сервис для скачивания и обработки аудио:
SoundCloud (для начала), далее YouTube/Яндекс.Музыка/Spotify; транскодирование,
теги и обложки, HTTP API, MCP tools, воркеры.

## Обзор проекта

- **MCP Server** (`mcp_music_forge/`): управление заданиями, провайдер ресурсов, MCP tools.
- **HTTP API** (`api/`): `POST /download`, `GET /jobs/{id}`, `/health`, админка.
- **Providers** (`providers/`): адаптеры к источникам (начинаем с SoundCloud).
- **Transcoder** (`transcoder/`): обёртка над `ffmpeg`.
- **Storage** (`storage/`): локальная FS (можно заменить на S3 и т.д.).
- **Queue** (`core/services/queue.py`): ARQ + Redis; обёртка в `workers/`.

## Быстрый старт

### Вариант A: Docker Compose (рекомендуется)

```bash
cp .env.example .env

# сборка и запуск стека
docker compose up -d --build

# проверка
curl -s http://localhost:8033/health | jq
```

**Эндпоинты:**
- API: http://localhost:8033
- Админка: http://localhost:8033/admin
- MCP HTTP: http://localhost:8033/mcp

**Управление:**
```bash
docker compose logs -f      # логи
docker compose ps           # статус контейнеров
docker compose restart      # рестарт
docker compose down -v      # остановка и удаление
```

---

### Вариант B: Локально (uv)

```bash
# создать окружение и установить зависимости
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e '.[dev]'

# скопировать .env
cp .env.example .env

# проверки
ruff check .
black --check .
mypy .
pytest -q

# запуск API
uvicorn api.main:app --reload

# MCP (stdio)
python -m mcp_music_forge.mcp_app
```

## MCP Tools

- **`probe_url`**: детектирование провайдера и проверка доступности.
- **`enqueue_download`**: создание задания и постановка в очередь.
- **`get_job_status`**: статус, артефакты, ссылки на файлы как MCP resources.
- Resources: `forge://jobs/<job_id>/{original|final}/<filename>` (байты файла).

## Документация

- [Сборка / Запуск / Деплой](BUILD_RUN_DEPLOY.md)
- [Архитектура](ARCHITECTURE.md)
- [CI/CD](CI_CD.md)

## Правовые ограничения

- Провайдер SoundCloud уважает ToU: скачивание возможно только если трек помечен как `downloadable` / имеет `download_url`.
- Cookie-файл поддерживается, но использовать строго в рамках правил сервиса.
