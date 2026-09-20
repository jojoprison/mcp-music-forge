from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from anyio import to_thread

from core.errors import (
    AuthRequiredError,
    MediaUnavailableError,
    ProviderError,
    TemporaryProviderError,
)
from core.ports.provider_port import ProbeResult, ProviderPort
from core.settings import get_settings

_log = logging.getLogger(__name__)

_YANDEX_HOSTS = (
    "music.yandex.ru",
    "music.yandex.com",
    "music.yandex.kz",
    "music.yandex.by",
)

# Из ссылки нужен ТОЛЬКО номер трека: /album/<n>/track/<n> и /track/<n>
# ведут на один и тот же трек, номер альбома API не требуется.
_TRACK_ID_RE = re.compile(r"/track/(\d+)")

# Что нельзя пускать в имя файла: разделители пути, спецсимволы Windows
# (файлы уезжают людям в телеграм) и управляющие байты.
_UNSAFE_CHARS = re.compile(r'[/\\:*?"<>|\x00-\x1f]')

# Ниже этой доли от заявленной длительности файл считаем обрезанным.
# Отрыв огромный (30 с против 125.8 с — это 24%), поэтому порог стоит
# высоко: запас нужен только на погрешность оценки длины по заголовкам mp3.
_MIN_DURATION_RATIO = 0.8

_HTTP_TIMEOUT = 120.0

# Прокси-строка может нести креды (socks5://user:pass@host), а сетевая ошибка
# печатает её целиком — и дальше она уезжает в technical, то есть в логи.
_CREDS_RE = re.compile(r"(?<=://)[^/\s@]+:[^/\s@]+(?=@)")


def _redact(text: str) -> str:
    return _CREDS_RE.sub("<REDACTED>", text)


def _track_id_from_url(url: str) -> str:
    # Разбираем path, а не сырую ссылку. Хвост «?utm_source=desktop&
    # utm_medium=copy_link», с которым ссылка приходит из телеграма, сам по
    # себе безобиден: `\d+` обрывается на «?» (проверено на обеих формах
    # ссылки). Опасен другой случай — «/track/<n>» ВНУТРИ query: по сырой
    # строке ссылка на альбом «…/album/40348473?from=/track/999» отдала бы
    # 999, то есть мы молча скачали бы чужой трек вместо отказа.
    match = _TRACK_ID_RE.search(urlsplit(url).path)
    if not match:
        raise ProviderError(
            "В ссылке нет номера трека. Нужна ссылка на трек, а не на "
            "альбом, плейлист или исполнителя.",
            technical=url,
        )
    return match.group(1)


def classify_yandex_error(exc: Exception) -> ProviderError:
    """Переводит отказ Яндекса в доменный — с текстом для человека."""
    if isinstance(exc, ImportError):
        return ProviderError(
            "Провайдер Яндекс.Музыки не установлен: не хватает пакета "
            "yandex-music. Повтор не поможет, нужна пересборка образа.",
            technical=_redact(str(exc)),
        )

    text = str(exc).lower()

    # 🛑 Голый «451» здесь не матчим: в тексте ошибки лежат номера треков и
    # альбомов, и любой из них может содержать эти три цифры — тогда обычный
    # сбой уехал бы в терминальные и потерял повторы. Библиотека форматирует
    # сетевую ошибку как «<код>: <причина>», поэтому проверяем начало строки.
    if "legal reasons" in text or text.startswith("451"):
        return MediaUnavailableError(
            "API Яндекс.Музыки закрыт для зарубежных адресов (451). Повтор "
            "не поможет — нужен российский прокси в YANDEX_MUSIC_API_PROXY.",
            technical=_redact(str(exc)),
        )

    if "unauthorized" in text or "invalid token" in text:
        return AuthRequiredError(
            "Токен Яндекс.Музыки не принят — истёк или отозван. Нужен "
            "новый токен аккаунта с подпиской Плюс.",
            technical=_redact(str(exc)),
        )

    # Голый «404» здесь так же опасен, как «451» выше, и по той же причине:
    # номер трека 40477104 содержит эти цифры подстрокой, и сетевой сбой на
    # нём уехал бы в терминальные, потеряв повторы.
    if "not found" in text or text.startswith("404"):
        return MediaUnavailableError(
            "Трек недоступен: удалён или закрыт для нашего региона.",
            technical=_redact(str(exc)),
        )

    # Всё прочее — сеть, таймаут, лимит частоты, протухшая за минуту прямая
    # ссылка (410). Ошибиться в эту сторону дёшево: цена — пара повторов.
    return TemporaryProviderError(
        "Яндекс.Музыка временно не отдала файл. Попробуй ещё раз через "
        "несколько минут.",
        technical=_redact(str(exc)),
    )


