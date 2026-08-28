from __future__ import annotations

from pathlib import Path
from typing import Any

from core.ports.provider_port import ProbeResult
from core.settings import get_settings
from providers.ytdlp_base import YtDlpProvider

_YOUTUBE_HOSTS = (
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
)


class YouTubeProvider(YtDlpProvider):
    name = "youtube"
    hosts = _YOUTUBE_HOSTS
    fallback_ext = "webm"

    def _cookie_file(self) -> Path | None:
        return get_settings().youtube_cookie_file

    def _extra_ydl_opts(self) -> dict[str, Any]:
        opts: dict[str, Any] = {
            "force_ipv4": True,
            # Решатель JS-челленджей: без него YouTube отдаёт «подтвердите,
            # что вы не бот» ещё на стадии метаданных.
            "remote_components": ["ejs:github"],
        }

        # Proof-of-origin токен: YouTube требует его для выдачи медиапотока
        # и отдаёт 403 без него — особенно датацентровым адресам. Сам yt-dlp
        # токены не генерирует, их выдаёт плагин-провайдер (bgutil).
        # Пусто — плагин берёт свой дефолт 127.0.0.1:4416.
        pot_base_url = get_settings().youtube_pot_base_url
        if pot_base_url:
            opts["extractor_args"] = {
                "youtubepot-bgutilhttp": {"base_url": [pot_base_url]}
            }

        return opts

    async def probe(self, url: str) -> ProbeResult:
        try:
            info = await self._extract_info(url, download=False)
        except Exception:
            # Приватное/удалённое видео либо отказ площадки — метаданных нет,
            # значит и качать нечего.
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
        _dur = info.get("duration")
        duration = int(_dur) if isinstance(_dur, int | float | str) else None

        artwork_url = None
        if info.get("thumbnails"):
            # Последний в списке — самый крупный.
            artwork_url = info["thumbnails"][-1].get("url")
        elif info.get("thumbnail"):
            artwork_url = info.get("thumbnail")

        return ProbeResult(
            provider=self.name,
            can_download=True,
            normalized_id=normalized_id,
            title=info.get("title"),
            artist=info.get("uploader") or info.get("channel"),
            duration=duration,
            artwork_url=artwork_url,
            reason_if_denied=None,
        )

    async def download(
        self, url: str, dest_dir: str, *, respect_tou: bool = True
    ) -> tuple[str, ProbeResult]:
        # respect_tou для YouTube не применяется: пометки «автор разрешил
        # скачивание», как у SoundCloud, здесь не существует.
        Path(dest_dir).mkdir(parents=True, exist_ok=True)

        probe = await self.probe(url)
        if not probe.can_download:
            raise PermissionError(
                probe.reason_if_denied or "Video unavailable"
            )

        outtmpl = str(Path(dest_dir) / "%(title)s.%(ext)s")
        info = await self._extract_info(url, download=True, outtmpl=outtmpl)

        return self._downloaded_path(info, dest_dir), probe
