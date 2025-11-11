# VER_1.0 — Примеры команд и ожидаемые результаты

Ниже — минимальный набор проверок того, что проект собран и работает разными способами.

## 0. Подготовка окружения

```bash
uv venv --python 3.12
source .venv/bin/activate
uv --version           # ожидаем увидеть версию uv
python --version       # ожидаем Python 3.12.x
```

Установка зависимостей (dev):

```bash
uv pip install -e '.[dev]'
```

## 1. Качество кода и тесты

```bash
pre-commit run -a
# Ожидаемо: все хуки Passed (black/ruff/mypy/pyupgrade)

black --check .
ruff check .
mypy .
pytest -q
# Ожидаемо: все проверки зелёные, тесты проходят (вывод вида: ... [100%])
```

## 2. Smoke‑тест API (локально)

Запуск API (в отдельном терминале):

```bash
uvicorn api.main:app --reload
# Ожидаемо: сервер слушает на 127.0.0.1:8033, лог FastAPI старта
```

Проверка `/health`:

```bash
curl -s http://127.0.0.1:8033/health | jq
# Ожидаемо: {"status": "ok"}
```

## 3. Очередь и скачивание через HTTP API

Требуется Redis (любой способ):

```bash
# Вариант через Docker:
docker run --rm -p 6379:6379 redis:7-alpine
```

Пример постановки задачи (SoundCloud ссылка, должна быть разрешена к скачиванию ToU):

```bash
curl -s -X POST \
  'http://127.0.0.1:8033/download?url=https://soundcloud.com/<artist>/<track>' | jq
# Ожидаемо: { "job_id": "<id>", "status": "queued" }
```

Проверка статуса:

```bash
curl -s 'http://127.0.0.1:8033/jobs/<job_id>' | jq
# Ожидаемо: статус меняется: running -> succeeded; присутствуют метаданные трека
# На диске артефакты: data/jobs/<job_id>/{original,final}/...
```

Если трек не разрешён к скачиванию, API вернёт 400 с причиной.

## 4. MCP сервер

Запуск MCP (stdio):

```bash
python -m mcp_music_forge.mcp_app
# Ожидаемо: процесс запускается и ждёт клиента MCP по stdio
# Для практической проверки нужен совместимый MCP‑клиент
```

HTTP‑режим MCP доступен, когда запущен API: `GET /mcp` (смонтировано в `api/main.py`).

## 5. Docker Compose стек

```bash
cp .env.example .env
# При необходимости поправьте переменные окружения (STORAGE_DIR/DATABASE_URL/REDIS_URL)

docker compose build
docker compose up
# Ожидаемо: api, worker, redis — подняты; API доступен на 8033
```

Далее повторите шаги «3. Очередь и скачивание через HTTP API».

## 6. Быстрые команды (Makefile)

Если создан `Makefile`, доступны команды:

```bash
make install      # venv + зависимости
make check        # black/ruff/mypy/pytest
make api          # uvicorn api.main:app
make mcp          # MCP stdio
make redis        # локальный Redis через docker
make compose-up   # docker compose up
```

## Подсказки

- Для SoundCloud соблюдаем ToU: качаем только разрешённые треки. Для приватных/
  ограниченных треков можно использовать `SOUNDCLOUD_COOKIE_FILE` (см. BUILD_RUN_DEPLOY.md).
- Если ffmpeg отсутствует — установите `brew install ffmpeg` (macOS) или
  пакет для вашей платформы.
