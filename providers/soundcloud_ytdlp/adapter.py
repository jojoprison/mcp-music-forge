from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yt_dlp as ytdlp
from anyio import to_thread

from core.ports.provider_port import ProbeResult, ProviderPort
from core.settings import get_settings

_SOUNDCLOUD_HOSTS = (
    "soundcloud.com",
    "m.soundcloud.com",
    "on.soundcloud.com",
)


@dataclass
class _DLResult:
    filepath: str
    info: dict[str, Any]


class SoundCloudYtDlpProvider(ProviderPort):
    name = "soundcloud"

    def can_handle(self, url: str) -> bool:
        return any(h in url for h in _SOUNDCLOUD_HOSTS)

    async def _extract_info(
        self, url: str, download: bool, outtmpl: str | None = None
    ) -> dict[str, Any]:
        settings = get_settings()
        ydl_opts: dict[str, Any] = {
            "quiet": True,
            "noprogress": True,
            "ignoreerrors": False,
            "nocheckcertificate": True,
            "outtmpl": outtmpl or "%(title)s.%(ext)s",
            "format": "bestaudio/best",
        }
        if settings.soundcloud_cookie_file:
            ydl_opts["cookiefile"] = str(settings.soundcloud_cookie_file)

        def _run() -> dict[str, Any]:
            with ytdlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=download)

        return await to_thread.run_sync(_run)

    async def probe(self, url: str) -> ProbeResult:
        info = await self._extract_info(url, download=False)
        # Only allow if uploader marked track as downloadable to respect ToU
        downloadable = bool(
            info.get("downloadable") or info.get("download_url")
        )
        normalized_id = (
            str(info.get("id")) if info.get("id") is not None else None
        )
        title = info.get("title")
        artist = info.get("uploader") or info.get("artist")
        _dur = info.get("duration")
        if isinstance(_dur, int | float | str):
            duration = int(_dur)
        else:
            duration = None
        artwork_url = (
            info.get("thumbnail") or info.get("thumbnails", [{}])[-1].get("url")
            if info.get("thumbnails")
            else None
        )
        reason = (
            None
            if downloadable
            else "Track is not marked as downloadable by uploader per ToU"
        )
        return ProbeResult(
            provider=self.name,
            can_download=downloadable,
            normalized_id=normalized_id,
            title=title,
            artist=artist,
            duration=duration,
            artwork_url=artwork_url,
            reason_if_denied=reason,
        )

    async def download(
        self, url: str, dest_dir: str
    ) -> tuple[str, ProbeResult]:
        Path(dest_dir).mkdir(parents=True, exist_ok=True)
        # Enforce can_download prior to downloading to respect ToU
        probe = await self.probe(url)
        if not probe.can_download:
            raise PermissionError(
                probe.reason_if_denied or "Track not allowed for download"
            )

        outtmpl = str(Path(dest_dir) / "%(title)s.%(ext)s")
        info = await self._extract_info(url, download=True, outtmpl=outtmpl)
        # Construct filepath like yt-dlp would have produced
        title = info.get("title") or info.get("id")
        ext = (
            info.get("ext")
            or (
                info.get("requested_downloads", [{}])[0].get("ext")
                if info.get("requested_downloads")
                else None
            )
            or "mp3"
        )
        filename = f"{title}.{ext}"
        filepath = str(Path(dest_dir) / filename)

        return filepath, probe
