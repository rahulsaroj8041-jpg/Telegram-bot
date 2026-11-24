import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Bot is ready!')

if __name__ == '__main__':
    application = ApplicationBuilder().token('9078873023:AAERG4g_4xBo7YnmrGtF-TY3GpqeeoUM1EQ').build()
    start_handler = CommandHandler('start', start)
    application.add_handler(start_handler)
    application.run_polling()
