"""Guard вокруг чистки каталога джоб (INF-1).

🛑 Опасная сторона этой задачи — не «места не хватило», а «удалили нужное».
Файлы джобы читает не только человек: досыл берёт готовый файл из final/,
а MCP-ресурс отдаёт байты из original/. Поэтому единственный тест, ради
которого всё это написано, — что каталог с ОТКРЫТОЙ доставкой не сносится,
сколько бы ему ни было дней.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from core.domain.delivery import Delivery
from core.domain.job import DownloadOptions, Job, JobStatus
from core.infra.db import create_db_and_tables, session_scope
from core.services import redelivery, retention
from core.settings import get_settings

NOW = datetime(2026, 8, 29, 12, 0, 0)


@pytest.fixture(autouse=True)
def _fresh(tmp_path: Path) -> None:
    get_settings().storage_dir = tmp_path / "data"
    get_settings().jobs_retention_days = 30
    create_db_and_tables()
    with session_scope() as s:
        s.query(Delivery).delete()
        s.query(Job).delete()


def _job_dir(job_id: str, *, size: int = 1024) -> Path:
    root = get_settings().storage_dir / "jobs" / job_id
    (root / "original").mkdir(parents=True, exist_ok=True)
    (root / "final").mkdir(parents=True, exist_ok=True)
    (root / "original" / "src.webm").write_bytes(b"x" * size)
    (root / "final" / "out.mp3").write_bytes(b"y" * size)
    return root


def _job(job_id: str, *, days_ago: int, status: str = "succeeded") -> None:
    stamp = NOW - timedelta(days=days_ago)
    with session_scope() as s:
        s.add(
            Job(
                id=job_id,
                provider="youtube",
                url=f"https://youtu.be/{job_id}",
                fingerprint=job_id,
                status=status,
                options=DownloadOptions().model_dump(),
                created_at=stamp,
                updated_at=stamp,
            )
        )


def _delivery(
    job_id: str, *, delivered: bool = False, attempts: int = 0
) -> None:
    with session_scope() as s:
        s.add(
            Delivery(
                job_id=job_id,
                chat_id=111,
                message_id=222,
                attempts=attempts,
                delivered_at=NOW if delivered else None,
            )
        )


def test_recent_job_survives() -> None:
    d = _job_dir("young")
    _job("young", days_ago=3)

    removed, freed = retention.sweep_old_jobs(now=NOW)

    assert (removed, freed) == (0, 0)
    assert d.exists()


def test_old_job_is_removed_with_reported_size() -> None:
    d = _job_dir("old", size=2048)
    _job("old", days_ago=90)

    removed, freed = retention.sweep_old_jobs(now=NOW)

    assert removed == 1
    assert freed == 4096, freed
    assert not d.exists()


def test_open_delivery_holds_files_forever() -> None:
    # 🛑 Ради этого теста задача и делалась осторожно: у джобы кто-то ждёт
    # файл, и снос каталога превратил бы должок в вечный «файла нет на
    # диске» — досыл никогда бы его не выполнил.
    d = _job_dir("waited")
    _job("waited", days_ago=365, status=JobStatus.failed.value)
    _delivery("waited")

    removed, _ = retention.sweep_old_jobs(now=NOW)

    assert removed == 0
    assert d.exists()


def test_delivered_delivery_does_not_hold_files() -> None:
    d = _job_dir("done")
    _job("done", days_ago=90)
    _delivery("done", delivered=True)

    removed, _ = retention.sweep_old_jobs(now=NOW)

    assert removed == 1
    assert not d.exists()


def test_exhausted_delivery_does_not_hold_files() -> None:
    # Исчерпавший попытки ждущий больше не придёт за файлом: досыл его уже
    # не выбирает (тот же потолок MAX_ATTEMPTS), значит держать нечего.
    d = _job_dir("gaveup")
    _job("gaveup", days_ago=90, status=JobStatus.failed.value)
    _delivery("gaveup", attempts=redelivery.MAX_ATTEMPTS)

    removed, _ = retention.sweep_old_jobs(now=NOW)

    assert removed == 1
    assert not d.exists()


def test_succeeded_job_with_open_row_does_not_hold_files() -> None:
    # 🛑 Боевой случай, которого не было в первой редакции фикстур: бот отдал
    # файл сразу, джоба осталась succeeded, а строка доставки так и стоит с
    # delivered_at IS NULL — её закрывает только досыл, а он на обычном пути
    # не участвует. Замер на проде 29.08: ровно 4 таких каталога держались
    # вечно, и доля росла бы с каждой успешной выдачей, пока чистка не
    # перестала бы чистить вовсе.
    d = _job_dir("shipped")
    _job("shipped", days_ago=90, status=JobStatus.succeeded.value)
    _delivery("shipped")

    removed, _ = retention.sweep_old_jobs(now=NOW)

    assert removed == 1
    assert not d.exists()


def test_disabled_retention_removes_nothing() -> None:
    get_settings().jobs_retention_days = 0
    d = _job_dir("old")
    _job("old", days_ago=999)

    removed, freed = retention.sweep_old_jobs(now=NOW)

    assert (removed, freed) == (0, 0)
    assert d.exists()


def test_orphan_dir_without_job_row_falls_back_to_mtime() -> None:
    # Каталог без записи в БД — след от прогонов до появления таблицы или
    # от ручных экспериментов. Возраст брать неоткуда, кроме файловой
    # системы; иначе такой каталог не удалится НИКОГДА.
    import os

    d = _job_dir("orphan")
    old = (NOW - timedelta(days=120)).timestamp()
    for p in sorted(d.rglob("*"), reverse=True):
        os.utime(p, (old, old))
    os.utime(d, (old, old))

    removed, _ = retention.sweep_old_jobs(now=NOW)

    assert removed == 1
    assert not d.exists()


def test_young_orphan_dir_survives() -> None:
    # Обратная сторона предыдущего: свежий осиротевший каталог — это чаще
    # всего джоба, которая ПРЯМО СЕЙЧАС качается и ещё не дописала строку.
    d = _job_dir("fresh-orphan")

    removed, _ = retention.sweep_old_jobs(now=NOW)

    assert removed == 0
    assert d.exists()


def test_missing_jobs_root_is_not_an_error() -> None:
    removed, freed = retention.sweep_old_jobs(now=NOW)

    assert (removed, freed) == (0, 0)
