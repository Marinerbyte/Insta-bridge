import asyncio
import threading
from fastapi import FastAPI
from instagram_bot import start_instagram_bot
from video_utils import scheduled_cleanup
from telegram_bot import start_telegram_bot

app = FastAPI()

def run_telegram_bot():
    import asyncio
    asyncio.run(start_telegram_bot())

@app.on_event("startup")
async def startup_event():
    # Run telegram bot in separate thread so it does not conflict with FastAPI event loop
    threading.Thread(target=run_telegram_bot, daemon=True).start()

    # Run Instagram bot and cleanup in async tasks normally
    asyncio.create_task(start_instagram_bot())
    asyncio.create_task(scheduled_cleanup())

@app.get("/")
async def root():
    return {"message": "Instagram-Telegram Reel Downloader Bridge Bot is running."}
    
