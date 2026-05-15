import logging
import os
import asyncio
import time
import psycopg2
import psycopg2.extras
from telegram import Update, BotCommand
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN        = os.environ["BOT_TOKEN"]
FOUNDER_ID   = 8034872992
DATABASE_URL = os.environ["DATABASE_URL"]

_db_lock = asyncio.Lock()

DEV = "\n\n🛠 Dev. @emektas"

def get_conn():
    for attempt in range(10):
        try:
            conn = psycopg2.connect(DATABASE_URL)
            conn.autocommit = False
            return conn
        except Exception as e:
            print(f"DB bağlantı xətası (cəhd {attempt+1}/10): {e}")
            time.sleep(3)
    raise Exception("DB-yə qoşulmaq mümkün olmadı!")

def init_db():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pro_users (
                chat_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                PRIMARY KEY (chat_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS locked_chats (
                chat_id TEXT PRIMARY KEY
            );
            CREATE TABLE IF NOT EXISTS exempt_users (
                chat_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                PRIMARY KEY (chat_id, user_id)
            );
        """)
        conn.commit()
        cur.close()
    finally:
        conn.close()

def is_pro(cur, chat_id, user_id):
    cur.execute(
        "SELECT 1 FROM pro_users WHERE chat_id=%s AND user_id=%s",
        (str(chat_id), str(user_id))
    )
    return cur.fetchone() is not None

def is_locked(cur, chat_id):
    cur.execute("SELECT 1 FROM locked_chats WHERE chat_id=%s", (str(chat_id),))
    return cur.fetchone() is not None

def is_exempt(cur, chat_id, user_id):
    cur.execute(
        "SELECT 1 FROM exempt_users WHERE chat_id=%s AND user_id=%s",
        (str(chat_id), str(user_id))
    )
    return cur.fetchone() is not None

def get_name(user) -> str:
    name = user.first_name or ""
    if user.last_name:
        name += " " + user.last_name
    return name.strip() or user.username or str(user.id)

def ensure_group(func):
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type == "private":
            await update.message.reply_text("🚫 Bu komut sadece gruplarda çalışır!" + DEV)
            return
        return await func(update, ctx)
    return wrapper

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await update.message.reply_text(
            "👋 Merhaba!\n\n"
            "🔒 Ben bir *medya kilit botuyum*.\n"
            "Beni grubuna ekle ve medyaları kontrol et!\n\n"
            "📌 Beni grubuna ekledikten sonra:\n"
            "• `/lock` — Medya paylaşımını kapatır\n"
            "• `/unlock` — Medya paylaşımını açar\n"
            "• `/exempt` — Kişiyi istisnaya ekler\n"
            "• `/unexempt` — Kişiyi istisnadan çıkarır\n\n"
            "⚠️ Bu komutları sadece yetkili kişiler kullanabilir."
            + DEV,
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "👋 Merhaba! Medya kilit botu aktif.\n"
            "Yetkili kişiler `/lock` ve `/unlock` komutlarını kullanabilir."
            + DEV,
            parse_mode="Markdown"
        )

@ensure_group
async def cmd_pro(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if update.effective_user.id != FOUNDER_ID:
        await msg.reply_text("🚫 Yetkin yok" + DEV)
        return
    if not msg.reply_to_message:
        await msg.reply_text("❗ Kullanım: Birine yanıt verip `/pro` yaz." + DEV, parse_mode="Markdown")
        return
    target      = msg.reply_to_message.from_user
    cid         = str(update.effective_chat.id)
    tid         = str(target.id)
    target_name = get_name(target)
    async with _db_lock:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO pro_users (chat_id, user_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                    (cid, tid)
                )
            conn.commit()
        finally:
            conn.close()
    await msg.reply_text(
        f"✅ *{target_name}* bu grupta `/lock` ve `/unlock` yetkisi aldı!" + DEV,
        parse_mode="Markdown"
    )

@ensure_group
async def cmd_unpro(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if update.effective_user.id != FOUNDER_ID:
        await msg.reply_text("🚫 Yetkin yok" + DEV)
        return
    if not msg.reply_to_message:
        await msg.reply_text("❗ Kullanım: Birine yanıt verip `/unpro` yaz." + DEV, parse_mode="Markdown")
        return
    target      = msg.reply_to_message.from_user
    cid         = str(update.effective_chat.id)
    tid         = str(target.id)
    target_name = get_name(target)
    async with _db_lock:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM pro_users WHERE chat_id=%s AND user_id=%s",
                    (cid, tid)
                )
            conn.commit()
        finally:
            conn.close()
    await msg.reply_text(
        f"❌ *{target_name}* yetkisi alındı." + DEV,
        parse_mode="Markdown"
    )

@ensure_group
async def cmd_exempt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    uid = update.effective_user.id
    cid = str(update.effective_chat.id)
    async with _db_lock:
        conn = get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if uid != FOUNDER_ID and not is_pro(cur, cid, uid):
                    await msg.reply_text("🚫 Yetkin yok" + DEV)
                    return
        finally:
            conn.close()
    if not msg.reply_to_message:
        await msg.reply_text("❗ Kullanım: Birine yanıt verip `/exempt` yaz." + DEV, parse_mode="Markdown")
        return
    target      = msg.reply_to_message.from_user
    tid         = str(target.id)
    target_name = get_name(target)
    async with _db_lock:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO exempt_users (chat_id, user_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                    (cid, tid)
                )
            conn.commit()
        finally:
            conn.close()
    await msg.reply_text(
        f"✅ *{target_name}* istisna listesine eklendi. Medyaları silinmeyecek!" + DEV,
        parse_mode="Markdown"
    )

@ensure_group
async def cmd_unexempt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    uid = update.effective_user.id
    cid = str(update.effective_chat.id)
    async with _db_lock:
        conn = get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if uid != FOUNDER_ID and not is_pro(cur, cid, uid):
                    await msg.reply_text("🚫 Yetkin yok" + DEV)
                    return
        finally:
            conn.close()
    if not msg.reply_to_message:
        await msg.reply_text("❗ Kullanım: Birine yanıt verip `/unexempt` yaz." + DEV, parse_mode="Markdown")
        return
    target      = msg.reply_to_message.from_user
    tid         = str(target.id)
    target_name = get_name(target)
    async with _db_lock:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM exempt_users WHERE chat_id=%s AND user_id=%s",
                    (cid, tid)
                )
            conn.commit()
        finally:
            conn.close()
    await msg.reply_text(
        f"❌ *{target_name}* istisna listesinden çıkarıldı." + DEV,
        parse_mode="Markdown"
    )

@ensure_group
async def cmd_lock(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    uid = update.effective_user.id
    cid = str(update.effective_chat.id)
    async with _db_lock:
        conn = get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if uid != FOUNDER_ID and not is_pro(cur, cid, uid):
                    await msg.reply_text("🚫 Yetkin yok" + DEV)
                    return
                cur.execute(
                    "INSERT INTO locked_chats (chat_id) VALUES (%s) ON CONFLICT DO NOTHING",
                    (cid,)
                )
            conn.commit()
        finally:
            conn.close()
    await msg.reply_text("✅ Medya kapandı" + DEV)

@ensure_group
async def cmd_unlock(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    uid = update.effective_user.id
    cid = str(update.effective_chat.id)
    async with _db_lock:
        conn = get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if uid != FOUNDER_ID and not is_pro(cur, cid, uid):
                    await msg.reply_text("🚫 Yetkin yok" + DEV)
                    return
                cur.execute(
                    "DELETE FROM locked_chats WHERE chat_id=%s",
                    (cid,)
                )
            conn.commit()
        finally:
            conn.close()
    await msg.reply_text("✅ Medya açıldı" + DEV)

async def delete_media(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message or update.effective_chat.type == "private":
        return
    cid = str(update.effective_chat.id)
    uid = str(update.effective_user.id)
    async with _db_lock:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                locked  = is_locked(cur, cid)
                exempted = is_exempt(cur, cid, uid)
        finally:
            conn.close()
    if locked and not exempted:
        try:
            await update.message.delete()
        except Exception as e:
            logger.warning(f"Medya silinemedi: {e}")

async def post_init(app: Application):
    init_db()
    commands = [
        BotCommand("start",    "Botu başlat"),
        BotCommand("lock",     "Medya paylaşımını kapat"),
        BotCommand("unlock",   "Medya paylaşımını aç"),
        BotCommand("pro",      "Kullanıcıya yetki ver"),
        BotCommand("unpro",    "Kullanıcının yetkisini al"),
        BotCommand("exempt",   "Kişiyi istisnaya ekle"),
        BotCommand("unexempt", "Kişiyi istisnadan çıkar"),
    ]
    await app.bot.set_my_commands(commands)

def main():
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("pro",      cmd_pro))
    app.add_handler(CommandHandler("unpro",    cmd_unpro))
    app.add_handler(CommandHandler("lock",     cmd_lock))
    app.add_handler(CommandHandler("unlock",   cmd_unlock))
    app.add_handler(CommandHandler("exempt",   cmd_exempt))
    app.add_handler(CommandHandler("unexempt", cmd_unexempt))

    media_filter = (
        filters.PHOTO |
        filters.VIDEO |
        filters.Document.ALL |
        filters.AUDIO |
        filters.VOICE |
        filters.VIDEO_NOTE |
        filters.Sticker.ALL |
        filters.ANIMATION
    )
    app.add_handler(MessageHandler(media_filter, delete_media))

    print("Bot başladı...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
