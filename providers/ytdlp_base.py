from __future__ import annotations

from pathlib import Path
from typing import Any

import yt_dlp as ytdlp
from anyio import to_thread

from core.errors import (
    AuthRequiredError,
    MediaUnavailableError,
    ProviderError,
    TemporaryProviderError,
)
from core.ports.provider_port import ProviderPort

# Подстрока в тексте ошибки yt-dlp → что сказать пользователю.
# Порядок значим: первое совпадение выигрывает, поэтому частные случаи
# стоят выше общих.
# Бот-челлендж стоит отдельно от настоящей авторизации, и это не
# придирка: замер 28.08 показал, что одна и та же ссылка в 10:33
# скачалась, а в 10:58 получила этот отказ. Флагуется наш адрес, а не
# видео, поэтому отказ ПЛАВАЮЩИЙ и повтор его лечит. Считать его
# терминальным — значит отдавать пользователю «нужны cookies» там, где
# помогла бы вторая попытка через минуту.
_BOT_CHECK_MARKERS = (
    "sign in to confirm you're not a bot",
    "confirm you're not a bot",
)

# А это — настоящая авторизация: возраст, приватность, членство. Повтор
# здесь бесполезен по построению, сколько ни жди.
_AUTH_MARKERS = (
    "sign in to confirm your age",
    "this video is available to this channel's members",
    "join this channel to get access",
    "private video",
    # 🛑 Голого «sign in» здесь быть не должно: он перехватывает любую чужую
    # ошибку со словом sign in И делает нормализацию апострофа мёртвой —
    # мутант «убрать нормализацию» выживал именно из-за него.
)
_UNAVAILABLE_MARKERS = (
    "video unavailable",
    "removed by the uploader",
    "account associated with this video has been terminated",
    # Гео-блок yt-dlp формулирует минимум двумя способами, и второй не
    # содержит «not available» подряд: «The uploader has not made this
    # video available in your country».
    "not available in your country",
    "available in your country",
    "not available from your location",
    "this live event has ended",
    "http error 404",
)


def _normalize(text: str) -> str:
    """Приводит текст ошибки к виду, по которому можно матчить подстроку.

    🛑 yt-dlp печатает типографский апостроф: «Sign in to confirm you’re not
    a bot». Наивный матч по ASCII-апострофу не срабатывает вовсе — и
    классификатор молча относит самую частую ошибку к «неизвестным».
    """
    return text.lower().replace("’", "'").replace("‘", "'")


def classify_ytdlp_error(exc: Exception) -> ProviderError:
    """Переводит ошибку yt-dlp в доменную — с текстом для человека."""
    raw = str(exc)
    text = _normalize(raw)

    # Бот-челлендж проверяем первым. Сейчас наборы маркеров не пересекаются,
    # но если пересекутся — выиграет более частный случай, а не общий.
    if any(m in text for m in _BOT_CHECK_MARKERS):
        return TemporaryProviderError(
            "YouTube принял нас за бота и не отдал видео. Обычно проходит "
            "со второй попытки — если повторяется, нужен файл cookies.",
            technical=raw,
        )

    if any(m in text for m in _AUTH_MARKERS):
        return AuthRequiredError(
            "YouTube отдаёт это видео только авторизованным: возрастное "
            "ограничение, приватный доступ или подписка на канал.",
            technical=raw,
        )

    if any(m in text for m in _UNAVAILABLE_MARKERS):
        return MediaUnavailableError(
            "Видео недоступно: удалено, приватное или закрыто для нашего "
            "региона.",
            technical=raw,
        )

    # Всё остальное считаем временным: сеть, лимит частоты, 403 на
    # медиапоток, «формат недоступен» после смены раскладки форматов.
    # Ошибиться в эту сторону дёшево — цена всего лишь пара повторов.
    return TemporaryProviderError(
        "Площадка временно не отдала файл. Попробуй ещё раз через несколько "
        "минут.",
        technical=raw,
    )


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

        try:
            return await to_thread.run_sync(_run)
        except ProviderError:
            raise
        except Exception as exc:
            # Единственное место, где сырая ошибка yt-dlp превращается в
            # доменную. Раньше её глотал probe и наружу уходило
            # «Could not extract info from YouTube» — по такому тексту нельзя
            # ни понять причину, ни решить, есть ли смысл повторять.
            raise classify_ytdlp_error(exc) from exc

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
