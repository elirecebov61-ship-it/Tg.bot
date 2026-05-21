import logging
import os
import time
from psycopg2 import pool
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

DEV = "\n\n🛠 Dev. @emektas"

cache_locked       = set()
cache_exempt       = set()
cache_pro          = set()
cache_ready        = False
cache_pro_names    = {}
cache_exempt_names = {}

db_pool = None

def get_pool():
    global db_pool
    if db_pool is None:
        for attempt in range(10):
            try:
                db_pool = pool.ThreadedConnectionPool(2, 10, DATABASE_URL)
                return db_pool
            except Exception as e:
                print(f"Pool hatası ({attempt+1}/10): {e}")
                time.sleep(3)
        raise Exception("DB pool oluşturulamadı!")
    return db_pool

from contextlib import contextmanager

@contextmanager
def get_conn():
    p = get_pool()
    conn = p.getconn()
    try:
        conn.autocommit = False
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        p.putconn(conn)

def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pro_users (
                    chat_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    name    TEXT,
                    PRIMARY KEY (chat_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS locked_chats (
                    chat_id TEXT PRIMARY KEY
                );
                CREATE TABLE IF NOT EXISTS exempt_users (
                    chat_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    name    TEXT,
                    PRIMARY KEY (chat_id, user_id)
                );
            """)
            try:
                cur.execute("ALTER TABLE pro_users ADD COLUMN IF NOT EXISTS name TEXT;")
                cur.execute("ALTER TABLE exempt_users ADD COLUMN IF NOT EXISTS name TEXT;")
            except Exception:
                pass

def load_cache():
    global cache_locked, cache_exempt, cache_pro, cache_ready
    global cache_pro_names, cache_exempt_names
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT chat_id FROM locked_chats")
            cache_locked = {r[0] for r in cur.fetchall()}

            cur.execute("SELECT chat_id, user_id, name FROM exempt_users")
            rows = cur.fetchall()
            cache_exempt = {(r[0], r[1]) for r in rows}
            cache_exempt_names = {(r[0], r[1]): r[2] if r[2] else f"ID: {r[1]}" for r in rows}

            cur.execute("SELECT chat_id, user_id, name FROM pro_users")
            rows = cur.fetchall()
            cache_pro = {(r[0], r[1]) for r in rows}
            cache_pro_names = {(r[0], r[1]): r[2] if r[2] else f"ID: {r[1]}" for r in rows}

    cache_ready = True
    print(f"Cache yüklendi: {len(cache_locked)} kilit, "
          f"{len(cache_exempt)} istisna, {len(cache_pro)} pro")

def c_is_locked(chat_id):
    return str(chat_id) in cache_locked

def c_is_exempt(chat_id, user_id):
    return (str(chat_id), str(user_id)) in cache_exempt

def c_is_pro(chat_id, user_id):
    return (str(chat_id), str(user_id)) in cache_pro

def get_name(user) -> str:
    name = user.first_name or ""
    if user.last_name:
        name += " " + user.last_name
    return name.strip() or user.username or str(user.id)

def ensure_group(func):
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type == "private":
            await update.message.reply_text("🚫 Bu komet sadece gruplarda çalışır!" + DEV)
            return
        return await func(update, ctx)
    return wrapper

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await update.message.reply_text(
            "👋 Merhaba!\n\n"
            "🔒 Ben bir *medya kilit botuyum*.\n"
            "Beni grubuna ekle ve medyaları kontrol et!\n\n"
            "📌 Komutlar:\n"
            "• `/lock` — Medya paylaşımını kapatır\n"
            "• `/unlock` — Medya paylaşımını açar\n"
            "• `/exempt` — Kişiyi istisnaya ekler\n"
            "• `/unexempt` — Kişiyi istisnadan çıkarır\n"
            "• `/list` — Yetkililer ve istisnalar listesi\n\n"
            "⚠️ Komutları sadece yetkili kişiler kullanabilir." + DEV,
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "👋 Medya kilit botu aktif.\n"
            "Yetkili kişiler `/lock` ve `/unlock` kullanabilir." + DEV,
            parse_mode="Markdown"
        )

@ensure_group
async def cmd_pro(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if update.effective_user.id != FOUNDER_ID:
        await msg.reply_text("🚫 Yetkin yok!" + DEV)
        return
    if not msg.reply_to_message:
        await msg.reply_text("❗ Kullanım: Birine yanıt verip `/pro` yaz." + DEV, parse_mode="Markdown")
        return
    target = msg.reply_to_message.from_user
    cid, tid = str(update.effective_chat.id), str(target.id)
    name = get_name(target)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO pro_users (chat_id, user_id, name) VALUES (%s,%s,%s) ON CONFLICT (chat_id, user_id) DO UPDATE SET name=%s",
                (cid, tid, name, name)
            )
    cache_pro.add((cid, tid))
    cache_pro_names[(cid, tid)] = name
    await msg.reply_text(f"✅ *{name}* yetki aldı!" + DEV, parse_mode="Markdown")

@ensure_group
async def cmd_unpro(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if update.effective_user.id != FOUNDER_ID:
        await msg.reply_text("🚫 Yetkin yok!" + DEV)
        return
    if not msg.reply_to_message:
        await msg.reply_text("❗ Kullanım: Birine yanıt verip `/unpro` yaz." + DEV, parse_mode="Markdown")
        return
    target = msg.reply_to_message.from_user
    cid, tid = str(update.effective_chat.id), str(target.id)
    name = get_name(target)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM pro_users WHERE chat_id=%s AND user_id=%s", (cid, tid))
    cache_pro.discard((cid, tid))
    cache_pro_names.pop((cid, tid), None)
    await msg.reply_text(f"❌ *{name}* yetkisi alındı." + DEV, parse_mode="Markdown")

@ensure_group
async def cmd_exempt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    uid = update.effective_user.id
    cid = str(update.effective_chat.id)
    if uid != FOUNDER_ID and not c_is_pro(cid, uid):
        await msg.reply_text("🚫 Yetkin yok!" + DEV)
        return
    if not msg.reply_to_message:
        await msg.reply_text("❗ Kullanım: Birine yanıt verip `/exempt` yaz." + DEV, parse_mode="Markdown")
        return
    target = msg.reply_to_message.from_user
    tid = str(target.id)
    name = get_name(target)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO exempt_users (chat_id, user_id, name) VALUES (%s,%s,%s) ON CONFLICT (chat_id, user_id) DO UPDATE SET name=%s",
                (cid, tid, name, name)
            )
    cache_exempt.add((cid, tid))
    cache_exempt_names[(cid, tid)] = name
    await msg.reply_text(f"✅ *{name}* istisna listesine eklendi!" + DEV, parse_mode="Markdown")

@ensure_group
async def cmd_unexempt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    uid = update.effective_user.id
    cid = str(update.effective_chat.id)
    if uid != FOUNDER_ID and not c_is_pro(cid, uid):
        await msg.reply_text("🚫 Yetkin yok!" + DEV)
        return
    if not msg.reply_to_message:
        await msg.reply_text("❗ Kullanım: Birine yanıt verip `/unexempt` yaz." + DEV, parse_mode="Markdown")
        return
    target = msg.reply_to_message.from_user
    tid = str(target.id)
    name = get_name(target)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM exempt_users WHERE chat_id=%s AND user_id=%s", (cid, tid))
    cache_exempt.discard((cid, tid))
    cache_exempt_names.pop((cid, tid), None)
    await msg.reply_text(f"❌ *{name}* istisna listesinden çıkarıldı." + DEV, parse_mode="Markdown")

@ensure_group
async def cmd_lock(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    uid = update.effective_user.id
    cid = str(update.effective_chat.id)
    if uid != FOUNDER_ID and not c_is_pro(cid, uid):
        await msg.reply_text("🚫 Yetkin yok!" + DEV)
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO locked_chats (chat_id) VALUES (%s) ON CONFLICT DO NOTHING", (cid,)
            )
    cache_locked.add(cid)
    await msg.reply_text("✅ Medya paylaşımı kapatıldı!" + DEV)

@ensure_group
async def cmd_unlock(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    uid = update.effective_user.id
    cid = str(update.effective_chat.id)
    if uid != FOUNDER_ID and not c_is_pro(cid, uid):
        await msg.reply_text("🚫 Yetkin yok!" + DEV)
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM locked_chats WHERE chat_id=%s", (cid,))
    cache_locked.discard(cid)
    await msg.reply_text("✅ Medya paylaşımı açıldı!" + DEV)

@ensure_group
async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    uid = update.effective_user.id
    cid = str(update.effective_chat.id)
    if uid != FOUNDER_ID and not c_is_pro(cid, uid):
        await msg.reply_text("🚫 Yetkin yok!" + DEV)
        return

    pro_list = [
        cache_pro_names.get((cid, uid), f"ID: {uid}")
        for (c, uid) in cache_pro if c == cid
    ]
    exempt_list = [
        cache_exempt_names.get((cid, uid), f"ID: {uid}")
        for (c, uid) in cache_exempt if c == cid
    ]

    durum = "🔒 Kapalı" if c_is_locked(cid) else "🔓 Açık"

    text  = "📋 *Grup Listesi*\n"
    text += "━━━━━━━━━━━━━━━\n"
    text += f"📡 Medya Durumu: {durum}\n\n"

    text += f"👑 *Yetkili Kullanıcılar* ({len(pro_list)} kişi)\n"
    if pro_list:
        for name in pro_list:
            text += f"  • {name}\n"
    else:
        text += "  _Henüz kimse yok_\n"

    text += f"\n🛡 *İstisna Listesi* ({len(exempt_list)} kişi)\n"
    if exempt_list:
        for name in exempt_list:
            text += f"  • {name}\n"
    else:
        text += "  _Henüz kimse yok_\n"

    text += DEV
    await msg.reply_text(text, parse_mode="Markdown")

async def delete_media(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message or update.effective_chat.type == "private":
        return
    if not cache_ready:
        return

    cid = str(update.effective_chat.id)

    # Bot olsa da olmasa da uid al
    if update.effective_user:
        uid = str(update.effective_user.id)
    else:
        uid = "bot"

    if c_is_locked(cid) and not c_is_exempt(cid, uid):
        try:
            await update.message.delete()
        except Exception as e:
            logger.warning(f"Silme hatası: {e}")

async def post_init(app: Application):
    init_db()
    load_cache()

    for (cid, uid) in list(cache_pro):
        if not cache_pro_names.get((cid, uid)) or cache_pro_names[(cid, uid)] == f"ID: {uid}":
            try:
                member = await app.bot.get_chat_member(int(cid), int(uid))
                name = get_name(member.user)
                cache_pro_names[(cid, uid)] = name
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE pro_users SET name=%s WHERE chat_id=%s AND user_id=%s",
                            (name, cid, uid)
                        )
            except Exception:
                pass

    for (cid, uid) in list(cache_exempt):
        if not cache_exempt_names.get((cid, uid)) or cache_exempt_names[(cid, uid)] == f"ID: {uid}":
            try:
                member = await app.bot.get_chat_member(int(cid), int(uid))
                name = get_name(member.user)
                cache_exempt_names[(cid, uid)] = name
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE exempt_users SET name=%s WHERE chat_id=%s AND user_id=%s",
                            (name, cid, uid)
                        )
            except Exception:
                pass

    await app.bot.set_my_commands([
        BotCommand("start",    "Botu başlat"),
        BotCommand("lock",     "Medya paylaşımını kapat"),
        BotCommand("unlock",   "Medya paylaşımını aç"),
        BotCommand("pro",      "Kullanıcıya yetki ver"),
        BotCommand("unpro",    "Kullanıcının yetkisini al"),
        BotCommand("exempt",   "Kişiyi istisnaya ekle"),
        BotCommand("unexempt", "Kişiyi istisnadan çıkar"),
        BotCommand("list",     "Yetkililer ve istisnalar listesi"),
    ])

def main():
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("pro",      cmd_pro))
    app.add_handler(CommandHandler("unpro",    cmd_unpro))
    app.add_handler(CommandHandler("lock",     cmd_lock))
    app.add_handler(CommandHandler("unlock",   cmd_unlock))
    app.add_handler(CommandHandler("exempt",   cmd_exempt))
    app.add_handler(CommandHandler("unexempt", cmd_unexempt))
    app.add_handler(CommandHandler("list",     cmd_list))

    media_filter = (
        filters.PHOTO | filters.VIDEO | filters.Document.ALL |
        filters.AUDIO | filters.VOICE | filters.VIDEO_NOTE |
        filters.Sticker.ALL | filters.ANIMATION
    )
    app.add_handler(MessageHandler(media_filter, delete_media))

    print("Bot başladı...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
