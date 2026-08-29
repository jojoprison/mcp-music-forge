from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from core.domain.delivery import Delivery
from core.domain.job import Job, JobStatus
from core.infra.db import session_scope
from core.services.download_orchestrator import process_job
from core.services.telegram_delivery import send_audio_reply
from core.settings import get_settings

_log = logging.getLogger(__name__)

# Потолок повторов на одного ждущего. Без него досыл превращается в вечный
# долбёж площадки с адреса, который она и так считает подозрительным.
MAX_ATTEMPTS = 8

_AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus"}

_REDELIVERY_CAPTION = (
    "✅ Готово — файл, который не доехал в прошлый раз. Извини за задержку."
)


def register_delivery(
    job_id: str, chat_id: int, message_id: int | None = None
) -> str:
    """Запоминает, кому отдать результат джобы.

    🛑 Вызывается ПРЯМО, без HTTP. Первая редакция выставляла это эндпоинтом
    `POST /deliveries` — и получалась дыра: api слушает `0.0.0.0:8033` без
    аутентификации, то есть кто угодно мог зарегистрировать доставку на чужой
    `chat_id` и заставить бота слать файлы чужим людям. Эндпоинт не нужен
    вовсе: бот поллится ВНУТРИ процесса api и ходил бы по HTTP сам к себе.

    Регистрируем в момент постановки, а не при выдаче: если процесс упадёт
    между ними — а это ровно тот случай, ради которого досыл и существует, —
    записывать будет уже некому.
    """
    with session_scope() as s:
        # Повтор той же ссылки тем же сообщением не должен плодить дубли:
        # файл пришёл бы человеку дважды.
        existing = (
            s.query(Delivery)
            .filter_by(job_id=job_id, chat_id=chat_id, message_id=message_id)
            .first()
        )
        if existing:
            return existing.id

        row = Delivery(job_id=job_id, chat_id=chat_id, message_id=message_id)
        s.add(row)
        s.flush()
        return row.id


def pending_job_ids() -> list[str]:
    """Джобы, которые кто-то ждёт, а они упали.

    Успешный обычный путь сюда не попадает по построению: бот отдал файл
    сразу, джоба осталась `succeeded`. Поэтому отдельная отметка «бот уже
    отправил» не нужна — её роль играет статус самой джобы.
    """
    with session_scope() as s:
        rows = (
            s.query(Delivery.job_id)
            .join(Job, Job.id == Delivery.job_id)
            .filter(
                Delivery.delivered_at.is_(None),
                Delivery.attempts < MAX_ATTEMPTS,
                Job.status == JobStatus.failed.value,
            )
            .distinct()
            .all()
        )
    return [r[0] for r in rows]


def _audio_file(job_id: str) -> Path | None:
    final_dir = get_settings().storage_dir / "jobs" / job_id / "final"
    if not final_dir.is_dir():
        return None

    files = [
        f
        for f in final_dir.iterdir()
        if f.is_file() and not f.name.startswith(".")
    ]
    audio = [f for f in files if f.suffix.lower() in _AUDIO_EXTENSIONS]
    if audio:
        return audio[0]
    return files[0] if files else None


async def redeliver_pending() -> int:
    """Повторяет упавшие джобы и досылает результат всем, кто его ждёт.

    Повтор самой джобы и есть проба «площадка ожила»: отдельная проверка
    здоровья была бы вторым источником правды, который может разойтись с
    настоящей загрузкой.

    Возвращает число фактически отправленных файлов.
    """
    delivered = 0

    for job_id in pending_job_ids():
        try:
            await process_job(job_id)
        except Exception as exc:  # noqa: BLE001 - повтор не должен ронять цикл
            _log.warning("redelivery: job %s still failing: %s", job_id, exc)

        with session_scope() as s:
            job = s.get(Job, job_id)
            status = job.status if job else None
            title, artist, duration = (
                (job.title, job.artist, job.duration) if job else (None,) * 3
            )

        if status != JobStatus.succeeded.value:
            _bump_attempts(job_id, "job still failing")
            continue

        path = _audio_file(job_id)
        if path is None:
            # 🛑 Не помечать доставленным: статус успешный, а файла нет
            # (каталог могли почистить). Отметка здесь потеряла бы человека
            # навсегда — в следующую выборку он уже не попадёт.
            _bump_attempts(job_id, "audio file missing on disk")
            continue

        delivered += await _send_to_waiters(
            job_id, path, title, artist, duration
        )

    return delivered


async def _send_to_waiters(
    job_id: str,
    path: Path,
    title: str | None,
    artist: str | None,
    duration: int | None,
) -> int:
    sent = 0
    for delivery_id, chat_id, message_id in _waiters_of(job_id):
        try:
            await send_audio_reply(
                chat_id=chat_id,
                message_id=message_id,
                path=path,
                title=title,
                artist=artist,
                duration=duration,
                caption=_REDELIVERY_CAPTION,
            )
        except Exception as exc:  # noqa: BLE001
            # Один заблокировал бота — остальные всё равно получат файл.
            _log.warning(
                "redelivery: send to chat %s failed: %s", chat_id, exc
            )
            _mark_error(delivery_id, str(exc))
            continue

        _mark_delivered(delivery_id)
        sent += 1

    return sent


def _waiters_of(job_id: str) -> list[tuple[str, int, int | None]]:
    with session_scope() as s:
        rows = (
            s.query(Delivery)
            .filter(
                Delivery.job_id == job_id,
                Delivery.delivered_at.is_(None),
                Delivery.attempts < MAX_ATTEMPTS,
            )
            .all()
        )
        return [(r.id, r.chat_id, r.message_id) for r in rows]


def _bump_attempts(job_id: str, reason: str) -> None:
    with session_scope() as s:
        rows = (
            s.query(Delivery)
            .filter(
                Delivery.job_id == job_id, Delivery.delivered_at.is_(None)
            )
            .all()
        )
        for row in rows:
            row.attempts += 1
            row.last_error = reason
            s.add(row)


def _mark_delivered(delivery_id: str) -> None:
    with session_scope() as s:
        row = s.get(Delivery, delivery_id)
        if row:
            row.delivered_at = datetime.now()
            row.last_error = None
            s.add(row)


def _mark_error(delivery_id: str, error: str) -> None:
    with session_scope() as s:
        row = s.get(Delivery, delivery_id)
        if row:
            row.attempts += 1
            row.last_error = error
            s.add(row)
