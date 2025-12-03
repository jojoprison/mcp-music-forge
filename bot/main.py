import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Message, FSInputFile
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

async def monitor_job(message: Message, job_id: str, api_base: str):
    """Poll API for job status and send file when done."""
    status_msg = await message.answer(f"⏳ Job <code>{job_id}</code> queued. Waiting for result...", disable_notification=True)
    
    # Poll for result
    # Max wait time: 5 minutes (100 * 3s = 300s)
    for _ in range(100):
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{api_base}/jobs/{job_id}")
                if resp.status_code != 200:
                    await asyncio.sleep(3)
                    continue
                
                data = resp.json()
                status = data.get("status")
                
                if status == "succeeded":
                    await status_msg.edit_text("⬇️ Downloading finished! Uploading to Telegram...")
                    
                    # Locate file on disk (shared volume)
                    storage_dir = settings.storage_dir
                    final_dir = storage_dir / "jobs" / job_id / "final"
                    
                    if not final_dir.exists():
                         await status_msg.edit_text("❌ Job succeeded, but file directory not found.")
                         return

                    # Find audio file
                    audio_extensions = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus"}
                    files = [f for f in final_dir.iterdir() if f.is_file() and not f.name.startswith(".")]
                    audio_files = [f for f in files if f.suffix.lower() in audio_extensions]
                    
                    file_to_send = audio_files[0] if audio_files else (files[0] if files else None)
                    
                    if file_to_send:
                        try:
                            audio = FSInputFile(path=file_to_send)
                            # Use title and artist from job data if available
                            title = data.get("title")
                            artist = data.get("artist")
                            duration = data.get("duration")
                            
                            await message.answer_audio(
                                audio, 
                                title=title, 
                                performer=artist, 
                                duration=duration,
                                caption=f"✅ Done! {title or ''}"
                            )
                            await status_msg.delete()
                        except Exception as send_err:
                            logger.error(f"Error sending file: {send_err}")
                            await status_msg.edit_text(f"❌ Error sending file: {send_err}")
                    else:
                         await status_msg.edit_text("❌ Job succeeded, but no file found to send.")
                    return
                    
                elif status == "failed":
                    error = data.get("error", "Unknown error")
                    await status_msg.edit_text(f"❌ Job failed: {error}")
                    return
                
                # If queued or processing, wait
                await asyncio.sleep(3)
                
        except Exception as e:
            logger.error(f"Polling error: {e}")
            await asyncio.sleep(3)
            
    await status_msg.edit_text("❌ Timeout waiting for job completion.")


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
    target_url = "http://api:8033/download"
    api_base = "http://api:8033"
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(target_url, params={"url": text}, timeout=10.0)
            response.raise_for_status()
            data = response.json()
            job_id = data.get("job_id")
            
            # Start monitoring task
            asyncio.create_task(monitor_job(message, job_id, api_base))
            
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
