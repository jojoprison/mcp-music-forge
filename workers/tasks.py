from __future__ import annotations

from arq.connections import RedisSettings
from arq.types import JobCtx

from core.domain.job import Job, JobStatus
from core.infra.db import create_db_and_tables, session_scope
from core.services.download_orchestrator import process_job
from core.settings import get_settings


async def startup(_: JobCtx) -> None:  # pragma: no cover - worker bootstrap
    # Ensure DB tables exist
    create_db_and_tables()


async def shutdown(_: JobCtx) -> None:  # pragma: no cover - worker bootstrap
    # Nothing to cleanup yet
    return None


async def process_download(ctx: JobCtx, job_id: str) -> None:
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
        raise


# Resolve Redis settings from env via our settings provider
_settings = get_settings()


class WorkerSettings:  # pragma: no cover - settings container used by arq CLI
    functions = [process_download]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(_settings.redis_url)
