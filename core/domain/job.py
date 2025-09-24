from __future__ import annotations

import enum
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import JSON as SAJSON
from sqlalchemy import Column
from sqlmodel import Field as SQLField
from sqlmodel import SQLModel


class JobStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class DownloadOptions(BaseModel):
    format: str = Field(
        default="mp3", description="Target format: mp3/flac/aac/opus"
    )
    quality: str = Field(
        default="v0",
        description=(
            "Quality profile. For mp3: v0/v2/320, opus: 160/96, "
            "aac: 256/192, flac: lossless"
        ),
    )
    embed_cover: bool = Field(default=True)
    tags: dict[str, Any] = Field(default_factory=dict)
    prefer_original: bool = Field(
        default=True,
        description="If true, store original file in addition to transcoded",
    )


class Job(SQLModel, table=True):  # type: ignore[call-arg]
    id: str = SQLField(primary_key=True, index=True)
    provider: str
    url: str
    fingerprint: str = SQLField(index=True, unique=True)
    status: str = SQLField(default=JobStatus.queued.value, index=True)
    error: str | None = None

    options: dict[str, Any] = SQLField(
        sa_column=Column(SAJSON), default_factory=dict
    )

    title: str | None = None
    artist: str | None = None
    duration: int | None = None
    artwork_url: str | None = None

    created_at: datetime = SQLField(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = SQLField(default_factory=lambda: datetime.now(UTC))


class ArtifactKind(str, enum.Enum):
    original = "original"
    final = "final"


class ArtifactDTO(BaseModel):
    kind: ArtifactKind
    filename: str
    mime: str
    size: int
    sha256: str
    resource_uri: str | None = None


class JobStatusDTO(BaseModel):
    id: str
    status: JobStatus
    error: str | None = None
    title: str | None = None
    artist: str | None = None
    duration: int | None = None
    artifacts: list[ArtifactDTO] = Field(default_factory=list)
