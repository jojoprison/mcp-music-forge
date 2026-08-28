from __future__ import annotations

from pathlib import Path

import pytest
from tenacity import wait_none

from core.domain.job import DownloadOptions, Job, JobStatus
from core.errors import (
    AuthRequiredError,
    MediaUnavailableError,
    ProviderError,
    TemporaryProviderError,
)
from core.infra.db import create_db_and_tables, session_scope
from core.ports.provider_port import ProbeResult, ProviderPort
from core.services import download_orchestrator, provider_registry
from core.services.download_orchestrator import process_job
from core.settings import get_settings
from providers.ytdlp_base import classify_ytdlp_error


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        # 🛑 Именно в этой форме yt-dlp и печатает — с ТИПОГРАФСКИМ
        # апострофом. Матч по ASCII-апострофу не сработал бы, и самая
        # частая ошибка уехала бы в «неизвестные».
        #
        # И она ПОПРАВИМАЯ: замер 28.08 — одна ссылка в 10:33 скачалась,
        # в 10:58 получила этот отказ. Флагуется адрес, а не видео.
        (
            "ERROR: [youtube] abc: Sign in to confirm you’re not a bot.",
            TemporaryProviderError,
        ),
        (
            "ERROR: [youtube] abc: Sign in to confirm you're not a bot.",
            TemporaryProviderError,
        ),
        # А вот это — настоящая авторизация, её повтор не лечит.
        (
            "ERROR: [youtube] abc: Sign in to confirm your age",
            AuthRequiredError,
        ),
        ("ERROR: [youtube] abc: Private video. Sign in", AuthRequiredError),
        (
            "ERROR: [youtube] abc: Video unavailable",
            MediaUnavailableError,
        ),
        (
            "ERROR: The uploader has not made this video available in your "
            "country",
            MediaUnavailableError,
        ),
        (
            "ERROR: unable to download video data: HTTP Error 403: Forbidden",
            TemporaryProviderError,
        ),
        ("ERROR: [youtube] abc: Read timed out.", TemporaryProviderError),
        ("совершенно новая ошибка площадки", TemporaryProviderError),
    ],
)
def test_classifier_maps_message_to_domain_error(
    message: str, expected: type[ProviderError]
) -> None:
    assert type(classify_ytdlp_error(Exception(message))) is expected


def test_auth_and_unavailable_are_not_retryable() -> None:
    assert AuthRequiredError("x").retryable is False
    assert MediaUnavailableError("x").retryable is False


def test_temporary_is_retryable() -> None:
    assert TemporaryProviderError("x").retryable is True


def test_technical_text_is_preserved_for_logs() -> None:
    raw = "ERROR: [youtube] abc: Sign in to confirm you’re not a bot."
    err = classify_ytdlp_error(Exception(raw))
    # Пользователю — человеческий текст, в лог — формулировка площадки.
    assert err.technical == raw
    assert "cookies" in err.user_message
    assert "Sign in" not in err.user_message


def test_bot_check_is_retried_but_real_auth_is_not() -> None:
    # Ядро различия: за бота нас принимают временно (флаг на адресе),
    # а возрастное ограничение повтором не снимается никогда.
    bot_check = classify_ytdlp_error(
        Exception("Sign in to confirm you’re not a bot")
    )
    age_gate = classify_ytdlp_error(
        Exception("Sign in to confirm your age")
    )

    assert bot_check.retryable is True
    assert age_gate.retryable is False


class _FailingProvider(ProviderPort):
    """Падает заданной ошибкой и считает, сколько раз его дёрнули."""

    name = "youtube"

    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    def can_handle(self, url: str) -> bool:
        return True

    async def probe(self, url: str) -> ProbeResult:
        raise self.error

    async def download(
        self, url: str, dest_dir: str, *, respect_tou: bool = True
    ) -> tuple[str, ProbeResult]:
        self.calls += 1
        raise self.error


async def _run_job_with(
    provider: _FailingProvider,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    job_id: str,
) -> tuple[str, str | None]:
    get_settings().storage_dir = tmp_path / "data"
    create_db_and_tables()
    monkeypatch.setattr(
        provider_registry, "detect_provider", lambda url: provider
    )
    # Без этого тест ждал бы настоящие окна ретрая — полторы минуты.
    monkeypatch.setattr(download_orchestrator, "_RETRY_WAIT", wait_none())

    with session_scope() as s:
        s.add(
            Job(
                id=job_id,
                provider="youtube",
                url="https://youtu.be/x",
                fingerprint=job_id,
                status=JobStatus.queued.value,
                options=DownloadOptions().model_dump(),
            )
        )

    await process_job(job_id)

    # Читаем поля внутри сессии: снаружи объект отвязан и атрибуты не тянутся.
    with session_scope() as s:
        job = s.get(Job, job_id)
        assert job is not None
        return job.status, job.error


@pytest.mark.asyncio
async def test_auth_error_is_not_retried_and_reaches_user(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _FailingProvider(
        AuthRequiredError("Нужен файл cookies", technical="Sign in ...")
    )

    status, error = await _run_job_with(
        provider, monkeypatch, tmp_path, "job-auth"
    )

    # Повтор такую ошибку не лечит — дёргать площадку второй раз незачем.
    assert provider.calls == 1
    assert status == JobStatus.failed.value
    assert error == "Нужен файл cookies"


@pytest.mark.asyncio
async def test_temporary_error_is_retried_until_attempts_run_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _FailingProvider(
        TemporaryProviderError("Попробуй позже", technical="HTTP Error 403")
    )

    status, error = await _run_job_with(
        provider, monkeypatch, tmp_path, "job-temp"
    )

    assert provider.calls == download_orchestrator._RETRY_ATTEMPTS
    assert status == JobStatus.failed.value
    assert error == "Попробуй позже"


@pytest.mark.asyncio
async def test_tou_refusal_still_fails_without_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Отказ по ToU у SoundCloud приходит обычным PermissionError —
    # он не должен ни ретраиться, ни потерять текст.
    provider = _FailingProvider(PermissionError("Track not allowed"))

    status, error = await _run_job_with(
        provider, monkeypatch, tmp_path, "job-tou"
    )

    assert provider.calls == 1
    assert status == JobStatus.failed.value
    assert error == "Track not allowed"
