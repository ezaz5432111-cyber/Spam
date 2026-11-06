import aiosqlite
from config import DB_PATH

DEFAULT_SETTINGS = {
    "bot_name": "FREE SMM",
    "bot_active": "1",
    "api_mode": "1",
    "welcome_message": "Welcome! Choose an option below.",
    "daily_bonus_active": "1",
    "daily_bonus_amount": "50",
    "daily_bonus_cooldown": "24",
    "scratch_active": "1",
    "scratch_min": "5",
    "scratch_max": "30",
    "scratch_cooldown": "12",
    "referral_active": "1",
    "referral_points": "100",
    "voucher_active": "1",
    "support_link": "https://t.me/admin",
    "coin_market_text": "Contact admin to buy coins.",
    "order_wait_msg": "Your order is processing. Please wait 10–20 minutes.",
    "maintenance_msg": "Bot is under maintenance. Please try again later.",
    "force_join_active": "1",
    "auto_post_active": "1",
    "refer_btn_active": "1",
    "my_account_btn_active": "1",
    "buy_coins_btn_active": "1",
    "bonus_btn_active": "1",
    "support_btn_active": "1"
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
 user_id INTEGER PRIMARY KEY, username TEXT DEFAULT '', first_name TEXT DEFAULT '',
 balance INTEGER DEFAULT 0, is_blocked INTEGER DEFAULT 0, referred_by INTEGER DEFAULT NULL,
 state TEXT DEFAULT NULL, state_data TEXT DEFAULT NULL, last_bonus TEXT DEFAULT NULL,
 last_scratch TEXT DEFAULT NULL, joined_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS categories (
 id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, emoji TEXT DEFAULT '📌',
 is_active INTEGER DEFAULT 1, sort_order INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS services (
 id INTEGER PRIMARY KEY AUTOINCREMENT, category_id INTEGER NOT NULL, name TEXT NOT NULL,
 description TEXT DEFAULT '', points_per_unit INTEGER DEFAULT 1, min_qty INTEGER DEFAULT 10,
 max_qty INTEGER DEFAULT 10000, api_service_id TEXT DEFAULT NULL, is_active INTEGER DEFAULT 1,
 sort_order INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS orders (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, service_id INTEGER NOT NULL,
 link TEXT NOT NULL, quantity INTEGER NOT NULL, points_spent INTEGER NOT NULL,
 api_order_id TEXT DEFAULT NULL, status TEXT DEFAULT 'processing', is_manual INTEGER DEFAULT 0,
 note TEXT DEFAULT '', created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS channels (
 id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT NOT NULL UNIQUE,
 title TEXT NOT NULL, invite_link TEXT NOT NULL, is_active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS smm_apis (
 id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, url TEXT NOT NULL,
 api_key TEXT NOT NULL, is_active INTEGER DEFAULT 1, created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS vouchers (
 id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL UNIQUE, points INTEGER NOT NULL,
 max_uses INTEGER DEFAULT 1, used_count INTEGER DEFAULT 0, is_active INTEGER DEFAULT 1,
 created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS voucher_uses (
 id INTEGER PRIMARY KEY AUTOINCREMENT, voucher_id INTEGER NOT NULL,
 user_id INTEGER NOT NULL, used_at TEXT DEFAULT (datetime('now')),
 UNIQUE(voucher_id, user_id)
);
CREATE TABLE IF NOT EXISTS referrals (
 id INTEGER PRIMARY KEY AUTOINCREMENT, referrer_id INTEGER NOT NULL,
 referred_id INTEGER NOT NULL UNIQUE, points INTEGER DEFAULT 0,
 created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS transactions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
 type TEXT NOT NULL, amount INTEGER NOT NULL, note TEXT DEFAULT '',
 created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS settings (
 key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '',
 updated_at TEXT DEFAULT (datetime('now'))
);
"""

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        for key, value in DEFAULT_SETTINGS.items():
            await db.execute(
                "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (key, value)
            )
        await db.commit()

async def fetchone(query, params=()):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query, params) as cur:
            return await cur.fetchone()

async def fetchall(query, params=()):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query, params) as cur:
            return await cur.fetchall()

async def execute(query, params=()):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(query, params) as cur:
            await db.commit()
            return cur.lastrowid

async def get_setting(key, default=""):
    row = await fetchone("SELECT value FROM settings WHERE key=?", (key,))
    return row["value"] if row else default

async def set_setting(key, value):
    await execute(
        "INSERT INTO settings(key,value,updated_at) VALUES(?,?,datetime('now')) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=datetime('now')",
        (key, str(value))
    )

async def upsert_user(user, referred_by=None):
    existing = await fetchone("SELECT user_id FROM users WHERE user_id=?", (user.id,))
    await execute(
        "INSERT INTO users(user_id,username,first_name,referred_by) VALUES(?,?,?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,first_name=excluded.first_name",
        (user.id, user.username or "", user.first_name or "", referred_by if not existing else None)
    )
    return existing is None

async def add_points(user_id, amount, tx_type="credit", note=""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, user_id))
        await db.execute(
            "INSERT INTO transactions(user_id,type,amount,note) VALUES(?,?,?,?)",
            (user_id, tx_type, amount, note)
        )
        await db.commit()

async def deduct_points(user_id, amount, note="Order"):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("BEGIN IMMEDIATE")
        async with db.execute("SELECT balance FROM users WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
        if not row or row[0] < amount:
            await db.rollback()
            return False
        await db.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (amount, user_id))
        await db.execute(
            "INSERT INTO transactions(user_id,type,amount,note) VALUES(?,?,?,?)",
            (user_id, "debit", amount, note)
        )
        await db.commit()
        return True

async def get_user(user_id):
    return await fetchone("SELECT * FROM users WHERE user_id=?", (user_id,))

async def get_categories(active_only=True):
    q = "SELECT * FROM categories" + (" WHERE is_active=1" if active_only else "") + " ORDER BY sort_order,id"
    return await fetchall(q)

async def get_services(category_id, active_only=True):
    q = "SELECT * FROM services WHERE category_id=?" + (" AND is_active=1" if active_only else "") + " ORDER BY sort_order,id"
    return await fetchall(q, (category_id,))

async def get_service(service_id):
    return await fetchone("SELECT * FROM services WHERE id=?", (service_id,))

async def create_order(user_id, service_id, link, quantity, points, is_manual, api_order_id=None):
    return await execute(
        "INSERT INTO orders(user_id,service_id,link,quantity,points_spent,is_manual,api_order_id) "
        "VALUES(?,?,?,?,?,?,?)",
        (user_id, service_id, link, quantity, points, is_manual, api_order_id)
    )

async def get_user_orders(user_id, limit=10):
    return await fetchall(
        "SELECT o.*,s.name AS service_name FROM orders o LEFT JOIN services s ON s.id=o.service_id "
        "WHERE o.user_id=? ORDER BY o.id DESC LIMIT ?", (user_id, limit)
    )

async def get_setting_keys():
    return await fetchall("SELECT key,value FROM settings ORDER BY key")

async def get_stats():
    return await fetchone(
        "SELECT (SELECT COUNT(*) FROM users) users,(SELECT COUNT(*) FROM orders) orders,"
        "(SELECT COUNT(*) FROM orders WHERE date(created_at)=date('now')) today_orders,"
        "(SELECT COUNT(*) FROM orders WHERE is_manual=1 AND status='processing') manual_pending"
    )
