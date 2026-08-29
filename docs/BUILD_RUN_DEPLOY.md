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
  бота. Как выгрузить правильно — ниже.
- `YOUTUBE_POT_BASE_URL=` (опционально) — адрес sidecar-провайдера
  proof-of-origin токенов. Пусто — плагин идёт на свой дефолт
  `127.0.0.1:4416`.

## Cookies для YouTube

🛑 **Главное, на чём легко обжечься: файл, выгруженный из ОБЫЧНОГО окна
браузера, умирает почти сразу.** Пока вы продолжаете пользоваться YouTube в
том же профиле, браузер ротирует сессию, и копия становится недействительной.
yt-dlp это прямо сообщает — но только предупреждением в логе:
`The provided YouTube account cookies are no longer valid. They have likely
been rotated in the browser as a security measure.` Со стороны бота отказ при
этом выглядит как обычное «подтвердите, что вы не бот».

**Правильная процедура** (любой из двух путей):

1. **Приватное окно.** Открыть приватное окно → войти в YouTube → открыть
   `https://www.youtube.com/robots.txt` (чтобы не плодить новых сессий) →
   выгрузить cookies расширением вроде «Get cookies.txt LOCALLY» **из этого
   окна** → закрыть окно, **не разлогиниваясь**. Сессия останется замороженной.
   Расширению нужно отдельно разрешить работу в приватном режиме.
2. **Отдельный профиль браузера**, которым потом не пользуются: войти там один
   раз и выгружать `yt-dlp --cookies-from-browser chrome:<Профиль>`. Ротации не
   будет, потому что профиль простаивает.

Аккаунт лучше отдельный: yt-dlp предупреждает о риске блокировки при таком
использовании.

**Доставка на сервер** (файл в чат не отправлять — он осядет в истории):

```bash
scp cookies.txt <сервер>:/root/mcp-music-forge/data/secret/youtube_cookies.txt
ssh <сервер> chmod 600 /root/mcp-music-forge/data/secret/youtube_cookies.txt
```

Каталог `data/secret/` в `.gitignore`; `data/` монтируется в контейнер, поэтому
дополнительных volume не нужно. Файл yt-dlp получает **копией** — оригинал не
перезаписывается (иначе конкурентные джобы обгладывают его сами, см. историю
PROV-1).

## Доступ к API и админке на проде

🛑 **На проде API слушает только `127.0.0.1`** (`API_HOST=127.0.0.1` в
`docker-compose.prod.yml`). Это не перестраховка: админка `sqladmin` смонтирована
**без аутентификации**, а `POST /download` не требует токена — с `0.0.0.0` любой,
знающий адрес сервера, видел бы и правил задания и жёг бы наш трафик.

Поэтому снаружи порт закрыт, а до админки ходят **ssh-туннелем**:

```bash
ssh -L 8033:127.0.0.1:8033 coco
# и в браузере на своей машине:
#   http://localhost:8033/admin  — админка
#   http://localhost:8033/docs   — swagger
```

Бот на это не влияет: он поллится внутри процесса api и ходит на
`API_BASE_URL=http://127.0.0.1:8033`, то есть по тому же loopback.

**Локальная разработка не меняется:** дефолт в образе остаётся `0.0.0.0`, потому что в
bridge-сети `127.0.0.1` внутри контейнера недостижим снаружи даже с проброшенными портами.

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