def _build_client() -> Any:
    """Собирает синхронный клиент. Зовётся только изнутри потока."""
    # 🛑 Импорт ленивый: библиотека тянет синхронный requests[socks], который
    # процессу api не нужен, пока не пришла ссылка на Яндекс. И отдельно —
    # падение импорта на старте унесло бы вместе с api телеграм-бота, он
    # поллится в том же процессе.
    from yandex_music import Client
    from yandex_music.utils.request import Request

    s = get_settings()
    if not s.yandex_music_token:
        raise AuthRequiredError(
            "Для Яндекс.Музыки нужен токен аккаунта с активной подпиской "
            "Яндекс Плюс: без него отдаётся только 30-секундный отрывок. "
            "Задай YANDEX_MUSIC_TOKEN.",
            technical="YANDEX_MUSIC_TOKEN is empty",
        )

    # 🛑 proxy_url живёт на Request, а не на Client — у Client такого
    # параметра нет вовсе, и передача его напрямую упадёт на подписи.
    request = Request(proxy_url=s.yandex_music_api_proxy)
    return Client(s.yandex_music_token, request=request).init()


def _fetch_sync(track_id: str) -> tuple[Any, list[Any]]:
    client = _build_client()
    tracks = client.tracks([track_id])
    track = tracks[0] if tracks else None
    if track is None:
        raise MediaUnavailableError(
            "Трек не найден — возможно, его убрали из каталога.",
            technical=f"tracks([{track_id}]) -> {tracks!r}",
        )
    # Прямые ссылки здесь НЕ запрашиваем: за каждую библиотека делает
    # отдельный поход в сеть, а живёт такая ссылка около минуты. Берём одну
    # и для выбранного варианта — непосредственно перед скачиванием.
    return track, list(track.get_download_info() or [])


def _direct_link_sync(info: Any) -> str:
    return str(info.get_direct_link())


def _best_variant(infos: list[Any]) -> Any | None:
    """Лучший ПОЛНЫЙ вариант; preview — это те самые 30 секунд."""
    full = [i for i in infos if not getattr(i, "preview", False)]
    if not full:
        return None
    return max(full, key=lambda i: getattr(i, "bitrate_in_kbps", 0) or 0)


def _artist_of(track: Any) -> str | None:
    names = [a.name for a in getattr(track, "artists", []) or [] if a.name]
    return ", ".join(names) or None


def _artwork_of(track: Any) -> str | None:
    # 🛑 cover_uri приходит без схемы и с плейсхолдером размера в хвосте
    # («avatars.yandex.net/get-music-content/…/%%»). Ссылку без подставленного
    # размера Яндекс не отдаёт, и обложка молча не прикрепится к файлу.
    uri = getattr(track, "cover_uri", None)
    if not uri:
        return None
    return "https://" + str(uri).replace("%%", "400x400")


def _safe_filename(probe: ProbeResult, codec: str | None) -> str:
    stem = " - ".join(p for p in (probe.artist, probe.title) if p)
    stem = _UNSAFE_CHARS.sub("_", stem).strip(" .")
    # Расширение — по фактическому кодеку, а не «.mp3» всегда: оркестратор
    # сравнивает расширение с запрошенным форматом и при совпадении
    # ПРОПУСКАЕТ перекодирование. Назвав aac-файл мп3-шкой, мы отдали бы
    # человеку битый mp3 (_produce_final в download_orchestrator).
    # 120 символов, а не 255: имена кириллические, в UTF-8 это два байта на
    # символ, а лимит файловой системы считается в байтах.
    return f"{stem[:120] or 'track'}.{codec or 'mp3'}"


def _file_duration_seconds(path: Path) -> float | None:
    """Фактическая длительность скачанного файла.

    mutagen, а не ffprobe: он уже в зависимостях (им проставляются теги в
    download_orchestrator), читает длину из заголовков без запуска процесса,
    и пути к ffprobe в настройках нет — есть только FFMPEG_BIN.
    """
    from mutagen import File as MutagenFile

    try:
        audio = MutagenFile(path)
    except Exception as exc:  # pragma: no cover - битый файл
        _log.warning("не смог прочитать длительность %s: %s", path, exc)
        return None
    length = getattr(getattr(audio, "info", None), "length", None)
    return float(length) if length else None


def _reject_if_truncated(path: Path, expected: int | None) -> None:
    """Второй гейт против тихого отказа.

    🛑 Первый гейт — флаг preview в download-info. Этот нужен потому, что
    без подписки Яндекс отдаёт полноценный с виду ответ и 30-секундный файл
    (замер 21.09.2026: 30.000 с вместо 125.8 с). Без проверки джоба
    завершилась бы успехом, а человек получил бы огрызок и даже не узнал.
    """
    actual = _file_duration_seconds(path)
    if expected is None:
        # ponytail: не с чем сравнивать — пропускаем. Потолок осознанный:
        # гейт держится на первом признаке (preview). Если появится площадка
        # без duration в метаданных — сверять по размеру.
        return

    # 🛑 А вот «длительность не прочиталась при ИЗВЕСТНОЙ заявленной» — не
    # повод пропустить, хотя выглядит тем же случаем. mutagen возвращает
    # None и тогда, когда файла-аудио нет вовсе: storage отдал 200 со
    # страницей ошибки, закачка оборвалась, на диске кончилось место. Пустить
    # такой файл дальше значит отдать человеку мусор под видом успеха — ровно
    # тот тихий отказ, против которого написан весь этот гейт.
    if actual is None:
        path.unlink(missing_ok=True)
        raise TemporaryProviderError(
            "Файл скачался битым — в нём нет аудио. Попробуй ещё раз.",
            technical=f"длительность не прочиталась, ждали {expected}s",
        )

    if actual >= expected * _MIN_DURATION_RATIO:
        return

    path.unlink(missing_ok=True)
    raise AuthRequiredError(
        "Яндекс отдал 30-секундный отрывок вместо трека — у аккаунта нет "
        "активной подписки Яндекс Плюс. Нужен токен аккаунта с подпиской.",
        technical=f"duration {actual:.1f}s < expected {expected}s",
    )


