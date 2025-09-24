from __future__ import annotations

from pydantic import BaseModel

from core.services.provider_registry import detect_provider
from mcp_music_forge.mcp_app import mcp


class ProbeToolResult(BaseModel):
    provider: str | None
    can_download: bool
    normalized_id: str | None
    title: str | None
    artist: str | None
    duration: int | None
    artwork_url: str | None
    reason_if_denied: str | None


@mcp.tool()
async def probe_url(url: str) -> ProbeToolResult:
    """
    Detect provider for URL and check whether track is downloadable per
    provider rules.
    """
    provider = detect_provider(url)
    if not provider:
        return ProbeToolResult(
            provider=None,
            can_download=False,
            normalized_id=None,
            title=None,
            artist=None,
            duration=None,
            artwork_url=None,
            reason_if_denied="No provider can handle this URL",
        )
    pr = await provider.probe(url)
    return ProbeToolResult(
        provider=pr.provider,
        can_download=pr.can_download,
        normalized_id=pr.normalized_id,
        title=pr.title,
        artist=pr.artist,
        duration=pr.duration,
        artwork_url=pr.artwork_url,
        reason_if_denied=pr.reason_if_denied,
    )
