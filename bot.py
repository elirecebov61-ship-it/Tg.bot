import logging
import os
import asyncio
import time
from contextlib import contextmanager
from psycopg2 import pool
from pyrogram import Client
from pyrogram.types import Message as PyroMessage
from telegram import Update, BotCommand
from telegram.ext import (
    Application, CommandHandler,
    ContextTypes
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN          = os.environ["BOT_TOKEN"]
API_ID         = int(os.environ["API_ID"])
API_HASH       = os.environ["API_HASH"]
SESSION_STRING = os.environ["STRING_SESSION"]
FOUNDER_ID     = 8034872992
DATABASE_URL   = os.environ.get("DATABASE_URL")

DEV = "\n\n🛠 Dev. @emektas"

GROUP_IDS = [
    -1003800695214,
    -1003751175874,
]

pro_users: dict[int, str] = {}

# ── DB ────────────────────────────────────────────────────────────────────
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
    if not DATABASE_URL:
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pro_users (
                    user_id TEXT PRIMARY KEY,
                    name    TEXT DEFAULT ''
                );
            """)

def load_pro_users():
    if not DATABASE_URL:
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id, name FROM pro_users")
            for r in cur.fetchall():
                pro_users[int(r[0])] = r[1] or ""
    print(f"Pro kullanıcılar yüklendi: {len(pro_users)} kişi")

def is_authorized(user_id: int) -> bool:
    return user_id == FOUNDER_ID or user_id in pro_users

# ── Pyrogram ──────────────────────────────────────────────────────────────
pyro = Client(
    "post_guard",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING
)

# ── Komutlar ──────────────────────────────────────────────────────────────
def ensure_group(func):
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type == "private":
            await update.message.reply_text("🚫 Bu komut sadece gruplarda çalışır!" + DEV)
            return
        return await func(update, ctx)
    return wrapper

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Merhaba!\n\n"
        "🗑 Ben bir *post silici botuyum*.\n\n"
        "📌 Komutlar:\n"
        "• `/sil` — Gruptaki tüm mesajları siler\n"
        "• `/sil <sayi>` — Son N mesajı siler\n"
        "• `/pro` — Kullanıcıya yetki ver _(Kurucu)_\n"
        "• `/unpro` — Kullanıcının yetkisini al _(Kurucu)_\n\n"
        "⚠️ Komutları sadece yetkili kişiler kullanabilir." + DEV,
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
    tid  = target.id
    name = target.first_name or str(tid)
    pro_users[tid] = name
    if DATABASE_URL:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO pro_users (user_id, name) VALUES (%s,%s) "
                    "ON CONFLICT (user_id) DO UPDATE SET name=%s",
                    (str(tid), name, name)
                )
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
    tid  = target.id
    name = target.first_name or str(tid)
    pro_users.pop(tid, None)
    if DATABASE_URL:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM pro_users WHERE user_id=%s", (str(tid),))
    await msg.reply_text(f"❌ *{name}* yetkisi alındı." + DEV, parse_mode="Markdown")

@ensure_group
async def cmd_sil(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("🚫 Yetkin yok!" + DEV)
        return

    cid = update.effective_chat.id

    limit = 0
    if ctx.args and len(ctx.args) > 0:
        try:
            limit = int(ctx.args[0])
            if limit <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                "❗ Kullanım: `/sil <sayi>` — Örnek: `/sil 100`" + DEV,
                parse_mode="Markdown"
            )
            return

    bildirim = await update.message.reply_text("🗑 Mesajlar siliniyor, lütfen bekleyin...")

    async def do_delete():
        silinen = 0
        batch   = []
        try:
            await pyro.get_chat(cid)
        except Exception:
            try:
                async for dialog in pyro.get_dialogs():
                    if dialog.chat.id == cid:
                        break
            except Exception:
                pass

        try:
            async for msg in pyro.get_chat_history(
                cid, limit=limit if limit > 0 else 100000
            ):
                if msg.id == bildirim.message_id:
                    continue
                batch.append(msg.id)
                if len(batch) == 100:
                    try:
                        await pyro.delete_messages(cid, batch)
                        silinen += len(batch)
                    except Exception as e:
                        print(f"Silme hatası: {e}")
                    batch = []
                    await asyncio.sleep(0.1)

            if batch:
                try:
                    await pyro.delete_messages(cid, batch)
                    silinen += len(batch)
                except Exception as e:
                    print(f"Silme hatası: {e}")

        except Exception as e:
            try:
                await bildirim.edit_text(f"❌ Hata: {e}" + DEV)
            except Exception:
                pass
            return

        try:
            await bildirim.edit_text(
                f"✅ *{silinen}* mesaj silindi!" + DEV, parse_mode="Markdown"
            )
        except Exception:
            pass

    asyncio.create_task(do_delete())

# ── post_init ─────────────────────────────────────────────────────────────
async def post_init(tg_app: Application):
    init_db()
    load_pro_users()

    await pyro.start()
    print("Pyrogram başladı!")

    print("Qruplar yüklənir...")
    for gid in GROUP_IDS:
        try:
            async for dialog in pyro.get_dialogs():
                if dialog.chat.id == gid:
                    print(f"Qrup tanındı: {dialog.chat.title}")
                    break
        except Exception as e:
            print(f"Qrup yüklənə bilmədi {gid}: {e}")

    await tg_app.bot.set_my_commands([
        BotCommand("start", "Botu başlat"),
        BotCommand("sil",   "Mesajları sil"),
        BotCommand("pro",   "Kullanıcıya yetki ver"),
        BotCommand("unpro", "Kullanıcının yetkisini al"),
    ])

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
    tg_app.add_handler(CommandHandler("start",  cmd_start))
    tg_app.add_handler(CommandHandler("sil",    cmd_sil))
    tg_app.add_handler(CommandHandler("pro",    cmd_pro))
    tg_app.add_handler(CommandHandler("unpro",  cmd_unpro))

    print("Bot başladı...")
    tg_app.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES
    )

if __name__ == "__main__":
    main()

