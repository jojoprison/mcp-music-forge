from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Optional


@dataclass
class ProbeResult:
    provider: str
    can_download: bool
    normalized_id: Optional[str]
    title: Optional[str]
    artist: Optional[str]
    duration: Optional[int]
    artwork_url: Optional[str]
    reason_if_denied: Optional[str]


class ProviderPort(abc.ABC):
    name: str

    @abc.abstractmethod
    def can_handle(self, url: str) -> bool:  # pragma: no cover - trivial
        ...

    @abc.abstractmethod
    async def probe(self, url: str) -> ProbeResult:
        ...

    @abc.abstractmethod
    async def download(self, url: str, dest_dir: str) -> tuple[str, ProbeResult]:
        """
        Download media into dest_dir and return (filepath, metadata).
        The filepath should point to an audio file (original) suitable for further processing.
        """
        ...
