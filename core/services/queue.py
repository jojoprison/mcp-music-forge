from __future__ import annotations

from arq import create_pool
from arq.connections import RedisSettings

from core.settings import get_settings


async def enqueue_download_job(job_id: str) -> None:
    settings = get_settings()
    async with await create_pool(
        RedisSettings.from_dsn(settings.redis_url)
    ) as redis:
        await redis.enqueue_job(
            "process_download", job_id
        )  # workers.tasks.process_download
