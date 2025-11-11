from __future__ import annotations

from pathlib import Path

from mcp_music_forge.mcp_app import mcp
from storage.local_fs import LocalStorage


def _read(path: Path) -> bytes:
    with path.open("rb") as f:
        return f.read()


@mcp.resource("music-forge://jobs/{job_id}/original/{name}")
def read_original(job_id: str, name: str) -> bytes:
    """Read bytes of an original artifact."""
    storage = LocalStorage()
    p = storage.ensure_subdir(job_id, "original") / name
    if not p.exists() or not p.is_file():
        raise FileNotFoundError(str(p))
    return _read(p)


@mcp.resource("music-forge://jobs/{job_id}/final/{name}")
def read_final(job_id: str, name: str) -> bytes:
    """Read bytes of a final artifact."""
    storage = LocalStorage()
    p = storage.ensure_subdir(job_id, "final") / name
    if not p.exists() or not p.is_file():
        raise FileNotFoundError(str(p))
    return _read(p)
