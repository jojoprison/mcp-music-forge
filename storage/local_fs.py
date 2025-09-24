from __future__ import annotations

from pathlib import Path

from core.ports.storage_port import StoragePort
from core.settings import get_settings


class LocalStorage(StoragePort):
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or get_settings().storage_dir
        self.root.mkdir(parents=True, exist_ok=True)

    def job_dir(self, job_id: str) -> Path:
        p = self.root / "jobs" / job_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    def ensure_subdir(self, job_id: str, name: str) -> Path:
        d = self.job_dir(job_id) / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def list_files(self, job_id: str) -> list[Path]:
        d = self.job_dir(job_id)
        if not d.exists():
            return []
        return [p for p in d.rglob("*") if p.is_file()]
