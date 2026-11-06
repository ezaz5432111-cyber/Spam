import json
import random
from datetime import datetime, timedelta, timezone
from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.constants import ParseMode
from telegram.ext import (
    ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters
)
import database as db
from smm_api import SMMApi
from config import ADMIN_ID

ORDER_LINK, ORDER_QTY, VOUCHER_INPUT, ADMIN_INPUT, ADMIN_BROADCAST = range(5)
api = SMMApi()

MAIN_BUTTONS = [
    ["💬 TELEGRAM", "🎵 TIKTOK"],
    ["🎟️ REFER"],
    ["👤 MY ACCOUNT", "💳 BUY COINS"],
    ["🎁 BONUS", "🛠 SUPPORT"]
]

def is_admin(user_id):
    return user_id == ADMIN_ID

async def main_keyboard():
    rows = [
        [KeyboardButton("💬 TELEGRAM"), KeyboardButton("🎵 TIKTOK")],
        [KeyboardButton("🎟️ REFER")],
        [KeyboardButton("👤 MY ACCOUNT"), KeyboardButton("💳 BUY COINS")],
        [KeyboardButton("🎁 BONUS"), KeyboardButton("🛠 SUPPORT")]
    ]
    for key, label, row_index, col_index in [
        ("refer_btn_active", "🎟️ REFER", 2, 0),
        ("my_account_btn_active", "👤 MY ACCOUNT", 3, 0),
        ("buy_coins_btn_active", "💳 BUY COINS", 3, 1),
        ("bonus_btn_active", "🎁 BONUS", 4, 0),
        ("support_btn_active", "🛠 SUPPORT", 4, 1)
    ]:
        if await db.get_setting(key, "1") != "1":
            if col_index < len(rows[row_index-1]):
                rows[row_index-1][col_index] = None
    rows = [[b for b in row if b] for row in rows]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

