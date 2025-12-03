from __future__ import annotations

from collections.abc import Iterable

from core.ports.provider_port import ProviderPort
from providers.soundcloud_ytdlp.adapter import SoundCloudYtDlpProvider
from providers.youtube.adapter import YouTubeProvider


def all_providers() -> list[ProviderPort]:
    # TODO: register more providers here (Yandex Music, Spotify)
    return [SoundCloudYtDlpProvider(), YouTubeProvider()]



def detect_provider(
    url: str, providers: Iterable[ProviderPort] | None = None
) -> ProviderPort | None:
    for p in providers or all_providers():
        if p.can_handle(url):
            return p
    return None
