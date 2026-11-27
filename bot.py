import sqlite3
import secrets
import string
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# --- CONFIGURATION ---
BOT_TOKEN = "9078873023:AAEsc1dcGsVKAqzzLhmP8ix4XuDiu2qlfN0"
ADMIN_IDS = [123456789] # अपनी न्यूमेरिक टेलीग्राम आईडी यहाँ डालें
UPI_ID = "yourupi@bank"
PRODUCT_PRICE = 240.0
DB_NAME = "bot_store.db"


# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute(
        """CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance REAL DEFAULT 0.0
        )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key_code TEXT UNIQUE,
            is_used INTEGER DEFAULT 0,
            assigned_to INTEGER
        )"""
    )
    conn.commit()
    conn.close()


def get_balance(user_id: int) -> float:
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 0.0)", (user_id,))
    conn.commit()
    c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    bal = c.fetchone()[0]
    conn.close()
    return bal


def update_balance(user_id: int, amount: float) -> float:
    """Adds or subtracts amount (supports negative values properly)."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 0.0)", (user_id,))
    c.execute("UPDATE users SET balance = MAX(0.0, balance + ?) WHERE user_id = ?", (amount, user_id))
    conn.commit()
    c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    new_bal = c.fetchone()[0]
    conn.close()
    return new_bal


def generate_key_code(length: int = 16) -> str:
    alphabet = string.ascii_uppercase + string.digits
    raw = "".join(secrets.choice(alphabet) for _ in range(length))
    return f"KEY-{raw[:4]}-{raw[4:8]}-{raw[8:12]}-{raw[12:]}"


def claim_or_generate_key(user_id: int) -> str:
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # Check if unused pre-stocked key exists; otherwise generate a new one
    c.execute("SELECT id, key_code FROM keys WHERE is_used = 0 LIMIT 1")
    row = c.fetchone()
    if row:
        key_id, key_code = row
        c.execute("UPDATE keys SET is_used = 1, assigned_to = ? WHERE id = ?", (user_id, key_id))
    else:
        key_code = generate_key_code()
        c.execute(
            "INSERT INTO keys (key_code, is_used, assigned_to) VALUES (?, 1, ?)",
            (key_code, user_id),
        )
    conn.commit()
    conn.close()
    return key_code


# --- USER HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bal = get_balance(user_id)
    keyboard = [
        [InlineKeyboardButton("💳 Add Balance", callback_data="add_balance")],
        [InlineKeyboardButton(f"🔑 Buy Key (₹{PRODUCT_PRICE:.0f})", callback_data="buy_key")],
        [InlineKeyboardButton("💰 My Balance", callback_data="check_balance")],
    ]
    await update.message.reply_text(
        f"Welcome to the Store!\nYour User ID: `{user_id}`\nCurrent Balance: ₹{bal:.2f}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
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
            f"Pay via UPI to: `{UPI_ID}`\n\n"
            "After payment, send the **12-digit UTR / Transaction ID** or **payment screenshot** here for verification.",
            parse_mode="Markdown",
        )

    elif query.data == "buy_key":
        bal = get_balance(user_id)
        if bal < PRODUCT_PRICE:
            await query.edit_message_text(
                f"{bal:.2f}). Required: ₹{PRODUCT_PRICE:.2f}.\nUse /start to add funds."
            )
            return

        new_bal = update_balance(user_id, -PRODUCT_PRICE)
        key_code = claim_or_generate_key(user_id)
        await query.edit_message_text(
            f"✅ Purchase Successful!\n\n"
            f"🔑 Your Product Key:\n`{key_code}`\n\n"
            f"Remaining Balance: ₹{new_bal:.2f}",
            parse_mode="Markdown",
        )


async def handle_payment_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_payment_proof"):
        return

    user = update.effective_user
    context.user_data["awaiting_payment_proof"] = False

    # Forward proof to admins with quick approve/reject buttons
    keyboard = [
        [
            InlineKeyboardButton("✅ Approve ₹240", callback_data=f"approve_{user.id}_240"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user.id}"),
        ]
    ]
    caption = (
        f"🔔 **New Payment Verification Request**\n"
        f"User: {user.full_name} (`{user.id}`)\n"
        f"Text/UTR: {update.message.text or update.message.caption or 'Screenshot attached'}"
    )

    for admin_id in ADMIN_IDS:
        if update.message.photo:
            await context.bot.send_photo(
                chat_id=admin_id,
                photo=update.message.photo[-1].file_id,
                caption=caption,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown",
            )
        else:
            await context.bot.send_message(
                chat_id=admin_id,
                text=caption,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown",
            )

    await update.message.reply_text("⏳ Payment proof submitted. You will be notified once verified.")


# --- ADMIN HANDLERS ---
async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id not in ADMIN_IDS:
        await query.answer("Unauthorized", show_alert=True)
        return

    await query.answer()
    parts = query.data.split("_")
    action = parts[0]
    target_user_id = int(parts[1])

    if action == "approve":
        amount = float(parts[2])
        new_bal = update_balance(target_user_id, amount)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(f"✅ Approved ₹{amount:.2f} for user `{target_user_id}`. New balance: ₹{new_bal:.2f}", parse_mode="Markdown")
        await context.bot.send_message(
            chat_id=target_user_id,
            text=f"✅ Payment verified! ₹{amount:.2f} added.\nNew Balance: ₹{new_bal:.2f}\nUse /start to buy your key.",
        )

    elif action == "reject":
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(f"❌ Rejected payment for user `{target_user_id}`.", parse_mode="Markdown")
        await context.bot.send_message(
            chat_id=target_user_id,
            text=" support or submit valid proof.",
        )


async def admin_adjust_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /bal <user_id> <amount> (e.g., /bal 123456789 240 or /bal 123456789 -240)"""
    if update.effective_user.id not in ADMIN_IDS:
        return

    try:
        target_id = int(context.args[0])
        amount = float(context.args[1]) # Properly parses negative signs (-240)
        new_bal = update_balance(target_id, amount)
        await update.message.reply_text(
            f"✅ Updated user `{target_id}` by {amount:+.2f}.\nNew Balance: ₹{new_bal:.2f}",
            parse_mode="Markdown",
        )
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: `/bal <user_id> <amount>` (use negative to deduct, e.g., `/bal 12345 -240`)", parse_mode="Markdown")


async def admin_add_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /addkey <CUSTOM_KEY_STRING>"""
    if update.effective_user.id not in ADMIN_IDS:
        return

    if not context.args:
        await update.message.reply_text("Usage: `/addkey <KEY_CODE>`", parse_mode="Markdown")
        return

    key_code = context.args[0]
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO keys (key_code) VALUES (?)", (key_code,))
        conn.commit()
        await update.message.reply_text(f"✅ Key `{key_code}` added to stock.", parse_mode="Markdown")
    except sqlite3.IntegrityError:
        await update.message.reply_text("⚠️ Key already exists in database.")
    finally:
        conn.close()


# --- MAIN ---
if __name__ == "__main__":
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("bal", admin_adjust_balance))
    app.add_handler(CommandHandler("addkey", admin_add_key))
    app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^(approve|reject)_"))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, handle_payment_proof))

    app.run_polling()
