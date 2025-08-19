import os
import asyncio
from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Users Table Fields: telegram_id, insta_username, is_banned, joined_at, activation_code

async def add_user(telegram_id: int, insta_username: str):
    # Check exists
    data = supabase.table("users").select("*").eq("telegram_id", telegram_id).execute()
    if data.data:
        # Update insta_username and reset ban
        supabase.table("users").update({"insta_username": insta_username, "is_banned": False}).eq("telegram_id", telegram_id).execute()
    else:
        supabase.table("users").insert({
            "telegram_id": telegram_id,
            "insta_username": insta_username,
            "is_banned": False,
            "joined_at": "now()"
        }).execute()

async def remove_user(telegram_id: int):
    supabase.table("users").delete().eq("telegram_id", telegram_id).execute()

async def set_user_banned(telegram_id: int, ban_status: bool):
    supabase.table("users").update({"is_banned": ban_status}).eq("telegram_id", telegram_id).execute()

async def is_user_banned(telegram_id: int) -> bool:
    response = supabase.table("users").select("is_banned").eq("telegram_id", telegram_id).execute()
    if response.data and len(response.data) > 0:
        return response.data['is_banned']
    return False

async def update_activation_code(telegram_id: int, code: str):
    supabase.table("users").update({"activation_code": code}).eq("telegram_id", telegram_id).execute()

async def get_user_by_activation_code(code: str):
    response = supabase.table("users").select("*").eq("activation_code", code).execute()
    if response.data and len(response.data) > 0:
        return response.data
    return None

async def link_user_instagram(telegram_id: int, insta_username: str):
    supabase.table("users").update({"insta_username": insta_username, "activation_code": None}).eq("telegram_id", telegram_id).execute()

async def get_user_linked_account(telegram_id: int):
    response = supabase.table("users").select("insta_username").eq("telegram_id", telegram_id).execute()
    if response.data and len(response.data) > 0:
        return response.data.get("insta_username")
    return None

async def list_all_users():
    response = supabase.table("users").select("telegram_id").execute()
    if response.data:
        return response.data
    return []

async def get_stats():
    users = supabase.table("users").select("*").execute()
    videos = supabase.table("videos").select("*").execute()
    total_users = len(users.data) if users.data else 0
    total_videos = len(videos.data) if videos.data else 0
    return total_users, total_videos

async def add_video_record(insta_link: str, telegram_id: int, file_size: int):
    from datetime import datetime
    supabase.table("videos").insert({
        "insta_link": insta_link,
        "telegram_id": telegram_id,
        "downloaded_at": datetime.utcnow().isoformat(),
        "file_size": file_size
    }).execute()
