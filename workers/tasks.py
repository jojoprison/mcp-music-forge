from __future__ import annotations

import logging
from typing import Any

from arq import cron
from arq.connections import RedisSettings

from core.domain.job import Job, JobStatus
from core.infra.db import create_db_and_tables, session_scope
from core.services.download_orchestrator import process_job
from core.services.redelivery import redeliver_pending
from core.services.retention import sweep_old_jobs
from core.settings import get_settings


async def startup(_: Any) -> None:  # pragma: no cover - worker bootstrap
    # Ensure DB tables exist
    create_db_and_tables()


async def shutdown(_: Any) -> None:  # pragma: no cover - worker bootstrap
    # Nothing to cleanup yet
    return None


async def process_download(ctx: Any, job_id: str) -> None:
    try:
        await process_job(job_id)
    except Exception as e:  # noqa: BLE001
        # Mark as failed
        with session_scope() as s:
            j = s.get(Job, job_id)
            if j:
                j.status = JobStatus.failed.value
                j.error = str(e)
                s.add(j)
        # Do not re-raise to keep ARQ from trying to
        # serialize complex exceptions
        return None


async def redeliver(ctx: Any) -> None:
    """Досылает файлы тем, у кого джоба упала, когда площадка снова отдаёт.

    Повтор самой джобы и есть проба «ожило ли»: отдельная проверка здоровья
    была бы вторым источником правды, который может разойтись с настоящей
    загрузкой. Пока площадка лежит, попытка просто не удаётся и счётчик
    растёт до потолка.
    """
    sent = await redeliver_pending()
    if sent:
        logging.getLogger(__name__).info("redelivered %s file(s)", sent)


async def cleanup_storage(ctx: Any) -> None:
    """Удаляет каталоги джоб старше срока хранения (INF-1).

    Ждущих досыла чистка не трогает, поэтому порядок с досылом не важен:
    пересечься они могут только на джобе, которую досыл уже закрыл.
    """
    removed, freed = sweep_old_jobs()
    if removed:
        logging.getLogger(__name__).info(
            "cleaned %s job dir(s), freed %.1f MB", removed, freed / 1048576
        )


# Resolve Redis settings from env via our settings provider
_settings = get_settings()


class WorkerSettings:  # pragma: no cover - settings container used by arq CLI
    functions = [process_download]
    # Раз в час: чаще смысла нет (окно блокировки у площадки — часы), реже
    # человек ждёт дольше необходимого. Минута не нулевая, чтобы не сходиться
    # с любыми другими часовыми задачами.
    # Ночью и раз в сутки: чистка сканирует весь каталог, а её результат
    # не нужен никому срочно.
    cron_jobs = [
        cron(redeliver, minute=17),
        cron(cleanup_storage, hour=4, minute=41),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(_settings.redis_url)
    max_jobs = 1