async def force_join_ok(context, user_id):
    if await db.get_setting("force_join_active", "1") != "1":
        return True
    channels = await db.fetchall("SELECT * FROM channels WHERE is_active=1")
    for channel in channels:
        try:
            member = await context.bot.get_chat_member(channel["chat_id"], user_id)
            if member.status in ("left", "kicked"):
                return False
        except Exception:
            return False
    return True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    referrer = None
    if context.args and context.args[0].startswith("Bot"):
        try:
            referrer = int(context.args[0][3:])
            if referrer == user.id:
                referrer = None
        except ValueError:
            referrer = None
    is_new = await db.upsert_user(user, referrer)
    if is_new and referrer:
        if await db.get_setting("referral_active", "1") == "1":
            points = int(await db.get_setting("referral_points", "100"))
            await db.add_points(referrer, points, "referral", f"Referral {user.id}")
            await db.execute(
                "INSERT OR IGNORE INTO referrals(referrer_id,referred_id,points) VALUES(?,?,?)",
                (referrer, user.id, points)
            )
    if not await force_join_ok(context, user.id):
        channels = await db.fetchall("SELECT title,invite_link FROM channels WHERE is_active=1")
        buttons = [[InlineKeyboardButton(c["title"], url=c["invite_link"])] for c in channels]
        buttons.append([InlineKeyboardButton("🔄 Joined - Check Again", callback_data="check_join")])
        await update.message.reply_text(
            "Please join the required channel(s) first.",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return
    if await db.get_setting("bot_active", "1") != "1" and not is_admin(user.id):
        await update.message.reply_text(await db.get_setting("maintenance_msg"))
        return
    await update.message.reply_text(
        await db.get_setting("welcome_message"), reply_markup=await main_keyboard()
    )

async def check_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if await force_join_ok(context, query.from_user.id):
        await query.edit_message_text("Membership verified. Send /start.")
    else:
        await query.answer("Please join all required channels.", show_alert=True)

async def category_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    category_name = "TELEGRAM" if "TELEGRAM" in update.message.text else "TIKTOK"
    cats = await db.get_categories()
    matched = [c for c in cats if category_name.lower() in c["name"].lower()]
    if not matched:
        await update.message.reply_text("No active category is configured yet.")
        return
    buttons = []
    for cat in matched:
        buttons.append([InlineKeyboardButton(
            f'{cat["emoji"]} {cat["name"]}', callback_data=f'cat:{cat["id"]}'
        )])
    await update.message.reply_text("Choose a category:", reply_markup=InlineKeyboardMarkup(buttons))

async def show_services(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category_id = int(query.data.split(":")[1])
    services = await db.get_services(category_id)
    if not services:
        await query.edit_message_text("No active services in this category.")
        return
    buttons = [[InlineKeyboardButton(
        f'{s["name"]} · {s["points_per_unit"]} pts/unit',
        callback_data=f'service:{s["id"]}'
    )] for s in services]
    await query.edit_message_text("Select a service:", reply_markup=InlineKeyboardMarkup(buttons))

async def choose_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    service_id = int(query.data.split(":")[1])
    service = await db.get_service(service_id)
    if not service or not service["is_active"]:
        await query.edit_message_text("This service is unavailable.")
        return ConversationHandler.END
    context.user_data["service_id"] = service_id
    await query.message.reply_text(
        f'Enter the target URL for <b>{service["name"]}</b>.',
        parse_mode=ParseMode.HTML
    )
    return ORDER_LINK

async def order_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    if not link.startswith(("http://", "https://")):
        await update.message.reply_text("Please enter a valid URL starting with http:// or https://.")
        return ORDER_LINK
    context.user_data["order_link"] = link
    await update.message.reply_text("Enter quantity:")
    return ORDER_QTY

async def order_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        quantity = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Quantity must be a whole number.")
        return ORDER_QTY
    service = await db.get_service(context.user_data["service_id"])
    if not service or quantity < service["min_qty"] or quantity > service["max_qty"]:
        await update.message.reply_text(
            f'Quantity must be between {service["min_qty"]} and {service["max_qty"]}.'
        )
        return ORDER_QTY
    cost = quantity * service["points_per_unit"]
    user = await db.get_user(update.effective_user.id)
    if not user or user["balance"] < cost:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("💳 BUY COINS", callback_data="buy_coins")]])
        await update.message.reply_text("Insufficient balance.", reply_markup=kb)
        return ConversationHandler.END
    if not await db.deduct_points(update.effective_user.id, cost):
        await update.message.reply_text("Balance changed; please try again.")
        return ConversationHandler.END
    api_mode = await db.get_setting("api_mode", "1") == "1"
    api_order_id = None
    manual = 0
    if api_mode and service["api_service_id"]:
        api_order_id = await api.add_order(
            service["api_service_id"], context.user_data["order_link"], quantity
        )
        if not api_order_id:
            await db.add_points(update.effective_user.id, cost, "refund", "API order failed")
            await update.message.reply_text("❌ Provider error. Your points have been refunded.")
            return ConversationHandler.END
    else:
        manual = 1
    order_id = await db.create_order(
        update.effective_user.id, service["id"], context.user_data["order_link"],
        quantity, cost, manual, api_order_id
    )
    await update.message.reply_text(
        f'📦 Order <code>#{order_id}</code>\n{await db.get_setting("order_wait_msg")}',
        parse_mode=ParseMode.HTML
    )
    if manual:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Done", callback_data=f"manual:{order_id}:done"),
            InlineKeyboardButton("❌ Reject", callback_data=f"manual:{order_id}:reject")
        ]])
        try:
            await context.bot.send_message(
                ADMIN_ID, f"Manual order #{order_id}\nUser: {update.effective_user.id}\n"
                f"Service: {service['name']}\nQuantity: {quantity}\n{context.user_data['order_link']}",
                reply_markup=keyboard
            )
        except Exception:
            pass
    return ConversationHandler.END

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.", reply_markup=await main_keyboard())
    return ConversationHandler.END

