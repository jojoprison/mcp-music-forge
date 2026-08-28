from __future__ import annotations


class ProviderError(Exception):
    """Отказ площадки, у которого есть текст для пользователя.

    `user_message` уезжает в `job.error` и оттуда прямо в телеграм, поэтому
    он должен объяснять, что произошло, человеку. Техническая формулировка
    yt-dlp остаётся в `technical` — для логов и разбора, не для чата.
    """

    retryable = False

    def __init__(self, user_message: str, *, technical: str | None = None):
        super().__init__(user_message)
        self.user_message = user_message
        self.technical = technical or user_message


class AuthRequiredError(ProviderError):
    """Площадка отдаёт материал только авторизованным.

    Повтор бесполезен по построению: без cookies результат не изменится
    ни через секунду, ни через час.
    """


class MediaUnavailableError(ProviderError):
    """Приватное, удалённое или недоступное в нашем регионе.

    Тоже терминальная: повторять нечего, материала нет.
    """


class TemporaryProviderError(ProviderError):
    """Сеть, лимит частоты, 403 на медиапоток — то, что лечится повтором."""

    retryable = True
