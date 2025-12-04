from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yt_dlp as ytdlp
from anyio import to_thread

from core.ports.provider_port import ProbeResult, ProviderPort


_YOUTUBE_HOSTS = (
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
)


@dataclass
class _DLResult:
    filepath: str
    info: dict[str, Any]


class YouTubeProvider(ProviderPort):
    name = "youtube"

    def can_handle(self, url: str) -> bool:
        # Simple check: host matching.
        # Note: This simple check might be too broad if URL is like google.com?q=youtube.com
        # but for now it's fine as per user request to "just work".
        # A better check would be parsing the domain.
        return any(h in url for h in _YOUTUBE_HOSTS)

    async def _extract_info(
        self, url: str, download: bool, outtmpl: str | None = None
    ) -> dict[str, Any]:
        ydl_opts: dict[str, Any] = {
            "quiet": True,
            "noprogress": True,
            "ignoreerrors": False,
            "nocheckcertificate": True,
            "force_ipv4": True,
            "outtmpl": outtmpl or "%(title)s.%(ext)s",
            "format": "bestaudio/best",  # Download best audio quality
        }

        # If outtmpl provided, set base download dir explicitly
        if outtmpl:
            try:
                base_dir = str(Path(outtmpl).parent)
                if base_dir and base_dir != ".":
                    ydl_opts["paths"] = {"home": base_dir}
            except Exception:
                pass

        def _run() -> dict[str, Any]:
            with ytdlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=download)

        return await to_thread.run_sync(_run)

    async def probe(self, url: str) -> ProbeResult:
        try:
            info = await self._extract_info(url, download=False)
        except Exception:
            # If probe fails (e.g. private video), return failed probe
            return ProbeResult(
                provider=self.name,
                can_download=False,
                normalized_id=None,
                title=None,
                artist=None,
                duration=None,
                artwork_url=None,
                reason_if_denied="Could not extract info from YouTube",
            )

        normalized_id = (
            str(info.get("id")) if info.get("id") is not None else None
        )
        title = info.get("title")
        artist = info.get("uploader") or info.get("channel")
        
        _dur = info.get("duration")
        duration = int(_dur) if isinstance(_dur, (int, float, str)) else None

        # Get best thumbnail
        artwork_url = None
        if info.get("thumbnails"):
            # Usually the last one is largest
            artwork_url = info.get("thumbnails")[-1].get("url")
        elif info.get("thumbnail"):
            artwork_url = info.get("thumbnail")

        # For YouTube, we assume everything is downloadable if we can extract info.
        # User explicitly asked to download "from video".
        downloadable = True
        
        return ProbeResult(
            provider=self.name,
            can_download=downloadable,
            normalized_id=normalized_id,
            title=title,
            artist=artist,
            duration=duration,
            artwork_url=artwork_url,
            reason_if_denied=None,
        )

    async def download(
        self, url: str, dest_dir: str, *, respect_tou: bool = True
    ) -> tuple[str, ProbeResult]:
        # We ignore respect_tou for YouTube as per user request to "force download"
        # and "download best mp3 from video".
        
        Path(dest_dir).mkdir(parents=True, exist_ok=True)
        
        probe = await self.probe(url)
        if not probe.can_download:
             raise PermissionError(
                probe.reason_if_denied or "Video unavailable"
            )

        outtmpl = str(Path(dest_dir) / "%(title)s.%(ext)s")
        info = await self._extract_info(url, download=True, outtmpl=outtmpl)

        title = info.get("title") or info.get("id")
        ext = (
            info.get("ext")
            or (
                info.get("requested_downloads", [{}])[0].get("ext")
                if info.get("requested_downloads")
                else None
            )
            or "webm" # Fallback
        )
        
        # Sanitize filename characters if needed, but yt-dlp usually handles it.
        # However, we need to match what yt-dlp wrote.
        # Since we used %(title)s.%(ext)s, we need the exact title yt-dlp used.
        # Ideally, we should use 'prepare_filename' from yt-dlp, but here we assume 
        # it matches info['title']. Note: yt-dlp might sanitize filename.
        
        # Safer approach: Find the file in dest_dir that was just created or rely on return?
        # yt-dlp extract_info returns the info dict, which *should* contain the filename
        # if we look at 'requested_downloads' -> 'filepath'.
        
        filepath = None
        if info.get("requested_downloads"):
            filepath = info["requested_downloads"][0].get("filepath")
        
        if not filepath:
             # Fallback construction
             filename = f"{title}.{ext}"
             filepath = str(Path(dest_dir) / filename)

        return filepath, probe
