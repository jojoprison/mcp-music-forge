# VER_1.0 — Примеры команд и ожидаемые результаты (Docker + Make)

Ниже — минимальный набор проверок того, что проект собран и работает через Docker Compose, управляется командами Make.

## 0. Подготовка (Docker-first)

```bash
cp .env.example .env
# при необходимости отредактируйте переменные в .env
# по умолчанию сервисы слушают на 8033, данные пишутся в ./data
```

## 1. Сборка и запуск стека

```bash
make build   # docker compose build
make upb     # docker compose up -d --build
# Ожидаемо: подняты контейнеры redis, api, worker
```

## 2. Smoke‑тест API

```bash
curl -s http://127.0.0.1:8033/health | jq
# Ожидаемо: {"status": "ok"}
```

## 3. Очередь и скачивание

Постановка задачи через Make (HTTP под капотом):

```bash
make enqueue URL="https://soundcloud.com/<artist>/<track>"
# Ожидаемо: { "job_id": "<id>", "status": "queued" }

make status JOB=<job_id>
# Ожидаемо: статус меняется queued -> running -> succeeded
# Артефакты: data/jobs/<job_id>/{original,final}/...
```

Замечания:
- По умолчанию в примере `.env` включён строгий режим ToU
  (`ALLOW_STREAM_DOWNLOADS=false`), т.е. качаются только треки с разрешением
  на скачивание. Для попытки скачать поток (m3u8) у треков без кнопки Download —
  установите `ALLOW_STREAM_DOWNLOADS=true` и перезапустите стек (`make upb`).
- Для приватных/регион‑ограниченных треков добавьте куки:
  `SOUNDCLOUD_COOKIE_FILE=/app/secret/soundcloud_cookies.txt` и примонтируйте
  каталог с файлом в compose (для api и worker): `./secret:/app/secret:ro`.

## 4. MCP сервер

- **Режим HTTP**: MCP смонтирован в API на `http://127.0.0.1:8033/mcp` (см. `api/main.py`).
  Подключайте MCP‑клиент с поддержкой HTTP‑транспорта к этому endpoint.

- **Поддерживаемые инструменты (tools):**
  - `probe_url(url: str)` — определить провайдера и проверить, можно ли скачивать по ToU.
  - `enqueue_download(url: str, options?: {
      format?: "mp3"|"flac"|"aac"|"opus",
      quality?: string,
      embed_cover?: bool,
      prefer_original?: bool,
      tags?: Record<string,string>,
      respect_tou?: bool
    })` — поставить задачу в очередь. Возвращает `{ job_id, status }`.
  - `get_job_status(job_id: str)` — вернуть статус и список артефактов (см. ниже).

- **Ресурсы (resources) для клиента MCP:**
  - `forge://jobs/{job_id}/original/{name}` — получить байты оригинального файла.
  - `forge://jobs/{job_id}/final/{name}` — получить байты итогового файла.

- **Поведение ToU:**
  - По умолчанию берётся `ALLOW_STREAM_DOWNLOADS` из `.env`.
  - Можно переопределить на уровне запроса: `options.respect_tou=false` позволит скачивать поток (m3u8), даже если у трека нет кнопки Download.

- **Stdio (опционально, внутри Docker):**
  Если нужен stdio‑режим для отладки клиента, можно запустить MCP‑сервер внутри контейнера API:
  ```bash
  docker compose exec -it api python -m mcp_music_forge.mcp_app
  ```
  В обычной работе достаточно HTTP‑режима (`/mcp`).

## 5. Управление стеком (Make)

```bash
make build     # сборка образов
make upb       # поднять стек (detached) с пересборкой
make logs      # посмотреть логи всех сервисов (api, worker, redis)
make ps        # статус контейнеров
make down      # остановить стек и удалить контейнеры/сети/volumes (compose down -v)
```

## 6. Качество кода и тесты (опционально для разработки)

```bash
make venv         # создать .venv (uv)
make install      # установить dev‑зависимости
make update       # обновить dev‑зависимости

make check        # black --check, ruff check, mypy, pytest
make check-f      # auto-fix: black + ruff --fix, затем mypy и pytest
make precommit    # pre-commit run -a
```

## Подсказки

- Режим ToU: по умолчанию из `.env.example` — строгий (`ALLOW_STREAM_DOWNLOADS=false`).
  Для разрешения потоковых скачиваний установите `ALLOW_STREAM_DOWNLOADS=true`.
- Куки для SoundCloud: используйте `SOUNDCLOUD_COOKIE_FILE` и соответствующий volume в compose.
- Путь хранения данных по умолчанию: `./data` на хосте, смонтирован в контейнеры как `/app/data`.
