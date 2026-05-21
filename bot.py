import logging
import os
import time
from contextlib import contextmanager
from psycopg2 import pool
from pyrogram import Client, filters
from pyrogram.types import Message

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_ID         = int(os.environ["API_ID"])
API_HASH       = os.environ["API_HASH"]
STRING_SESSION = os.environ["STRING_SESSION"]
FOUNDER_ID     = 8034872992

DATABASE_URL = os.environ["DATABASE_URL"]

DEV = "\n\n🛠 Dev. @emektas"

cache_locked       = set()
cache_exempt       = set()
cache_pro          = set()
cache_ready        = False
cache_pro_names    = {}
cache_exempt_names = {}

# ── DB Pool ───────────────────────────────────────────────────────────────
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
            cache_exempt_names = {
                (r[0], r[1]): r[2] if r[2] else f"ID: {r[1]}" for r in rows
            }

            cur.execute("SELECT chat_id, user_id, name FROM pro_users")
            rows = cur.fetchall()
            cache_pro = {(r[0], r[1]) for r in rows}
            cache_pro_names = {
                (r[0], r[1]): r[2] if r[2] else f"ID: {r[1]}" for r in rows
            }

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

# ── Pyrogram client ───────────────────────────────────────────────────────
app = Client(
    "media_guard",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=STRING_SESSION
)

# ── Medya filter ──────────────────────────────────────────────────────────
media_filter = (
    filters.photo
    | filters.video
    | filters.document
    | filters.audio
    | filters.voice
    | filters.video_note
    | filters.sticker
    | filters.animation
)

# ── Medya sil ─────────────────────────────────────────────────────────────
@app.on_message(filters.group & media_filter)
async def delete_media(client: Client, message: Message):
    if not cache_ready:
        return

    cid = str(message.chat.id)

    if not c_is_locked(cid):
        return

    # Göndərənin ID-sini tap
    uid = None
    if message.from_user:
        uid = str(message.from_user.id)
    elif message.sender_chat:
        uid = f"chat_{message.sender_chat.id}"

    # İstisnadakıları keç
    if uid and c_is_exempt(cid, uid):
        return

    # Sil — Pyrogram user account olduğu üçün admin botları da silinir
    try:
        await message.delete()
    except Exception as e:
        logger.warning(f"Silme hatası: {e}")

# ── /lock ─────────────────────────────────────────────────────────────────
@app.on_message(filters.group & filters.command("lock"))
async def cmd_lock(client: Client, message: Message):
    uid = message.from_user.id if message.from_user else None
    cid = str(message.chat.id)
    if uid != FOUNDER_ID and not c_is_pro(cid, uid):
        await message.reply("🚫 Yetkin yok!" + DEV)
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO locked_chats (chat_id) VALUES (%s) ON CONFLICT DO NOTHING", (cid,)
            )
    cache_locked.add(cid)
    await message.reply("✅ Medya paylaşımı kapatıldı!" + DEV)

# ── /unlock ───────────────────────────────────────────────────────────────
@app.on_message(filters.group & filters.command("unlock"))
async def cmd_unlock(client: Client, message: Message):
    uid = message.from_user.id if message.from_user else None
    cid = str(message.chat.id)
    if uid != FOUNDER_ID and not c_is_pro(cid, uid):
        await message.reply("🚫 Yetkin yok!" + DEV)
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM locked_chats WHERE chat_id=%s", (cid,))
    cache_locked.discard(cid)
    await message.reply("✅ Medya paylaşımı açıldı!" + DEV)

# ── /pro ──────────────────────────────────────────────────────────────────
@app.on_message(filters.group & filters.command("pro"))
async def cmd_pro(client: Client, message: Message):
    uid = message.from_user.id if message.from_user else None
    if uid != FOUNDER_ID:
        await message.reply("🚫 Yetkin yok!" + DEV)
        return
    if not message.reply_to_message:
        await message.reply("❗ Kullanım: Birine yanıt verip `/pro` yaz." + DEV)
        return
    target = message.reply_to_message.from_user
    cid    = str(message.chat.id)
    tid    = str(target.id)
    name   = get_name(target)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO pro_users (chat_id, user_id, name) VALUES (%s,%s,%s) "
                "ON CONFLICT (chat_id, user_id) DO UPDATE SET name=%s",
                (cid, tid, name, name)
            )
    cache_pro.add((cid, tid))
    cache_pro_names[(cid, tid)] = name
    await message.reply(f"✅ **{name}** yetki aldı!" + DEV)

