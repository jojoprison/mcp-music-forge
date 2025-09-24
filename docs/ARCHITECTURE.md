# Архитектура проекта

`mcp-music-forge` — расширяемый сервис загрузки и обработки аудио с MCP-сервером, HTTP API и воркером фона. Целей два:
удобная локальная автоматизация (MCP/CLI/HTTP) и возможность масштабирования.

## Основные компоненты

- **`mcp_music_forge/`** — MCP-сервер (FastMCP):
    - `mcp_app.py` — инициализация, lifespan (логирование, БД), регистрация tools/resources.
    - `tools/` — инструменты:
        - `probe_url.py` — определение провайдера и проверка права на скачивание.
        - `enqueue_download.py` — постановка задачи на скачивание/транскод.
        - `get_job_status.py` — статус задачи, список артефактов и ресурсные URI.
    - `resources/files.py` — выдаёт файлы артефактов через `forge://jobs/...`.

- **`api/`** — FastAPI-приложение:
    - `main.py` — эндпоинты `/download`, `/jobs/{id}`, `/health`, админка SQLAdmin (`/admin`), монтаж MCP HTTP `/mcp`,
      опциональный OTEL.

- **`core/`** — домен и инфраструктура:
    - `domain/job.py` — модели `Job`, `DownloadOptions`, DTO для статусов и артефактов.
    - `infra/db.py` — SQLModel/SQLAlchemy engine, `session_scope()`, создание таблиц.
    - `logging.py` — structlog JSON-логи.
    - `ports/` — `ProviderPort`, `StoragePort`.
    - `services/`:
        - `provider_registry.py` — регистрация/детект провайдеров.
        - `download_orchestrator.py` — оркестровка: скачивание, транскод, теги, статусы.
        - `queue.py` — постановка задач в ARQ/Redis.

- **`providers/`** — адаптеры источников:
    - `soundcloud_ytdlp/adapter.py` — SoundCloud на базе `yt-dlp`, принудительная проверка ToU (`downloadable`/
      `download_url`).

- **`storage/`** — хранилища артефактов:
    - `local_fs.py` — локальная ФС с layout: `data/jobs/<job_id>/{original,final}`.

- **`transcoder/`** — работа с аудио:
    - `ffmpeg_cli.py` — обёртка поверх `ffmpeg`, профили качества.

- **`workers/`** — ARQ-воркер (`workers.tasks.WorkerSettings`).

## Поток данных (Happy Path)

1. Клиент вызывает MCP `enqueue_download` или HTTP `POST /download?url=...`.
2. Сервис определяет провайдера, создаёт/дедупит `Job` (fingerprint по `url+options`), кладёт `job_id` в очередь (
   ARQ/Redis).
3. Воркер `process_job(job_id)`:
    - ставит статус `running`;
    - скачивает оригинал через провайдера (с retry);
    - обновляет метаданные (title/artist/duration/cover-url);
    - транскодирует в целевой формат (или копирует если совпадает);
    - пробует вшить теги и обложку (best-effort);
    - помечает `succeeded`.
4. Клиент получает статус через MCP `get_job_status` или HTTP `GET /jobs/{id}` и может скачать артефакты через MCP
   ресурсы `forge://jobs/...`.

## Паттерны и принципы

- **Ports & Adapters (Hexagonal)**: `ProviderPort`, `StoragePort`; адаптеры провайдеров и стораджей можно добавлять без
  изменения домена.
- **Очереди и идемпотентность**: ARQ/Redis, `fingerprint` для избежания дубликатов.
- **Separation of Concerns**: домен (`core/domain`) отделён от инфраструктуры (`core/infra`), API и MCP.
- **DRY/KISS/YAGNI**: минимум магии, чёткие границы, понятные контракты.

## Масштабирование

- **Горизонталь**: масштабирование воркеров ARQ и инстансов API; Redis как общая очередь.
- **Хранилище**: вынести `local_fs` на S3/GCS, реализовав `StoragePort`.
- **БД**: перейти на Postgres/MySQL; заменить URL и настроить пул.
- **Наблюдаемость**: включить OTEL (экспорт OTLP), собирать метрики/трейсы, добавить Prometheus/Grafana.
- **Кэширование/Rate limiting**: добавить Redis-кэши на пробу/метаданные и rate limit на вызовы провайдеров.

## Подводные камни

- **ToU провайдеров**: SoundCloud — скачиваем только если uploader разрешил.
- **ffmpeg**: ошибки входных данных; в тестах используется monkeypatch.
- **Типизация SQLModel/SQLAlchemy**: местами нужны обходные решения (JSON поле, select/filter_by).
- **Долгоживущие задачи**: транскодирование может быть тяжёлым — контролируйте нагрузку, очереди, ретраи.

## Расширение провайдеров

Добавление нового провайдера:

1. Создать `providers/<name>/adapter.py`, реализующий `ProviderPort`.
2. Добавить фабрику в `core/services/provider_registry.py`.
3. Учесть ToU и особенности API/антибот защит.

## Структура данных и ресурсы

- Артефакты:
    - `original/` — исходники провайдера;
    - `final/` — итоговый формат (mp3/flac/aac/opus);
- MCP ресурсы: `forge://jobs/<job_id>/{original|final}/<filename>` возвращают bytes.

## Будущее

- S3-хранилище, другие провайдеры (YouTube, Yandex Music, Spotify)
- Качество/метрики: background health, экспортеры OTEL для Redis/HTTP
- UI (web) поверх API, очереди заданий, управление профилями качества