async def bonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await db.get_user(user_id)
    if await db.get_setting("daily_bonus_active", "1") == "1":
        cooldown = int(await db.get_setting("daily_bonus_cooldown", "24"))
        if user["last_bonus"]:
            last = datetime.fromisoformat(user["last_bonus"]).replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - last < timedelta(hours=cooldown):
                await update.message.reply_text("⏳ Daily bonus is not ready yet.")
                return
        amount = int(await db.get_setting("daily_bonus_amount", "50"))
        await db.add_points(user_id, amount, "bonus", "Daily bonus")
        await db.execute("UPDATE users SET last_bonus=datetime('now') WHERE user_id=?", (user_id,))
        await update.message.reply_text(f"✅ You received {amount} points.")
    else:
        await update.message.reply_text("Daily bonus is disabled.")

async def scratch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await db.get_user(user_id)
    if await db.get_setting("scratch_active", "1") != "1":
        await update.message.reply_text("Scratch card is disabled.")
        return
    cooldown = int(await db.get_setting("scratch_cooldown", "12"))
    if user["last_scratch"]:
        last = datetime.fromisoformat(user["last_scratch"]).replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - last < timedelta(hours=cooldown):
            await update.message.reply_text("⏳ Scratch card is not ready yet.")
            return
    low = int(await db.get_setting("scratch_min", "5"))
    high = int(await db.get_setting("scratch_max", "30"))
    amount = random.randint(min(low, high), max(low, high))
    await db.add_points(user_id, amount, "scratch", "Scratch card")
    await db.execute("UPDATE users SET last_scratch=datetime('now') WHERE user_id=?", (user_id,))
    await update.message.reply_text(f"🎁 You won {amount} points!")

async def voucher_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send your voucher code:")
    return VOUCHER_INPUT

async def voucher_redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await db.get_setting("voucher_active", "1") != "1":
        await update.message.reply_text("Voucher redemption is disabled.")
        return ConversationHandler.END
    code = update.message.text.strip().upper()
    voucher = await db.fetchone(
        "SELECT * FROM vouchers WHERE code=? AND is_active=1", (code,)
    )
    if not voucher or voucher["used_count"] >= voucher["max_uses"]:
        await update.message.reply_text("Invalid or exhausted voucher.")
        return ConversationHandler.END
    try:
        await db.execute(
            "INSERT INTO voucher_uses(voucher_id,user_id) VALUES(?,?)",
            (voucher["id"], update.effective_user.id)
        )
    except Exception:
        await update.message.reply_text("You have already used this voucher.")
        return ConversationHandler.END
    await db.execute("UPDATE vouchers SET used_count=used_count+1 WHERE id=?", (voucher["id"],))
    await db.add_points(update.effective_user.id, voucher["points"], "voucher", code)
    await update.message.reply_text(f'✅ {voucher["points"]} points added.')
    return ConversationHandler.END

async def account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await db.get_user(user_id)
    orders = await db.fetchone("SELECT COUNT(*) n FROM orders WHERE user_id=?", (user_id,))
    refs = await db.fetchone("SELECT COUNT(*) n FROM referrals WHERE referrer_id=?", (user_id,))
    text = (
        f"<b>👤 MY ACCOUNT</b>\n══════════════════\n"
        f"ID: <code>{user_id}</code>\nBalance: 💰 {user['balance']}\n"
        f"Orders: {orders['n']}\nReferrals: {refs['n']}\nJoined: {user['joined_at']}"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 My Orders", callback_data="my_orders")],
        [InlineKeyboardButton("🎟️ Redeem Voucher", callback_data="redeem")]
    ])
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

async def my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    orders = await db.get_user_orders(query.from_user.id)
    if not orders:
        await query.edit_message_text("No orders found.")
        return
    lines = ["<b>📦 MY LAST 10 ORDERS</b>"]
    for order in orders:
        icon = "✅" if order["status"] == "completed" else "❌" if order["status"] == "rejected" else "⏳"
        lines.append(
            f"{icon} #{order['id']} · {order['service_name'] or 'Service'} · "
            f"{order['quantity']} · {order['points_spent']} pts"
        )
    await query.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML)

