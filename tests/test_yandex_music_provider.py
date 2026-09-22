from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from core.errors import (
    AuthRequiredError,
    MediaUnavailableError,
    ProviderError,
)
from providers.yandex_music import adapter as ym
from providers.yandex_music.adapter import YandexMusicProvider

# Ссылка ровно в том виде, в каком её присылают из десктопного клиента.
_URL = (
    "https://music.yandex.ru/album/40348473/track/147503042"
    "?utm_source=desktop&utm_medium=copy_link"
)

# 🛑 Настоящий mp3, а не b"audio": гейт длительности читает файл mutagen'ом,
# и на произвольных байтах тот вернул бы None — гейт молча пропустил бы
# огрызок, а тест остался бы зелёным, не дойдя до проверяемой ветки.
# Кадр: MPEG-1 Layer III, 128 kbps, 44.1 кГц, стерео → 417 байт и 1152
# сэмпла; длину CBR-файла mutagen считает из размера, поэтому тишины хватает.
_MP3_FRAME = bytes((0xFF, 0xFB, 0x90, 0x00)) + b"\x00" * 413
_FRAME_SECONDS = 1152 / 44100


def _mp3_bytes(seconds: float) -> bytes:
    return _MP3_FRAME * round(seconds / _FRAME_SECONDS)


