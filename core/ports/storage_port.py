from __future__ import annotations

import abc
from pathlib import Path


class StoragePort(abc.ABC):
    @abc.abstractmethod
    def job_dir(self, job_id: str) -> Path:  # pragma: no cover - trivial
        ...

    @abc.abstractmethod
    def ensure_subdir(self, job_id: str, name: str) -> Path: ...

    @abc.abstractmethod
    def list_files(self, job_id: str) -> list[Path]: ...
