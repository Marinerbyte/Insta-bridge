import os
import shutil
import subprocess
import asyncio
from yt_dlp import YoutubeDL
from telegram import Update
from telegram.ext import ContextTypes
from database import add_video_record

MAX_VIDEO_SIZE_MB = int(os.getenv("MAX_VIDEO_SIZE_MB", "50"))
VIDEO_FOLDER = "./videos"

if not os.path.exists(VIDEO_FOLDER):
    os.makedirs(VIDEO_FOLDER)

ydl_opts = {
    'outtmpl': VIDEO_FOLDER + '/%(id)s.%(ext)s',
    'format': 'mp4',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True
}

async def download_and_send_video(link: str, update: Update, context: ContextTypes.DEFAULT_TYPE, telegram_id: int):
    loop = asyncio.get_event_loop()

    def download():
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(link, download=True)
            filename = ydl.prepare_filename(info)
            return filename, info

    filename, info = await loop.run_in_executor(None, download)

    # Check size MB and compress if needed
    file_size = os.path.getsize(filename) / (1024 * 1024)
    if file_size > MAX_VIDEO_SIZE_MB:
        compressed_file = filename.replace(".mp4", "-compressed.mp4")
        await compress_video(filename, compressed_file)
        os.remove(filename)
        filename = compressed_file

    # Send video to Telegram user
    await context.bot.send_video(chat_id=telegram_id, video=open(filename, "rb"))

    # Add metadata to DB
    await add_video_record(link, telegram_id, int(file_size))

    # Delete file after sending
    os.remove(filename)

async def compress_video(input_path, output_path):
    cmd = [
        "ffmpeg", "-i", input_path,
        "-vcodec", "libx264",
        "-crf", "28",
        "-preset", "fast",
        "-acodec", "aac",
        output_path,
    ]
    proc = await asyncio.create_subprocess_exec(*cmd)
    await proc.communicate()

async def scheduled_cleanup():
    while True:
        try:
            for filename in os.listdir(VIDEO_FOLDER):
                if filename.endswith(".mp4"):
                    filepath = os.path.join(VIDEO_FOLDER, filename)
                    os.remove(filepath)
        except Exception as e:
            print(f"Cleanup error: {e}")
        await asyncio.sleep(3600)  # run cleanup every hour

# For use in instagram_bot.py to notify users by Telegram
telegram_bot_instance = None

def set_telegram_bot(bot):
    global telegram_bot_instance
    telegram_bot_instance = bot

async def send_telegram_message(chat_id: int, message: str):
    if telegram_bot_instance:
        await telegram_bot_instance.send_message(chat_id=chat_id, text=message)