async def buy_coins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = await db.get_setting("coin_market_text")
    link = await db.get_setting("support_link")
    await update.effective_message.reply_text(
        message, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Contact support", url=link)]])
    )

async def refer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot = await context.bot.get_me()
    points = await db.get_setting("referral_points", "100")
    await update.message.reply_text(
        f"Invite friends using:\nhttps://t.me/{bot.username}?start=Bot{update.effective_user.id}\n"
        f"Reward: {points} points per new user."
    )

async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = await db.get_setting("support_link")
    await update.message.reply_text("Contact support:", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("🛠 Support", url=link)]
    ]))

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    stats = await db.get_stats()
    text = (
        "<b>🛡️ ADMIN PANEL</b>\n══════════════════\n"
        f"Users: {stats['users']}\nOrders: {stats['orders']}\n"
        f"Today orders: {stats['today_orders']}\nManual pending: {stats['manual_pending']}\n"
        f"Bot: {'ON' if await db.get_setting('bot_active') == '1' else 'OFF'}\n"
        f"API mode: {'AUTO' if await db.get_setting('api_mode') == '1' else 'MANUAL'}"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Toggle Bot", callback_data="adm:bot"),
         InlineKeyboardButton("Toggle API", callback_data="adm:api")],
        [InlineKeyboardButton("Categories", callback_data="adm:categories"),
         InlineKeyboardButton("Services", callback_data="adm:services")],
        [InlineKeyboardButton("Manual orders", callback_data="adm:manual")],
        [InlineKeyboardButton("Vouchers", callback_data="adm:vouchers"),
         InlineKeyboardButton("Settings", callback_data="adm:settings")],
        [InlineKeyboardButton("Broadcast", callback_data="adm:broadcast")]
    ])
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

async def admin_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    action = query.data
    if action == "adm:bot":
        value = "0" if await db.get_setting("bot_active") == "1" else "1"
        await db.set_setting("bot_active", value)
        await query.edit_message_text(f"Bot is now {'ON' if value == '1' else 'OFF'}. Use /admin.")
    elif action == "adm:api":
        value = "0" if await db.get_setting("api_mode") == "1" else "1"
        await db.set_setting("api_mode", value)
        await query.edit_message_text(f"API mode is now {'AUTO' if value == '1' else 'MANUAL'}. Use /admin.")
    elif action == "adm:categories":
        cats = await db.get_categories(False)
        buttons = [[InlineKeyboardButton(
            f'{"✅" if c["is_active"] else "❌"} {c["name"]} · toggle',
            callback_data=f"cat_toggle:{c['id']}"
        )] for c in cats]
        buttons.append([InlineKeyboardButton("➕ Add category", callback_data="adm:addcat")])
        await query.edit_message_text("Categories:", reply_markup=InlineKeyboardMarkup(buttons))
    elif action == "adm:services":
        cats = await db.get_categories(False)
        buttons = [[InlineKeyboardButton(c["name"], callback_data=f"svc_cat:{c['id']}")] for c in cats]
        await query.edit_message_text("Select category:", reply_markup=InlineKeyboardMarkup(buttons))
    elif action == "adm:manual":
        rows = await db.fetchall(
            "SELECT * FROM orders WHERE is_manual=1 AND status='processing' ORDER BY id DESC LIMIT 20"
        )
        buttons = [[InlineKeyboardButton(
            f"Order #{r['id']} · user {r['user_id']}",
            callback_data=f"manual_view:{r['id']}"
        )] for r in rows]
        await query.edit_message_text("Pending manual orders:", reply_markup=InlineKeyboardMarkup(buttons))
    elif action == "adm:vouchers":
        rows = await db.fetchall("SELECT * FROM vouchers ORDER BY id DESC LIMIT 20")
        lines = [f"{r['code']} · {r['points']} pts · {r['used_count']}/{r['max_uses']}" for r in rows]
        buttons = [[InlineKeyboardButton("➕ Create voucher", callback_data="adm:addvoucher")]]
        await query.edit_message_text("\n".join(lines) or "No vouchers.", reply_markup=InlineKeyboardMarkup(buttons))
    elif action == "adm:settings":
        rows = await db.get_setting_keys()
        buttons = [[InlineKeyboardButton(r["key"], callback_data=f"setting:{r['key']}")] for r in rows]
        await query.edit_message_text("Choose a setting to edit:", reply_markup=InlineKeyboardMarkup(buttons))
    elif action == "adm:broadcast":
        context.user_data["admin_action"] = "broadcast"
        await query.message.reply_text("Send the broadcast message, or /cancel.")
        return ADMIN_BROADCAST

