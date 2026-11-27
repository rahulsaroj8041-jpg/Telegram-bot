import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import sqlite3
import secrets
import string

# --- CONFIGURATION ---
ADMIN_IDE = [123456789] # अपनी न्यूमेरिक टेलीग्राम आईडी यहाँ डालें
UPI_ID = "yourupi@bank"
PRODUCT_PRICE = 240.0
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
    conn.commit()
    conn.close()

def get_balance(user_id: int) -> float:
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 0.0)", (user_id,))
    c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    bal = c.fetchone()[0]
    conn.close()
    return bal

def update_balance(user_id: int, amount: float) -> float:
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET balance = MAX(0.0, balance + ?) WHERE user_id = ?", (amount, user_id))
    c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    new_bal = c.fetchone()[0]
    conn.commit()
    conn.close()
    return new_bal

def generate_key_code(length: int = 16) -> str:
    alphabet = string.ascii_uppercase + string.digits
    raw = "".join(secrets.choice(alphabet) for _ in range(length))
    return f"KEY-{raw[:4]}-{raw[4:8]}-{raw[8:12]}-{raw[12:]}"

def claim_or_generate_key(user_id: int) -> str:
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, key_code FROM keys WHERE is_used = 0 LIMIT 1")
    row = c.fetchone()
    if row:
        key_id, key_code = row
        c.execute("UPDATE keys SET is_used = 1, assigned_to = ? WHERE id = ?", (user_id, key_id))
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
    keyboard = [
        [InlineKeyboardButton("💳 Add Balance", callback_data="add_balance")],
        [InlineKeyboardButton(f"🔑 Buy Key (₹{PRODUCT_PRICE})", callback_data="buy_key")],
        [InlineKeyboardButton("💰 My Balance", callback_data="check_balance")]
    ]
    await update.message.reply_text(
        f"Welcome to the Store!\nYour User ID: `{user_id}`\nYour Balance: ₹{bal:.2f}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "check_balance":
        bal = get_balance(user_id)
        await query.edit_message_text(f"💰 Your Current Balance: ₹{bal:.2f}")

    elif query.data == "add_balance":
        context.user_data["awaiting_payment_proof"] = True
        await query.edit_message_text(
            f"Pay via UPI to: `{UPI_ID}`\n\nAfter payment, send the screenshot as proof.",
            parse_mode="Markdown"
        )

    elif query.data == "buy_key":
        bal = get_balance(user_id)
        if bal < PRODUCT_PRICE:
            await query.edit_message_text(f"❌ Insufficient Balance. Required: ₹{PRODUCT_PRICE}. Your balance: ₹{bal:.2f}")
            return

        new_bal = update_balance(user_id, -PRODUCT_PRICE)
        key_code = claim_or_generate_key(user_id)
        await query.edit_message_text(
            f"✅ Purchase Successful!\n\n🔑 Your Product Key:\n`{key_code}`\n\nRemaining Balance: ₹{new_bal:.2f}",
            parse_mode="Markdown"
        )

async def handle_payment_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_payment_proof"):
        return

    user = update.effective_user
    context.user_data["awaiting_payment_proof"] = False

    keyboard = [
        [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user.id}_240"),
         InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user.id}")
    ]
    caption = f"🔔 New Payment Verification Request\nUser: {user.full_name} (`{user.id}`)"
    
    for admin_id in ADMIN_IDE:
        if update.message.photo:
            await context.bot.send_photo(chat_id=admin_id, photo=update.message.photo[-1].file_id, caption=caption, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        else:
            await context.bot.send_message(chat_id=admin_id, text=caption, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    
    await update.message.reply_text("⏳ Payment proof sent to admins for verification.")

# --- ADMIN HANDLERS ---
async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id not in ADMIN_IDE:
        await query.answer("Unauthorized", show_alert=True)
        return

    await query.answer()
    parts = query.data.split("_")
    action = parts[0]
    target_user_id = int(parts[1])

    if action == "approve":
        amount = float(parts[2])
        new_bal = update_balance(target_user_id, amount)
        await query.edit_message_text(f"✅ Approved ₹{amount} for user `{target_user_id}`.", parse_mode="Markdown")
        try:
            await context.bot.send_message(chat_id=target_user_id, text=f"🎉 Your payment of ₹{amount} has been verified! Balance added.")
        except Exception:
            pass

    elif action == "reject":
        await query.edit_message_text(f"❌ Payment rejected for user `{target_user_id}`.", parse_mode="Markdown")
        try:
            await context.bot.send_message(chat_id=target_user_id, text="⚠️ Your payment proof was rejected by admin.")
        except Exception:
            pass

# --- MAIN ---
if __name__ == '__main__':
    init_db()
    token = os.environ.get("BOT_TOKEN")
    if not token:
        exit("Error: BOT_TOKEN is not set.")
    
    app = ApplicationBuilder().token(token).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^(approve|reject)_"))
    app.add_handler(MessageHandler(filters.PHOTO | filters.TEXT & ~filters.COMMAND, handle_payment_proof))
    
    app.run_polling()
