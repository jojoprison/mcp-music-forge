# mcp-music-forge

FastAPI + `arq` worker. YouTube/SoundCloud → mp3 downloader. Telegram-бот **@yt_sc_mp3_downloader_bot** (bot id 8224583085) поллится **ВНУТРИ `api`-процесса** (не отдельный контейнер) — поэтому при миграции легко проглядеть; два инстанса дают 409.

## Сервер
Живёт на сервере **`coco`** (Hetzner Singapore, `ssh coco` → 5.223.47.40, root), каталог `/root/mcp-music-forge`. Переехал 2026-05-31 с изъятого THE.Hosting. *(`tg`/`tg-2` — это ДРУГОЙ сервер, ThorGash; не сюда.)*

## Запуск (prod)
```bash
ssh coco
cd /root/mcp-music-forge
docker compose -f docker-compose.prod.yml up -d --build api worker pot-provider
```
- `pot-provider` — sidecar `bgutil`, выдаёт YouTube proof-of-origin токены на `127.0.0.1:4416`;
  без него YouTube отвечает 403 на медиапоток с датацентрового адреса.
- `network_mode: host`; нужен host-redis на `127.0.0.1:6379` (контейнер `mf-redis` в host-сети: `docker run -d --name mf-redis --network host --restart unless-stopped redis:7-alpine`).
- БД — sqlite `./data/db.sqlite3`; env — `.env.prod`. Публичного домена нет (внутренний/MCP).

## Хранилище
Сгенерированные джобы — в `./data/jobs/`. Фотки/медиа проекта — в Cloudflare R2 (аккаунт-уровень).

## Доки и беклог
`docs/tasks/BACKLOG.md` — хаб отложенной работы (только ссылки), детали в `docs/tasks/bugs/<домен>.md`,
закрытое уезжает в `docs/tasks/DONE.md`. Формат карточки и правила нумерации — `docs/tasks/bugs/README.md`.
Разборы и замеры — `docs/research/`.
