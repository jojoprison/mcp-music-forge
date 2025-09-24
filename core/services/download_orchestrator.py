from __future__ import annotations

import httpx
from pathlib import Path
from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential

from core.domain.job import DownloadOptions, Job, JobStatus
from core.infra.db import session_scope
from core.services.provider_registry import detect_provider
from storage.local_fs import LocalStorage
from transcoder.ffmpeg_cli import transcode


async def _download_cover(url: str, dest: Path) -> Path | None:
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(r.content)
            return dest
    except Exception:
        return None


def _ext_of(path: Path) -> str:
    return path.suffix.lstrip(".").lower()


async def process_job(job_id: str) -> None:
    storage = LocalStorage()

    # Load job
    with session_scope() as s:
        job = s.get(Job, job_id)
        if not job:
            return
        job.status = JobStatus.running.value
        s.add(job)

    provider = detect_provider(job.url)
    if not provider:
        with session_scope() as s:
            job = s.get(Job, job_id)
            if job:
                job.status = JobStatus.failed.value
                job.error = "No provider available"
                s.add(job)
        return

    # Download original with retries
    async for attempt in AsyncRetrying(wait=wait_exponential(multiplier=1, min=1, max=8),
                                       stop=stop_after_attempt(3)):  # type: ignore[misc]
        with attempt:
            original_dir = storage.ensure_subdir(job_id, "original")
            original_path_str, probe = await provider.download(job.url, str(original_dir))

    # Update metadata
    with session_scope() as s:
        j = s.get(Job, job_id)
        if j:
            j.title = probe.title
            j.artist = probe.artist
            j.duration = probe.duration
            j.artwork_url = probe.artwork_url
            s.add(j)

    original_path = Path(original_path_str)

    # Transcode if needed
    opts = DownloadOptions.model_validate(job.options)
    final_dir = storage.ensure_subdir(job_id, "final")
    final_path: Path
    if _ext_of(original_path) == opts.format.lower():
        final_path = final_dir / original_path.name
        if original_path != final_path:
            final_path.write_bytes(original_path.read_bytes())
    else:
        final_path = await transcode(original_path, final_dir, opts.format, opts.quality)

    # Embed basic tags and cover (best-effort)
    try:
        from mutagen import File as MutagenFile
        from mutagen.flac import Picture
        from mutagen.id3 import APIC, ID3, TIT2, TPE1

        mf = MutagenFile(final_path, easy=False)
        if final_path.suffix.lower() == ".mp3":
            tags = ID3(final_path)
            if probe.title:
                tags.add(TIT2(encoding=3, text=probe.title))
            if probe.artist:
                tags.add(TPE1(encoding=3, text=probe.artist))
            # Cover
            if opts.embed_cover and probe.artwork_url:
                cover = await _download_cover(probe.artwork_url, final_dir / "cover.jpg")
                if cover and cover.exists():
                    tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover.read_bytes()))
            tags.save(v2_version=3)
        elif final_path.suffix.lower() == ".flac":
            f = mf
            if f is not None and hasattr(f, "pictures"):
                if opts.embed_cover and probe.artwork_url:
                    cover = await _download_cover(probe.artwork_url, final_dir / "cover.jpg")
                    if cover and cover.exists():
                        pic = Picture()
                        pic.data = cover.read_bytes()
                        pic.mime = "image/jpeg"
                        f.add_picture(pic)  # type: ignore[attr-defined]
                        f.save()
    except Exception:
        # Non-fatal
        pass

    with session_scope() as s:
        j = s.get(Job, job_id)
        if j:
            j.status = JobStatus.succeeded.value
            s.add(j)
