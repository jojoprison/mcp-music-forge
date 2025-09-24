from __future__ import annotations

import enum
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from sqlmodel import Field as SQLField, JSON, SQLModel
from typing import Any, Optional


class JobStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class DownloadOptions(BaseModel):
    format: str = Field(default="mp3", description="Target format: mp3/flac/aac/opus")
    quality: str = Field(
        default="v0",
        description="Quality profile. For mp3: v0/v2/320, opus: 160/96, aac: 256/192, flac: lossless",
    )
    embed_cover: bool = Field(default=True)
    tags: dict[str, Any] = Field(default_factory=dict)
    prefer_original: bool = Field(
        default=True, description="If true, store original file in addition to transcoded"
    )


class Job(SQLModel, table=True):
    id: str = SQLField(primary_key=True, index=True)
    provider: str
    url: str
    fingerprint: str = SQLField(index=True, unique=True)
    status: str = SQLField(default=JobStatus.queued.value, index=True)
    error: Optional[str] = None

    options: dict[str, Any] = SQLField(sa_column_kwargs={"type_": JSON}, default_factory=dict)

    title: Optional[str] = None
    artist: Optional[str] = None
    duration: Optional[int] = None
    artwork_url: Optional[str] = None

    created_at: datetime = SQLField(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = SQLField(default_factory=lambda: datetime.now(timezone.utc))


class ArtifactKind(str, enum.Enum):
    original = "original"
    final = "final"


class ArtifactDTO(BaseModel):
    kind: ArtifactKind
    filename: str
    mime: str
    size: int
    sha256: str
    resource_uri: Optional[str] = None


class JobStatusDTO(BaseModel):
    id: str
    status: JobStatus
    error: Optional[str] = None
    title: Optional[str] = None
    artist: Optional[str] = None
    duration: Optional[int] = None
    artifacts: list[ArtifactDTO] = Field(default_factory=list)
