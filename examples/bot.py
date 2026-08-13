"""Telegram bot example using the Render Bypass API.

pip install python-telegram-bot==21.9 httpx
BOT_TOKEN=xxx API_BASE=https://your-app.onrender.com python bot.py
"""
import os

import httpx
from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

API_BASE = os.getenv("API_BASE", "https://your-app.onrender.com")
API_KEY = os.getenv("API_KEY", "")


async def handle(update: Update, _: ContextTypes.DEFAULT_TYPE):
    url = (update.message.text or "").strip()
    if not url.startswith("http"):
        return await update.message.reply_text("Send me a shortlink.")
    msg = await update.message.reply_text("Bypassing... (1-3 min)")
    params = {"bypass": url}
    if API_KEY:
        params["key"] = API_KEY
    async with httpx.AsyncClient(timeout=330) as c:
        try:
            data = (await c.get(f"{API_BASE}/api", params=params)).json()
        except Exception as e:  # noqa: BLE001
            return await msg.edit_text(f"Request failed: {e}")
    if data.get("success"):
        await msg.edit_text(f"Done:\n{data['bypassed']}")
    else:
        await msg.edit_text(f"Failed: {data.get('error')}")


app = Application.builder().token(os.environ["BOT_TOKEN"]).build()
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
app.run_polling()
