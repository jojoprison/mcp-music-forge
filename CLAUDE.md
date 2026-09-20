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
- 🛑 API слушает **только loopback** (`API_HOST=127.0.0.1`): у `/admin` нет пароля, а `POST /download`
  без токена. Снаружи — через туннель: `ssh -N -L 8033:127.0.0.1:8033 coco`, дальше `localhost:8033`.

## YouTube: что держит загрузки живыми
Три вещи одновременно, снятие любой ломает всё: **cookies** (путь в `YOUTUBE_COOKIE_FILE`,
на проде `data/secret/youtube_cookies.txt` — gitignored, `chmod 600`) + **PO-token** от `pot-provider` + **EJS-солвер** challenge'ей.
- 🛑 Cookies выгружать из **простаивающего** профиля Chrome. Выгрузка из активного протухает в тот же
  день: браузер ротирует сессию и аннулирует копию. Признак протухания видно только в **предупреждении**
  yt-dlp (`cookies are no longer valid`), в тексте ошибки его нет.
- 🛑 `player_client` — `["tv_simply", "default"]`, `default` удалять нельзя: `tv_simply` не поддерживает
  cookies и молча пропускается, оставшись один — «Requested format is not available».
- Полный разбор трёх разных отказов YouTube (403 / бот-челлендж / протухшие куки) — `docs/research/`.

## Яндекс.Музыка: два канала, и путать их нельзя
`api.music.yandex.net` отвечает **451** всему, что не из России, — включая прод в Сингапуре.
Поэтому API ходит через SOCKS5 из `YANDEX_MUSIC_API_PROXY` (туннель до российского узла,
служба `yandex-proxy` на `coco`), а сам файл качается **напрямую**: раздача
(`storage.yandex.net`) гео-блока не имеет, и гнать мегабайты через прокси незачем.
- 🛑 Схема прокси — **`socks5h://`**, не `socks5://`. У `api.music.yandex.net` локальный резолв
  отдаёт IPv6 (`2a02:6b8::5:246`), ssh-туннель его не несёт, и соединение рвётся на установке:
  `socks5h` отдаёт имя на ту сторону и резолвит уже там. Отличить по симптому нельзя — обе схемы
  дают «Connection closed unexpectedly», а порт при этом доступен. Арбитр — пара
  `curl --socks5` (падает) против `curl --socks5-hostname` (200).
- 🛑 Без подписки Плюс API отдаёт валидный с виду ответ и **30-секундный огрызок**. Против этого
  два гейта: флаг `preview` в download-info и сверка длительности скачанного файла с
  метаданными. Снимать любой из них нельзя — первый приходит от той же стороны, что и огрызок.
- 🛑 Встроенный экстрактор `yandexmusic` в yt-dlp существует по имени, но **сломан** — на это
  легко купиться. Провайдер написан поверх библиотеки `yandex-music`.
- `YANDEX_MUSIC_TOKEN` — OAuth всего аккаунта Яндекса, не только музыки: только `.env.prod`.
- Замеры целиком — `docs/research/2026-09-21-yandex-music-geo-and-preview.md`.

## Досыл (redelivery)
`core/services/redelivery.py` + cron в воркере (`workers/tasks.py`, `minute=17`): если джоба упала, а
пользователь ждал, файл уезжает ему **реплаем на исходное сообщение** после починки. Ждущие — таблица
`delivery` (одна джоба, много ждущих: джобы дедуплицируются по фингерпринту).
Досыл берёт готовый файл из `final/`; `original/` держит MCP-ресурс
`music-forge://jobs/{id}/original/{name}`. Поэтому чистка (`core/services/retention.py`, ночной
cron) сносит каталог джобы **целиком** и только когда ему больше `JOBS_RETENTION_DAYS` (30) и
никто не ждёт файл — половинчатая чистка оставила бы живые ссылки с 404.

## Хранилище
Сгенерированные джобы — в `./data/jobs/`. Фотки/медиа проекта — в Cloudflare R2 (аккаунт-уровень).

## Доки и беклог
`docs/tasks/BACKLOG.md` — хаб отложенной работы (только ссылки), детали в `docs/tasks/bugs/<домен>.md`,
закрытое уезжает в `docs/tasks/DONE.md`. Формат карточки и правила нумерации — `docs/tasks/bugs/README.md`.
Разборы и замеры — `docs/research/`.
