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
from dotenv import load_dotenv
import uuid

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
INSTA_BOT_USERNAME = 'instasave_tg'  # Hardcoded as per specs

# Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Instagram client
insta = InstaClient()
if INSTAGRAM_PASSWORD:
    insta.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
else:
    # If using sessionid, set it here: insta.load_settings(json.loads(os.getenv('INSTAGRAM_SESSIONID')))
    pass

# Telegram application
application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

# Helper functions
def is_admin(user_id: int) -> bool:
    return user_id == MASTER_ID

async def send_activation_instructions(update: Update):
    keyboard = [[InlineKeyboardButton("Activate ✅", callback_data='activate')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message = (
        "Welcome to Instagram Reel Downloader Bot!\n\n"
        "Step-by-step guide:\n"
        "1. Follow our Instagram account: @instasave_tg\n"
        "2. Tap the Activate button below.\n"
        "3. Send the generated activation code to @instasave_tg via DM.\n"
        "4. Once confirmed, start sending reel links via Instagram DM to download them here.\n\n"
        "You can also use /download <link> directly here after activation (for public/private reels accessible by the bot)."
    )
    await update.message.reply_text(message, reply_markup=reply_markup)

# Command handlers
async def start(update: Update, context: CallbackContext):
    await send_activation_instructions(update)

async def help_command(update: Update, context: CallbackContext):
    await send_activation_instructions(update)

async def myaccount(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    res = supabase.table('users').select('insta_username').eq('telegram_id', user_id).execute()
    if res.data and res.data[0]['insta_username']:
        await update.message.reply_text(f"Your linked Instagram username: @{res.data[0]['insta_username']}")
    else:
        await update.message.reply_text("No Instagram account linked yet. Use /start to activate.")

async def download(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    res = supabase.table('users').select('insta_username, is_banned').eq('telegram_id', user_id).execute()
    if not res.data or not res.data[0]['insta_username'] or res.data[0]['is_banned']:
        await update.message.reply_text("You must be activated and not banned to download.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /download <instagram_link>")
        return

    link = context.args[0]
    await process_download(update, user_id, link)

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

        # Update videos table (metadata only)
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

# Activation button handler
async def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    if query.data == 'activate':
        user_id = query.from_user.id
        res = supabase.table('users').select('insta_username, activation_code').eq('telegram_id', user_id).execute()
        if res.data:
            data = res.data[0]
            if data['insta_username']:
                await query.edit_message_text("Your account is already activated!")
                return
            if data['activation_code']:
                await query.edit_message_text(f"Your existing code: {data['activation_code']}. Send it to @{INSTA_BOT_USERNAME} on Instagram.")
                return

        code = uuid.uuid4().hex[:8]
        activation_code = f"auth:0:{code}"
        user_data = {
            'telegram_id': user_id,
            'is_banned': False,
            'joined_at': datetime.now().isoformat(),
            'activation_code': activation_code
        }
        supabase.table('users').upsert(user_data).execute()
        await query.edit_message_text(f"Send this code to @{INSTA_BOT_USERNAME} on Instagram via DM: {activation_code}")

# Admin commands
async def adduser(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        return
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("Usage: /adduser <telegram_id> <insta_username>")
        return
    tg_id = int(args[0])
    insta_user = args[1]
    data = {
        'telegram_id': tg_id,
        'insta_username': insta_user,
        'is_banned': False,
        'joined_at': datetime.now().isoformat(),
        'activation_code': None
    }
    supabase.table('users').upsert(data).execute()
    await update.message.reply_text("User added successfully.")

async def removeuser(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        return
    args = context.args
    if len(args) != 1:
        await update.message.reply_text("Usage: /removeuser <telegram_id>")
        return
    tg_id = int(args[0])
    supabase.table('users').delete().eq('telegram_id', tg_id).execute()
    await update.message.reply_text("User removed.")

async def ban(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        return
    args = context.args
    if len(args) != 1:
        await update.message.reply_text("Usage: /ban <telegram_id>")
        return
    tg_id = int(args[0])
    supabase.table('users').update({'is_banned': True}).eq('telegram_id', tg_id).execute()
    await update.message.reply_text("User banned.")

async def unban(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        return
    args = context.args
    if len(args) != 1:
        await update.message.reply_text("Usage: /unban <telegram_id>")
        return
    tg_id = int(args[0])
    supabase.table('users').update({'is_banned': False}).eq('telegram_id', tg_id).execute()
    await update.message.reply_text("User unbanned.")

async def stats(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        return
    users_res = supabase.table('users').select('count(*)', count='exact').execute()
    videos_res = supabase.table('videos').select('count(*)', count='exact').execute()
    users_count = users_res.data[0]['count'] if users_res.data else 0
    videos_count = videos_res.data[0]['count'] if videos_res.data else 0
    await update.message.reply_text(f"Total users: {users_count}\nTotal videos downloaded: {videos_count}")

async def broadcast(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    message = ' '.join(context.args)
    users = supabase.table('users').select('telegram_id').execute()
    for user in users.data:
        try:
            await context.bot.send_message(user['telegram_id'], message)
        except:
            pass
    await update.message.reply_text("Broadcast sent.")

async def set_limit(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        return
    args = context.args
    if len(args) != 1:
        await update.message.reply_text("Usage: /set_limit <size_MB>")
        return
    global MAX_VIDEO_SIZE_BYTES
    MAX_VIDEO_SIZE_BYTES = int(args[0]) * 1024 * 1024
    await update.message.reply_text(f"Max video size set to {args[0]} MB.")

# Instagram DM polling
def poll_instagram():
    seen_messages = set()
    while True:
        try:
            if insta.sessionid is None:  # Relogin if needed
                insta.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
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
                                # Check for duplicate download (within last 1 hour)
                                one_hour_ago = (datetime.now() - timedelta(hours=1)).isoformat()
                                dup_res = supabase.table('videos').select('video_id').eq('insta_link', link).eq('telegram_id', tg_id).gte('downloaded_at', one_hour_ago).execute()
                                if dup_res.data:
                                    application.bot.send_message(tg_id, "This video was recently downloaded. Skipping to avoid duplicates.")
                                    continue
                                await process_download(application.bot, tg_id, link)
            time.sleep(30)
        except LoginRequired:
            insta.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
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

# Register handlers
application.add_handler(CommandHandler('start', start))
application.add_handler(CommandHandler('help', help_command))
application.add_handler(CommandHandler('myaccount', myaccount))
application.add_handler(CommandHandler('download', download))
application.add_handler(CommandHandler('adduser', adduser))
application.add_handler(CommandHandler('removeuser', removeuser))
application.add_handler(CommandHandler('ban', ban))
application.add_handler(CommandHandler('unban', unban))
application.add_handler(CommandHandler('stats', stats))
application.add_handler(CommandHandler('broadcast', broadcast))
application.add_handler(CommandHandler('set_limit', set_limit))
application.add_handler(CallbackQueryHandler(button_handler))

# Start polling thread for Instagram
threading.Thread(target=poll_instagram, daemon=True).start()

# Start Telegram bot
application.run_polling()
