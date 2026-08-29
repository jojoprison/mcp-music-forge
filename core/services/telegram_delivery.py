from __future__ import annotations

from pathlib import Path

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import FSInputFile, ReplyParameters

from core.settings import get_settings


async def send_audio_reply(
    *,
    chat_id: int,
    message_id: int | None,
    path: Path,
    title: str | None = None,
    artist: str | None = None,
    duration: int | None = None,
    caption: str | None = None,
) -> None:
    """Отправляет аудио реплаем на исходное сообщение пользователя.

    Отдельный короткоживущий `Bot` — не поллер: конфликт 409 даёт только
    `getUpdates`, а отправка сообщений с ним не спорит. Поэтому воркер может
    писать в Telegram, не трогая бота, который живёт внутри api-процесса.
    """
    token = get_settings().telegram_bot_token
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

    reply = None
    if message_id is not None:
        # 🛑 allow_sending_without_reply обязателен: за время простоя человек
        # мог удалить своё сообщение, и без этого флага отправка упала бы
        # целиком — то есть ровно в том случае, ради которого досыл и нужен.
        reply = ReplyParameters(
            message_id=message_id, allow_sending_without_reply=True
        )

    bot = Bot(
        token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    try:
        await bot.send_audio(
            chat_id=chat_id,
            audio=FSInputFile(path=path),
            title=title,
            performer=artist,
            duration=duration,
            caption=caption,
            reply_parameters=reply,
        )
    finally:
        await bot.session.close()
