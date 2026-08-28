from __future__ import annotations

from pathlib import Path

from core.ports.provider_port import ProbeResult
from core.settings import get_settings
from providers.ytdlp_base import YtDlpProvider

_SOUNDCLOUD_HOSTS = (
    "soundcloud.com",
    "m.soundcloud.com",
    "on.soundcloud.com",
)


class SoundCloudYtDlpProvider(YtDlpProvider):
    name = "soundcloud"
    hosts = _SOUNDCLOUD_HOSTS
    fallback_ext = "mp3"

    def _cookie_file(self) -> Path | None:
        return get_settings().soundcloud_cookie_file

    async def probe(self, url: str) -> ProbeResult:
        info = await self._extract_info(url, download=False)
        # Качаем только то, что автор сам пометил доступным — этого требует ToU.
        downloadable = bool(
            info.get("downloadable") or info.get("download_url")
        )
        normalized_id = (
            str(info.get("id")) if info.get("id") is not None else None
        )
        _dur = info.get("duration")
        duration = int(_dur) if isinstance(_dur, int | float | str) else None
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
            title=info.get("title"),
            artist=info.get("uploader") or info.get("artist"),
            duration=duration,
            artwork_url=artwork_url,
            reason_if_denied=reason,
        )

    async def download(
        self, url: str, dest_dir: str, *, respect_tou: bool = True
    ) -> tuple[str, ProbeResult]:
        Path(dest_dir).mkdir(parents=True, exist_ok=True)

        probe = await self.probe(url)
        if respect_tou and not probe.can_download:
            raise PermissionError(
                probe.reason_if_denied or "Track not allowed for download"
            )

        outtmpl = str(Path(dest_dir) / "%(title)s.%(ext)s")
        info = await self._extract_info(url, download=True, outtmpl=outtmpl)

        return self._downloaded_path(info, dest_dir), probe
