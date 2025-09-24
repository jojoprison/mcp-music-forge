from __future__ import annotations

import shlex
import subprocess
from anyio import to_thread
from pathlib import Path
from typing import Sequence

from core.settings import get_settings


def _args_for(format: str, quality: str) -> list[str]:
    f = format.lower()
    q = quality.lower()
    if f == "mp3":
        if q in {"v0", "v2"}:
            qmap = {"v0": "0", "v2": "2"}
            return ["-c:a", "libmp3lame", "-q:a", qmap[q]]
        elif q == "320":
            return ["-c:a", "libmp3lame", "-b:a", "320k"]
        else:
            return ["-c:a", "libmp3lame", "-q:a", "0"]
    if f == "opus":
        kbps = q if q.isdigit() else "160"
        return ["-c:a", "libopus", "-b:a", f"{kbps}k", "-vbr", "on"]
    if f == "aac":
        kbps = q if q.isdigit() else "256"
        return ["-c:a", "aac", "-b:a", f"{kbps}k"]
    if f == "flac":
        return ["-c:a", "flac"]
    # fallback: copy
    return ["-c:a", "copy"]


async def transcode(input_path: Path, output_dir: Path, target_format: str, quality: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / (input_path.stem + f".{target_format}")
    ffmpeg = get_settings().ffmpeg_bin
    args: list[str] = [ffmpeg, "-y", "-i", str(input_path), *(_args_for(target_format, quality)), str(out)]

    def _run() -> None:
        proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            msg = proc.stderr.decode("utf-8", errors="ignore")
            raise RuntimeError(f"ffmpeg failed: {msg}")

    await to_thread.run_sync(_run)
    return out
