from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pytest

from core.domain.delivery import Delivery
from core.domain.job import DownloadOptions, Job, JobStatus
from core.infra.db import create_db_and_tables, session_scope
from core.services import redelivery
from core.settings import get_settings


@pytest.fixture(autouse=True)
def _fresh_db(tmp_path: Path) -> None:
    get_settings().storage_dir = tmp_path / "data"
    create_db_and_tables()
    with session_scope() as s:
        s.query(Delivery).delete()
        s.query(Job).delete()


def _job(job_id: str, status: str) -> None:
    with session_scope() as s:
        s.add(
            Job(
                id=job_id,
                provider="youtube",
                url=f"https://youtu.be/{job_id}",
                fingerprint=job_id,
                status=status,
                options=DownloadOptions().model_dump(),
            )
        )


def _delivery(
    job_id: str,
    *,
    chat_id: int = 111,
    message_id: int | None = 222,
    delivered: bool = False,
    attempts: int = 0,
) -> str:
    with session_scope() as s:
        d = Delivery(
            job_id=job_id,
            chat_id=chat_id,
            message_id=message_id,
            attempts=attempts,
            delivered_at=datetime.now() if delivered else None,
        )
        s.add(d)
        s.flush()
        return d.id


def test_create_db_and_tables_creates_delivery_table(tmp_path: Path) -> None:
    # 🛑 create_all читает SQLModel.metadata, а она наполняется ИМПОРТОМ
    # моделей: не импортированную в цепочке он пропускает молча, и таблицы на
    # проде просто нет — без единой ошибки при старте.
    #
    # 🛑 Проверять это ВНУТРИ сюиты нельзя: файл сам импортирует Delivery
    # в шапке, метаданные уже наполнены, и мутант «убрать импорт из
    # create_db_and_tables» такой тест переживает. Поэтому отдельный процесс,
    # где импортирован только сам модуль db, — то есть ровно как у воркера.
    import subprocess
    import sys

    db_path = tmp_path / "probe.sqlite3"
    code = (
        "from sqlalchemy import inspect;"
        "from core.infra.db import create_db_and_tables, get_engine;"
        "create_db_and_tables();"
        "print(sorted(inspect(get_engine()).get_table_names()))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "DATABASE_URL": f"sqlite:///{db_path}",
            "STORAGE_DIR": str(tmp_path),
        },
        cwd=Path(__file__).resolve().parent.parent,
    )

    assert proc.returncode == 0, proc.stderr
    assert "delivery" in proc.stdout, proc.stdout
    assert "job" in proc.stdout, proc.stdout


def test_no_http_endpoint_can_register_a_delivery() -> None:
    # 🛑 Регистрация НЕ должна быть выставлена наружу. api слушал тогда
    # 0.0.0.0:8033 без аутентификации (порт закрыт позже), поэтому эндпоинт
    # позволял кому угодно заставить бота слать файлы чужим людям. Бот живёт
    # внутри того же процесса — HTTP тут не нужен вовсе.
    from api.main import app

    paths = {route.path for route in app.routes}

    assert "/deliveries" not in paths
    # Позитивный контроль: маршруты вообще читаются этим способом.
    assert "/health" in paths


def test_register_delivery_is_idempotent_for_the_same_message() -> None:
    # Повтор той же ссылки тем же сообщением не должен слать файл дважды.
    _job("job-1", JobStatus.failed.value)

    first = redelivery.register_delivery("job-1", chat_id=5, message_id=7)
    second = redelivery.register_delivery("job-1", chat_id=5, message_id=7)
    other = redelivery.register_delivery("job-1", chat_id=6, message_id=8)

    assert first == second
    assert other != first
    with session_scope() as s:
        assert s.query(Delivery).count() == 2


def test_pending_picks_only_failed_jobs() -> None:
    # Удачный обычный путь бот уже закрыл сам — джоба succeeded, и досылать
    # нечего. Иначе пользователь получил бы файл дважды.
    _job("failed-one", JobStatus.failed.value)
    _job("ok-one", JobStatus.succeeded.value)
    _job("running-one", JobStatus.running.value)
    _delivery("failed-one")
    _delivery("ok-one")
    _delivery("running-one")

    assert redelivery.pending_job_ids() == ["failed-one"]


def test_pending_skips_already_delivered() -> None:
    _job("job-1", JobStatus.failed.value)
    _delivery("job-1", delivered=True)

    assert redelivery.pending_job_ids() == []


def test_pending_gives_up_after_max_attempts() -> None:
    # Без потолка досыл превращается в вечный долбёж площадки с адреса,
    # который она и так считает подозрительным.
    _job("job-1", JobStatus.failed.value)
    _delivery("job-1", attempts=redelivery.MAX_ATTEMPTS)

    assert redelivery.pending_job_ids() == []


