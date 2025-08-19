import os
import asyncio
import logging
from instagrapi import Client
from database import (
    get_user_by_activation_code,
    link_user_instagram
)

INSTAGRAM_USERNAME = os.getenv("INSTAGRAM_USERNAME")
INSTAGRAM_PASSWORD = os.getenv("INSTAGRAM_PASSWORD")

# Instagram bot account username mentioned in Telegram instructions
BOT_INSTAGRAM_USERNAME = "instasave_tg"

logger = logging.getLogger(__name__)

cl = Client()

async def start_instagram_bot():
    # Login with username/password or sessionid
    try:
        logger.info("Logging into Instagram...")
        if INSTAGRAM_PASSWORD and len(INSTAGRAM_PASSWORD) > 100:  # assume sessionid or cookie string
            cl.set_settings({'sessionid': INSTAGRAM_PASSWORD})
            cl.login(INSTAGRAM_USERNAME, "")  # Using sessionid only
        else:
            cl.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
        logger.info("Instagram logged in.")
    except Exception as e:
        logger.error(f"Instagram login failed: {e}")
        return

    # Continuously poll for new DMs every 15 seconds
    last_seen_thread_ids = set()

    while True:
        try:
            threads = cl.direct_threads()
            for thread in threads:
                if thread.pk in last_seen_thread_ids:
                    continue
                # Process new thread for activation code verification
                await process_thread(thread)
                last_seen_thread_ids.add(thread.pk)
            await asyncio.sleep(15)
        except Exception as e:
            logger.error(f"Error fetching Instagram DMs: {e}")
            await asyncio.sleep(30)

async def process_thread(thread):
    # Parse messages in DM thread to find activation code messages
    for item in thread.items:
        text = item.text or ""
        if text.startswith("auth:0:"):
            # Lookup activation code in DB
            telegram_user = await get_user_by_activation_code(text.strip())
            if telegram_user:
                insta_username = thread.users[0].username
                telegram_id = telegram_user['telegram_id']
                # Link Instagram username to Telegram user (activate)
                await link_user_instagram(telegram_id, insta_username)
                # Optionally send confirmation messages
                try:
                    # Send confirmation via Telegram bot
                    from telegram_bot import send_telegram_message
                    await send_telegram_message(
                        telegram_id,
                        "✅ Your account is now activated! You can now send reels to download."
                    )
                except Exception as e:
                    logger.error(f"Failed to send Telegram confirmation: {e}")
                    
