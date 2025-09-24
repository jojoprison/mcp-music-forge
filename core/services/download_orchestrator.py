from __future__ import annotations

import logging
from pathlib import Path

import httpx
from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential

import transcoder.ffmpeg_cli as ffmpeg_cli
from core.domain.job import DownloadOptions, Job, JobStatus
from core.infra.db import session_scope
from core.services import provider_registry
from storage.local_fs import LocalStorage


async def _download_cover(url: str, dest: Path) -> Path | None:
    try:
        async with httpx.AsyncClient(
            timeout=20.0, follow_redirects=True
        ) as client:
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

    # Load and mark running; capture essentials
    with session_scope() as s:
        job = s.get(Job, job_id)
        if not job:
            return
        job.status = JobStatus.running.value
        s.add(job)
        url = job.url
        options = job.options

    provider = provider_registry.detect_provider(url)
    if not provider:
        _mark_failed(job_id, "No provider available")
        return

    # Download original with retries
    async for attempt in AsyncRetrying(
        wait=wait_exponential(multiplier=1, min=1, max=8),
        stop=stop_after_attempt(3),
    ):
        with attempt:
            original_dir = storage.ensure_subdir(job_id, "original")
            original_path_str, probe = await provider.download(
                url, str(original_dir)
            )

    # Update metadata
    _update_job_metadata(job_id, probe)

    original_path = Path(original_path_str)
    opts = DownloadOptions.model_validate(options)
    final_dir = storage.ensure_subdir(job_id, "final")
    final_path = await _produce_final(original_path, final_dir, opts)

    # Embed tags and cover (best-effort)
    await _embed_tags_and_cover(final_path, opts, probe, final_dir)

    # Mark success
    with session_scope() as s:
        j = s.get(Job, job_id)
        if j:
            j.status = JobStatus.succeeded.value
            s.add(j)


def _mark_failed(job_id: str, error: str) -> None:
    with session_scope() as s:
        job = s.get(Job, job_id)
        if job:
            job.status = JobStatus.failed.value
            job.error = error
            s.add(job)


def _update_job_metadata(job_id: str, probe) -> None:
    with session_scope() as s:
        j = s.get(Job, job_id)
        if j:
            j.title = probe.title
            j.artist = probe.artist
            j.duration = probe.duration
            j.artwork_url = probe.artwork_url
            s.add(j)


async def _produce_final(
    original_path: Path, final_dir: Path, opts: DownloadOptions
) -> Path:
    if _ext_of(original_path) == opts.format.lower():
        final_path = final_dir / original_path.name
        if original_path != final_path:
            final_dir.mkdir(parents=True, exist_ok=True)
            final_path.write_bytes(original_path.read_bytes())
        return final_path
    return await ffmpeg_cli.transcode(
        original_path, final_dir, opts.format, opts.quality
    )


async def _embed_tags_and_cover(
    final_path: Path, opts: DownloadOptions, probe, final_dir: Path
) -> None:
    try:
        suffix = final_path.suffix.lower()
        if suffix == ".mp3":
            await _tag_mp3(final_path, opts, probe, final_dir)
        elif suffix == ".flac":
            await _tag_flac(final_path, opts, probe, final_dir)
    except Exception as e:  # pragma: no cover - best-effort
        logging.getLogger(__name__).warning("Tagging skipped: %s", e)


async def _tag_mp3(
    final_path: Path, opts: DownloadOptions, probe, final_dir: Path
) -> None:
    from mutagen.id3 import APIC, ID3, TIT2, TPE1

    tags = ID3(final_path)
    if probe.title:
        tags.add(TIT2(encoding=3, text=probe.title))
    if probe.artist:
        tags.add(TPE1(encoding=3, text=probe.artist))
    if opts.embed_cover and probe.artwork_url:
        cover = await _download_cover(
            probe.artwork_url, final_dir / "cover.jpg"
        )
        if cover and cover.exists():
            tags.add(
                APIC(
                    encoding=3,
                    mime="image/jpeg",
                    type=3,
                    desc="Cover",
                    data=cover.read_bytes(),
                )
            )
    tags.save(v2_version=3)


async def _tag_flac(
    final_path: Path, opts: DownloadOptions, probe, final_dir: Path
) -> None:
    from mutagen import File as MutagenFile
    from mutagen.flac import Picture

    mf = MutagenFile(final_path, easy=False)
    f = mf
    if f is not None and hasattr(f, "pictures"):
        if opts.embed_cover and probe.artwork_url:
            cover = await _download_cover(
                probe.artwork_url, final_dir / "cover.jpg"
            )
            if cover and cover.exists():
                pic = Picture()
                pic.data = cover.read_bytes()
                pic.mime = "image/jpeg"
                f.add_picture(pic)
                f.save()
