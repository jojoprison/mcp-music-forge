from __future__ import annotations

from pathlib import Path

import pytest

from core.domain.job import DownloadOptions, Job, JobStatus
from core.infra.db import create_db_and_tables, session_scope
from core.ports.provider_port import ProbeResult, ProviderPort
from core.services.download_orchestrator import process_job
from core.settings import get_settings


class _FakeProvider(ProviderPort):
    name = "soundcloud"

    def can_handle(self, url: str) -> bool:
        return True

    async def probe(self, url: str) -> ProbeResult:
        return ProbeResult(
            provider=self.name,
            can_download=True,
            normalized_id="fake-1",
            title="Fake",
            artist="Tester",
            duration=1,
            artwork_url=None,
            reason_if_denied=None,
        )

    async def download(
        self, url: str, dest_dir: str, *, respect_tou: bool = True
    ) -> tuple[str, ProbeResult]:
        d = Path(dest_dir)
        d.mkdir(parents=True, exist_ok=True)
        p = d / "fake.wav"
        # Write a few bytes (not a real audio), enough for test with
        # patched transcode
        p.write_bytes(b"RIFF0000WAVEfmt ")
        probe = await self.probe(url)
        return str(p), probe


@pytest.mark.asyncio
async def test_process_job_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Settings
    settings = get_settings()
    settings.storage_dir = tmp_path / "data"
    create_db_and_tables()

    # Patch provider detection
    from core.services import provider_registry

    monkeypatch.setattr(
        provider_registry, "detect_provider", lambda url: _FakeProvider()
    )

    # Patch transcode to just copy with new extension
    async def fake_transcode(
        input_path: Path, output_dir: Path, target_format: str, quality: str
    ) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        out = output_dir / (input_path.stem + ".mp3")
        out.write_bytes(Path(input_path).read_bytes())
        return out

    import transcoder.ffmpeg_cli as ffmpeg_cli

    monkeypatch.setattr(ffmpeg_cli, "transcode", fake_transcode)

    # Create job
    with session_scope() as s:
        j = Job(
            id="job1",
            provider="soundcloud",
            url="http://example.com/x",
            fingerprint="fp1",
            status=JobStatus.queued.value,
            options=DownloadOptions().model_dump(),
        )
        s.add(j)

    # Run
    await process_job("job1")

    # Assert
    with session_scope() as s:
        job_db = s.get(Job, "job1")
        assert job_db is not None
        assert job_db.status == JobStatus.succeeded.value
        job_dir = settings.storage_dir / "jobs" / "job1" / "final"
        assert job_dir.exists()
        files = list(job_dir.glob("*"))
        assert files, "No output files created"
