import os
import re
import threading
import time
import subprocess
from datetime import datetime, timedelta
from instagrapi import Client as InstaClient
from instagrapi.exceptions import LoginRequired
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, CallbackContext
from supabase import create_client, Client
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from uvicorn import Config, Server
import asyncio
import json
import uuid
from dotenv import load_dotenv

load_dotenv()

# Environment variables
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
MASTER_ID = int(os.getenv('MASTER_ID'))
INSTAGRAM_USERNAME = os.getenv('INSTAGRAM_USERNAME')
INSTAGRAM_PASSWORD = os.getenv('INSTAGRAM_PASSWORD')
MAX_VIDEO_SIZE_MB = int(os.getenv('MAX_VIDEO_SIZE_MB', 50))
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

MAX_VIDEO_SIZE_BYTES = MAX_VIDEO_SIZE_MB * 1024 * 1024
INSTA_BOT_USERNAME = 'instasave_tg'

# Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Instagram client
insta = InstaClient()
if INSTAGRAM_PASSWORD:
    try:
        insta.load_settings(json.loads(INSTAGRAM_PASSWORD))
    except Exception as e:
        print(f"Session load failed: {e}")
        insta.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)

# Telegram application
application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

# FastAPI app for health check
app = FastAPI()

@app.get("/health")
async def health_check():
    return {"status": "ok"}

# Helper functions aur command handlers (same as original app.py, yahaan chhota karke dikha raha hoon)
async def start(update: Update, context: CallbackContext):
    keyboard = [[InlineKeyboardButton("Activate ✅", callback_data='activate')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message = (
        "Welcome to Instagram Reel Downloader Bot!\n\n"
        "Step-by-step guide:\n"
        "1. Follow our Instagram account: @instasave_tg\n"
        "2. Tap the Activate button below.\n"
        "3. Send the generated activation code to @instasave_tg via DM.\n"
        "4. Once confirmed, start sending reel links via Instagram DM to download them here.\n\n"
        "You can also use /download <link> directly here after activation."
    )
    await update.message.reply_text(message, reply_markup=reply_markup)

async def process_download(update_or_bot, user_id: int, link: str):
    try:
        pk = insta.media_pk_from_url(link)
        path = insta.clip_download(pk)
        if not path:
            raise Exception("Download failed.")
        size = os.path.getsize(path)
        path = compress_video(path)
        final_size = os.path.getsize(path)
        with open(path, 'rb') as video_file:
            if isinstance(update_or_bot, Update):
                await update_or_bot.message.reply_video(video=video_file)
            else:
                await application.bot.send_video(user_id, video=video_file)
        os.remove(path)
        video_data = {
            'insta_link': link,
            'telegram_id': user_id,
            'downloaded_at': datetime.now().isoformat(),
            'file_size': final_size
        }
        supabase.table('videos').insert(video_data).execute()
    except Exception as e:
        print(f"Download error: {e}")
        error_msg = "Failed to download or send the video. Ensure the link is valid and accessible."
        if isinstance(update_or_bot, Update):
            await update_or_bot.message.reply_text(error_msg)
        else:
            await application.bot.send_message(user_id, error_msg)

def compress_video(input_path: str) -> str:
    size = os.path.getsize(input_path)
    if size <= MAX_VIDEO_SIZE_BYTES:
        return input_path
    output_path = input_path.replace('.mp4', '_compressed.mp4')
    cmd = ['ffmpeg', '-i', input_path, '-vcodec', 'libx264', '-crf', '28', output_path]
    subprocess.run(cmd, check=True, capture_output=True)
    os.remove(input_path)
    return output_path

# Instagram DM polling (same as original)
def poll_instagram():
    seen_messages = set()
    while True:
        try:
            if insta.sessionid is None:
                insta.load_settings(json.loads(INSTAGRAM_PASSWORD))
            threads = insta.direct_threads(amount=20)
            for thread in threads:
                messages = insta.direct_messages(thread.id, amount=10)
                for msg in messages:
                    if msg.id in seen_messages:
                        continue
                    seen_messages.add(msg.id)
                    sender_user = insta.user_info(msg.user_id).username
                    text = msg.text or ''
                    if text.startswith('auth:0:'):
                        code = text
                        res = supabase.table('users').select('telegram_id').eq('activation_code', code).execute()
                        if res.data:
                            tg_id = res.data[0]['telegram_id']
                            supabase.table('users').update({'insta_username': sender_user, 'activation_code': None}).eq('telegram_id', tg_id).execute()
                            application.bot.send_message(tg_id, "✅ Your account is now activated! You can now send reels to download.")
                    else:
                        urls = re.findall(r'(https?://[^\s]+)', text)
                        if urls and 'instagram.com' in urls[0] and any(x in urls[0] for x in ['reel', '/p/', '/tv/']):
                            res = supabase.table('users').select('telegram_id, is_banned').eq('insta_username', sender_user).execute()
                            if res.data and not res.data[0]['is_banned']:
                                tg_id = res.data[0]['telegram_id']
                                link = urls[0]
                                one_hour_ago = (datetime.now() - timedelta(hours=1)).isoformat()
                                dup_res = supabase.table('videos').select('video_id').eq('insta_link', link).eq('telegram_id', tg_id).gte('downloaded_at', one_hour_ago).execute()
                                if dup_res.data:
                                    application.bot.send_message(tg_id, "This video was recently downloaded. Skipping to avoid duplicates.")
                                    continue
                                asyncio.run_coroutine_threadsafe(process_download(application.bot, tg_id, link), asyncio.get_event_loop())
            time.sleep(30)
        except LoginRequired:
            insta.load_settings(json.loads(INSTAGRAM_PASSWORD))
        except Exception as e:
            print(f"Polling error: {e}")
            time.sleep(60)

# Auto cleanup
def cleanup_files():
    for file in os.listdir('.'):
        if file.endswith(('.mp4', '_compressed.mp4')):
            try:
                os.remove(file)
            except:
                pass

scheduler = BackgroundScheduler()
scheduler.add_job(cleanup_files, 'interval', hours=1)
scheduler.start()

# Register Telegram handlers (same as original, add other handlers as needed)
application.add_handler(CommandHandler('start', start))
application.add_handler(CommandHandler('help', start))
application.add_handler(CommandHandler('myaccount', myaccount))
application.add_handler(CommandHandler('download', download))
application.add_handler(CallbackQueryHandler(button_handler))

# Run FastAPI and Telegram bot concurrently
async def main():
    config = Config(app=app, host="0.0.0.0", port=8000)
    server = Server(config)
    fastapi_task = asyncio.create_task(server.serve())
    threading.Thread(target=poll_instagram, daemon=True).start()
    await application.run_polling()
    await fastapi_task

if __name__ == "__main__":
    asyncio.run(main())