def test_pending_deduplicates_job_with_several_waiters() -> None:
    # Ссылка дедуплицируется по фингерпринту: одна джоба — сколько угодно
    # ждущих. Повторять её нужно ОДИН раз, а разослать всем.
    _job("shared", JobStatus.failed.value)
    _delivery("shared", chat_id=1)
    _delivery("shared", chat_id=2)
    _delivery("shared", chat_id=3)

    assert redelivery.pending_job_ids() == ["shared"]


@pytest.mark.asyncio
async def test_successful_retry_sends_to_every_waiter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _job("shared", JobStatus.failed.value)
    _delivery("shared", chat_id=1, message_id=10)
    _delivery("shared", chat_id=2, message_id=20)

    async def _fake_process(job_id: str) -> None:
        with session_scope() as s:
            j = s.get(Job, job_id)
            j.status = JobStatus.succeeded.value
            j.title = "Song"
            s.add(j)

    sent: list[tuple[int, int | None]] = []

    async def _fake_send(**kwargs) -> None:
        sent.append((kwargs["chat_id"], kwargs["message_id"]))

    monkeypatch.setattr(redelivery, "process_job", _fake_process)
    monkeypatch.setattr(redelivery, "send_audio_reply", _fake_send)
    monkeypatch.setattr(
        redelivery, "_audio_file", lambda job_id: tmp_path / "x.mp3"
    )

    delivered = await redelivery.redeliver_pending()

    assert delivered == 2
    assert sorted(sent) == [(1, 10), (2, 20)]

    with session_scope() as s:
        rows = s.query(Delivery).all()
        assert all(r.delivered_at is not None for r in rows)


@pytest.mark.asyncio
async def test_still_failing_job_counts_attempt_and_sends_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _job("job-1", JobStatus.failed.value)
    _delivery("job-1")

    async def _fake_process(job_id: str) -> None:
        # Площадка всё ещё не отдаёт — статус остаётся failed.
        return None

    sent: list[int] = []

    async def _fake_send(**kwargs) -> None:
        sent.append(kwargs["chat_id"])

    monkeypatch.setattr(redelivery, "process_job", _fake_process)
    monkeypatch.setattr(redelivery, "send_audio_reply", _fake_send)

    delivered = await redelivery.redeliver_pending()

    assert delivered == 0
    assert sent == []
    with session_scope() as s:
        row = s.query(Delivery).first()
        assert row.attempts == 1
        assert row.delivered_at is None


@pytest.mark.asyncio
async def test_missing_file_does_not_mark_as_delivered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 🛑 Джоба может стать succeeded, а файла на диске не оказаться (каталог
    # почистили). Пометить доставленным здесь — значит потерять человека
    # навсегда: в следующую выборку он уже не попадёт.
    _job("job-1", JobStatus.failed.value)
    _delivery("job-1")

    async def _fake_process(job_id: str) -> None:
        with session_scope() as s:
            j = s.get(Job, job_id)
            j.status = JobStatus.succeeded.value
            s.add(j)

    sent: list[int] = []

    async def _fake_send(**kwargs) -> None:
        sent.append(kwargs["chat_id"])

    monkeypatch.setattr(redelivery, "process_job", _fake_process)
    monkeypatch.setattr(redelivery, "send_audio_reply", _fake_send)
    monkeypatch.setattr(redelivery, "_audio_file", lambda job_id: None)

    delivered = await redelivery.redeliver_pending()

    assert delivered == 0
    # 🛑 Именно «не пытались отправить», а не «отправка не удалась»: без мока
    # тест проходил бы из-за отсутствия токена в окружении — то есть по
    # случайной причине, и мутант «считать доставленным» его переживал.
    assert sent == []
    with session_scope() as s:
        row = s.query(Delivery).first()
        assert row.delivered_at is None
        assert row.attempts == 1


@pytest.mark.asyncio
async def test_send_failure_of_one_does_not_block_others(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Один заблокировал бота — остальные всё равно должны получить файл.
    _job("shared", JobStatus.failed.value)
    _delivery("shared", chat_id=1)
    _delivery("shared", chat_id=2)

    async def _fake_process(job_id: str) -> None:
        with session_scope() as s:
            j = s.get(Job, job_id)
            j.status = JobStatus.succeeded.value
            s.add(j)

    async def _fake_send(**kwargs) -> None:
        if kwargs["chat_id"] == 1:
            raise RuntimeError("bot was blocked by the user")

    monkeypatch.setattr(redelivery, "process_job", _fake_process)
    monkeypatch.setattr(redelivery, "send_audio_reply", _fake_send)
    monkeypatch.setattr(
        redelivery, "_audio_file", lambda job_id: tmp_path / "x.mp3"
    )

    delivered = await redelivery.redeliver_pending()

    assert delivered == 1
    with session_scope() as s:
        rows = {r.chat_id: r for r in s.query(Delivery).all()}
        assert rows[1].delivered_at is None
        assert rows[1].last_error
        assert rows[2].delivered_at is not None