async def admin_toggle_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    cid = int(query.data.split(":")[1])
    row = await db.fetchone("SELECT is_active FROM categories WHERE id=?", (cid,))
    await db.execute("UPDATE categories SET is_active=? WHERE id=?", (0 if row["is_active"] else 1, cid))
    await query.edit_message_text("Category updated. Use /admin.")

async def admin_category_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    cid = int(query.data.split(":")[1])
    rows = await db.get_services(cid, False)
    buttons = [[InlineKeyboardButton(
        f'{"✅" if r["is_active"] else "❌"} {r["name"]} · toggle',
        callback_data=f"svc_toggle:{r['id']}"
    )] for r in rows]
    buttons.append([InlineKeyboardButton("➕ Add service", callback_data=f"svc_add:{cid}")])
    await query.edit_message_text("Services:", reply_markup=InlineKeyboardMarkup(buttons))

async def admin_toggle_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    sid = int(query.data.split(":")[1])
    row = await db.fetchone("SELECT is_active FROM services WHERE id=?", (sid,))
    await db.execute("UPDATE services SET is_active=? WHERE id=?", (0 if row["is_active"] else 1, sid))
    await query.edit_message_text("Service updated. Use /admin.")

async def admin_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return ConversationHandler.END
    action = query.data
    if action.startswith("setting:"):
        context.user_data["admin_action"] = "setting"
        context.user_data["setting_key"] = action.split(":", 1)[1]
        await query.message.reply_text(f"Send new value for {context.user_data['setting_key']}:")
    elif action == "adm:addcat":
        context.user_data["admin_action"] = "addcat"
        await query.message.reply_text("Send category name:")
    elif action.startswith("svc_add:"):
        context.user_data["admin_action"] = "addservice"
        context.user_data["category_id"] = int(action.split(":")[1])
        await query.message.reply_text("Send service as: name|points_per_unit|min_qty|max_qty|api_service_id")
    elif action == "adm:addvoucher":
        context.user_data["admin_action"] = "addvoucher"
        await query.message.reply_text("Send voucher as: CODE|POINTS|MAX_USES")
    elif action.startswith("manual_view:"):
        oid = int(action.split(":")[1])
        context.user_data["manual_order_id"] = oid
        await query.message.reply_text(
            f"Order #{oid}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Done", callback_data=f"manual:{oid}:done"),
                InlineKeyboardButton("❌ Reject", callback_data=f"manual:{oid}:reject")
            ]])
        )
        return ConversationHandler.END
    return ADMIN_INPUT

async def admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    value = update.message.text.strip()
    action = context.user_data.get("admin_action")
    try:
        if action == "setting":
            await db.set_setting(context.user_data["setting_key"], value)
            reply = "Setting updated."
        elif action == "addcat":
            await db.execute("INSERT INTO categories(name) VALUES(?)", (value,))
            reply = "Category added."
        elif action == "addservice":
            name, rate, minimum, maximum, api_id = value.split("|", 4)
            await db.execute(
                "INSERT INTO services(category_id,name,points_per_unit,min_qty,max_qty,api_service_id) "
                "VALUES(?,?,?,?,?,?)",
                (context.user_data["category_id"], name.strip(), int(rate), int(minimum), int(maximum), api_id.strip() or None)
            )
            reply = "Service added."
        elif action == "addvoucher":
            code, points, max_uses = value.split("|", 2)
            await db.execute(
                "INSERT INTO vouchers(code,points,max_uses) VALUES(?,?,?)",
                (code.upper(), int(points), int(max_uses))
            )
            reply = "Voucher created."
        else:
            reply = "No pending admin action."
    except Exception:
        reply = "Invalid input or database error."
    context.user_data.pop("admin_action", None)
    await update.message.reply_text(reply)
    return ConversationHandler.END

