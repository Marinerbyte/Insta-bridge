import asyncio
from fastapi import FastAPI
from telegram_bot import start_telegram_bot
from instagram_bot import start_instagram_bot
from video_utils import scheduled_cleanup

app = FastAPI()

@app.on_event("startup")
async def startup_event():
    # Run Telegram bot, Instagram bot, and cleanup concurrently
    asyncio.create_task(start_telegram_bot())
    asyncio.create_task(start_instagram_bot())
    asyncio.create_task(scheduled_cleanup())

@app.get("/")
async def root():
    return {"message": "Instagram-Telegram Reel Downloader Bridge Bot is running."}