# ── /unpro ────────────────────────────────────────────────────────────────
@app.on_message(filters.group & filters.command("unpro"))
async def cmd_unpro(client: Client, message: Message):
    uid = message.from_user.id if message.from_user else None
    if uid != FOUNDER_ID:
        await message.reply("🚫 Yetkin yok!" + DEV)
        return
    if not message.reply_to_message:
        await message.reply("❗ Kullanım: Birine yanıt verip `/unpro` yaz." + DEV)
        return
    target = message.reply_to_message.from_user
    cid    = str(message.chat.id)
    tid    = str(target.id)
    name   = get_name(target)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM pro_users WHERE chat_id=%s AND user_id=%s", (cid, tid))
    cache_pro.discard((cid, tid))
    cache_pro_names.pop((cid, tid), None)
    await message.reply(f"❌ **{name}** yetkisi alındı." + DEV)

# ── /exempt ───────────────────────────────────────────────────────────────
@app.on_message(filters.group & filters.command("exempt"))
async def cmd_exempt(client: Client, message: Message):
    uid = message.from_user.id if message.from_user else None
    cid = str(message.chat.id)
    if uid != FOUNDER_ID and not c_is_pro(cid, uid):
        await message.reply("🚫 Yetkin yok!" + DEV)
        return
    if not message.reply_to_message:
        await message.reply("❗ Kullanım: Birine yanıt verip `/exempt` yaz." + DEV)
        return
    target = message.reply_to_message.from_user
    tid    = str(target.id)
    name   = get_name(target)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO exempt_users (chat_id, user_id, name) VALUES (%s,%s,%s) "
                "ON CONFLICT (chat_id, user_id) DO UPDATE SET name=%s",
                (cid, tid, name, name)
            )
    cache_exempt.add((cid, tid))
    cache_exempt_names[(cid, tid)] = name
    await message.reply(f"✅ **{name}** istisna listesine eklendi!" + DEV)

# ── /unexempt ─────────────────────────────────────────────────────────────
@app.on_message(filters.group & filters.command("unexempt"))
async def cmd_unexempt(client: Client, message: Message):
    uid = message.from_user.id if message.from_user else None
    cid = str(message.chat.id)
    if uid != FOUNDER_ID and not c_is_pro(cid, uid):
        await message.reply("🚫 Yetkin yok!" + DEV)
        return
    if not message.reply_to_message:
        await message.reply("❗ Kullanım: Birine yanıt verip `/unexempt` yaz." + DEV)
        return
    target = message.reply_to_message.from_user
    tid    = str(target.id)
    name   = get_name(target)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM exempt_users WHERE chat_id=%s AND user_id=%s", (cid, tid)
            )
    cache_exempt.discard((cid, tid))
    cache_exempt_names.pop((cid, tid), None)
    await message.reply(f"❌ **{name}** istisna listesinden çıkarıldı." + DEV)

# ── /list ─────────────────────────────────────────────────────────────────
@app.on_message(filters.group & filters.command("list"))
async def cmd_list(client: Client, message: Message):
    uid = message.from_user.id if message.from_user else None
    cid = str(message.chat.id)
    if uid != FOUNDER_ID and not c_is_pro(cid, uid):
        await message.reply("🚫 Yetkin yok!" + DEV)
        return

    pro_list = [
        cache_pro_names.get((cid, u), f"ID: {u}")
        for (c, u) in cache_pro if c == cid
    ]
    exempt_list = [
        cache_exempt_names.get((cid, u), f"ID: {u}")
        for (c, u) in cache_exempt if c == cid
    ]

    durum = "🔒 Kapalı" if c_is_locked(cid) else "🔓 Açık"

    text  = "📋 **Grup Listesi**\n"
    text += "━━━━━━━━━━━━━━━\n"
    text += f"📡 Medya Durumu: {durum}\n\n"
    text += f"👑 **Yetkili Kullanıcılar** ({len(pro_list)} kişi)\n"
    if pro_list:
        for name in pro_list:
            text += f"  • {name}\n"
    else:
        text += "  _Henüz kimse yok_\n"
    text += f"\n🛡 **İstisna Listesi** ({len(exempt_list)} kişi)\n"
    if exempt_list:
        for name in exempt_list:
            text += f"  • {name}\n"
    else:
        text += "  _Henüz kimse yok_\n"
    text += DEV
    await message.reply(text)

# ── Başlat ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    load_cache()
    print("Bot başladı...")
    app.run()
