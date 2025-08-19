import os
import logging
import asyncio
from uuid import uuid4
from telegram import (
    BotCommand, Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
from database import (
    add_user, get_user_by_telegram, set_user_banned,
    remove_user, list_all_users, get_stats,
    is_user_banned, update_activation_code, get_user_by_activation_code,
    link_user_instagram, get_user_linked_account
)
from video_utils import download_and_send_video

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MASTER_ID = int(os.getenv("MASTER_ID"))
INSTAGRAM_BOT_USERNAME = "instasave_tg"

MAX_VIDEO_SIZE_MB = int(os.getenv("MAX_VIDEO_SIZE_MB", "50"))

ACTIVATE_CALLBACK = "activate_account"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.full_name

    if await is_user_banned(user_id):
        await update.message.reply_text("🚫 You are banned from using this bot.")
        return

    # Activation button inline
    keyboard = InlineKeyboardMarkup.from_button(
        InlineKeyboardButton("Activate ✅", callback_data=ACTIVATE_CALLBACK)
    )
    welcome_text = (
        f"👋 Hello {username}!\n\n"
        "Welcome to Instagram→Telegram Reel Downloader Bot.\n\n"
        "To start, please activate your account.\n\n"
        "Steps:\n"
        f"1️⃣ Follow our Instagram: @{INSTAGRAM_BOT_USERNAME}\n"
        "2️⃣ Tap Activate button below\n"
        "3️⃣ Send the generated code to our Instagram DM\n"
        "4️⃣ Once confirmed, start sending reel links here to download!\n\n"
        "Use /help for instructions."
    )

    await update.message.reply_text(welcome_text, reply_markup=keyboard)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if await is_user_banned(user_id):
        await update.message.reply_text("🚫 You are banned from using this bot.")
        return

    keyboard = InlineKeyboardMarkup.from_button(
        InlineKeyboardButton("Activate ✅", callback_data=ACTIVATE_CALLBACK)
    )
    help_text = (
        "Instructions to use this bot:\n\n"
        "1. Activate your account by tapping the button below.\n"
        f"2. Send the activation code to our Instagram DM: @{INSTAGRAM_BOT_USERNAME}\n"
        "3. After confirmation, send reel/video links here.\n\n"
        "Commands:\n"
        "/start - Welcome message\n"
        "/help - This message\n"
        "/myaccount - Show linked Instagram username\n"
        "/download <link> - Download a reel/video link\n\n"
        "Admin commands (only for master):\n"
        "/adduser <Telegram_ID> <Insta_Username>\n"
        "/removeuser <Telegram_ID>\n"
        "/ban <Telegram_ID>\n"
        "/unban <Telegram_ID>\n"
        "/stats\n"
        "/broadcast <message>\n"
        "/set_limit <size_MB>\n"
    )
    await update.message.reply_text(help_text, reply_markup=keyboard)

async def activate_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    if await is_user_banned(user_id):
        await query.edit_message_text("🚫 You are banned from using this bot.")
        return

    # Generate unique activation code and store in DB
    code = f"auth:0:{uuid4()}"
    await update_activation_code(user_id, code)

    msg = (
        "🔑 Your activation code:\n\n"
        f"`{code}`\n\n"
        f"Send this exact code to our Instagram DM @{INSTAGRAM_BOT_USERNAME}.\n"
        "Once we verify, your Telegram account will be activated to download reels."
    )
    await query.edit_message_text(msg, parse_mode="Markdown")

async def myaccount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if await is_user_banned(user_id):
        await update.message.reply_text("🚫 You are banned from using this bot.")
        return

    linked_insta = await get_user_linked_account(user_id)
    if linked_insta:
        await update.message.reply_text(f"Your linked Instagram username: @{linked_insta}")
    else:
        await update.message.reply_text(
            "You have not activated your account yet. Please use /start and activate first."
        )

async def download_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if await is_user_banned(user_id):
        await update.message.reply_text("🚫 You are banned from using this bot.")
        return

    if not context.args:
        await update.message.reply_text("Please provide an Instagram reel/post/video link.\nUsage: /download <link>")
        return

    link = context.args[0]
    # Check if user activated (linked Instagram)
    linked_insta = await get_user_linked_account(user_id)
    if not linked_insta:
        await update.message.reply_text(
            "❗ You must activate your account first. Use /start and follow activation steps."
        )
        return

    await update.message.reply_text("Downloading your video, please wait...")

    try:
        await download_and_send_video(link, update, context, user_id)
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to download/send video: {e}")

# Admin commands: restricted to MASTER_ID

async def adduser_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != MASTER_ID:
        return
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /adduser <Telegram_ID> <Insta_Username>")
        return

    telegram_id = int(context.args)
    insta_username = context.args
    await add_user(telegram_id, insta_username)
    await update.message.reply_text(f"User {telegram_id} with Instagram @{insta_username} added.")

async def removeuser_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != MASTER_ID:
        return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /removeuser <Telegram_ID>")
        return
    telegram_id = int(context.args)
    await remove_user(telegram_id)
    await update.message.reply_text(f"User {telegram_id} removed.")

async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != MASTER_ID:
        return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /ban <Telegram_ID>")
        return
    telegram_id = int(context.args)
    await set_user_banned(telegram_id, True)
    await update.message.reply_text(f"User {telegram_id} banned.")

async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != MASTER_ID:
        return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /unban <Telegram_ID>")
        return
    telegram_id = int(context.args)
    await set_user_banned(telegram_id, False)
    await update.message.reply_text(f"User {telegram_id} unbanned.")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != MASTER_ID:
        return
    total_users, total_videos = await get_stats()
    await update.message.reply_text(
        f"📊 Total registered users: {total_users}\n"
        f"📥 Total videos downloaded: {total_videos}"
    )

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != MASTER_ID:
        return
    message = ' '.join(context.args)
    if not message:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    users = await list_all_users()
    sent = 0
    bot = context.bot
    for user in users:
        try:
            await bot.send_message(user['telegram_id'], message)
            sent += 1
        except Exception:
            continue
    await update.message.reply_text(f"Broadcast sent to {sent} users.")

async def set_limit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != MASTER_ID:
        return
    global MAX_VIDEO_SIZE_MB
    if len(context.args) != 1 or not context.args.isdigit():
        await update.message.reply_text("Usage: /set_limit <size_MB>")
        return
    MAX_VIDEO_SIZE_MB = int(context.args)
    await update.message.reply_text(f"Max video size for compression set to {MAX_VIDEO_SIZE_MB} MB.")

# Handler to process messages with reel links (optional enhancement)
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    if await is_user_banned(user_id):
        await update.message.reply_text("🚫 You are banned from using this bot.")
        return
    # If text contains Instagram reel link, process download automatically
    if text.startswith("http") and ("instagram.com" in text):
        linked_insta = await get_user_linked_account(user_id)
        if not linked_insta:
            await update.message.reply_text(
                "❗ You must activate your account first. Use /start and follow activation steps."
            )
            return
        await update.message.reply_text("Downloading your video, please wait...")
        try:
            await download_and_send_video(text, update, context, user_id)
        except Exception as e:
            await update.message.reply_text(f"❌ Failed to download/send video: {e}")

async def start_telegram_bot():
    application = ApplicationBuilder().token(TOKEN).build()

    # Commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("myaccount", myaccount))
    application.add_handler(CommandHandler("download", download_command))
    # Admin commands
    application.add_handler(CommandHandler("adduser", adduser_command))
    application.add_handler(CommandHandler("removeuser", removeuser_command))
    application.add_handler(CommandHandler("ban", ban_command))
    application.add_handler(CommandHandler("unban", unban_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    application.add_handler(CommandHandler("set_limit", set_limit_command))

    # CallbackQuery for Activate button
    application.add_handler(CallbackQueryHandler(activate_button, pattern=f"^{ACTIVATE_CALLBACK}$"))

    # Message handler for direct links
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    logger.info("Starting Telegram bot...")
    await application.run_polling()
  
