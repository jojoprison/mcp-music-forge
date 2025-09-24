from __future__ import annotations

import hashlib
from pydantic import BaseModel, Field
from typing import Optional

from core.domain.job import ArtifactDTO, ArtifactKind, Job, JobStatus
from core.infra.db import session_scope
from core.ports.storage_port import StoragePort
from mcp_music_forge.mcp_app import mcp
from storage.local_fs import LocalStorage


class GetJobStatusResult(BaseModel):
    id: str
    status: JobStatus
    error: Optional[str] = None
    title: Optional[str] = None
    artist: Optional[str] = None
    duration: Optional[int] = None
    artifacts: list[ArtifactDTO] = Field(default_factory=list)


def _gather_artifacts(job_id: str, storage: StoragePort) -> list[ArtifactDTO]:
    artifacts: list[ArtifactDTO] = []
    for p in storage.list_files(job_id):
        # Simple heuristic: files in 'final/' are final, others original
        kind = ArtifactKind.final if "/final/" in str(p) else ArtifactKind.original
        # Compute sha256
        h = hashlib.sha256()
        try:
            h.update(p.read_bytes())
            sha = h.hexdigest()
        except Exception:
            sha = ""
        # Build resource URI matching resource templates
        if kind is ArtifactKind.final:
            resource_uri = f"forge://jobs/{job_id}/final/{p.name}"
        else:
            resource_uri = f"forge://jobs/{job_id}/original/{p.name}"
        artifacts.append(
            ArtifactDTO(
                kind=kind,
                filename=p.name,
                mime="application/octet-stream",
                size=p.stat().st_size,
                sha256=sha,
                resource_uri=resource_uri,
            )
        )
    return artifacts


@mcp.tool()
async def get_job_status(job_id: str) -> GetJobStatusResult:
    """Return job status and artifact list."""
    with session_scope() as s:
        job: Optional[Job] = s.get(Job, job_id)
        if not job:
            raise ValueError("Job not found")
        storage = LocalStorage()
        artifacts = _gather_artifacts(job_id, storage)
        return GetJobStatusResult(
            id=job.id,
            status=JobStatus(job.status),
            error=job.error,
            title=job.title,
            artist=job.artist,
            duration=job.duration,
            artifacts=artifacts,
        )
