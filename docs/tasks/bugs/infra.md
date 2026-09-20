# INF — docker, деплой, сервер `coco`, диск, бэкапы

Формат карточки — [`README.md`](README.md). Закрытые уезжают в [`DONE.md`](../DONE.md).

---

## INF-2 — Яндекс.Музыка не заработает на проде, пока нет маршрута в РФ
- **Статус:** open · 🟠 medium — код готов и покрыт тестами, но на проде провайдер отдаст отказ
- **Что:** `api.music.yandex.net` отвечает **451** всему, что не из России, включая Сингапур, где
  живёт `coco`. Провайдер это переживает корректно (терминальная ошибка с внятным текстом), но
  скачать не может ничего. Нужен SOCKS5-маршрут до российского узла и `YANDEX_MUSIC_API_PROXY` в
  `.env.prod`. Через прокси идут только метаданные: сам файл `storage.yandex.net` раздаёт без
  гео-блока, и провайдер качает его напрямую.
- **Где:** `providers/yandex_music/adapter.py` — `_build_client()` (прокси) и `_http_download()`
  (прямой канал); `core/settings.py` — `YANDEX_MUSIC_API_PROXY`.
- **Простейший фикс:** `autossh -N -D 1080` с `coco` на `vpn-gateway` (111.88.254.249,
  Yandex.Cloud, RU — чистая машина, кроме ssh на ней ничего не крутится) под systemd-юнитом,
  `YANDEX_MUSIC_API_PROXY=socks5://127.0.0.1:1080`. Потолок названный: туннель — единая точка
  отказа, и пока он лежит, Яндекс отдаёт терминальный отказ вместо повтора; если это начнёт
  мешать — 3proxy на самом узле либо второй узел про запас.
- **Чего не хватает для фикса:** публичный ключ `coco` не лежит в `authorized_keys` на
  `vpn-gateway` (проверено 2026-09-21: `grep -c tg-3-hetzner-prod` → `0`), `autossh` на `coco`
  не установлен.
- **Готовые шаги** (выполняет человек — установка ключей и постоянных служб агенту не разрешена):

  ```bash
  # 1. ключ прода на российский узел
  ssh coco 'cat ~/.ssh/id_ed25519.pub' | ssh vpn-gateway 'cat >> ~/.ssh/authorized_keys'
  ssh coco 'ssh -o BatchMode=yes root@111.88.254.249 hostname'   # ждём: vpn-gateway

  # 2. туннель как служба на coco
  ssh coco 'apt-get update && apt-get install -y autossh'
  ssh coco 'cat > /etc/systemd/system/yandex-proxy.service' <<'UNIT'
  [Unit]
  Description=SOCKS5 в РФ для API Яндекс.Музыки (api.music.yandex.net отдаёт 451 из SG)
  After=network-online.target
  Wants=network-online.target

  [Service]
  # -N без команды, -D локальный SOCKS5; ServerAlive добивает мёртвый туннель,
  # иначе он висит «живым» и провайдер получает таймауты вместо отказа.
  ExecStart=/usr/bin/autossh -M 0 -N -D 127.0.0.1:1080 \
    -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
    -o ExitOnForwardFailure=yes -o StrictHostKeyChecking=accept-new \
    root@111.88.254.249
  Restart=always
  RestartSec=10

  [Install]
  WantedBy=multi-user.target
  UNIT
  ssh coco 'systemctl daemon-reload && systemctl enable --now yandex-proxy'

  # 3. настройки прода (network_mode: host, поэтому 127.0.0.1 виден контейнерам)
  #    YANDEX_MUSIC_TOKEN берётся из get_yandex_token.py, в репозиторий не попадает
  ssh coco 'cd /root/mcp-music-forge && echo "YANDEX_MUSIC_API_PROXY=socks5://127.0.0.1:1080" >> .env.prod'

  # 4. пересборка: без неё в образе нет пакета yandex-music
  ssh coco 'cd /root/mcp-music-forge && git pull && \
    docker compose -f docker-compose.prod.yml up -d --build api worker'
  ```
- **Проверка:** с `coco` изнутри контейнера `worker` — запрос к `api.music.yandex.net` отдаёт
  **200**, а не 451; следом боевая джоба по ссылке на трек кладёт в `final/` файл, чья
  длительность совпадает с заявленной (а не 30 с).
- **Ключи:** `451` · `socks5` · `YANDEX_MUSIC_API_PROXY` · `vpn-gateway` · `autossh`
- **Связи:** `docs/research/2026-09-21-yandex-music-geo-and-preview.md`
- **История:**
  - `2026-09-21` заведена вместе с провайдером Яндекс.Музыки; замеры 451/200 с четырёх точек
    и подтверждённая связность `coco` → РФ (188 мс) — в разборе выше
