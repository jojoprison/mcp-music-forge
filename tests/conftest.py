from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from core.settings import get_settings


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path: Path) -> Iterator[None]:
    # isolate storage and db per test session
    os.environ["STORAGE_DIR"] = str(tmp_path / "data")
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path}/db.sqlite3"
    # reset cached settings
    get_settings.cache_clear()
    yield
    # cleanup
    get_settings.cache_clear()