async def broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    users = await db.fetchall("SELECT user_id FROM users WHERE is_blocked=0")
    sent = 0
    for user in users:
        try:
            await context.bot.send_message(user["user_id"], update.message.text)
            sent += 1
        except Exception:
            await db.execute("UPDATE users SET is_blocked=1 WHERE user_id=?", (user["user_id"],))
    await update.message.reply_text(f"Broadcast sent to {sent} users.")
    return ConversationHandler.END

async def manual_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    _, oid, result = query.data.split(":")
    order = await db.fetchone("SELECT user_id,points_spent FROM orders WHERE id=?", (int(oid),))
    if not order:
        return
    status = "completed" if result == "done" else "rejected"
    await db.execute("UPDATE orders SET status=? WHERE id=?", (status, int(oid)))
    if result == "reject":
        await db.add_points(order["user_id"], order["points_spent"], "refund", f"Order #{oid} rejected")
    try:
        await context.bot.send_message(
            order["user_id"],
            f"{'✅ Order completed' if result == 'done' else '❌ Order rejected; points refunded'}: #{oid}"
        )
    except Exception:
        pass
    await query.edit_message_text(f"Order #{oid}: {status}")

async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text in ("💬 TELEGRAM", "🎵 TIKTOK"):
        return await category_button(update, context)
    if text == "👤 MY ACCOUNT":
        return await account(update, context)
    if text == "💳 BUY COINS":
        return await buy_coins(update, context)
    if text == "🎁 BONUS":
        return await bonus(update, context)
    if text == "🛠 SUPPORT":
        return await support(update, context)
    if text == "🎟️ REFER":
        return await refer(update, context)

def register_handlers(application):
    order_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(choose_service, pattern=r"^service:\d+$")],
        states={
            ORDER_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_link)],
            ORDER_QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_qty)]
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
        allow_reentry=True
    )
    voucher_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(lambda u, c: voucher_start(u, c), pattern="^redeem$")],
        states={VOUCHER_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, voucher_redeem)]},
        fallbacks=[CommandHandler("cancel", cancel_conversation)]
    )
    admin_input_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_prompt, pattern=r"^(setting:|adm:addcat$|svc_add:|adm:addvoucher$|manual_view:)")],
        states={ADMIN_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_input)]},
        fallbacks=[CommandHandler("cancel", cancel_conversation)]
    )
    broadcast_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_actions, pattern="^adm:broadcast$")],
        states={ADMIN_BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_send)]},
        fallbacks=[CommandHandler("cancel", cancel_conversation)]
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin))
    application.add_handler(order_conv)
    application.add_handler(voucher_conv)
    application.add_handler(admin_input_conv)
    application.add_handler(broadcast_conv)
    application.add_handler(CallbackQueryHandler(check_join, pattern="^check_join$"))
    application.add_handler(CallbackQueryHandler(show_services, pattern=r"^cat:\d+$"))
    application.add_handler(CallbackQueryHandler(admin_actions, pattern=r"^adm:(bot|api|categories|services|manual|vouchers|settings)$"))
    application.add_handler(CallbackQueryHandler(admin_toggle_category, pattern=r"^cat_toggle:\d+$"))
    application.add_handler(CallbackQueryHandler(admin_category_service, pattern=r"^svc_cat:\d+$"))
    application.add_handler(CallbackQueryHandler(admin_toggle_service, pattern=r"^svc_toggle:\d+$"))
    application.add_handler(CallbackQueryHandler(manual_result, pattern=r"^manual:\d+:(done|reject)$"))
    application.add_handler(CallbackQueryHandler(my_orders, pattern="^my_orders$"))
    application.add_handler(CallbackQueryHandler(buy_coins, pattern="^buy_coins$"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, button_router))