def _track(**kw: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "id": 147503042,
        "title": "Трек",
        "artists": [SimpleNamespace(name="Исполнитель")],
        # 125.8 с — настоящая длительность трека из замера 21.09.2026.
        "duration_ms": 125800,
        "cover_uri": "avatars.yandex.net/get-music-content/1/%%",
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _info(bitrate: int, *, preview: bool = False, codec: str = "mp3") -> Any:
    return SimpleNamespace(
        codec=codec, bitrate_in_kbps=bitrate, preview=preview
    )


def _with_fetch(
    provider: YandexMusicProvider,
    monkeypatch: pytest.MonkeyPatch,
    track: Any,
    infos: list[Any],
) -> None:
    async def fake_fetch(track_id: str) -> tuple[Any, list[Any]]:
        assert track_id == "147503042"
        return track, infos

    monkeypatch.setattr(provider, "_fetch", fake_fetch)


def test_track_id_ignores_query_tail() -> None:
    assert ym._track_id_from_url(_URL) == "147503042"
    assert (
        ym._track_id_from_url("https://music.yandex.ru/track/147503042")
        == "147503042"
    )


def test_track_id_rejects_album_link() -> None:
    with pytest.raises(ProviderError):
        ym._track_id_from_url("https://music.yandex.ru/album/40348473")


def test_track_id_ignores_track_inside_query() -> None:
    # 🛑 Настоящая причина разбирать path, а не сырую строку: по сырой
    # ссылке этот адрес отдал бы 999 и мы молча скачали бы чужой трек.
    with pytest.raises(ProviderError):
        ym._track_id_from_url(
            "https://music.yandex.ru/album/40348473?from=/track/999"
        )


def test_can_handle() -> None:
    provider = YandexMusicProvider()
    assert provider.can_handle(_URL) is True
    # Зарубежные витрины ведут в тот же каталог и присылаются так же часто.
    assert provider.can_handle("https://music.yandex.com/track/1") is True
    assert provider.can_handle("https://music.yandex.kz/track/1") is True
    assert provider.can_handle("https://soundcloud.com/a/b") is False
    assert provider.can_handle("https://youtu.be/abc") is False


@pytest.mark.asyncio
async def test_probe_full_track(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = YandexMusicProvider()
    _with_fetch(provider, monkeypatch, _track(), [_info(192), _info(320)])

    res = await provider.probe(_URL)

    assert res.can_download is True
    assert res.provider == "yandex_music"
    assert res.title == "Трек"
    assert res.artist == "Исполнитель"
    assert res.duration == 125
    assert res.artwork_url == (
        "https://avatars.yandex.net/get-music-content/1/1000x1000"
    )
    assert res.reason_if_denied is None


@pytest.mark.asyncio
async def test_probe_preview_only_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Первый гейт: без подписки API отдаёт вариант с preview=True.
    provider = YandexMusicProvider()
    track = _track(cover_uri=None)
    _with_fetch(provider, monkeypatch, track, [_info(128, preview=True)])

    res = await provider.probe(_URL)

    assert res.can_download is False
    assert res.reason_if_denied
    assert "Плюс" in res.reason_if_denied
    # Трек без обложки — не «https://None»: такую ссылку тегировщик потащил
    # бы в сеть и получил мусор вместо картинки.
    assert res.artwork_url is None


@pytest.mark.asyncio
async def test_download_picks_best_full_variant(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = YandexMusicProvider()
    # Превью 320 стоит выше всех по битрейту — если сортировка забудет про
    # preview, скачается именно оно.
    variants = [_info(192), _info(320, preview=True), _info(256)]
    _with_fetch(provider, monkeypatch, _track(title="Тр/ек"), variants)

    chosen: list[Any] = []

    async def fake_link(info: Any) -> str:
        chosen.append(info)
        return "https://storage.yandex.net/file.mp3"

    async def fake_http(url: str, dest: Path) -> None:
        dest.write_bytes(b"audio")

    monkeypatch.setattr(provider, "_direct_link", fake_link)
    monkeypatch.setattr(ym, "_http_download", fake_http)
    monkeypatch.setattr(ym, "_file_duration_seconds", lambda p: 125.8)

    path, probe = await provider.download(_URL, str(tmp_path))

    assert chosen == [variants[2]]  # 256, а не превью-320
    assert Path(path).name == "Исполнитель - Тр_ек.mp3"
    assert Path(path).exists()
    assert probe.can_download is True


@pytest.mark.asyncio
async def test_download_uses_real_codec_extension(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Расширение должно идти от кодека: aac-файл с именем .mp3 оркестратор
    # скопировал бы в final без перекодирования и отдал битым.
    provider = YandexMusicProvider()
    _with_fetch(provider, monkeypatch, _track(), [_info(256, codec="aac")])

    async def fake_link(info: Any) -> str:
        return "https://storage.yandex.net/file"

    async def fake_http(url: str, dest: Path) -> None:
        dest.write_bytes(b"audio")

    monkeypatch.setattr(provider, "_direct_link", fake_link)
    monkeypatch.setattr(ym, "_http_download", fake_http)
    monkeypatch.setattr(ym, "_file_duration_seconds", lambda p: 125.8)

    path, _ = await provider.download(_URL, str(tmp_path))

    assert Path(path).suffix == ".aac"


@pytest.mark.asyncio
async def test_download_denied_without_full_variant(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = YandexMusicProvider()
    _with_fetch(provider, monkeypatch, _track(), [_info(128, preview=True)])

    calls: list[str] = []

    async def fake_link(info: Any) -> str:
        calls.append("link")
        return "https://storage.yandex.net/preview.mp3"

    async def fake_http(url: str, dest: Path) -> None:
        calls.append("http")
        dest.write_bytes(_mp3_bytes(30.0))

    monkeypatch.setattr(provider, "_direct_link", fake_link)
    monkeypatch.setattr(ym, "_http_download", fake_http)

    with pytest.raises(AuthRequiredError):
        await provider.download(_URL, str(tmp_path))

    # Отказ обязан наступить ДО сети: прямая ссылка — отдельный поход в API,
    # и брать её ради заведомо отказного трека незачем.
    assert calls == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_download_rejects_truncated_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # 🛑 Главный тест файла. Второй гейт: preview проехал мимо первого (флаг
    # не выставлен), а файл всё равно 30-секундный — замер 21.09.2026,
    # 30.000 с против 125.8 с. Длительность здесь НЕ подменяется: читает её
    # настоящий mutagen из настоящих mp3-кадров, иначе тест проверял бы
    # только сравнение чисел, а не работу гейта целиком.
    provider = YandexMusicProvider()
    _with_fetch(provider, monkeypatch, _track(), [_info(320)])

    written: list[Path] = []

    async def fake_link(info: Any) -> str:
        return "https://storage.yandex.net/preview.mp3"

    async def fake_http(url: str, dest: Path) -> None:
        dest.write_bytes(_mp3_bytes(30.0))
        written.append(dest)

    monkeypatch.setattr(provider, "_direct_link", fake_link)
    monkeypatch.setattr(ym, "_http_download", fake_http)

    with pytest.raises(AuthRequiredError) as err:
        await provider.download(_URL, str(tmp_path))

    # Ветка отработала целиком: файл скачался, был измерен и удалён.
    assert written, "скачивание не дошло до гейта"
    assert not written[0].exists()  # иначе досыл подберёт огрызок позже
    assert "подписки" in err.value.user_message
    assert err.value.retryable is False


def test_file_duration_read_from_real_file(tmp_path: Path) -> None:
    # Позитивный контроль к гейту: читалка обязана отдавать число, а не
    # None. Мутант «всегда None» выключает гейт целиком и тихо, потому что
    # во всех остальных тестах она подменена.
    path = tmp_path / "track.mp3"
    path.write_bytes(_mp3_bytes(30.0))

    assert ym._file_duration_seconds(path) == pytest.approx(30.0, abs=0.5)


@pytest.mark.asyncio
async def test_probe_translates_geo_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Сквозной путь: отказ прилетает из синхронной библиотеки в потоке, а
    # наружу обязан выйти доменной ошибкой, которую оркестратор не повторяет.
    def boom(track_id: str) -> tuple[Any, list[Any]]:
        raise RuntimeError("451: Unavailable For Legal Reasons")

    monkeypatch.setattr(ym, "_fetch_sync", boom)

    with pytest.raises(MediaUnavailableError) as err:
        await YandexMusicProvider().probe(_URL)

    assert err.value.retryable is False
    assert "прокси" in err.value.user_message


@pytest.mark.asyncio
async def test_probe_keeps_domain_error_from_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 🛑 Доменная ошибка из потока не должна переклассифицироваться: текст
    # «нет токена» не похож ни на один известный признак, и общая ветка
    # сделала бы её повторяемой — джоба без токена крутилась бы вечно.
    def boom(track_id: str) -> tuple[Any, list[Any]]:
        raise AuthRequiredError("Нужен токен аккаунта с подпиской")

    monkeypatch.setattr(ym, "_fetch_sync", boom)

    with pytest.raises(AuthRequiredError) as err:
        await YandexMusicProvider().probe(_URL)

    assert err.value.retryable is False


def test_classify_geo_block_is_terminal() -> None:
    err = ym.classify_yandex_error(Exception("451: Unavailable For Legal"))
    assert err.retryable is False
    assert "прокси" in err.user_message


def test_classify_does_not_read_track_id_as_status() -> None:
    # 🛑 Номер трека может содержать «451» — такой сбой обязан остаться
    # повторяемым, иначе обычная сетевая ошибка потеряет ретраи.
    err = ym.classify_yandex_error(Exception("connection reset for 4516"))
    assert err.retryable is True


def test_classify_dead_token_is_terminal() -> None:
    # Истёкший токен повтором не лечится — в отличие от сети.
    err = ym.classify_yandex_error(Exception("401: Unauthorized"))
    assert isinstance(err, AuthRequiredError)
    assert err.retryable is False


def test_classify_does_not_read_track_id_as_404() -> None:
    # 🛑 Парный случай к 451: номер трека 40477104 содержит «404» подстрокой.
    # Голый матч записал бы обычный обрыв связи в терминальные, и джоба умерла
    # бы без единого повтора — при том что повтор её и лечит.
    err = ym.classify_yandex_error(
        Exception("Connection aborted while fetching track 40477104")
    )

    assert err.retryable is True


def test_technical_hides_proxy_credentials() -> None:
    # Прокси к российскому узлу может идти с паролем в строке, а она целиком
    # попадает в текст сетевой ошибки и дальше в логи.
    err = ym.classify_yandex_error(
        Exception("SOCKS5 failure via socks5://bot:hunter2@ru.example:1080")
    )

    assert "hunter2" not in err.technical
    assert "<REDACTED>" in err.technical


def test_rejects_file_without_readable_duration(tmp_path: Path) -> None:
    # 🛑 «Длину прочитать не удалось» — это не «нечего сравнивать»: mutagen
    # молчит и тогда, когда аудио в файле нет вовсе (storage отдал 200 со
    # страницей ошибки, закачка оборвалась, кончилось место). Пустить такой
    # файл дальше значит отдать человеку мусор под видом успеха.
    path = tmp_path / "track.mp3"
    path.write_bytes(b"<html>Error</html>")

    with pytest.raises(ProviderError) as err:
        ym._reject_if_truncated(path, 125)

    assert not path.exists()
    assert err.value.retryable is True


def test_truncation_gate_skips_when_nothing_to_compare(tmp_path: Path) -> None:
    # Негативный контроль к тесту выше: без заявленной длительности гейт
    # обязан промолчать, иначе он рубил бы площадки, которые её не отдают.
    path = tmp_path / "track.mp3"
    path.write_bytes(b"<html>Error</html>")

    ym._reject_if_truncated(path, None)

    assert path.exists()


def test_bot_accepts_every_host_the_provider_serves() -> None:
    # 🛑 Список хостов в боте был копией провайдерского и разъехался с ним:
    # Яндекс приехал с четырьмя доменами, в боте оказался один. Теперь бот
    # спрашивает реестр — тест держит эту связь.
    from bot.main import is_valid_url

    for host in YandexMusicProvider.hosts:
        assert is_valid_url(f"https://{host}/album/1/track/2") is True
    assert is_valid_url("https://example.com/track/2") is False
