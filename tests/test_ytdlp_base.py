from __future__ import annotations

from pathlib import Path

import pytest

from core.settings import get_settings
from providers.soundcloud_ytdlp.adapter import SoundCloudYtDlpProvider
from providers.youtube.adapter import YouTubeProvider


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()


def test_cookie_file_applied_only_when_regular_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cookies = tmp_path / "yt-cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    monkeypatch.setenv("YOUTUBE_COOKIE_FILE", str(cookies))
    get_settings.cache_clear()

    opts = YouTubeProvider()._build_opts(None)
    assert opts["cookiefile"] == str(cookies)


def test_cookie_file_ignored_when_path_is_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Каталог вместо файла — частая ошибка монтирования тома,
    # yt-dlp на таком пути падает.
    monkeypatch.setenv("YOUTUBE_COOKIE_FILE", str(tmp_path))
    get_settings.cache_clear()

    assert "cookiefile" not in YouTubeProvider()._build_opts(None)


def test_cookie_file_absent_by_default() -> None:
    assert "cookiefile" not in YouTubeProvider()._build_opts(None)


def test_pot_provider_url_reaches_extractor_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YOUTUBE_POT_BASE_URL", "http://127.0.0.1:4416")
    get_settings.cache_clear()

    args = YouTubeProvider()._build_opts(None)["extractor_args"]
    assert args["youtubepot-bgutilhttp"] == {
        "base_url": ["http://127.0.0.1:4416"]
    }


def test_no_pot_key_without_url() -> None:
    # Пусто — плагин сам идёт на свой дефолтный адрес, ключ навязывать нельзя.
    args = YouTubeProvider()._build_opts(None)["extractor_args"]
    assert "youtubepot-bgutilhttp" not in args


def test_tv_simply_client_goes_first() -> None:
    # Порядок несёт смысл: на видео, требующих входа, остальные клиенты
    # получают бот-челлендж, а android отдаёт форматы без URL (SABR-only).
    clients = YouTubeProvider()._build_opts(None)["extractor_args"]["youtube"][
        "player_client"
    ]
    assert clients[0] == "tv_simply"
    assert "default" in clients


def test_youtube_keeps_js_challenge_solver() -> None:
    opts = YouTubeProvider()._build_opts(None)
    assert opts["remote_components"] == ["ejs:github"]
    assert opts["force_ipv4"] is True


def test_soundcloud_does_not_inherit_youtube_opts() -> None:
    opts = SoundCloudYtDlpProvider()._build_opts(None)
    assert "remote_components" not in opts
    assert "extractor_args" not in opts


def test_outtmpl_sets_download_home(tmp_path: Path) -> None:
    outtmpl = str(tmp_path / "%(title)s.%(ext)s")
    opts = SoundCloudYtDlpProvider()._build_opts(outtmpl)
    assert opts["paths"] == {"home": str(tmp_path)}


def test_downloaded_path_prefers_ytdlp_own_filepath(tmp_path: Path) -> None:
    # yt-dlp санитайзит имя, поэтому его путь — арбитр, а не наш title.
    info = {
        "title": "Track / with : slashes",
        "ext": "m4a",
        "requested_downloads": [{"filepath": str(tmp_path / "sanitized.m4a")}],
    }
    provider = SoundCloudYtDlpProvider()
    assert provider._downloaded_path(info, str(tmp_path)) == str(
        tmp_path / "sanitized.m4a"
    )


def test_downloaded_path_falls_back_to_title(tmp_path: Path) -> None:
    info = {"title": "Track", "ext": "opus"}
    provider = YouTubeProvider()
    assert provider._downloaded_path(info, str(tmp_path)) == str(
        tmp_path / "Track.opus"
    )


def test_downloaded_path_uses_provider_fallback_ext(tmp_path: Path) -> None:
    info = {"title": "Track"}
    assert YouTubeProvider()._downloaded_path(info, str(tmp_path)).endswith(
        "Track.webm"
    )
    assert SoundCloudYtDlpProvider()._downloaded_path(
        info, str(tmp_path)
    ).endswith("Track.mp3")


def test_can_handle_matches_own_hosts_only() -> None:
    yt, sc = YouTubeProvider(), SoundCloudYtDlpProvider()
    assert yt.can_handle("https://youtu.be/abc") is True
    assert yt.can_handle("https://soundcloud.com/a/b") is False
    assert sc.can_handle("https://soundcloud.com/a/b") is True
    assert sc.can_handle("https://www.youtube.com/watch?v=abc") is False
