import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, filters
import sqlite3
import secrets
import string

# --- CONFIGURATION ---
ADMIN_IDE = [7057164680]
UPI_ID = "yourupi@bank"
DB_NAME = "bot_store.db"

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    balance REAL DEFAULT 0.0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key_code TEXT UNIQUE,
                    is_used INTEGER DEFAULT 0,
                    assigned_to INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE,
                    price REAL)''')
    
    c.execute("SELECT COUNT(*) FROM products")
    if c.fetchone()[0] == 0:
        default_products = [("Panel 1", 240.0), ("Panel 2", 480.0), ("Panel 3", 999.0)]
        c.executemany("INSERT INTO products (name, price) VALUES (?, ?)", default_products)
    
    conn.commit()
    conn.close()

def get_balance(user_id: int) -> float:
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 0.0)", (user_id,))
    c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    val = c.fetchone()[0]
    conn.close()
    return val

def update_balance(user_id: int, amount: float):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 0.0)", (user_id,))
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

def get_products():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, name, price FROM products")
    products = c.fetchall()
    conn.close()
    return products

def generate_key_code(length: int = 16) -> str:
    alphabet = string.ascii_uppercase + string.digits
    raw = "".join(secrets.choice(alphabet) for _ in range(length))
    return f"KEY-{raw[:4]}-{raw[4:8]}-{raw[8:12]}-{raw[12:]}"

def claim_or_generate_key(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, key_code FROM keys WHERE is_used = 0 LIMIT 1")
    row = c.fetchone()
    if row:
        key_id, key_code = row
        c.execute("UPDATE keys SET is_used = 1, assigned_to = ? WHERE id = ?", (user_id, key_id))
        conn.commit()
    else:
        key_code = generate_key_code()
        c.execute("INSERT INTO keys (key_code, is_used, assigned_to) VALUES (?, 1, ?)", (key_code, user_id))
        conn.commit()
    conn.close()
    return key_code

# --- USER HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bal = get_balance(user_id)
    await update.message.reply_text(
        f"Welcome to the Store!\nYour User ID: `{user_id}`\nYour Balance: ₹{bal:.2f}",
        parse_mode="Markdown"
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == "check_balance":
        bal = get_balance(user_id)
        await query.edit_message_text(f"💰 Your Current Balance: ₹{bal:.2f}")

    elif data == "add_balance":
        await query.edit_message_text(f"Pay via UPI to: `{UPI_ID}`")
        context.user_data["awaiting_payment_proof"] = True

    elif data == "select_product":
        products = get_products()
        keyboard = []
        for p_id, name, price in products:
            keyboard.append([InlineKeyboardButton(f"{name} - ₹{price}", callback_data=f"buy_p_{p_id}")])
        keyboard.append([InlineKeyboardButton("Back", callback_data="main_menu")])
        await query.edit_message_text("Select a product to buy:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "main_menu":
        bal = get_balance(user_id)
        keyboard = [
            [InlineKeyboardButton("💳 Add Balance", callback_data="add_balance"), InlineKeyboardButton("🔑 Buy Panel/Key", callback_data="select_product")],
            [InlineKeyboardButton("💰 My Balance", callback_data="check_balance")]
        ]
        await query.edit_message_text(
            f"Welcome to the Store!\nYour User ID: `{user_id}`\nYour Balance: ₹{bal:.2f}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif data.startswith("buy_p_"):
        product_id = int(data.split("_")[2])
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT name, price FROM products WHERE id = ?", (product_id,))
        product = c.fetchone()
        conn.close()

        if not product:
            await query.edit_message_text("Product not found.")
            return

        p_name, price = product
        bal = get_balance(user_id)

        if bal >= price:
            update_balance(user_id, -price)
            key = claim_or_generate_key(user_id)
            await query.edit_message_text(f"🎉 Purchased {p_name}\nYour Key: `{key}`", parse_mode="Markdown")
        else:
            await query.edit_message_text("❌ Insufficient Balance.")

    elif data.startswith("approve_"):
        if query.from_user.id not in ADMIN_IDE:
            return
        parts = data.split("_")
        target_user = int(parts[1])
        amount = 499.0
        update_balance(target_user, amount)
        await query.edit_message_text(f"✅ Payment approved! Added ₹{amount} to user.")
        try:
            await context.bot.send_message(target_user, f"🎉 Your payment of ₹{amount} has been approved!")
        except Exception:
            pass

    elif data.startswith("reject_"):
        if query.from_user.id not in ADMIN_IDE:
            return
        parts = data.split("_")
        target_user = int(parts[1])
        await query.edit_message_text("❌ Payment rejected.")
        try:
            await context.bot.send_message(target_user, "⚠️ Your payment proof was rejected.")
        except Exception:
            pass

async def handle_payment_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_payment_proof"):
        return

    context.user_data["awaiting_payment_proof"] = False
    user = update.effective_user
    amount = 499.0

    keyboard = [
        [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user.id}"), InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user.id}")]
    ]
    caption = f"🔔 New Payment Verification Request\nUser: {user.first_name} (`{user.id}`)\nAmount: ₹{amount}"

    for admin_id in ADMIN_IDE:
        try:
            if update.message.photo:
                await context.bot.send_photo(admin_id, update.message.photo[-1].file_id, caption=caption, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            else:
                await context.bot.send_message(admin_id, caption, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        except Exception:
            pass

    await update.message.reply_text("⏳ Payment proof sent to admin for verification.")

# --- ADMIN HANDLERS ---
async def admin_add_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDE:
        return
    try:
        args = " ".join(context.args).split(",")
        name = args[0].strip()
        price = float(args[1].strip())
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO products (name, price) VALUES (?, ?)", (name, price))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"📦 Product '{name}' added/updated with price ₹{price:.2f}.")
    except Exception:
        await update.message.reply_text("Usage: /addproduct <name>, <price>")

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDE:
        return
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    users = c.fetchall()
    conn.close()
    for u in users:
        try:
            await context.bot.send_message(u[0], text)
        except Exception:
            pass
    await update.message.reply_text("📢 Broadcast sent.")

async def admin_set_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDE:
        return
    try:
        target_id = int(context.args[0])
        new_bal = float(context.args[1])
        update_balance(target_id, new_bal - get_balance(target_id))
        await update.message.reply_text(f"⚖️ Set balance of {target_id} to ₹{new_bal:.2f}.")
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /setbalance <user_id> <amount>")

# --- MAIN ---
if __name__ == '__main__':
    init_db()
    token = os.environ.get("BOT_TOKEN")
    if not token:
        exit("Error: BOT_TOKEN is not set.")

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(CommandHandler("addproduct", admin_add_product))
    app.add_handler(CommandHandler("broadcast", admin_broadcast))
    app.add_handler(CommandHandler("setbalance", admin_set_balance))
    app.add_handler(MessageHandler(filters.PHOTO | filters.TEXT, handle_payment_proof))

    app.run_polling()
