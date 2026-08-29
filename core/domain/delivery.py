from __future__ import annotations

import uuid
from datetime import datetime

from sqlmodel import Field as SQLField
from sqlmodel import SQLModel


class Delivery(SQLModel, table=True):
    """Кому отдать результат джобы.

    Отдельная таблица, а не колонки в `job`, по двум причинам.

    Первая — смысловая: джобы дедуплицируются по фингерпринту, поэтому одну
    ссылку могут ждать несколько человек. Колонка `chat_id` в `job` хранила бы
    только последнего, то есть фича молча теряла бы получателей — ровно тех,
    ради кого она и пишется.

    Вторая — практическая: `SQLModel.create_all` создаёт новые таблицы, но
    НЕ добавляет колонки в существующие. Отдельная таблица заводится на проде
    сама, миграция не нужна.
    """

    id: str = SQLField(
        default_factory=lambda: uuid.uuid4().hex, primary_key=True
    )
    job_id: str = SQLField(index=True)

    chat_id: int = SQLField(index=True)
    # Нужен, чтобы ответить реплаем на исходное сообщение: человек через
    # неделю не помнит, какая из его ссылок наконец доехала.
    message_id: int | None = None

    # Проставляется только после фактической отправки файла. Пока пусто —
    # долг перед человеком не закрыт.
    delivered_at: datetime | None = None
    attempts: int = SQLField(default=0)
    last_error: str | None = None

    created_at: datetime = SQLField(default_factory=datetime.now)

    def __str__(self) -> str:
        return f"delivery {self.id} → chat {self.chat_id} (job {self.job_id})"
