from __future__ import annotations

from pathlib import Path
from typing import Any

import yt_dlp as ytdlp
from anyio import to_thread

from core.ports.provider_port import ProviderPort


class YtDlpProvider(ProviderPort):
    """Общая обвязка над yt-dlp для всех площадок.

    Наследник объявляет `name`/`hosts`, при необходимости добавляет свои
    опции в `_extra_ydl_opts` и файл cookies в `_cookie_file`. Семантику
    `probe`/`download` каждый решает сам — она у площадок разная: SoundCloud
    качает только помеченное автором, YouTube качает всё, что открывается.
    """

    hosts: tuple[str, ...] = ()
    fallback_ext: str = "m4a"

    def can_handle(self, url: str) -> bool:
        return any(h in url for h in self.hosts)

    def _extra_ydl_opts(self) -> dict[str, Any]:
        """Опции, специфичные для площадки."""
        return {}

    def _cookie_file(self) -> Path | None:
        """Файл cookies площадки; None — работаем анонимно."""
        return None

    def _build_opts(self, outtmpl: str | None) -> dict[str, Any]:
        opts: dict[str, Any] = {
            "quiet": True,
            "noprogress": True,
            "ignoreerrors": False,
            "nocheckcertificate": True,
            "outtmpl": outtmpl or "%(title)s.%(ext)s",
            "format": "bestaudio/best",
        }
        opts.update(self._extra_ydl_opts())

        # Путь может указывать на каталог или на несуществующий файл —
        # yt-dlp в обоих случаях падает, поэтому кладём только обычный файл.
        cookie_file = self._cookie_file()
        if cookie_file is not None and Path(cookie_file).is_file():
            opts["cookiefile"] = str(cookie_file)

        # Без явного home yt-dlp пишет относительно cwd процесса.
        if outtmpl:
            base_dir = str(Path(outtmpl).parent)
            if base_dir and base_dir != ".":
                opts["paths"] = {"home": base_dir}

        return opts

    async def _extract_info(
        self, url: str, download: bool, outtmpl: str | None = None
    ) -> dict[str, Any]:
        opts = self._build_opts(outtmpl)

        def _run() -> dict[str, Any]:
            with ytdlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=download)

        return await to_thread.run_sync(_run)

    def _downloaded_path(self, info: dict[str, Any], dest_dir: str) -> str:
        """Куда yt-dlp реально положил файл.

        Сперва спрашиваем сам yt-dlp: он санитайзит имя, и собранное из
        `title` имя расходится с ним на спецсимволах.
        """
        requested = info.get("requested_downloads") or [{}]
        filepath = requested[0].get("filepath")
        if filepath:
            return str(filepath)

        title = info.get("title") or info.get("id")
        ext = info.get("ext") or requested[0].get("ext") or self.fallback_ext
        return str(Path(dest_dir) / f"{title}.{ext}")
