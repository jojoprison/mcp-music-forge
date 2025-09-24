from __future__ import annotations

import hashlib
import json
import uuid

from pydantic import BaseModel, Field
from sqlalchemy import select

from core.domain.job import Job, JobStatus
from core.infra.db import session_scope
from core.services.provider_registry import detect_provider
from core.services.queue import enqueue_download_job
from mcp_music_forge.mcp_app import mcp


class EnqueueOptions(BaseModel):
    format: str = Field(default="mp3")
    quality: str = Field(default="v0")
    embed_cover: bool = Field(default=True)
    prefer_original: bool = Field(default=True)
    tags: dict[str, str] = Field(default_factory=dict)


class EnqueueResult(BaseModel):
    job_id: str
    status: JobStatus


def _fingerprint(url: str, opts: EnqueueOptions) -> str:
    h = hashlib.sha256()
    key = json.dumps({"url": url, "opts": opts.model_dump()}, sort_keys=True)
    h.update(key.encode("utf-8"))
    return h.hexdigest()


@mcp.tool()
async def enqueue_download(
    url: str, options: EnqueueOptions | None = None
) -> EnqueueResult:
    """Create or dedupe a job and enqueue it for processing."""
    options = options or EnqueueOptions()
    provider = detect_provider(url)
    if not provider:
        raise ValueError("No provider can handle this URL")

    fp = _fingerprint(url, options)

    with session_scope() as s:
        # Our primary key is id; fingerprint is indexed unique.
        # Query by fingerprint.
        res = s.execute(select(Job).where(Job.fingerprint == fp))
        existing = res.scalar_one_or_none()
        if existing:
            job_id = existing.id
            status = JobStatus(existing.status)
        else:
            job_id = uuid.uuid4().hex
            job = Job(
                id=job_id,
                provider=provider.name,
                url=url,
                fingerprint=fp,
                status=JobStatus.queued.value,
                options=options.model_dump(),
            )
            s.add(job)
            status = JobStatus.queued
    # enqueue outside session
    await enqueue_download_job(job_id)
    return EnqueueResult(job_id=job_id, status=status)
