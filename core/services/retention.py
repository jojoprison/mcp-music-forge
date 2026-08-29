from __future__ import annotations

import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from core.domain.job import Job
from core.infra.db import session_scope
from core.services.redelivery import pending_job_ids
from core.settings import get_settings

_log = logging.getLogger(__name__)


def _waiting_job_ids() -> set[str]:
    """Джобы, чей файл досыл ещё собирается отдать.

    🛑 Не «повторить условие досыла», а ВЫЗВАТЬ его: первая редакция
    переписала предикат своими словами и потеряла третье условие
    (`job.status == failed`). Тихая цена — обычная успешная выдача бота
    оставляет строку с `delivered_at IS NULL` навсегда (закрывать её на этом
    пути некому), и такой каталог не удалялся бы НИКОГДА. Замер на проде
    29.08: 4 каталога из 121 уже держались так, и доля росла бы с каждой
    выдачей, пока чистка не перестала бы чистить вовсе.
    """
    return set(pending_job_ids())


def _last_activity(job_id: str, job_dir: Path) -> datetime:
    """Когда джобу трогали в последний раз.

    Приоритет у базы: mtime каталога сдвигает любое чтение метаданных, а
    updated_at меняется только при настоящей работе. Каталога без записи в
    БД это не касается — там кроме файловой системы спросить некого.
    """
    with session_scope() as s:
        job = s.get(Job, job_id)
        if job is not None:
            return job.updated_at
    return datetime.fromtimestamp(job_dir.stat().st_mtime)


def _dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def sweep_old_jobs(now: datetime | None = None) -> tuple[int, int]:
    """Удаляет каталоги старых джоб. Возвращает (сколько, сколько байт).

    🛑 Каталог сносится ЦЕЛИКОМ, а не по частям: original/ и final/ оба
    доступны наружу (final — досылу, original — MCP-ресурсу
    music-forge://jobs/{id}/original/{name}), и разный возраст у них
    означал бы только то, что половина ссылок отдаёт 404 при живой второй.

    Данные восстановимы повторной загрузкой — это кэш скачанного, а не
    единственная копия. Невосстановимо здесь только одно: файл, которого
    кто-то ещё ждёт, поэтому ждущие исключаются раньше возраста.
    """
    days = get_settings().jobs_retention_days
    if days <= 0:
        return 0, 0

    root = get_settings().storage_dir / "jobs"
    if not root.is_dir():
        return 0, 0

    now = now or datetime.now()
    cutoff = now - timedelta(days=days)
    waiting = _waiting_job_ids()

    removed = freed = 0
    for job_dir in sorted(root.iterdir()):
        if not job_dir.is_dir() or job_dir.name in waiting:
            continue
        if _last_activity(job_dir.name, job_dir) > cutoff:
            continue

        size = _dir_size(job_dir)
        shutil.rmtree(job_dir, ignore_errors=True)
        if job_dir.exists():  # права, занятый файл — не наше дело чинить
            _log.warning("retention: could not remove %s", job_dir)
            continue
        removed += 1
        freed += size

    if removed:
        _log.info("retention: removed %s job dir(s), %s bytes", removed, freed)
    return removed, freed