async def _http_download(url: str, dest: Path) -> None:
    # 🛑 Без прокси, и это не экономия на спичках: storage.yandex.net гео-блока
    # не имеет (замер 21.09.2026 — 481115 байт отдано на тайский адрес),
    # закрыт только api.music.yandex.net. Гнать мегабайты через чужой прокси
    # значит медленнее качать и зря грузить его канал.
    try:
        async with httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT, follow_redirects=True
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            # ponytail: трек целиком в память, это единицы мегабайт.
            # Понадобятся часовые миксы — переписать на client.stream.
            dest.write_bytes(resp.content)
    except ProviderError:
        raise
    except Exception as exc:
        # Сообщение httpx устроено иначе, чем у библиотеки Яндекса («Client
        # error '410 Gone' for url …» против «410: Gone»), но классификатор
        # матчит слова причины, а не код, поэтому обе формы разбирает верно.
        # Проверено мутантом: отдельная ветка по status_code не меняла ни
        # одного исхода, и её убрали.
        raise classify_yandex_error(exc) from exc


class YandexMusicProvider(ProviderPort):
    """Яндекс.Музыка через официальную обёртку yandex-music.

    🛑 Встроенный в yt-dlp экстрактор `yandexmusic` сломан (замер 21.09.2026:
    «Failed to parse JSON» → TypeError), поэтому общую обвязку
    `providers/ytdlp_base.py` здесь не наследуем — от неё нечего брать.

    🛑 Два канала намеренно разведены: API ходит через российский прокси
    (api.music.yandex.net отдаёт 451 из Сингапура, где живёт прод, и из
    Таиланда; с российских адресов — 200), а сам файл качается напрямую.
    """

    name = "yandex_music"
    hosts = _YANDEX_HOSTS

    def can_handle(self, url: str) -> bool:
        return any(h in url for h in self.hosts)

    async def _in_thread(self, func: Callable[..., Any], *args: Any) -> Any:
        """Единственное место, где синхронная библиотека уходит в поток."""
        try:
            return await to_thread.run_sync(func, *args)
        except ProviderError:
            raise
        except Exception as exc:
            raise classify_yandex_error(exc) from exc

    async def _fetch(self, track_id: str) -> tuple[Any, list[Any]]:
        return await self._in_thread(_fetch_sync, track_id)

    async def _direct_link(self, info: Any) -> str:
        return await self._in_thread(_direct_link_sync, info)

    def _to_probe(self, track: Any, infos: list[Any]) -> ProbeResult:
        best = _best_variant(infos)
        reason = (
            None
            if best is not None
            else (
                "Яндекс отдаёт только 30-секундный отрывок: нужен токен "
                "аккаунта с активной подпиской Яндекс Плюс."
            )
        )
        duration_ms = getattr(track, "duration_ms", None)
        return ProbeResult(
            provider=self.name,
            can_download=best is not None,
            normalized_id=str(track.id),
            title=track.title,
            artist=_artist_of(track),
            duration=int(duration_ms // 1000) if duration_ms else None,
            artwork_url=_artwork_of(track),
            reason_if_denied=reason,
        )

    async def probe(self, url: str) -> ProbeResult:
        track, infos = await self._fetch(_track_id_from_url(url))
        return self._to_probe(track, infos)

    async def download(
        self, url: str, dest_dir: str, *, respect_tou: bool = True
    ) -> tuple[str, ProbeResult]:
        # respect_tou здесь ни на что не влияет: пометки «автор разрешил
        # скачивание», как у SoundCloud, у Яндекса не существует. Единственный
        # признак доступности — подписка Плюс у нашего аккаунта, и он
        # проверяется всегда, независимо от флага.
        Path(dest_dir).mkdir(parents=True, exist_ok=True)

        track, infos = await self._fetch(_track_id_from_url(url))
        probe = self._to_probe(track, infos)
        best = _best_variant(infos)
        if best is None:
            raise AuthRequiredError(
                probe.reason_if_denied or "Трек доступен только по подписке",
                technical=f"download-info variants: {infos!r}",
            )

        # 🛑 Прямую ссылку берём последним шагом: она живёт около минуты,
        # запрошенная на этапе probe протухла бы ещё до начала скачивания
        # и отдала бы 410.
        link = await self._direct_link(best)
        dest = Path(dest_dir) / _safe_filename(
            probe, getattr(best, "codec", None)
        )
        await _http_download(link, dest)
        _reject_if_truncated(dest, probe.duration)

        return str(dest), probe
