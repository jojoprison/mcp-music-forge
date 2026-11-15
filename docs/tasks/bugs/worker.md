# Воркер и очередь (`WRK`)

Формат карточки — [`README.md`](README.md).

## WRK-1 — задача, убитая таймаутом, навсегда остаётся «выполняется»
- **Статус:** open · 🟠 medium
- **Что:** arq снимает задачу через 300 с (`TimeoutError`), но статус в БД никто не меняет —
  джоба висит `running`. Досыл берёт только `failed` (`pending_job_ids`), поэтому ждущий
  человек не получит файл никогда, а бот не сообщает об отказе. Почему статус не пишется:
  таймаут отменяет задачу через `asyncio.CancelledError`, а он наследует `BaseException`,
  не `Exception`, — `except Exception` в `process_download` его пропускает.
- **Где:** `workers/tasks.py:27-30` — `process_download`; `core/services/redelivery.py:61` —
  `pending_job_ids`.
- **Простейший фикс:** ловить `asyncio.CancelledError`/таймаут вокруг `process_job` и
  записывать `failed` с понятной ошибкой до повторного выброса.
- **Проверка:** тест с задачей, которая дольше таймаута → статус `failed`, джоба попадает в
  `pending_job_ids()`.
- **Ключи:** `TimeoutError` · `running` · `job_timeout`
- **Связи:** [PROV-3] — самый частый источник таймаута
- **История:**
  - `2026-11-12` джоба `ddd6d2ac…` (ссылка из микса) висит `running` после таймаута
