import logging
import os
import asyncio
from pyrogram import Client
from telegram import Update
from telegram.ext import (
    Application, MessageHandler,
    ContextTypes, filters
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN    = os.environ["BOT_TOKEN"]
API_ID   = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]

SESSION_1 = os.environ["SESSION_1"]
SESSION_2 = os.environ["SESSION_2"]
SESSION_3 = os.environ["SESSION_3"]

ALLOWED = {8034872992, 8793739928}

clients = [
    Client("ban_guard_1", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_1, sleep_threshold=60),
    Client("ban_guard_2", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_2, sleep_threshold=60),
    Client("ban_guard_3", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_3, sleep_threshold=60),
]

async def ban_chunk(pyro: Client, cid: int, user_ids: list):
    banned = 0
    skipped = 0
    for i in range(0, len(user_ids), 150):
        batch = user_ids[i:i+150]
        async def ban_one(uid, p=pyro):
            nonlocal banned, skipped
            try:
                await p.ban_chat_member(cid, uid)
                banned += 1
            except Exception as e:
                err = str(e)
                if "FLOOD_WAIT" in err:
                    wait = int(''.join(filter(str.isdigit, err)) or 5)
                    logger.warning(f"FloodWait {wait}s — {p.name}")
                    await asyncio.sleep(wait)
                    try:
                        await p.ban_chat_member(cid, uid)
                        banned += 1
                    except Exception:
                        skipped += 1
                else:
                    skipped += 1
        await asyncio.gather(*[ban_one(uid) for uid in batch])
        await asyncio.sleep(1)
    logger.info(f"{pyro.name}: banlanan={banned}, atlanan={skipped}")

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return

    msg  = update.message
    uid  = update.effective_user.id
    text = (msg.text or "").strip()

    if not text.startswith("/sik"):
        return

    if uid not in ALLOWED:
        return

    parts = text.split()
    if len(parts) < 2:
        await msg.reply_text("❗ İstifadə: /sik -100xxxxxxxxxx")
        return

    try:
        cid = int(parts[1])
    except ValueError:
        await msg.reply_text("❗ Qrup ID düzgün deyil!")
        return

    # Adminləri al
    admins = set()
    try:
        admins_list = await ctx.bot.get_chat_administrators(cid)
        for admin in admins_list:
            admins.add(admin.user.id)
    except Exception as e:
        logger.warning(f"Admin siyahısı alınamadı: {e}")

    # Üzv siyahısını al
    to_ban = []
    try:
        async for member in clients[0].get_chat_members(cid):
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
        logger.warning(f"Üzvlər alınamadı: {e}")
        return

    total = len(to_ban)
    await msg.reply_text(f"🚀 {total} nəfər banlanır...")

    # Siyahını 3 hissəyə böl
    chunk = (total + 2) // 3
    chunks = [
        to_ban[0*chunk:1*chunk],
        to_ban[1*chunk:2*chunk],
        to_ban[2*chunk:],
    ]

    # 3 hesab paralel işləsin
    await asyncio.gather(*[
        ban_chunk(clients[i], cid, chunks[i])
        for i in range(3)
    ])

    await msg.reply_text(f"✅ Tamamlandı! {total} nəfər banlandı.")

async def post_init(tg_app: Application):
    for c in clients:
        await c.start()
    print("Bütün Pyrogram clientlər başladı!")
    await tg_app.bot.set_my_commands([])

async def post_shutdown(tg_app: Application):
    for c in clients:
        try:
            await c.stop()
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

