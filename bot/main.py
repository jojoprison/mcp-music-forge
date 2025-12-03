import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Message
from aiogram.filters import CommandStart
import httpx

# We need to add project root to sys.path to import core modules
import os
sys.path.append(os.getcwd())

from core.settings import get_settings
from core.logging import configure_logging

# Configure logging
configure_logging(logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()

dp = Dispatcher()

def is_valid_url(text: str) -> bool:
    if not text:
        return False
    text = text.strip()
    if not (text.startswith("http://") or text.startswith("https://")):
        return False
    # Simple check for domains
    domains = ["soundcloud.com", "youtube.com", "youtu.be", "m.soundcloud.com", "www.youtube.com"]
    return any(d in text for d in domains)

@dp.message(CommandStart())
async def command_start_handler(message: Message) -> None:
    await message.answer(f"Hello, {message.from_user.full_name}! Send me a SoundCloud or YouTube link to download.")

@dp.message()
async def handle_message(message: Message) -> None:
    text = message.text
    
    if not text:
        await message.answer("Please send a valid YouTube or SoundCloud link.")
        return

    text = text.strip()
    
    if not is_valid_url(text):
        await message.answer("Please send a valid YouTube or SoundCloud link.")
        return

    # Call API to enqueue
    # We assume the bot is running in the same docker network as the API service named 'api'
    target_url = "http://api:8033/download"
    
    await message.answer("Processing...")
    
    try:
        async with httpx.AsyncClient() as client:
            # The API expects 'url' as a query parameter
            response = await client.post(target_url, params={"url": text}, timeout=10.0)
            response.raise_for_status()
            data = response.json()
            job_id = data.get("job_id")
            status = data.get("status")
            await message.answer(f"✅ Task queued!\nID: <code>{job_id}</code>\nStatus: {status}")
    except httpx.ConnectError:
        await message.answer("❌ Error: Could not connect to the API server.")
    except Exception as e:
        logger.error(f"Error calling API: {e}")
        await message.answer(f"❌ Error queuing task: {str(e)}")

async def main() -> None:
    token = settings.telegram_bot_token
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN is not set. Please check your .env file.")
        return

    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    
    logger.info("Starting bot...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
