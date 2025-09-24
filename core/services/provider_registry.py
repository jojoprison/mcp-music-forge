from __future__ import annotations

from typing import Iterable, Optional

from core.ports.provider_port import ProviderPort
from providers.soundcloud_ytdlp.adapter import SoundCloudYtDlpProvider


def all_providers() -> list[ProviderPort]:
    # TODO: register more providers here (YouTube, Yandex Music, Spotify)
    return [SoundCloudYtDlpProvider()]


def detect_provider(url: str, providers: Iterable[ProviderPort] | None = None) -> Optional[ProviderPort]:
    for p in providers or all_providers():
        if p.can_handle(url):
            return p
    return None
