from __future__ import annotations

import asyncio
import pytest
from typing import Any

from providers.soundcloud_ytdlp.adapter import SoundCloudYtDlpProvider


@pytest.mark.asyncio
async def test_probe_downloadable(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = SoundCloudYtDlpProvider()

    async def fake_extract(url: str, download: bool, outtmpl: str | None = None) -> dict[str, Any]:
        return {
            "id": 123,
            "title": "Test Track",
            "uploader": "Artist",
            "duration": 42,
            "thumbnail": "http://example.com/cover.jpg",
            "downloadable": True,
        }

    monkeypatch.setattr(provider, "_extract_info", fake_extract)

    res = await provider.probe("https://soundcloud.com/artist/test-track")
    assert res.can_download is True
    assert res.provider == "soundcloud"
    assert res.title == "Test Track"
    assert res.artist == "Artist"


@pytest.mark.asyncio
async def test_probe_not_downloadable(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = SoundCloudYtDlpProvider()

    async def fake_extract(url: str, download: bool, outtmpl: str | None = None) -> dict[str, Any]:
        return {
            "id": 321,
            "title": "ND Track",
            "downloadable": False,
        }

    monkeypatch.setattr(provider, "_extract_info", fake_extract)

    res = await provider.probe("https://soundcloud.com/x/y")
    assert res.can_download is False
    assert res.reason_if_denied
